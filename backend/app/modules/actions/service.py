"""
Actions module — Service layer.

Turns verified answers into reviewable work. An *action run* is an AI- or
user-drafted proposal (a task or an email draft) that does nothing until a
person approves it:

    propose (draft payload + source citations) -> edit -> approve | reject

Approving a task proposal creates a ``Task``; approving an email draft
finalises the text (KnowOps does not send email). Tasks can also be managed
directly.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.modules.actions.models import (
    ActionRun,
    ActionStatus,
    ActionType,
    Task,
    TaskPriority,
    TaskStatus,
)
from app.modules.actions.schemas import EmailPayload, TaskPayload
from app.modules.conversations.models import (
    Conversation,
    Message,
    MessageCitation,
    MessageRole,
)
from app.modules.documents.access import visible_versions
from app.modules.documents.models import Document, DocumentVersion
from app.modules.organizations.models import Membership, OrgRole
from app.modules.organizations.service import MANAGER_ROLES, OrganizationService
from app.services.llm.client import (
    LLMRequestError,
    LLMUnavailableError,
    get_llm_service,
    llm_app_error,
    parse_json_object,
)
from app.shared.utils import AppError, ForbiddenError, NotFoundError, utcnow

WorkItem = TypeVar("WorkItem", bound=ActionRun | Task)

logger = structlog.get_logger()

PAYLOAD_MODELS: dict[ActionType, type[BaseModel]] = {
    ActionType.TASK_CREATE: TaskPayload,
    ActionType.EMAIL_DRAFT: EmailPayload,
}

GENERATION_PROMPTS = {
    ActionType.TASK_CREATE: (
        "You turn verified company knowledge into a concrete work task. Use only "
        "the information provided. Reply with only a JSON object:\n"
        '{"title": "imperative, at most 12 words", '
        '"description": "2-5 sentences of context, mentioning the source documents", '
        '"priority": "low" | "medium" | "high" | "urgent", '
        '"checklist": ["short concrete step", ...] (3-8 steps), '
        '"due_date": "YYYY-MM-DD" or null (only if the sources state a deadline)}'
    ),
    ActionType.EMAIL_DRAFT: (
        "You draft a clear, professional workplace email based on verified company "
        "knowledge. Use only the information provided; do not invent names, numbers, "
        "or commitments. Refer to source documents by title where helpful. Reply "
        "with only a JSON object:\n"
        '{"subject": "concise subject line", "to": [], '
        '"body": "plain-text email body with greeting and sign-off placeholder [Your name]"}'
    ),
}


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def validate_payload(action_type: ActionType, payload: dict[str, Any]) -> dict[str, Any]:
    model = PAYLOAD_MODELS[action_type]
    try:
        return model.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise AppError(
            f"Invalid {action_type.value} payload — {problems}", "INVALID_PAYLOAD", 422
        ) from None


def answer_key(kind: ActionType, message_id: str, user_id: str) -> str:
    return f"{kind.value}:{message_id}:{user_id}"


def answer_message_id(run: ActionRun) -> str | None:
    """The assistant message a draft was made from, if any."""
    key = run.idempotency_key or ""
    parts = key.split(":")
    if len(parts) == 3 and parts[0] == run.action_type.value:
        return parts[1]
    return None


def _due(value: date | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


class ActionsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.orgs = OrganizationService(db)

    async def _require_contributor(self, user_id: str, org_id: str) -> Membership:
        membership = await self.orgs.require_membership(user_id, org_id)
        if membership.role == OrgRole.VIEWER:
            raise ForbiddenError("Viewers have read-only access")
        return membership

    # ------------------------------------------------------------------
    # Action runs
    # ------------------------------------------------------------------

    async def propose(
        self,
        org_id: str,
        user_id: str,
        action_type: str,
        message_id: str | None,
        instructions: str | None,
        payload: dict[str, Any] | None,
    ) -> tuple[ActionRun, bool]:
        """Create a proposal. Returns ``(run, created)``.

        One answer yields at most one live draft of each kind per user: asking
        again returns the existing draft (proposed or completed) instead of
        generating a duplicate. Rejecting a draft frees the slot.
        """
        await self._require_contributor(user_id, org_id)
        kind = ActionType(action_type)

        references: list[dict[str, Any]] = []
        context = ""
        key: str | None = None
        if message_id:
            context, references = await self._answer_context(org_id, user_id, message_id)
            key = answer_key(kind, message_id, user_id)
            existing = await self._by_key(org_id, key)
            if existing is not None:
                return existing, False

        if payload is not None:
            clean = validate_payload(kind, payload)
        elif message_id and not references and not (instructions and instructions.strip()):
            # The answer cited nothing — it's a "not found" reply, and drafting
            # work from it would just repeat that the information is missing.
            raise AppError(
                "This answer isn't backed by any document, so there's nothing to draft "
                "from. Upload a document that covers it, or add instructions.",
                "NO_SOURCES",
                422,
            )
        else:
            if not context and not (instructions and instructions.strip()):
                raise AppError(
                    "Provide an answer to draft from, instructions, or a payload",
                    "NOTHING_TO_DRAFT",
                    422,
                )
            clean = await self._generate(kind, context, instructions)

        run = ActionRun(
            id=str(ULID()),
            organization_id=org_id,
            action_type=kind,
            status=ActionStatus.PROPOSED,
            payload=json.dumps(clean),
            proposed_by=user_id,
            source_references=json.dumps(references) if references else None,
            idempotency_key=key,
        )
        try:
            # Savepoint: a concurrent identical request may win the unique key.
            async with self.db.begin_nested():
                self.db.add(run)
                await self.db.flush()
        except IntegrityError:
            existing = await self._by_key(org_id, key) if key else None
            if existing is None:
                raise
            return existing, False
        return run, True

    async def _by_key(self, org_id: str, key: str) -> ActionRun | None:
        result = await self.db.execute(
            select(ActionRun).where(
                ActionRun.organization_id == org_id, ActionRun.idempotency_key == key
            )
        )
        return result.scalar_one_or_none()

    async def _answer_context(
        self, org_id: str, user_id: str, message_id: str
    ) -> tuple[str, list[dict[str, Any]]]:
        row = (
            await self.db.execute(
                select(Message, Conversation)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(Message.id == message_id)
            )
        ).first()
        if (
            row is None
            or row[1].organization_id != org_id
            or row[1].user_id != user_id
            or row[0].role != MessageRole.ASSISTANT
        ):
            raise NotFoundError("Answer", message_id)
        answer, conversation = row

        question = (
            await self.db.execute(
                select(Message.content)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.role == MessageRole.USER,
                    Message.created_at <= answer.created_at,
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        cited = (
            await self.db.execute(
                select(MessageCitation, Document.id, Document.title)
                .join(DocumentVersion, DocumentVersion.id == MessageCitation.document_version_id)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(MessageCitation.message_id == answer.id)
                .order_by(MessageCitation.citation_index)
            )
        ).all()

        allowed = await visible_versions(self.db, user_id, org_id)
        if any(c.document_version_id not in allowed for c, _, _ in cited):
            raise ForbiddenError("Source access has changed; this answer cannot be used")

        references = [
            {
                "conversation_id": conversation.id,
                "message_id": answer.id,
                "citation_index": c.citation_index,
                "document_id": doc_id,
                "document_title": title,
                "document_version_id": c.document_version_id,
                "page_number": c.page_number,
                "section_heading": c.section_heading,
                "quoted_text": c.quoted_text[:600],
            }
            for c, doc_id, title in cited
        ]
        sources = "\n\n".join(
            f"[{r['citation_index']}] {r['document_title']}\n{r['quoted_text']}" for r in references
        )
        context = f"QUESTION:\n{question or '(unknown)'}\n\nVERIFIED ANSWER:\n{answer.content}" + (
            f"\n\nSOURCES:\n{sources}" if sources else ""
        )
        return context, references

    async def _generate(
        self, kind: ActionType, context: str, instructions: str | None
    ) -> dict[str, Any]:
        """Ask the LLM for a draft, giving it one chance to fix a bad reply."""
        parts = [context] if context else []
        if instructions and instructions.strip():
            parts.append(f"INSTRUCTIONS FROM THE USER:\n{instructions.strip()}")
        parts.append(f"TODAY: {utcnow():%Y-%m-%d}")
        messages = [{"role": "user", "content": "\n\n".join(parts)}]

        problem = ""
        for attempt in range(2):
            try:
                result = await get_llm_service().chat_completion(
                    messages=messages,
                    max_tokens=2048,
                    temperature=0.2 if attempt == 0 else 0.0,
                    system_prompt=GENERATION_PROMPTS[kind],
                )
            except (LLMUnavailableError, LLMRequestError) as exc:
                raise llm_app_error(exc) from exc

            content = result.get("content") or ""
            try:
                return self._clean_draft(kind, parse_json_object(content))
            except (ValueError, AppError) as exc:
                problem = str(exc.detail if isinstance(exc, AppError) else exc)
                logger.warning(
                    "Unusable draft from LLM",
                    action_type=kind.value,
                    attempt=attempt + 1,
                    problem=problem,
                    reply=content[:500],
                )
                # Show the model its reply and ask for the required format once.
                messages = messages + [
                    {"role": "assistant", "content": content or "(empty)"},
                    {
                        "role": "user",
                        "content": "That was not a valid draft. Reply with only the JSON "
                        "object described in your instructions, filling every field.",
                    },
                ]

        raise AppError(
            "The AI engine couldn't produce a usable draft. Please try again.",
            "LLM_BAD_DRAFT",
            502,
        )

    @staticmethod
    def _clean_draft(kind: ActionType, raw: dict[str, Any]) -> dict[str, Any]:
        if kind == ActionType.TASK_CREATE:
            raw["checklist"] = [
                item if isinstance(item, dict) else {"text": str(item)}
                for item in raw.get("checklist") or []
                if (item.get("text") if isinstance(item, dict) else str(item).strip())
            ][:50]
            if raw.get("priority") not in ("low", "medium", "high", "urgent"):
                raw["priority"] = "medium"
            try:
                if raw.get("due_date"):
                    date.fromisoformat(str(raw["due_date"]))
            except ValueError:
                raw["due_date"] = None
        else:
            raw["to"] = []  # Recipients are always chosen by the user.
        return validate_payload(kind, raw)

    async def _evidence_visible(
        self, org_id: str, user_id: str, rows: list[WorkItem]
    ) -> list[WorkItem]:
        allowed = await visible_versions(self.db, user_id, org_id)
        return [
            row
            for row in rows
            if all(
                ref.get("document_version_id") in allowed
                for ref in _loads(row.source_references, [])
            )
        ]

    async def _require_evidence(self, org_id: str, user_id: str, row: ActionRun | Task) -> None:
        if not await self._evidence_visible(org_id, user_id, [row]):
            raise NotFoundError("Source-backed work")

    async def list_runs(self, org_id: str, user_id: str, status: str | None) -> list[ActionRun]:
        membership = await self.orgs.require_membership(user_id, org_id)
        query = select(ActionRun).where(ActionRun.organization_id == org_id)
        if membership.role not in MANAGER_ROLES:
            query = query.where(ActionRun.proposed_by == user_id)
        if status:
            try:
                query = query.where(ActionRun.status == ActionStatus(status))
            except ValueError:
                raise AppError(f"Unknown status '{status}'", "INVALID_STATUS", 400) from None
        query = query.order_by(ActionRun.created_at.desc(), ActionRun.id.desc()).limit(200)
        return await self._evidence_visible(
            org_id, user_id, list((await self.db.execute(query)).scalars())
        )

    async def _get_run_for_review(
        self, org_id: str, user_id: str, run_id: str, lock: bool = False
    ) -> ActionRun:
        membership = await self._require_contributor(user_id, org_id)
        query = select(ActionRun).where(ActionRun.id == run_id, ActionRun.organization_id == org_id)
        if lock:
            query = query.with_for_update()
        run = (await self.db.execute(query)).scalar_one_or_none()
        if run is None:
            raise NotFoundError("Action", run_id)
        if membership.role not in MANAGER_ROLES and run.proposed_by != user_id:
            raise NotFoundError("Action", run_id)
        await self._require_evidence(org_id, user_id, run)
        return run

    async def update_payload(
        self, org_id: str, user_id: str, run_id: str, payload: dict[str, Any]
    ) -> ActionRun:
        run = await self._get_run_for_review(org_id, user_id, run_id, lock=True)
        if run.status != ActionStatus.PROPOSED:
            raise AppError("Only proposed actions can be edited", "NOT_EDITABLE", 409)
        run.payload = json.dumps(validate_payload(run.action_type, payload))
        await self.db.flush()
        return run

    async def approve(self, org_id: str, user_id: str, run_id: str) -> ActionRun:
        """Approve and execute. Idempotent for already-completed runs."""
        run = await self._get_run_for_review(org_id, user_id, run_id, lock=True)
        if run.status == ActionStatus.COMPLETED:
            return run
        if run.status != ActionStatus.PROPOSED:
            raise AppError(
                f"This action is {run.status.value} and cannot be approved",
                "NOT_APPROVABLE",
                409,
            )

        now = utcnow()
        run.approved_by = user_id
        run.approved_at = now
        run.idempotency_key = run.idempotency_key or f"action:{run.id}"
        payload = validate_payload(run.action_type, _loads(run.payload, {}))

        if run.action_type == ActionType.TASK_CREATE:
            task = Task(
                id=str(ULID()),
                organization_id=org_id,
                title=payload["title"],
                description=payload.get("description") or None,
                status=TaskStatus.TODO,
                priority=TaskPriority(payload.get("priority", "medium")),
                # The person who asked for the draft owns the resulting work.
                assignee_id=run.proposed_by or user_id,
                created_by=run.proposed_by or user_id,
                due_date=_due(payload.get("due_date")),
                source_references=run.source_references,
                checklist=json.dumps(payload.get("checklist") or []),
            )
            self.db.add(task)
            await self.db.flush()
            run.result = json.dumps({"task_id": task.id})
        else:
            run.result = json.dumps(payload)

        run.status = ActionStatus.COMPLETED
        run.executed_at = now
        await self.db.flush()
        return run

    async def reject(self, org_id: str, user_id: str, run_id: str) -> ActionRun:
        run = await self._get_run_for_review(org_id, user_id, run_id, lock=True)
        if run.status == ActionStatus.REJECTED:
            return run
        if run.status != ActionStatus.PROPOSED:
            raise AppError(
                f"This action is {run.status.value} and cannot be rejected",
                "NOT_REJECTABLE",
                409,
            )
        run.status = ActionStatus.REJECTED
        # Free the per-answer slot so the user can ask for a fresh draft.
        run.idempotency_key = None
        await self.db.flush()
        return run

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def list_tasks(
        self,
        org_id: str,
        user_id: str,
        status: str | None = None,
        assignee: str | None = None,
    ) -> list[Task]:
        await self.orgs.require_membership(user_id, org_id)
        query = select(Task).where(Task.organization_id == org_id)
        if status:
            try:
                query = query.where(Task.status == TaskStatus(status))
            except ValueError:
                raise AppError(f"Unknown status '{status}'", "INVALID_STATUS", 400) from None
        if assignee == "me":
            query = query.where(Task.assignee_id == user_id)
        elif assignee:
            query = query.where(Task.assignee_id == assignee)
        query = query.order_by(Task.updated_at.desc(), Task.id.desc()).limit(500)
        return await self._evidence_visible(
            org_id, user_id, list((await self.db.execute(query)).scalars())
        )

    async def _validate_assignee(self, org_id: str, assignee_id: str | None) -> None:
        if assignee_id:
            try:
                await self.orgs.require_membership(assignee_id, org_id)
            except ForbiddenError:
                raise AppError(
                    "The assignee must be a member of this organization",
                    "INVALID_ASSIGNEE",
                    400,
                ) from None

    async def create_task(self, org_id: str, user_id: str, data: dict[str, Any]) -> Task:
        await self._require_contributor(user_id, org_id)
        await self._validate_assignee(org_id, data.get("assignee_id"))
        task = Task(
            id=str(ULID()),
            organization_id=org_id,
            title=data["title"],
            description=data.get("description") or None,
            status=TaskStatus(data.get("status", "todo")),
            priority=TaskPriority(data.get("priority", "medium")),
            assignee_id=data.get("assignee_id") or None,
            created_by=user_id,
            due_date=_due(data.get("due_date")),
            checklist=json.dumps([dict(item) for item in data.get("checklist") or []]),
        )
        self.db.add(task)
        await self.db.flush()
        return task

    async def _get_task_for_edit(self, org_id: str, user_id: str, task_id: str) -> Task:
        membership = await self._require_contributor(user_id, org_id)
        task = await self.db.get(Task, task_id)
        if task is None or task.organization_id != org_id:
            raise NotFoundError("Task", task_id)
        if membership.role not in MANAGER_ROLES and user_id not in (
            task.created_by,
            task.assignee_id,
        ):
            raise ForbiddenError("Only the creator, the assignee, or an admin can change this task")
        await self._require_evidence(org_id, user_id, task)
        return task

    async def update_task(
        self, org_id: str, user_id: str, task_id: str, changes: dict[str, Any]
    ) -> Task:
        task = await self._get_task_for_edit(org_id, user_id, task_id)
        if "title" in changes and changes["title"] is not None:
            task.title = changes["title"]
        if "description" in changes:
            task.description = changes["description"] or None
        if changes.get("priority"):
            task.priority = TaskPriority(changes["priority"])
        if changes.get("status"):
            task.status = TaskStatus(changes["status"])
        if "assignee_id" in changes:
            await self._validate_assignee(org_id, changes["assignee_id"])
            task.assignee_id = changes["assignee_id"] or None
        if "due_date" in changes:
            task.due_date = _due(changes["due_date"])
        if "checklist" in changes and changes["checklist"] is not None:
            task.checklist = json.dumps([dict(item) for item in changes["checklist"]])
        await self.db.flush()
        return task

    async def delete_task(self, org_id: str, user_id: str, task_id: str) -> None:
        task = await self._get_task_for_edit(org_id, user_id, task_id)
        await self.db.delete(task)
        await self.db.flush()
