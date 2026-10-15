"""Authorization regressions use real PostgreSQL with transactional test organizations."""

import pytest
from sqlalchemy import select

from app.modules.conversations.models import Conversation, Message
from app.modules.conversations.service import ConversationService
from app.modules.documents.models import Document, DocumentVersion, ProcessingJob, VersionStatus
from app.modules.organizations.models import OrgRole
from tests.api.test_workspace import FakeStorage, cited_answer, setup_org, upload
from tests.conftest import AuthHelper, UserFactory


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr("app.modules.documents.service.get_storage_service", lambda: fake)
    return fake


async def test_revoked_sources_are_hidden_from_history_drafts_and_tasks(
    client, db_session, storage, monkeypatch
):
    org, _, owner_headers, member, headers = await setup_org(db_session, OrgRole.MEMBER)
    # Owner's document is initially open; member asks with it as evidence.
    message_id = await cited_answer(client, org.id, headers, monkeypatch)
    message = await db_session.get(Message, message_id)
    conversation = await db_session.get(Conversation, message.conversation_id)
    doc = (
        await db_session.execute(select(Document).where(Document.organization_id == org.id))
    ).scalar_one()
    # Make the document owned by the organization owner, not the asking member.
    owner_id = (
        await db_session.execute(select(Document.owner_id).where(Document.id == doc.id))
    ).scalar_one()
    assert owner_id == member.id
    from app.modules.organizations.models import Membership

    owner = (
        await db_session.execute(
            select(Membership.user_id).where(
                Membership.organization_id == org.id, Membership.role == OrgRole.OWNER
            )
        )
    ).scalar_one()
    doc.owner_id = owner
    await db_session.flush()
    base = f"/api/v1/organizations/{org.id}"
    draft = await client.post(
        f"{base}/actions",
        headers=headers,
        json={
            "action_type": "task_create",
            "message_id": message_id,
            "payload": {"title": "Review leave policy"},
        },
    )
    assert draft.status_code == 201, draft.text
    approved = await client.post(f"{base}/actions/{draft.json()['id']}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert len((await client.get(f"{base}/tasks", headers=headers)).json()) == 1
    doc.restricted = True
    await db_session.flush()
    detail = await client.get(f"{base}/conversations/{conversation.id}", headers=headers)
    assert detail.status_code == 200
    answer = detail.json()["messages"][-1]
    assert answer["citations"] == []
    assert "20 days" not in answer["content"]
    history = await ConversationService(db_session)._history(conversation.id, org.id, member.id)
    assert all("20 days" not in turn["content"] for turn in history)
    denied = await client.post(
        f"{base}/actions",
        headers=headers,
        json={
            "action_type": "email_draft",
            "message_id": message_id,
            "payload": {"subject": "Leave", "body": "Policy"},
        },
    )
    assert denied.status_code == 403
    assert (await client.get(f"{base}/actions", headers=headers)).json() == []
    assert (await client.get(f"{base}/tasks", headers=headers)).json() == []
    task_id = approved.json()["result"]["task_id"]
    assert (
        await client.patch(f"{base}/tasks/{task_id}", headers=headers, json={"status": "completed"})
    ).status_code == 404
    # A different organization cannot retrieve the conversation either.
    outsider = await UserFactory.create(db_session)
    outsider_headers = AuthHelper.auth_header(await AuthHelper.get_token(db_session, outsider))
    assert (
        await client.get(f"{base}/conversations/{conversation.id}", headers=outsider_headers)
    ).status_code == 403
    assert (
        await client.get(f"{base}/documents/{doc.id}", headers=owner_headers)
    ).status_code == 200


async def test_queue_outage_is_visible_and_retryable(client, db_session, storage, monkeypatch):
    org, _, headers, _, _ = await setup_org(db_session)
    monkeypatch.setattr("app.modules.documents.service.enqueue_version_processing", lambda _: False)
    result = await upload(client, org.id, headers)
    assert result.status_code == 201, result.text
    doc_id = result.json()["id"]
    version = (
        await db_session.execute(
            select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
        )
    ).scalar_one()
    assert version.status == VersionStatus.FAILED
    job = (
        await db_session.execute(
            select(ProcessingJob).where(ProcessingJob.version_id == version.id)
        )
    ).scalar_one()
    assert job.status == "failed"
    assert "job queue" in version.error_message


async def test_invitation_requires_private_valid_token(client, db_session):
    org, _, headers, member, member_headers = await setup_org(db_session, OrgRole.MEMBER)
    base = f"/api/v1/organizations/{org.id}"
    invite = await client.post(
        f"{base}/members", headers=headers, json={"email": "invite-target@example.com"}
    )
    token = invite.json()["invitation"]["token"]
    for candidate in (token, token + "tampered"):
        response = await client.post(
            "/api/v1/organizations/invitations/accept",
            headers=member_headers,
            json={"token": candidate},
        )
        assert response.status_code in (400, 404)
    await client.delete(f"{base}/invitations/{invite.json()['invitation']['id']}", headers=headers)
    response = await client.post(
        "/api/v1/organizations/invitations/accept", headers=member_headers, json={"token": token}
    )
    assert response.status_code == 404
