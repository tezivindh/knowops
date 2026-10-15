"""Regressions for audit findings: independent transactions and queue recovery."""

import asyncio
from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import Base
from app.modules.documents.models import DocumentVersion, ProcessingJob, VersionStatus
from app.modules.identity.models import User
from app.modules.organizations.models import Membership, Organization, OrgRole
from app.modules.organizations.service import OrganizationService
from app.services.queue.reconcile import recover_pending_uploads
from app.shared.utils import AppError, utcnow
from tests.api.test_workspace import setup_org, upload
from tests.conftest import TEST_DATABASE_URL, OrgFactory, UserFactory


@pytest.fixture
def storage(monkeypatch):
    from tests.api.test_workspace import FakeStorage

    fake = FakeStorage()
    monkeypatch.setattr("app.modules.documents.service.get_storage_service", lambda: fake)
    return fake


@pytest.mark.parametrize("mode", ["demote", "leave", "reauthorize"])
async def test_concurrent_owner_departures_preserve_an_owner(mode):
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    org_id = None
    user_ids = []
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            first = await UserFactory.create(session)
            second = await UserFactory.create(session)
            user_ids = [first.id, second.id]
            org = await OrgFactory.create(session, first.id)
            org_id = org.id
            session.add(Membership(
                id="M" + second.id[1:], user_id=second.id, organization_id=org.id,
                role=OrgRole.OWNER,
            ))
            await session.commit()

        # Hold the first change open while the second transaction begins.
        async with sessions() as primary, sessions() as secondary:
            a, b = OrganizationService(primary), OrganizationService(secondary)
            # Prime the second session's identity map to exercise stale role reads.
            stale = await b.get_membership(second.id, org_id)
            assert stale.role == OrgRole.OWNER
            await a._lock_membership_changes(org_id)
            started = asyncio.Event()
            original_lock = b._lock_membership_changes

            async def lock(org_id):
                started.set()
                await original_lock(org_id)

            b._lock_membership_changes = lock

            async def depart(service, user_id):
                if mode == "leave":
                    await service.remove_member(org_id, user_id, user_id)
                else:
                    await service.update_member_role(org_id, user_id, user_id, "member")

            task = asyncio.create_task(depart(b, second.id))
            await started.wait()
            try:
                if mode == "reauthorize":
                    await a.update_member_role(org_id, first.id, second.id, "member")
                else:
                    await depart(a, first.id)
                await primary.commit()
                with pytest.raises(AppError) as error:
                    await asyncio.wait_for(task, timeout=5)
                assert error.value.error_code == (
                    "FORBIDDEN" if mode == "reauthorize" else "LAST_OWNER"
                )
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await secondary.rollback()
        async with sessions() as session:
            assert await session.scalar(select(func.count(Membership.id)).where(
                Membership.organization_id == org_id, Membership.role == OrgRole.OWNER,
            )) == 1
    finally:
        async with sessions() as session:
            if org_id:
                await session.execute(delete(Organization).where(Organization.id == org_id))
            if user_ids:
                await session.execute(delete(User).where(User.id.in_(user_ids)))
            await session.commit()
        await engine.dispose()


async def test_expired_invitation_can_be_replaced_and_old_link_is_rejected(db_session):
    org, owner, _, _, _ = await setup_org(db_session)
    service = OrganizationService(db_session)
    recipient = await UserFactory.create(db_session)
    invitation = await service.invite_member(org.id, owner.id, recipient.email)
    old_token = service.invitation_token(invitation)
    invitation.created_at = utcnow() - timedelta(days=8)
    await db_session.flush()
    assert await service.list_invitations(org.id, owner.id) == []
    replacement = await service.invite_member(org.id, owner.id, recipient.email)
    assert replacement.id != invitation.id
    with pytest.raises(AppError):
        await service.accept_invitation(recipient, old_token)
    membership = await service.accept_invitation(recipient, service.invitation_token(replacement))
    assert membership.user_id == recipient.id


async def test_committed_unpublished_upload_is_recovered(client, db_session, storage, monkeypatch):
    org, _, headers, _, _ = await setup_org(db_session)
    document = (await upload(client, org.id, headers)).json()
    job = (await db_session.scalars(select(ProcessingJob).where(
        ProcessingJob.organization_id == org.id,
    ))).one()
    job.created_at = utcnow() - timedelta(minutes=2)
    await db_session.flush()
    publish = Mock(return_value=False)
    monkeypatch.setattr("app.services.queue.reconcile.enqueue_version_processing", publish)
    assert await recover_pending_uploads(db_session) == 0
    assert job.status == "queued"
    publish.return_value = True
    assert await recover_pending_uploads(db_session) == 1
    publish.assert_called_with(job.version_id)
    version = await db_session.get(DocumentVersion, job.version_id)
    assert version.document_id == document["id"]
    version.status = VersionStatus.READY
    await db_session.flush()
    publish.reset_mock()
    assert await recover_pending_uploads(db_session) == 0
    publish.assert_not_called()
