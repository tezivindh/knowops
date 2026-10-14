"""
Organizations module — Service layer.

Organization CRUD, membership management, and group operations.
All operations enforce tenant scoping.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.modules.identity.models import User
from app.modules.organizations.models import (
    Group,
    GroupMembership,
    Membership,
    MembershipStatus,
    Organization,
    OrgInvitation,
    OrgRole,
)
from app.shared.utils import AppError, ConflictError, ForbiddenError, NotFoundError, utcnow

MANAGER_ROLES = (OrgRole.OWNER, OrgRole.ADMIN)


class OrganizationService:
    """Organization and membership management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- Organization CRUD ---

    async def create_organization(
        self, name: str, slug: str, creator_id: str, description: str | None = None
    ) -> Organization:
        """Create an organization and make the creator the owner."""
        existing = await self.db.execute(select(Organization.id).where(Organization.slug == slug))
        if existing.scalar_one_or_none():
            raise ConflictError(f"The URL name '{slug}' is already taken. Choose another.")

        org = Organization(
            id=str(ULID()),
            name=name,
            slug=slug,
            description=description,
        )
        self.db.add(org)
        await self.db.flush()

        membership = Membership(
            id=str(ULID()),
            user_id=creator_id,
            organization_id=org.id,
            role=OrgRole.OWNER,
            status=MembershipStatus.ACTIVE,
        )
        self.db.add(membership)
        await self.db.flush()

        return org

    async def get_organization(self, org_id: str) -> Organization:
        org = await self.db.get(Organization, org_id)
        if not org:
            raise NotFoundError("Organization", org_id)
        return org

    async def list_user_organizations(self, user_id: str) -> list[tuple[Organization, OrgRole]]:
        """List all organizations a user belongs to, with their role in each."""
        result = await self.db.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(
                Membership.user_id == user_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
            .order_by(Organization.created_at)
        )
        return [(org, role) for org, role in result.all()]

    async def update_organization(
        self, org_id: str, user_id: str, name: str | None = None, description: str | None = None
    ) -> Organization:
        await self.require_role(user_id, org_id, MANAGER_ROLES)
        org = await self.get_organization(org_id)
        if name is not None:
            org.name = name
        if description is not None:
            org.description = description or None
        await self.db.flush()
        return org

    async def _lock_membership_changes(self, org_id: str) -> None:
        await self.db.execute(
            select(Organization.id).where(Organization.id == org_id).with_for_update()
        )

    # --- Membership ---

    async def get_membership(self, user_id: str, org_id: str) -> Membership | None:
        result = await self.db.execute(
            select(Membership)
            .where(
                Membership.user_id == user_id,
                Membership.organization_id == org_id,
            )
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def require_role(
        self, user_id: str, org_id: str, roles: tuple[OrgRole, ...] | list[OrgRole]
    ) -> Membership:
        """Verify user has one of the required roles. Raises ForbiddenError."""
        membership = await self.require_membership(user_id, org_id)
        if membership.role not in roles:
            raise ForbiddenError(f"Requires role: {', '.join(r.value for r in roles)}")
        return membership

    async def require_membership(self, user_id: str, org_id: str) -> Membership:
        """Verify user is an active member. Returns membership."""
        membership = await self.get_membership(user_id, org_id)
        if not membership or membership.status != MembershipStatus.ACTIVE:
            raise ForbiddenError("You are not a member of this organization")
        return membership

    async def list_members(self, org_id: str) -> list[dict[str, Any]]:
        """List all members of an organization with user details."""
        result = await self.db.execute(
            select(Membership, User)
            .join(User, Membership.user_id == User.id)
            .where(Membership.organization_id == org_id)
            .order_by(Membership.created_at)
        )
        return [self.member_dict(membership, user) for membership, user in result.all()]

    @staticmethod
    def member_dict(membership: Membership, user: User) -> dict[str, Any]:
        return {
            "id": membership.id,
            "user_id": user.id,
            "organization_id": membership.organization_id,
            "role": membership.role.value,
            "status": membership.status.value,
            "user_email": user.email,
            "user_name": user.full_name,
            "created_at": membership.created_at,
        }

    async def invite_member(
        self,
        org_id: str,
        inviter_id: str,
        email: str,
        role: str = "member",
    ) -> tuple[Membership, User] | OrgInvitation:
        """Add someone to the organization by email.

        A pending ``OrgInvitation`` is stored for every invited account and
        returned; acceptance requires a signed invitation link.
        """
        await self._lock_membership_changes(org_id)
        await self.db.execute(
            delete(OrgInvitation).where(
                OrgInvitation.organization_id == org_id,
                OrgInvitation.email == email.strip().lower(),
                OrgInvitation.accepted_at.is_(None),
                OrgInvitation.created_at <= utcnow() - timedelta(days=7),
            )
        )
        inviter = await self.require_role(inviter_id, org_id, MANAGER_ROLES)
        org_role = self._parse_role(role)
        if org_role == OrgRole.OWNER and inviter.role != OrgRole.OWNER:
            raise ForbiddenError("Only owners can grant the owner role")
        email = email.strip().lower()

        user = (await self.db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user and await self.get_membership(user.id, org_id):
            raise ConflictError("User is already a member of this organization")
        if await self._pending_invitation(org_id, email):
            raise ConflictError("This address has already been invited")
        invitation = OrgInvitation(
            id=str(ULID()),
            organization_id=org_id,
            email=email,
            role=org_role,
            invited_by=inviter_id,
        )
        self.db.add(invitation)
        await self.db.flush()
        return invitation

    @staticmethod
    def invitation_token(invitation: OrgInvitation) -> str:
        import jwt

        from app.config import get_settings

        settings = get_settings()
        return jwt.encode(
            {
                "sub": invitation.id,
                "type": "invitation",
                "exp": invitation.created_at + timedelta(days=7),
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

    async def accept_invitation(self, user: User, token: str) -> Membership:
        import jwt
        from jwt import InvalidTokenError

        from app.config import get_settings

        settings = get_settings()
        try:
            claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            if claims.get("type") != "invitation" or not claims.get("sub"):
                raise ValueError("Invalid token type")
        except (InvalidTokenError, ValueError):
            raise AppError("Invalid or expired invitation", "INVALID_INVITATION", 400) from None
        invitation = (
            await self.db.execute(
                select(OrgInvitation).where(OrgInvitation.id == claims["sub"]).with_for_update()
            )
        ).scalar_one_or_none()
        if invitation is None or invitation.email != user.email.lower():
            raise NotFoundError("Invitation")
        membership = await self.get_membership(user.id, invitation.organization_id)
        if invitation.accepted_at is not None:
            if membership is not None:
                return membership
            raise AppError("Invitation already used", "INVALID_INVITATION", 409)
        if membership is None:
            membership = Membership(
                id=str(ULID()),
                user_id=user.id,
                organization_id=invitation.organization_id,
                role=invitation.role,
                status=MembershipStatus.ACTIVE,
            )
            self.db.add(membership)
        invitation.accepted_at = utcnow()
        await self.db.flush()
        return membership

    async def _pending_invitation(self, org_id: str, email: str) -> OrgInvitation | None:
        return (
            await self.db.execute(
                select(OrgInvitation).where(
                    OrgInvitation.organization_id == org_id,
                    OrgInvitation.email == email,
                    OrgInvitation.accepted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def list_invitations(self, org_id: str, user_id: str) -> list[OrgInvitation]:
        await self.require_role(user_id, org_id, MANAGER_ROLES)
        result = await self.db.execute(
            select(OrgInvitation)
            .where(
                OrgInvitation.organization_id == org_id,
                OrgInvitation.accepted_at.is_(None),
                OrgInvitation.created_at > utcnow() - timedelta(days=7),
            )
            .order_by(OrgInvitation.created_at.desc())
        )
        return list(result.scalars())

    async def cancel_invitation(self, org_id: str, user_id: str, invitation_id: str) -> None:
        await self.require_role(user_id, org_id, MANAGER_ROLES)
        result = await self.db.execute(
            delete(OrgInvitation)
            .where(
                OrgInvitation.id == invitation_id,
                OrgInvitation.organization_id == org_id,
                OrgInvitation.accepted_at.is_(None),
            )
            .returning(OrgInvitation.id)
        )
        if result.scalar_one_or_none() is None:
            raise NotFoundError("Invitation", invitation_id)

    async def remove_member(self, org_id: str, remover_id: str, target_user_id: str) -> None:
        """Remove a member (or leave, when remover == target)."""
        await self._lock_membership_changes(org_id)
        if remover_id == target_user_id:
            await self.require_membership(remover_id, org_id)
        else:
            remover = await self.require_role(remover_id, org_id, MANAGER_ROLES)
        membership = await self.get_membership(target_user_id, org_id)
        if not membership:
            raise NotFoundError("Membership")

        if remover_id != target_user_id:
            if membership.role == OrgRole.OWNER:
                raise ForbiddenError("Owners cannot be removed by other members")
            if membership.role == OrgRole.ADMIN and remover.role != OrgRole.OWNER:
                raise ForbiddenError("Only owners can remove admins")

        if membership.role == OrgRole.OWNER:
            await self._ensure_another_owner(org_id, target_user_id)

        # Drop the user's group memberships in this organization as well.
        org_group_ids = select(Group.id).where(Group.organization_id == org_id)
        await self.db.execute(
            delete(GroupMembership).where(
                GroupMembership.user_id == target_user_id,
                GroupMembership.group_id.in_(org_group_ids),
            )
        )
        await self.db.delete(membership)
        await self.db.flush()

    async def update_member_role(
        self, org_id: str, updater_id: str, target_user_id: str, role: str
    ) -> tuple[Membership, User]:
        """Change a member's role. Owner-only."""
        await self._lock_membership_changes(org_id)
        await self.require_role(updater_id, org_id, [OrgRole.OWNER])
        membership = await self.get_membership(target_user_id, org_id)
        if not membership:
            raise NotFoundError("Membership")
        new_role = self._parse_role(role)
        if membership.role == OrgRole.OWNER and new_role != OrgRole.OWNER:
            await self._ensure_another_owner(org_id, target_user_id)
        membership.role = new_role
        await self.db.flush()
        user = await self.db.get(User, target_user_id)
        assert user is not None
        return membership, user

    async def _ensure_another_owner(self, org_id: str, user_id: str) -> None:
        result = await self.db.execute(
            select(func.count(Membership.id)).where(
                Membership.organization_id == org_id,
                Membership.role == OrgRole.OWNER,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.user_id != user_id,
            )
        )
        if not result.scalar():
            raise AppError(
                "An organization must keep at least one owner. "
                "Promote someone else to owner first.",
                "LAST_OWNER",
                400,
            )

    @staticmethod
    def _parse_role(role: str) -> OrgRole:
        try:
            return OrgRole(role)
        except ValueError:
            raise AppError(f"Invalid role: {role}", "INVALID_ROLE", 400) from None

    # --- Groups ---

    async def create_group(
        self,
        org_id: str,
        creator_id: str,
        name: str,
        department: str | None = None,
        description: str | None = None,
    ) -> Group:
        await self.require_role(creator_id, org_id, MANAGER_ROLES)

        existing = await self.db.execute(
            select(Group.id).where(Group.organization_id == org_id, Group.name == name)
        )
        if existing.scalar_one_or_none():
            raise ConflictError(f"Group '{name}' already exists in this organization")

        group = Group(
            id=str(ULID()),
            organization_id=org_id,
            name=name,
            department=department or None,
            description=description or None,
        )
        self.db.add(group)
        await self.db.flush()
        return group

    async def list_groups(self, org_id: str) -> list[dict[str, Any]]:
        """List groups with member counts."""
        result = await self.db.execute(
            select(
                Group,
                func.count(GroupMembership.id).label("member_count"),
            )
            .outerjoin(GroupMembership, GroupMembership.group_id == Group.id)
            .where(Group.organization_id == org_id)
            .group_by(Group.id)
            .order_by(Group.name)
        )
        return [
            {
                "id": group.id,
                "organization_id": group.organization_id,
                "name": group.name,
                "department": group.department,
                "description": group.description,
                "member_count": count,
                "created_at": group.created_at,
            }
            for group, count in result.all()
        ]

    async def get_group(self, org_id: str, group_id: str) -> Group:
        result = await self.db.execute(
            select(Group).where(Group.id == group_id, Group.organization_id == org_id)
        )
        group = result.scalar_one_or_none()
        if not group:
            raise NotFoundError("Group", group_id)
        return group

    async def delete_group(self, org_id: str, admin_id: str, group_id: str) -> None:
        from app.modules.documents.models import DocumentPermission, SubjectType

        await self.require_role(admin_id, org_id, MANAGER_ROLES)
        group = await self.get_group(org_id, group_id)
        # Group grants reference the group by id only (no FK), so clean them up.
        await self.db.execute(
            delete(DocumentPermission).where(
                DocumentPermission.subject_type == SubjectType.GROUP,
                DocumentPermission.subject_id == group.id,
            )
        )
        await self.db.execute(delete(GroupMembership).where(GroupMembership.group_id == group.id))
        await self.db.execute(delete(Group).where(Group.id == group.id))

    async def list_group_members(self, org_id: str, group_id: str) -> list[dict[str, Any]]:
        await self.get_group(org_id, group_id)
        result = await self.db.execute(
            select(GroupMembership, User)
            .join(User, User.id == GroupMembership.user_id)
            .where(GroupMembership.group_id == group_id)
            .order_by(User.full_name)
        )
        return [
            {
                "user_id": user.id,
                "user_email": user.email,
                "user_name": user.full_name,
                "added_at": gm.created_at,
            }
            for gm, user in result.all()
        ]

    async def add_group_member(
        self, org_id: str, admin_id: str, group_id: str, user_id: str
    ) -> GroupMembership:
        await self.require_role(admin_id, org_id, MANAGER_ROLES)
        await self.get_group(org_id, group_id)
        try:
            await self.require_membership(user_id, org_id)
        except ForbiddenError:
            raise AppError(
                "Only members of this organization can be added to its groups",
                "NOT_A_MEMBER",
                400,
            ) from None

        existing = await self.db.execute(
            select(GroupMembership.id).where(
                GroupMembership.group_id == group_id,
                GroupMembership.user_id == user_id,
            )
        )
        if existing.scalar_one_or_none():
            raise ConflictError("User is already in this group")

        gm = GroupMembership(
            id=str(ULID()),
            group_id=group_id,
            user_id=user_id,
        )
        self.db.add(gm)
        await self.db.flush()
        return gm

    async def remove_group_member(
        self, org_id: str, admin_id: str, group_id: str, user_id: str
    ) -> None:
        await self.require_role(admin_id, org_id, MANAGER_ROLES)
        await self.get_group(org_id, group_id)
        result = await self.db.execute(
            delete(GroupMembership)
            .where(
                GroupMembership.group_id == group_id,
                GroupMembership.user_id == user_id,
            )
            .returning(GroupMembership.id)
        )
        if result.scalar_one_or_none() is None:
            raise NotFoundError("Group membership")
