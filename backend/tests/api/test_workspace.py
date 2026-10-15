"""
API tests — documents, chat, knowledge findings, actions.

External services (object storage, the LLM, vector search) are replaced with
in-memory fakes; everything else — routing, permissions, persistence — is real.
"""

import pytest
from httpx import AsyncClient

from app.modules.organizations.models import Membership, MembershipStatus, OrgRole
from app.modules.retrieval.service import RetrievalService, RetrievedChunk
from tests.conftest import AuthHelper, OrgFactory, UserFactory


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload_file(self, key, data, content_type="application/octet-stream"):
        self.objects[key] = data
        return key

    def download_file(self, key):
        return self.objects[key]


class FakeLLM:
    """Returns the given replies in order, repeating the last one."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    async def chat_completion(self, messages, max_tokens=0, temperature=0.0, system_prompt=None):
        self.calls.append(messages)
        reply = self.replies[min(len(self.calls), len(self.replies)) - 1]
        return {"content": reply, "model": "fake-model", "metrics": None}


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr("app.modules.documents.service.get_storage_service", lambda: fake)
    return fake


def use_llm(monkeypatch, *replies: str) -> FakeLLM:
    fake = FakeLLM(*replies)
    for module in (
        "app.modules.conversations.service",
        "app.modules.actions.service",
        "app.modules.versioning.service",
    ):
        monkeypatch.setattr(f"{module}.get_llm_service", lambda: fake)
    return fake


async def setup_org(db_session, member_role: OrgRole | None = None):
    owner = await UserFactory.create(db_session, full_name="Olive Owner")
    org = await OrgFactory.create(db_session, owner_id=owner.id)
    headers = AuthHelper.auth_header(await AuthHelper.get_token(db_session, owner))
    member = member_headers = None
    if member_role is not None:
        member = await UserFactory.create(db_session, full_name="Max Member")
        db_session.add(
            Membership(
                id=f"M{member.id[1:]}",
                user_id=member.id,
                organization_id=org.id,
                role=member_role,
                status=MembershipStatus.ACTIVE,
            )
        )
        await db_session.flush()
        member_headers = AuthHelper.auth_header(await AuthHelper.get_token(db_session, member))
    return org, owner, headers, member, member_headers


async def upload(client, org_id, headers, name="policy.txt", body=b"Leave is 20 days.", **form):
    return await client.post(
        f"/api/v1/organizations/{org_id}/documents",
        headers=headers,
        files={"file": (name, body, "text/plain")},
        data=form,
    )


async def cited_answer(client, org_id, headers, monkeypatch) -> str:
    """Ask a question whose answer cites an uploaded document; return its message id."""
    doc_id = (await upload(client, org_id, headers)).json()["id"]
    versions = (await client.get(f"/api/v1/organizations/{org_id}/documents/{doc_id}/versions",
                                 headers=headers)).json()
    chunk = RetrievedChunk(document_id=doc_id, version_id=versions[0]["id"], chunk_id="1",
                           text="Leave is 20 days.", score=0.9, chunk_index=0)

    async def fake_search(self, org_id, user_id, query, **kwargs):
        return [chunk]

    monkeypatch.setattr(RetrievalService, "search", fake_search)
    use_llm(monkeypatch, "Leave is 20 days [1].")
    base = f"/api/v1/organizations/{org_id}"
    conv = (await client.post(f"{base}/conversations", headers=headers, json={})).json()
    sent = await client.post(f"{base}/conversations/{conv['id']}/messages", headers=headers,
                             json={"content": "Leave?"})
    assert sent.json()["assistant_message"]["citations"], sent.text
    return sent.json()["assistant_message"]["id"]


# --- Profile & organization regressions ---


async def test_profile_update_returns_fresh_timestamps(client: AsyncClient, db_session):
    user = await UserFactory.create(db_session, email="profile@example.com")
    await UserFactory.create(db_session, email="taken@example.com")
    headers = AuthHelper.auth_header(await AuthHelper.get_token(db_session, user))

    res = await client.patch("/api/v1/auth/me", headers=headers, json={"full_name": "  New  "})
    assert res.status_code == 200, res.text
    assert res.json()["full_name"] == "New"

    res = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"email": "taken@example.com"}
    )
    assert res.status_code == 409


async def test_org_update_and_owner_safeguards(client: AsyncClient, db_session):
    org, owner, headers, member, member_headers = await setup_org(db_session, OrgRole.ADMIN)

    res = await client.patch(f"/api/v1/organizations/{org.id}", headers=headers,
                             json={"name": "Renamed"})
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Renamed" and res.json()["role"] == "owner"

    # The only owner cannot demote themselves or leave.
    res = await client.patch(f"/api/v1/organizations/{org.id}/members/{owner.id}/role",
                             headers=headers, json={"role": "member"})
    assert res.status_code == 400 and res.json()["error_code"] == "LAST_OWNER"
    res = await client.delete(f"/api/v1/organizations/{org.id}/members/{owner.id}",
                              headers=headers)
    assert res.status_code == 400

    # Admins cannot mint owners.
    await UserFactory.create(db_session, email="newbie@example.com")
    res = await client.post(f"/api/v1/organizations/{org.id}/members", headers=member_headers,
                            json={"email": "newbie@example.com", "role": "owner"})
    assert res.status_code == 403


async def test_validation_errors_have_string_detail(client: AsyncClient):
    res = await client.post("/api/v1/auth/register", json={"email": "nope"})
    assert res.status_code == 422
    assert isinstance(res.json()["detail"], str)


async def test_oversized_request_id_is_replaced(client: AsyncClient):
    res = await client.get("/health", headers={"X-Request-ID": "x" * 80})
    assert res.status_code == 200
    assert len(res.headers["X-Request-ID"]) == 36


# --- Documents ---


async def test_upload_list_download_and_validation(client: AsyncClient, db_session, storage):
    org, _, headers, _, _ = await setup_org(db_session)

    res = await upload(client, org.id, headers, tags='["hr", "hr", "policy"]')
    assert res.status_code == 201, res.text
    doc_id = res.json()["id"]
    assert res.json()["title"] == "policy"

    res = await client.get(f"/api/v1/organizations/{org.id}/documents", headers=headers)
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["tags"] == ["hr", "policy"]

    res = await client.get(f"/api/v1/organizations/{org.id}/documents?status=bogus",
                           headers=headers)
    assert res.status_code == 400

    res = await client.get(f"/api/v1/organizations/{org.id}/documents/{doc_id}/download",
                           headers=headers)
    assert res.status_code == 200 and res.content == b"Leave is 20 days."
    assert "attachment" in res.headers["content-disposition"]

    res = await upload(client, org.id, headers, name="virus.exe")
    assert res.status_code == 400
    res = await upload(client, org.id, headers, body=b"")
    assert res.status_code == 400
    res = await upload(client, org.id, headers, tags="{not json")
    assert res.status_code == 201  # Falls back to comma-separated parsing.


async def test_restricted_documents_are_hidden_from_other_members(
    client: AsyncClient, db_session, storage
):
    org, owner, headers, member, member_headers = await setup_org(db_session, OrgRole.MEMBER)
    open_doc = (await upload(client, org.id, headers, name="open.txt")).json()["id"]
    secret = (await upload(client, org.id, headers, name="secret.txt")).json()["id"]

    # Granting someone access restricts the document to its grantees.
    res = await client.post(
        f"/api/v1/organizations/{org.id}/documents/{secret}/permissions",
        headers=headers,
        json={"subject_type": "user", "subject_id": owner.id, "permission": "view"},
    )
    assert res.status_code == 201, res.text

    res = await client.get(f"/api/v1/organizations/{org.id}/documents", headers=member_headers)
    assert [d["id"] for d in res.json()["items"]] == [open_doc]
    res = await client.get(f"/api/v1/organizations/{org.id}/documents/{secret}",
                           headers=member_headers)
    assert res.status_code == 403

    # Grants must target members of this organization.
    stranger = await UserFactory.create(db_session)
    res = await client.post(
        f"/api/v1/organizations/{org.id}/documents/{secret}/permissions",
        headers=headers,
        json={"subject_type": "user", "subject_id": stranger.id, "permission": "view"},
    )
    assert res.status_code == 400


async def test_viewers_cannot_upload(client: AsyncClient, db_session, storage):
    org, _, _, _, viewer_headers = await setup_org(db_session, OrgRole.VIEWER)
    res = await upload(client, org.id, viewer_headers)
    assert res.status_code == 403


async def test_new_versions_and_comparison(client: AsyncClient, db_session, storage):
    org, _, headers, _, _ = await setup_org(db_session)
    doc_id = (await upload(client, org.id, headers, body=b"Intro\nLeave: 20 days\n")).json()["id"]
    base = f"/api/v1/organizations/{org.id}/documents/{doc_id}"

    res = await client.get(f"{base}/compare", headers=headers)
    assert res.status_code == 400  # Only one version so far.

    files = {"file": ("policy.txt", b"Intro\nLeave: 20 days\n", "text/plain")}
    assert (await client.post(f"{base}/versions", headers=headers, files=files)).status_code == 409
    files = {"file": ("policy.pdf", b"%PDF", "application/pdf")}
    assert (await client.post(f"{base}/versions", headers=headers, files=files)).status_code == 400
    files = {"file": ("policy.txt", b"Intro\nLeave: 25 days\n", "text/plain")}
    res = await client.post(f"{base}/versions", headers=headers, files=files)
    assert res.status_code == 201 and res.json()["version_number"] == 2

    res = await client.get(f"{base}/compare", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["base"]["version_number"], body["target"]["version_number"]) == (1, 2)
    assert (body["added"], body["removed"]) == (1, 1)


# --- Chat ---


async def test_chat_without_documents_records_a_gap(client: AsyncClient, db_session, monkeypatch):
    org, _, headers, _, _ = await setup_org(db_session)
    use_llm(monkeypatch, "The parking code is 1234. This unsupported claim must be suppressed.")
    conv = (await client.post(f"/api/v1/organizations/{org.id}/conversations", headers=headers,
                              json={})).json()

    for _ in range(2):
        res = await client.post(
            f"/api/v1/organizations/{org.id}/conversations/{conv['id']}/messages",
            headers=headers, json={"content": "What is the   parking policy?"},
        )
        assert res.status_code == 201, res.text
        assert res.json()["assistant_message"]["citations"] == []
        assert "1234" not in res.json()["assistant_message"]["content"]

    res = await client.get(f"/api/v1/organizations/{org.id}/knowledge/findings?type=unanswered",
                           headers=headers)
    findings = res.json()
    assert len(findings) == 1
    assert findings[0]["title"] == "What is the parking policy?"
    assert findings[0]["evidence"]["count"] == 2 and findings[0]["severity"] == "medium"


async def test_chat_citations_are_renumbered_and_ordered(
    client: AsyncClient, db_session, storage, monkeypatch
):
    org, _, headers, _, _ = await setup_org(db_session)
    doc_id = (await upload(client, org.id, headers)).json()["id"]
    versions = (await client.get(f"/api/v1/organizations/{org.id}/documents/{doc_id}/versions",
                                 headers=headers)).json()
    version_id = versions[0]["id"]

    chunks = [
        RetrievedChunk(document_id=doc_id, version_id=version_id, chunk_id=str(i),
                       text=f"passage {i}", score=0.9 - i / 10, chunk_index=i)
        for i in range(1, 4)
    ]

    async def fake_search(self, org_id, user_id, query, **kwargs):
        return chunks

    monkeypatch.setattr(RetrievalService, "search", fake_search)
    llm = use_llm(monkeypatch, "Twenty days [3]. Capped [1, 3].")

    conv = (await client.post(f"/api/v1/organizations/{org.id}/conversations", headers=headers,
                              json={})).json()
    url = f"/api/v1/organizations/{org.id}/conversations/{conv['id']}"
    res = await client.post(f"{url}/messages", headers=headers, json={"content": "Leave?"})
    assert res.status_code == 201, res.text
    answer = res.json()["assistant_message"]
    assert answer["content"] == "Twenty days [1]. Capped [2][1]."
    assert [(c["citation_index"], c["quoted_text"]) for c in answer["citations"]] == [
        (1, "passage 3"),
        (2, "passage 1"),
    ]
    assert answer["citations"][0]["document_title"] == "policy"

    # A second turn sends history without stale markers.
    await client.post(f"{url}/messages", headers=headers, json={"content": "And part-timers?"})
    history = llm.calls[-1]
    assert history[1] == {"role": "assistant", "content": "Twenty days. Capped."}

    detail = (await client.get(url, headers=headers)).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] * 2
    assert detail["conversation"]["title"] == "Leave?"


async def test_other_users_conversations_are_not_found(client: AsyncClient, db_session):
    org, _, headers, _, member_headers = await setup_org(db_session, OrgRole.MEMBER)
    conv = (await client.post(f"/api/v1/organizations/{org.id}/conversations", headers=headers,
                              json={})).json()
    res = await client.get(f"/api/v1/organizations/{org.id}/conversations/{conv['id']}",
                           headers=member_headers)
    assert res.status_code == 404


# --- Actions ---


async def test_task_proposal_approval_is_idempotent(client: AsyncClient, db_session):
    org, _, headers, _, _ = await setup_org(db_session)
    base = f"/api/v1/organizations/{org.id}"
    res = await client.post(f"{base}/actions", headers=headers, json={
        "action_type": "task_create",
        "payload": {"title": "Update leave policy", "checklist": [{"text": "Draft"}],
                    "due_date": "2026-12-01"},
    })
    assert res.status_code == 201, res.text
    run_id = res.json()["id"]
    assert res.json()["payload"]["priority"] == "medium"

    res = await client.patch(f"{base}/actions/{run_id}", headers=headers,
                             json={"payload": {"title": ""}})
    assert res.status_code == 422

    first = await client.post(f"{base}/actions/{run_id}/approve", headers=headers)
    second = await client.post(f"{base}/actions/{run_id}/approve", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["result"] == second.json()["result"]
    rejected = await client.post(f"{base}/actions/{run_id}/reject", headers=headers)
    assert rejected.status_code == 409

    tasks = (await client.get(f"{base}/tasks", headers=headers)).json()
    assert len(tasks) == 1 and tasks[0]["id"] == first.json()["result"]["task_id"]
    assert tasks[0]["due_date"] == "2026-12-01"
    assert tasks[0]["checklist"] == [{"text": "Draft", "done": False}]
    assert tasks[0]["assignee_name"] == "Olive Owner"


async def test_email_draft_generated_from_answer(
    client: AsyncClient, db_session, storage, monkeypatch
):
    org, _, headers, _, _ = await setup_org(db_session)
    message_id = await cited_answer(client, org.id, headers, monkeypatch)

    use_llm(monkeypatch, 'Here you go: {"subject": "Leave", "to": ["x@y.z"], "body": "Hi"}')
    res = await client.post(f"/api/v1/organizations/{org.id}/actions", headers=headers, json={
        "action_type": "email_draft", "message_id": message_id,
    })
    assert res.status_code == 201, res.text
    assert res.json()["payload"] == {"subject": "Leave", "to": [], "body": "Hi"}
    assert res.json()["source_references"][0]["document_title"] == "policy"


async def test_answer_without_sources_cannot_be_drafted(
    client: AsyncClient, db_session, monkeypatch
):
    org, _, headers, _, _ = await setup_org(db_session)
    base = f"/api/v1/organizations/{org.id}"
    use_llm(monkeypatch, "I don't have any sources for that.")
    conv = (await client.post(f"{base}/conversations", headers=headers, json={})).json()
    sent = await client.post(f"{base}/conversations/{conv['id']}/messages", headers=headers,
                             json={"content": "Parking?"})
    message_id = sent.json()["assistant_message"]["id"]

    llm = use_llm(monkeypatch, '{"subject": "x", "to": [], "body": "y"}')
    res = await client.post(f"{base}/actions", headers=headers,
                            json={"action_type": "email_draft", "message_id": message_id})
    assert res.status_code == 422 and res.json()["error_code"] == "NO_SOURCES"
    assert llm.calls == []  # Refused before spending an AI call.

    # Explicit instructions still allow a draft.
    res = await client.post(f"{base}/actions", headers=headers, json={
        "action_type": "email_draft", "message_id": message_id,
        "instructions": "Ask Facilities who owns the parking policy.",
    })
    assert res.status_code == 201, res.text


async def test_unusable_draft_is_retried_once(
    client: AsyncClient, db_session, storage, monkeypatch
):
    org, _, headers, _, _ = await setup_org(db_session)
    message_id = await cited_answer(client, org.id, headers, monkeypatch)
    base = f"/api/v1/organizations/{org.id}/actions"

    # First reply is prose (what Groq actually did), second is valid JSON.
    llm = use_llm(monkeypatch, "Sorry, I can't help with that.",
                  '{"subject": "Leave", "to": [], "body": "Hi"}')
    res = await client.post(base, headers=headers,
                            json={"action_type": "email_draft", "message_id": message_id})
    assert res.status_code == 201, res.text
    assert len(llm.calls) == 2
    assert llm.calls[1][-1]["role"] == "user"  # The retry asked for the JSON format.

    # Two unusable replies give a clear error instead of a broken draft.
    use_llm(monkeypatch, "nope", "still nope")
    res = await client.post(base, headers=headers,
                            json={"action_type": "task_create", "message_id": message_id})
    assert res.status_code == 502 and res.json()["error_code"] == "LLM_BAD_DRAFT"


async def test_viewer_cannot_create_tasks(client: AsyncClient, db_session):
    org, _, _, _, viewer_headers = await setup_org(db_session, OrgRole.VIEWER)
    res = await client.post(f"/api/v1/organizations/{org.id}/tasks", headers=viewer_headers,
                            json={"title": "x"})
    assert res.status_code == 403


async def test_drafting_the_same_answer_twice_returns_the_first_draft(
    client: AsyncClient, db_session, storage, monkeypatch
):
    org, _, headers, _, _ = await setup_org(db_session)
    base = f"/api/v1/organizations/{org.id}"
    message_id = await cited_answer(client, org.id, headers, monkeypatch)

    llm = use_llm(monkeypatch, '{"subject": "Leave", "to": [], "body": "Hi"}')
    body = {"action_type": "email_draft", "message_id": message_id}
    first = await client.post(f"{base}/actions", headers=headers, json=body)
    second = await client.post(f"{base}/actions", headers=headers, json=body)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["source_message_id"] == message_id
    assert len(llm.calls) == 1  # The repeat did not generate again.

    # A task from the same answer is a separate draft.
    task = await client.post(f"{base}/actions", headers=headers,
                             json={"action_type": "task_create", "message_id": message_id,
                                   "payload": {"title": "Follow up"}})
    assert task.status_code == 201 and task.json()["id"] != first.json()["id"]

    # Still the same draft after approval...
    await client.post(f"{base}/actions/{first.json()['id']}/approve", headers=headers)
    again = await client.post(f"{base}/actions", headers=headers, json=body)
    assert again.json()["id"] == first.json()["id"] and again.json()["status"] == "completed"

    # ...but rejecting a draft frees the slot for a fresh one.
    rejected = await client.post(f"{base}/actions/{task.json()['id']}/reject", headers=headers)
    assert rejected.status_code == 200
    fresh = await client.post(f"{base}/actions", headers=headers,
                              json={"action_type": "task_create", "message_id": message_id,
                                    "payload": {"title": "Follow up again"}})
    assert fresh.status_code == 201 and fresh.json()["id"] != task.json()["id"]


# --- Invitations ---


async def test_inviting_someone_without_an_account(client: AsyncClient, db_session):
    org, _, headers, _, member_headers = await setup_org(db_session, OrgRole.MEMBER)
    base = f"/api/v1/organizations/{org.id}"

    res = await client.post(f"{base}/members", headers=headers,
                            json={"email": "New.Hire@Example.com", "role": "admin"})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "invited"
    assert res.json()["invitation"]["email"] == "new.hire@example.com"

    dup = await client.post(f"{base}/members", headers=headers,
                            json={"email": "new.hire@example.com"})
    assert dup.status_code == 409

    pending = (await client.get(f"{base}/invitations", headers=headers)).json()
    assert [i["email"] for i in pending] == ["new.hire@example.com"]
    assert (await client.get(f"{base}/invitations", headers=member_headers)).status_code == 403

    # A matching email alone must not grant access. The private link is required.
    reg = await client.post("/api/v1/auth/register", json={
        "email": "new.hire@example.com", "password": "password123", "full_name": "New Hire",
    })
    assert reg.status_code == 201, reg.text
    login = await client.post("/api/v1/auth/login", json={
        "email": "new.hire@example.com", "password": "password123",
    })
    new_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    orgs = (await client.get("/api/v1/organizations", headers=new_headers)).json()
    assert orgs == []
    token = res.json()["invitation"]["token"]
    accepted = await client.post("/api/v1/organizations/invitations/accept",
                                 headers=new_headers, json={"token": token})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["organization_id"] == org.id
    assert accepted.json()["role"] == "admin"
    repeat = await client.post("/api/v1/organizations/invitations/accept",
                               headers=new_headers, json={"token": token})
    assert repeat.json()["id"] == accepted.json()["id"]

    # The invitation is no longer pending, and they're listed as a member.
    assert (await client.get(f"{base}/invitations", headers=headers)).json() == []
    members = (await client.get(f"{base}/members", headers=headers)).json()
    assert "new.hire@example.com" in [m["user_email"] for m in members]


async def test_existing_accounts_also_require_private_invitation(client: AsyncClient, db_session):
    org, _, headers, _, _ = await setup_org(db_session)
    await UserFactory.create(db_session, email="already@example.com")
    res = await client.post(f"/api/v1/organizations/{org.id}/members", headers=headers,
                            json={"email": "already@example.com"})
    assert res.status_code == 201 and res.json()["status"] == "invited"
    assert res.json()["invitation"]["email"] == "already@example.com"


async def test_cancelled_invitations_are_not_accepted(client: AsyncClient, db_session):
    org, _, headers, _, _ = await setup_org(db_session)
    base = f"/api/v1/organizations/{org.id}"
    inv = (await client.post(f"{base}/members", headers=headers,
                             json={"email": "maybe@example.com"})).json()["invitation"]
    url = f"{base}/invitations/{inv['id']}"
    assert (await client.delete(url, headers=headers)).status_code == 204
    assert (await client.delete(url, headers=headers)).status_code == 404

    await client.post("/api/v1/auth/register", json={
        "email": "maybe@example.com", "password": "password123", "full_name": "Maybe",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": "maybe@example.com", "password": "password123",
    })
    orgs = (await client.get("/api/v1/organizations", headers={
        "Authorization": f"Bearer {login.json()['access_token']}"})).json()
    assert orgs == []


# --- Restricted documents & groups ---


async def _visible(client, org_id, headers) -> list[str]:
    res = await client.get(f"/api/v1/organizations/{org_id}/documents", headers=headers)
    return sorted(d["title"] for d in res.json()["items"])


async def test_group_access_and_deleting_the_group_keeps_document_restricted(
    client: AsyncClient, db_session, storage
):
    org, _, headers, member, member_headers = await setup_org(db_session, OrgRole.MEMBER)
    other = await UserFactory.create(db_session, full_name="Other Member")
    db_session.add(Membership(id=f"N{other.id[1:]}", user_id=other.id, organization_id=org.id,
                              role=OrgRole.MEMBER, status=MembershipStatus.ACTIVE))
    await db_session.flush()
    other_headers = AuthHelper.auth_header(await AuthHelper.get_token(db_session, other))
    base = f"/api/v1/organizations/{org.id}"

    await upload(client, org.id, headers, name="open.txt")
    secret = (await upload(client, org.id, headers, name="salary.txt")).json()["id"]
    group = (await client.post(f"{base}/groups", headers=headers, json={"name": "Finance"})).json()
    await client.post(f"{base}/groups/{group['id']}/members", headers=headers,
                      json={"user_id": member.id})
    res = await client.post(f"{base}/documents/{secret}/permissions", headers=headers, json={
        "subject_type": "group", "subject_id": group["id"], "permission": "view"})
    assert res.status_code == 201, res.text

    assert await _visible(client, org.id, member_headers) == ["open", "salary"]
    assert await _visible(client, org.id, other_headers) == ["open"]

    # Deleting the group removes its grant — but the document stays restricted.
    deleted = await client.delete(f"{base}/groups/{group['id']}", headers=headers)
    assert deleted.status_code == 204
    assert await _visible(client, org.id, member_headers) == ["open"]
    assert await _visible(client, org.id, other_headers) == ["open"]
    assert await _visible(client, org.id, headers) == ["open", "salary"]  # owner/admins still
    detail = (await client.get(f"{base}/documents/{secret}", headers=headers)).json()
    assert detail["restricted"] is True


async def test_revoking_the_last_grant_keeps_document_restricted(
    client: AsyncClient, db_session, storage
):
    org, _, headers, member, member_headers = await setup_org(db_session, OrgRole.MEMBER)
    base = f"/api/v1/organizations/{org.id}/documents"
    doc = (await upload(client, org.id, headers, name="plan.txt")).json()["id"]
    await client.post(f"{base}/{doc}/permissions", headers=headers, json={
        "subject_type": "user", "subject_id": member.id, "permission": "view"})
    assert await _visible(client, org.id, member_headers) == ["plan"]

    res = await client.delete(
        f"{base}/{doc}/permissions?subject_type=user&subject_id={member.id}", headers=headers)
    assert res.status_code == 204
    assert await _visible(client, org.id, member_headers) == []
    assert (await client.get(f"{base}/{doc}", headers=member_headers)).status_code == 403

    # Opening it up is an explicit action.
    res = await client.put(f"{base}/{doc}/access", headers=headers, json={"restricted": False})
    assert res.status_code == 200 and res.json()["restricted"] is False
    assert await _visible(client, org.id, member_headers) == ["plan"]

    # Members can't change access on documents they don't manage.
    res = await client.put(
        f"{base}/{doc}/access", headers=member_headers, json={"restricted": True}
    )
    assert res.status_code == 403
