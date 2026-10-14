"""
Knowledge quality module — Service layer.

Finds and tracks problems in an organization's knowledge base:

- **unanswered** — questions the assistant could not ground in any document
  (recorded live by the chat flow, de-duplicated per question);
- **stale** — documents whose active version is older than a threshold;
- **conflict** — passages in different documents that are semantically close
  and that the LLM judges to make contradictory claims.

Stale and conflict detection run as an on-demand scan in the worker. The scan
state is stored on the organization (``settings["knowledge_scan"]``) so every
client can see whether a scan is queued, running, or finished.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, TypeVar

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.config import get_settings
from app.modules.documents.models import Document, DocumentStatus, DocumentVersion
from app.modules.documents.service import visible_documents_filter
from app.modules.identity.models import User
from app.modules.ingestion.models import VectorIndex
from app.modules.knowledge_quality.models import (
    FindingSeverity,
    FindingStatus,
    FindingType,
    KnowledgeFinding,
)
from app.modules.organizations.models import Organization
from app.modules.organizations.service import MANAGER_ROLES, OrganizationService
from app.services.embeddings.client import get_embedding_service
from app.services.llm.client import (
    LLMRequestError,
    LLMService,
    LLMUnavailableError,
    get_llm_service,
    llm_app_error,
    parse_json_object,
)
from app.services.vector.client import get_vector_service
from app.shared.utils import AppError, ConflictError, ForbiddenError, NotFoundError, utcnow

EnumT = TypeVar("EnumT", bound=Enum)

logger = structlog.get_logger()

ACTIVE_STATUSES = (FindingStatus.OPEN, FindingStatus.IN_REVIEW)
# A queued/running scan older than this is assumed dead (worker crash).
SCAN_TIMEOUT = timedelta(minutes=30)
# Bounds that keep a scan's cost predictable on large organizations.
SCAN_MAX_DOCUMENTS = 50
SCAN_CHUNKS_PER_DOCUMENT = 48
SCAN_NEIGHBOURS_PER_CHUNK = 3

CONFLICT_SYSTEM_PROMPT = (
    "You audit company documents for contradictions. You are given two passages "
    "from different documents. Decide whether they make directly contradictory "
    "claims about the same subject — for example different numbers, dates, "
    "deadlines, owners, or rules for the same thing. Differences in scope, "
    "wording, emphasis, or level of detail are NOT conflicts, and neither is one "
    "passage simply covering something the other does not mention.\n"
    "Reply with only a JSON object:\n"
    '{"conflict": true or false, "severity": "low" | "medium" | "high" | "critical", '
    '"title": "at most 12 words naming the disputed fact", '
    '"explanation": "1-3 sentences quoting the conflicting statements"}'
)


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _normalise_question(text: str) -> str:
    return " ".join(text.split())[:500]


class KnowledgeQualityService:
    """Detection, listing, and triage of knowledge findings."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()

    # ------------------------------------------------------------------
    # Unanswered questions (recorded live from chat)
    # ------------------------------------------------------------------

    async def record_unanswered(
        self,
        org_id: str,
        question: str,
        asked_by: str,
        conversation_id: str,
        had_sources: bool,
    ) -> KnowledgeFinding:
        title = _normalise_question(question)
        result = await self.db.execute(
            select(KnowledgeFinding).where(
                KnowledgeFinding.organization_id == org_id,
                KnowledgeFinding.finding_type == FindingType.UNANSWERED,
                KnowledgeFinding.status.in_(ACTIVE_STATUSES),
                func.lower(KnowledgeFinding.title) == title.lower(),
            )
        )
        finding = result.scalars().first()
        occurrence = {
            "asked_by": asked_by,
            "conversation_id": conversation_id,
            "asked_at": utcnow().isoformat(),
            "had_sources": had_sources,
        }

        if finding is None:
            evidence: dict[str, Any] = {"count": 1, "occurrences": [occurrence]}
            finding = KnowledgeFinding(
                id=str(ULID()),
                organization_id=org_id,
                finding_type=FindingType.UNANSWERED,
                title=title,
                description="",
                evidence="",
                severity=FindingSeverity.LOW,
                status=FindingStatus.OPEN,
                related_documents="[]",
                detected_by="chat",
            )
            self.db.add(finding)
        else:
            evidence = _loads(finding.evidence, {"count": 0, "occurrences": []})
            evidence["count"] = int(evidence.get("count", 0)) + 1
            evidence["occurrences"] = (evidence.get("occurrences", []) + [occurrence])[-20:]

        count = evidence["count"]
        finding.evidence = json.dumps(evidence)
        finding.severity = (
            FindingSeverity.HIGH
            if count >= 5
            else FindingSeverity.MEDIUM
            if count >= 2
            else FindingSeverity.LOW
        )
        times = "once" if count == 1 else f"{count} times"
        finding.description = (
            f"Asked {times}. "
            + (
                "Related passages were found, but none of them answered the question."
                if had_sources
                else "No indexed document contains relevant information."
            )
            + " Consider adding or updating a document that covers it."
        )
        await self.db.flush()
        return finding

    # ------------------------------------------------------------------
    # Listing and triage
    # ------------------------------------------------------------------

    async def list_findings(
        self,
        org_id: str,
        user_id: str,
        finding_type: str | None = None,
        status: str | None = None,
    ) -> list[tuple[KnowledgeFinding, str | None]]:
        membership = await OrganizationService(self.db).require_membership(user_id, org_id)
        query = (
            select(KnowledgeFinding, User.full_name)
            .outerjoin(User, User.id == KnowledgeFinding.assigned_to)
            .where(KnowledgeFinding.organization_id == org_id)
        )
        if finding_type:
            query = query.where(KnowledgeFinding.finding_type == _enum(FindingType, finding_type))
        if status:
            query = query.where(KnowledgeFinding.status == _enum(FindingStatus, status))
        query = query.order_by(KnowledgeFinding.updated_at.desc(), KnowledgeFinding.id.desc())
        rows: list[tuple[KnowledgeFinding, str | None]] = [
            (f, name) for f, name in (await self.db.execute(query)).all()
        ]

        if membership.role in MANAGER_ROLES:
            return rows

        # Non-managers only see findings whose evidence comes entirely from
        # documents they can open, and never other people's questions.
        visible = set(
            (
                await self.db.execute(
                    select(Document.id).where(
                        Document.organization_id == org_id,
                        visible_documents_filter(user_id, membership),
                    )
                )
            ).scalars()
        )
        return [
            (f, name)
            for f, name in rows
            if f.finding_type != FindingType.UNANSWERED
            and set(_loads(f.related_documents, [])) <= visible
        ]

    async def update_finding(
        self,
        org_id: str,
        user_id: str,
        finding_id: str,
        changes: dict[str, Any],
    ) -> KnowledgeFinding:
        membership = await OrganizationService(self.db).require_membership(user_id, org_id)
        finding = await self.db.get(KnowledgeFinding, finding_id)
        if finding is None or finding.organization_id != org_id:
            raise NotFoundError("Finding", finding_id)

        is_manager = membership.role in MANAGER_ROLES
        if not is_manager and finding.id not in {
            f.id for f, _ in await self.list_findings(org_id, user_id)
        }:
            raise NotFoundError("Finding")
        if not is_manager and finding.assigned_to != user_id:
            raise ForbiddenError("Only admins or the assignee can update this finding")
        if "assigned_to" in changes and not is_manager:
            raise ForbiddenError("Only admins can assign findings")

        if "assigned_to" in changes:
            assignee = changes["assigned_to"] or None
            if assignee:
                await OrganizationService(self.db).require_membership(assignee, org_id)
            finding.assigned_to = assignee
            if assignee and finding.status == FindingStatus.OPEN and "status" not in changes:
                finding.status = FindingStatus.IN_REVIEW

        if changes.get("status"):
            new_status = FindingStatus(changes["status"])
            finding.status = new_status
            if new_status in (FindingStatus.RESOLVED, FindingStatus.DISMISSED):
                finding.resolved_by = user_id
            else:
                finding.resolved_by = None

        if "resolution_notes" in changes:
            finding.resolution_notes = (changes["resolution_notes"] or "").strip() or None

        await self.db.flush()
        return finding

    async def summary(self, org_id: str, user_id: str) -> dict[str, Any]:
        await OrganizationService(self.db).require_membership(user_id, org_id)
        findings = await self.list_findings(org_id, user_id)
        open_by_type = {t.value: 0 for t in FindingType}
        resolved = 0
        for finding, _ in findings:
            if finding.status in ACTIVE_STATUSES:
                open_by_type[finding.finding_type.value] += 1
            elif finding.status == FindingStatus.RESOLVED:
                resolved += 1

        status_counts = dict(
            (
                await self.db.execute(
                    select(Document.status, func.count(Document.id))
                    .where(Document.organization_id == org_id)
                    .group_by(Document.status)
                )
            ).all()
        )
        embeddings = get_embedding_service()
        index = (
            await self.db.execute(
                select(VectorIndex).where(
                    VectorIndex.organization_id == org_id,
                    VectorIndex.collection_name
                    == get_vector_service().collection_name(org_id, embeddings.model_tag),
                )
            )
        ).scalar_one_or_none()

        return {
            "open_by_type": open_by_type,
            "total_open": sum(open_by_type.values()),
            "resolved": resolved,
            "documents_ready": status_counts.get(DocumentStatus.READY, 0),
            "documents_processing": status_counts.get(DocumentStatus.PROCESSING, 0)
            + status_counts.get(DocumentStatus.UPLOADED, 0),
            "documents_failed": status_counts.get(DocumentStatus.FAILED, 0),
            "indexed_chunks": index.chunk_count if index else 0,
            "embedding_model": embeddings.model_name,
            "scan": await self.get_scan_state(org_id),
        }

    # ------------------------------------------------------------------
    # Scan state
    # ------------------------------------------------------------------

    async def get_scan_state(self, org_id: str) -> dict[str, Any]:
        org = await self.db.get(Organization, org_id)
        if org is None:
            raise NotFoundError("Organization", org_id)
        state = _loads(org.settings, {}).get("knowledge_scan") or {"status": "idle"}
        if state.get("status") in ("queued", "running") and self._timed_out(state):
            state = {
                **state,
                "status": "failed",
                "error": "The scan did not finish. Check that the worker is running.",
            }
        return state

    @staticmethod
    def _timed_out(state: dict[str, Any]) -> bool:
        started = state.get("started_at")
        if not started:
            return True
        try:
            started_at = datetime.fromisoformat(started)
        except ValueError:
            return True
        return utcnow() - started_at > SCAN_TIMEOUT

    async def _set_scan_state(self, org_id: str, **state: Any) -> None:
        # Lock the row: the API and the worker both write org.settings.
        org = (
            await self.db.execute(
                select(Organization).where(Organization.id == org_id).with_for_update()
            )
        ).scalar_one()
        settings = _loads(org.settings, {})
        if not isinstance(settings, dict):
            settings = {}
        settings["knowledge_scan"] = state
        org.settings = json.dumps(settings)
        await self.db.flush()

    async def request_scan(self, org_id: str, user_id: str) -> dict[str, Any]:
        """Queue a stale + conflict scan. Admins/owners only."""
        from app.modules.knowledge_quality.tasks import enqueue_scan

        await OrganizationService(self.db).require_role(user_id, org_id, MANAGER_ROLES)
        await self.db.execute(
            select(Organization).where(Organization.id == org_id).with_for_update()
        )
        current = await self.get_scan_state(org_id)
        if current.get("status") in ("queued", "running"):
            raise ConflictError("A scan is already in progress")

        state = {"status": "queued", "started_at": utcnow().isoformat(), "requested_by": user_id}
        await self._set_scan_state(org_id, **state)
        await self.db.commit()

        if not enqueue_scan(org_id):
            state = {
                **state,
                "status": "failed",
                "finished_at": utcnow().isoformat(),
                "error": "Could not reach the job queue. Is Redis running?",
            }
            await self._set_scan_state(org_id, **state)
            await self.db.commit()
        return state

    # ------------------------------------------------------------------
    # Scan (runs in the worker)
    # ------------------------------------------------------------------

    async def run_scan(self, org_id: str) -> dict[str, Any]:
        started_at = utcnow().isoformat()
        await self._set_scan_state(org_id, status="running", started_at=started_at)
        await self.db.commit()

        summary: dict[str, Any] = {}
        try:
            summary["auto_resolved"] = await self._auto_resolve(org_id)
            summary["stale_found"] = await self._detect_stale(org_id)
            await self.db.commit()
            conflicts = await self._detect_conflicts(org_id)
            summary.update(conflicts)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            await self._set_scan_state(
                org_id,
                status="failed",
                started_at=started_at,
                finished_at=utcnow().isoformat(),
                error="Scan failed. Check worker diagnostics and retry.",
                summary=summary,
            )
            await self.db.commit()
            raise

        await self._set_scan_state(
            org_id,
            status="completed",
            started_at=started_at,
            finished_at=utcnow().isoformat(),
            summary=summary,
        )
        await self.db.commit()
        logger.info("Knowledge scan complete", org_id=org_id, **summary)
        return summary

    async def _active_documents(self, org_id: str) -> list[tuple[Document, DocumentVersion]]:
        result = await self.db.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.id == Document.active_version_id)
            .where(
                Document.organization_id == org_id,
                Document.status == DocumentStatus.READY,
            )
            .order_by(Document.updated_at.desc())
        )
        return [(d, v) for d, v in result.all()]

    async def _existing_fingerprints(self, org_id: str, finding_type: FindingType) -> set[str]:
        rows = await self.db.execute(
            select(KnowledgeFinding.evidence).where(
                KnowledgeFinding.organization_id == org_id,
                KnowledgeFinding.finding_type == finding_type,
            )
        )
        return {fp for raw in rows.scalars() if (fp := _loads(raw, {}).get("fingerprint"))}

    async def _auto_resolve(self, org_id: str) -> int:
        """Close stale/conflict findings whose evidence is no longer current."""
        active_versions = {v.id for _, v in await self._active_documents(org_id)}
        rows = await self.db.execute(
            select(KnowledgeFinding).where(
                KnowledgeFinding.organization_id == org_id,
                KnowledgeFinding.finding_type.in_([FindingType.STALE, FindingType.CONFLICT]),
                KnowledgeFinding.status.in_(ACTIVE_STATUSES),
            )
        )
        resolved = 0
        for finding in rows.scalars():
            evidence = _loads(finding.evidence, {})
            versions = evidence.get("version_ids") or []
            if versions and not set(versions) <= active_versions:
                finding.status = FindingStatus.RESOLVED
                finding.resolution_notes = (
                    "Resolved automatically: a document involved was updated or archived."
                )
                resolved += 1
        await self.db.flush()
        return resolved

    async def _detect_stale(self, org_id: str) -> int:
        days = self.settings.stale_document_days
        cutoff = utcnow() - timedelta(days=days)
        known = await self._existing_fingerprints(org_id, FindingType.STALE)
        created = 0
        for document, version in await self._active_documents(org_id):
            if version.created_at >= cutoff:
                continue
            fingerprint = f"stale:{version.id}"
            if fingerprint in known:
                continue
            age_days = (utcnow() - version.created_at).days
            self.db.add(
                KnowledgeFinding(
                    id=str(ULID()),
                    organization_id=org_id,
                    finding_type=FindingType.STALE,
                    title=f"{document.title} has not been updated in {age_days} days"[:500],
                    description=(
                        f"Version {version.version_number} was uploaded on "
                        f"{version.created_at.astimezone(UTC):%d %b %Y}. Check it is still "
                        "accurate, then upload a new version or dismiss this finding."
                    ),
                    evidence=json.dumps(
                        {
                            "fingerprint": fingerprint,
                            "version_ids": [version.id],
                            "document_title": document.title,
                            "version_number": version.version_number,
                            "uploaded_at": version.created_at.isoformat(),
                            "age_days": age_days,
                        }
                    ),
                    severity=(
                        FindingSeverity.MEDIUM if age_days > 2 * days else FindingSeverity.LOW
                    ),
                    status=FindingStatus.OPEN,
                    related_documents=json.dumps([document.id]),
                    detected_by="scan",
                )
            )
            created += 1
        await self.db.flush()
        return created

    async def _candidate_pairs(
        self, org_id: str, active: list[tuple[Document, DocumentVersion]]
    ) -> list[dict[str, Any]]:
        """Most similar passage pair for each pair of distinct documents."""
        vectors = get_vector_service()
        collection = vectors.collection_name(org_id, get_embedding_service().model_tag)
        version_by_doc = {d.id: v.id for d, v in active}
        threshold = self.settings.conflict_similarity_threshold

        best: dict[tuple[str, str], dict[str, Any]] = {}
        for document, version in active:
            others = [vid for did, vid in version_by_doc.items() if did != document.id]
            if not others:
                continue
            points = await vectors.scroll_version(
                collection, version.id, with_vectors=True, limit=SCAN_CHUNKS_PER_DOCUMENT
            )
            for point in points:
                vector = point["vector"]
                if not isinstance(vector, list):
                    continue
                hits = await vectors.search(
                    collection,
                    vector,
                    limit=SCAN_NEIGHBOURS_PER_CHUNK,
                    org_id=org_id,
                    version_ids=others,
                    score_threshold=threshold,
                )
                for hit in hits:
                    payload_a, payload_b = point["payload"], hit["payload"] or {}
                    text_a = " ".join(str(payload_a.get("text", "")).split())
                    text_b = " ".join(str(payload_b.get("text", "")).split())
                    if not text_a or not text_b or text_a == text_b:
                        continue  # Verbatim duplicates agree by definition.
                    other_doc = str(payload_b.get("document_id"))
                    first, second = sorted((document.id, other_doc))
                    key = (first, second)
                    if key in best and best[key]["score"] >= hit["score"]:
                        continue
                    best[key] = {"score": float(hit["score"]), "a": payload_a, "b": payload_b}
        return sorted(best.values(), key=lambda c: c["score"], reverse=True)

    async def _detect_conflicts(self, org_id: str) -> dict[str, Any]:
        active = (await self._active_documents(org_id))[:SCAN_MAX_DOCUMENTS]
        result: dict[str, Any] = {"conflict_pairs_checked": 0, "conflicts_found": 0}
        if len(active) < 2:
            result["conflict_note"] = "At least two ready documents are needed."
            return result

        titles = {d.id: d.title for d, _ in active}
        known = await self._existing_fingerprints(org_id, FindingType.CONFLICT)
        candidates = await self._candidate_pairs(org_id, active)

        llm = get_llm_service()
        for candidate in candidates:
            if result["conflict_pairs_checked"] >= self.settings.conflict_max_pairs:
                break
            a, b = candidate["a"], candidate["b"]
            fingerprint = "conflict:" + ":".join(
                sorted([str(a.get("chunk_id")), str(b.get("chunk_id"))])
            )
            if fingerprint in known:
                continue
            result["conflict_pairs_checked"] += 1
            try:
                verdict = await self._judge_pair(llm, a, b, titles)
            except (LLMUnavailableError, LLMRequestError) as exc:
                result["conflict_pairs_checked"] -= 1
                result["conflict_note"] = f"Conflict check stopped: {llm_app_error(exc).detail}"
                break
            except ValueError:
                continue  # Unparseable verdict for this pair; skip it.
            if not verdict.get("conflict"):
                continue

            passages = [
                {
                    "document_id": p.get("document_id"),
                    "document_title": titles.get(str(p.get("document_id")), "Untitled"),
                    "version_id": p.get("version_id"),
                    "chunk_id": str(p.get("chunk_id")),
                    "text": p.get("text"),
                    "page_number": p.get("page_number"),
                    "section_heading": p.get("section_heading"),
                }
                for p in (a, b)
            ]
            self.db.add(
                KnowledgeFinding(
                    id=str(ULID()),
                    organization_id=org_id,
                    finding_type=FindingType.CONFLICT,
                    title=str(verdict.get("title") or "Conflicting statements")[:500],
                    description=str(verdict.get("explanation") or "")[:5000]
                    or "These passages appear to contradict each other.",
                    evidence=json.dumps(
                        {
                            "fingerprint": fingerprint,
                            "similarity": round(candidate["score"], 4),
                            "version_ids": [p["version_id"] for p in passages],
                            "passages": passages,
                        }
                    ),
                    severity=_enum_or(
                        FindingSeverity, verdict.get("severity"), FindingSeverity.MEDIUM
                    ),
                    status=FindingStatus.OPEN,
                    related_documents=json.dumps(sorted({str(p["document_id"]) for p in passages})),
                    detected_by="scan",
                )
            )
            known.add(fingerprint)
            result["conflicts_found"] += 1
        await self.db.flush()
        return result

    @staticmethod
    async def _judge_pair(
        llm: LLMService, a: dict[str, Any], b: dict[str, Any], titles: dict[str, str]
    ) -> dict[str, Any]:
        def describe(label: str, p: dict[str, Any]) -> str:
            location = []
            if p.get("section_heading"):
                location.append(f"section: {p['section_heading']}")
            if p.get("page_number"):
                location.append(f"page {p['page_number']}")
            loc = f" ({', '.join(location)})" if location else ""
            title = titles.get(str(p.get("document_id")), "Untitled")
            return f"PASSAGE {label} — {title}{loc}\n{p.get('text', '')}"

        response = await llm.chat_completion(
            messages=[{"role": "user", "content": f"{describe('A', a)}\n\n{describe('B', b)}"}],
            max_tokens=1024,
            temperature=0.0,
            system_prompt=CONFLICT_SYSTEM_PROMPT,
        )
        verdict = parse_json_object(response.get("content"))
        if not isinstance(verdict.get("conflict"), bool):
            raise ValueError("Verdict is missing a boolean 'conflict'")
        return verdict


def _enum(enum_cls: type[EnumT], value: str) -> EnumT:
    try:
        return enum_cls(value)
    except ValueError:
        raise AppError(f"Invalid value '{value}'", "INVALID_FILTER", 400) from None


def _enum_or(enum_cls: type[EnumT], value: Any, default: EnumT) -> EnumT:
    try:
        return enum_cls(str(value).lower())
    except ValueError:
        return default
