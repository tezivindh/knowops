"""Opt-in, real integration campaign; creates and removes only its own scratch database.

Run from backend: .venv/bin/python scripts/verify_live.py
Uses real Redis/Celery/MinIO/Qdrant/embeddings/Groq. Never sends email.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config import get_settings  # noqa: E402


async def main():
    settings = get_settings()
    if not settings.llm_api_key:
        raise RuntimeError("Set LLM_API_KEY before running live verification")
    suffix = uuid.uuid4().hex
    database = f"knowops_audit_{suffix}"
    queue = f"audit_{suffix}"
    base = make_url(settings.test_database_url)
    admin = await asyncpg.connect(host=base.host, port=base.port or 5432,
                                 user=base.username, password=base.password, database=base.database)
    await admin.execute(f'CREATE DATABASE "{database}"')
    scratch_url = base.set(database=database).render_as_string(hide_password=False)
    os.environ.update(DATABASE_URL=scratch_url, TEST_DATABASE_URL=scratch_url,
                      APP_ENV="development", CELERY_QUEUE=queue)
    get_settings.cache_clear()
    worker = None
    org_ids = []
    object_keys = []
    report = {"database": "isolated scratch database", "checks": [], "timings_seconds": {}}
    log = tempfile.NamedTemporaryFile(prefix="knowops-audit-worker-", suffix=".log", mode="w+")
    try:
        for args in (("upgrade", "head"), ("check",)):
            subprocess.run([sys.executable, "-m", "alembic", *args], check=True,
                           stdout=subprocess.DEVNULL)
        report["checks"].append("fresh Alembic upgrade and metadata check")
        from httpx import ASGITransport, AsyncClient
        from sqlalchemy import select

        from app.database import async_session_factory, engine
        from app.main import create_app
        from app.modules.documents.models import DocumentVersion, ProcessingJob
        from app.services.queue.reconcile import recover_pending_uploads
        from app.shared.utils import utcnow
        from app.services.embeddings.client import get_embedding_service
        from app.services.queue.celery_app import celery_app
        from app.services.storage.client import get_storage_service
        from app.services.vector.client import get_vector_service

        worker = subprocess.Popen([sys.executable, "-m", "celery", "-A",
            "app.services.queue.celery_app", "worker", "--pool=solo", "--concurrency=1",
            "--queues", queue, "--hostname", f"audit-{suffix}@localhost", "--loglevel=WARNING"],
            stdout=log, stderr=log, env=os.environ.copy())
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://audit") as client:
            async def request(method, path, **kwargs):
                response = await client.request(method, path, **kwargs)
                if response.status_code >= 400:
                    raise RuntimeError(f"{method} {path}: HTTP {response.status_code}")
                return response.json() if response.content else None

            async def account(name):
                email = f"{name}-{suffix}@example.com"
                await request("POST", "/api/v1/auth/register", json={"email": email,
                    "password": "Synthetic-audit-password-123", "full_name": name})
                pair = await request("POST", "/api/v1/auth/login", json={"email": email,
                    "password": "Synthetic-audit-password-123"})
                headers = {"Authorization": f"Bearer {pair['access_token']}"}
                org = await request("POST", "/api/v1/organizations", headers=headers,
                    json={"name": name, "slug": f"{name}-{suffix}"})
                org_ids.append(org["id"])
                return headers, org["id"]

            headers, org_id = await account("audit")
            foreign_headers, foreign_org = await account("outsider")
            prefix = f"/api/v1/organizations/{org_id}"
            started = time.monotonic()

            async def upload(title, body):
                result = await request("POST", f"{prefix}/documents", headers=headers,
                    files={"file": (f"{title}.txt", body.encode(), "text/plain")}, data={"title": title})
                return result["id"]

            # Simulate the API disappearing after commit but before publication.
            with patch("app.modules.documents.service.enqueue_version_processing", return_value=True):
                doc_a = await upload("Annual leave policy", "All full-time employees receive exactly 20 days of annual paid leave per year.")
            async with async_session_factory() as session:
                pending = (await session.scalars(select(ProcessingJob).where(
                    ProcessingJob.organization_id == org_id,
                ))).one()
                pending.created_at = utcnow() - timedelta(minutes=2)
                await session.commit()
                assert await recover_pending_uploads(session) == 1
                await session.commit()
            report["checks"].append("committed upload without broker message → durable recovery → real worker")
            doc_b = await upload("Annual leave policy alternate", "All full-time employees receive exactly 30 days of annual paid leave per year.")

            async def wait_document(doc_id, version_count=1, failed=False):
                for _ in range(240):
                    versions = await request("GET", f"{prefix}/documents/{doc_id}/versions", headers=headers)
                    if len(versions) >= version_count and versions[0]["status"] in ("ready", "failed"):
                        expected = "failed" if failed else "ready"
                        if versions[0]["status"] != expected:
                            raise RuntimeError(
                                f"Expected document status {expected}: "
                                f"{versions[0].get('error_message')}"
                            )
                        return versions
                    await asyncio.sleep(1)
                raise RuntimeError("Timed out waiting for real worker ingestion")

            versions_a = await wait_document(doc_a)
            await wait_document(doc_b)
            report["timings_seconds"]["two_uploads_to_ready"] = round(time.monotonic() - started, 2)
            report["checks"].append("HTTP upload → MinIO → Redis/Celery worker → extraction → real embeddings → Qdrant → ready")
            conversation = await request("POST", f"{prefix}/conversations", headers=headers, json={})
            started = time.monotonic()
            answer = await request("POST", f"{prefix}/conversations/{conversation['id']}/messages",
                headers=headers, json={"content": "Compare both annual leave policies. How many days does each specify? Cite both documents."})
            citations = answer["assistant_message"]["citations"]
            assert {c["document_id"] for c in citations} == {doc_a, doc_b}, "Answer must cite both real documents"
            assert all(c["quoted_text"] and c["chunk_id"] for c in citations)
            report["timings_seconds"]["multi_document_answer"] = round(time.monotonic() - started, 2)
            report["checks"].append("real multi-document retrieval → Groq answer → persisted citations from both documents")
            assert (await client.get(f"{prefix}/documents/{doc_a}", headers=foreign_headers)).status_code == 403
            assert (await client.get(f"{prefix}/conversations/{conversation['id']}", headers=foreign_headers)).status_code == 403
            report["checks"].append("synthetic cross-tenant document and conversation denials")
            draft = await request("POST", f"{prefix}/actions", headers=headers, json={
                "action_type": "task_create", "message_id": answer["assistant_message"]["id"],
                "instructions": "Create a task to reconcile these conflicting policies."})
            approved = await request("POST", f"{prefix}/actions/{draft['id']}/approve", headers=headers)
            repeated = await request("POST", f"{prefix}/actions/{draft['id']}/approve", headers=headers)
            assert approved["result"]["task_id"] == repeated["result"]["task_id"]
            report["checks"].append("real model task proposal → persisted approval → idempotent task creation; no external action")
            await request("POST", f"{prefix}/knowledge/scan", headers=headers)
            for _ in range(180):
                state = await request("GET", f"{prefix}/knowledge/scan", headers=headers)
                if state["status"] in ("completed", "failed"):
                    assert state["status"] == "completed", "Real scan failed"
                    break
                await asyncio.sleep(1)
            else:
                raise RuntimeError("Scan timed out")
            findings = await request("GET", f"{prefix}/knowledge/findings", headers=headers)
            conflicts = [f for f in findings if f["finding_type"] == "conflict"]
            assert conflicts and len(conflicts[0]["evidence"]["passages"]) == 2
            await request("PATCH", f"{prefix}/knowledge/findings/{conflicts[0]['id']}",
                          headers=headers, json={"status": "in_review"})
            report["checks"].append("contradictory documents → real queued scan/vector candidates/Groq judge → persisted evidence → API review")
            await request("POST", f"{prefix}/documents/{doc_a}/versions", headers=headers,
                files={"file": ("revision.txt", b"All full-time employees receive exactly 25 days of annual paid leave per year.", "text/plain")})
            versions = await wait_document(doc_a, 2)
            assert versions[0]["is_active"] and not versions[1]["is_active"]
            await request("POST", f"{prefix}/documents/{doc_a}/versions", headers=headers,
                files={"file": ("blank.txt", b"   ", "text/plain")})
            versions = await wait_document(doc_a, 3, failed=True)
            assert versions[1]["is_active"] and versions[1]["status"] == "ready"
            report["checks"].append("real version activation and failed blank revision preserve last valid active version")
            ready = await request("GET", "/ready")
            assert all(ready["checks"].values())
            report["checks"].append("readiness probes reach all four real backing services")
        await app.state.rate_limiter.close()
    except Exception:
        log.flush()
        log.seek(0)
        print(log.read()[-12000:], file=sys.stderr)
        raise
    finally:
        if worker:
            worker.terminate()
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
        # Each deletion is confined to this campaign's generated orgs/database.
        if "async_session_factory" in locals():
            async with async_session_factory() as session:
                object_keys = list((await session.execute(select(DocumentVersion.object_key))).scalars())
            for key in object_keys:
                await asyncio.to_thread(get_storage_service().delete_file, key)
            vector = get_vector_service()
            for org_id in org_ids:
                collection = vector.collection_name(org_id, get_embedding_service().model_tag)
                if await vector.client.collection_exists(collection):
                    await vector.client.delete_collection(collection)
            await vector.client.close()
            await engine.dispose()
            # Delete only our queue; never purge shared Redis.
            from redis.asyncio import Redis
            redis = Redis.from_url(get_settings().celery_broker_url)
            await redis.delete(queue)
            await redis.aclose()
            celery_app.close()
        await admin.execute(f'DROP DATABASE "{database}"')
        await admin.close()
        log.close()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
