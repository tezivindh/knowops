"""
Organizations module — API router.

Organization CRUD, membership management, and group operations.
All endpoints require authentication and organization membership.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select

from app.dependencies import DbSession
from app.modules.audit.models import AuditAction
from app.modules.audit.service import AuditService
from app.modules.identity.models import User
from app.modules.identity.router import get_current_user
from app.modules.organizations.models import Organization, OrgInvitation
from app.modules.organizations.schemas import (
    AcceptInvitationRequest,
    AddGroupMemberRequest,
    CreateGroupRequest,
    CreateOrganizationRequest,
    GroupMemberResponse,
    GroupResponse,
    InvitationResponse,
    InviteMemberRequest,
    InviteResultResponse,
    MembershipResponse,
    OrganizationResponse,
    UpdateMemberRoleRequest,
    UpdateOrganizationRequest,
)
from app.modules.organizations.service import OrganizationService
from app.shared.utils import client_ip, request_id_of

router = APIRouter(prefix="/organizations", tags=["organizations"])


async def get_org_service(db: DbSession) -> OrganizationService:
    return OrganizationService(db)


def _org_response(org: Organization, role: str | None) -> OrganizationResponse:
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        description=org.description,
        role=role,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


async def _audit(
    service: OrganizationService,
    request: Request,
    action: AuditAction,
    actor_id: str,
    org_id: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    await AuditService(service.db).log_event(
        action=action,
        actor_id=actor_id,
        organization_id=org_id,
        resource_type=resource_type,
        resource_id=resource_id,
        details=json.dumps(details) if details else None,
        ip_address=client_ip(request),
        request_id=request_id_of(request),
    )


@router.post("/invitations/accept", response_model=MembershipResponse)
async def accept_invitation(
    request: AcceptInvitationRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> MembershipResponse:
    membership = await service.accept_invitation(current_user, request.token)
    await _audit(
        service,
        http_request,
        AuditAction.MEMBER_INVITED,
        current_user.id,
        membership.organization_id,
        "membership",
        membership.id,
        {"accepted": True},
    )
    return MembershipResponse(**service.member_dict(membership, current_user))


# --- Organization CRUD ---


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    request: CreateOrganizationRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> OrganizationResponse:
    """Create a new organization. The creator becomes the owner."""
    org = await service.create_organization(
        name=request.name,
        slug=request.slug,
        creator_id=current_user.id,
        description=request.description,
    )
    await _audit(
        service,
        http_request,
        AuditAction.ORG_CREATED,
        current_user.id,
        org.id,
        "organization",
        org.id,
    )
    return _org_response(org, "owner")


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> list[OrganizationResponse]:
    """List organizations the current user belongs to."""
    rows = await service.list_user_organizations(current_user.id)
    return [_org_response(org, role.value) for org, role in rows]


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: str,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> OrganizationResponse:
    """Get organization details. Requires membership."""
    membership = await service.require_membership(current_user.id, org_id)
    org = await service.get_organization(org_id)
    return _org_response(org, membership.role.value)


@router.patch("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: str,
    request: UpdateOrganizationRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> OrganizationResponse:
    """Update organization. Requires admin or owner role."""
    org = await service.update_organization(
        org_id=org_id,
        user_id=current_user.id,
        name=request.name,
        description=request.description,
    )
    membership = await service.require_membership(current_user.id, org_id)
    await _audit(
        service,
        http_request,
        AuditAction.ORG_UPDATED,
        current_user.id,
        org_id,
        "organization",
        org_id,
        request.model_dump(exclude_none=True),
    )
    return _org_response(org, membership.role.value)


# --- Members ---


@router.get("/{org_id}/members", response_model=list[MembershipResponse])
async def list_members(
    org_id: str,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> list[MembershipResponse]:
    """List all members of the organization."""
    await service.require_membership(current_user.id, org_id)
    members = await service.list_members(org_id)
    return [MembershipResponse(**m) for m in members]


@router.post(
    "/{org_id}/members",
    response_model=InviteResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    org_id: str,
    request: InviteMemberRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> InviteResultResponse:
    """Add someone by email. Requires admin or owner.

    The administrator shares the signed link with the intended recipient.
    """
    outcome = await service.invite_member(
        org_id=org_id,
        inviter_id=current_user.id,
        email=request.email,
        role=request.role,
    )
    if isinstance(outcome, OrgInvitation):
        await _audit(
            service,
            http_request,
            AuditAction.MEMBER_INVITED,
            current_user.id,
            org_id,
            "invitation",
            outcome.id,
            {"email": outcome.email, "role": request.role},
        )
        return InviteResultResponse(
            status="invited",
            invitation=_invitation_response(outcome, current_user.full_name),
        )
    membership, user = outcome
    await _audit(
        service,
        http_request,
        AuditAction.MEMBER_INVITED,
        current_user.id,
        org_id,
        "user",
        user.id,
        {"role": request.role},
    )
    return InviteResultResponse(
        status="added", member=MembershipResponse(**service.member_dict(membership, user))
    )


def _invitation_response(inv: OrgInvitation, inviter_name: str | None) -> InvitationResponse:
    return InvitationResponse(
        token=OrganizationService.invitation_token(inv),
        id=inv.id,
        organization_id=inv.organization_id,
        email=inv.email,
        role=inv.role.value,
        invited_by=inv.invited_by,
        invited_by_name=inviter_name,
        created_at=inv.created_at,
    )


@router.get("/{org_id}/invitations", response_model=list[InvitationResponse])
async def list_invitations(
    org_id: str,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> list[InvitationResponse]:
    """Pending invitations (people who haven't signed up yet). Admins only."""
    invitations = await service.list_invitations(org_id, current_user.id)
    inviter_ids = {i.invited_by for i in invitations if i.invited_by}
    names: dict[str, str] = {}
    if inviter_ids:
        rows = await service.db.execute(
            select(User.id, User.full_name).where(User.id.in_(inviter_ids))
        )
        names = dict(rows.all())
    return [_invitation_response(i, names.get(i.invited_by or "")) for i in invitations]


@router.delete("/{org_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invitation(
    org_id: str,
    invitation_id: str,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> None:
    """Cancel a pending invitation. Admins only."""
    await service.cancel_invitation(org_id, current_user.id, invitation_id)


@router.delete(
    "/{org_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    org_id: str,
    user_id: str,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> None:
    """Remove a member from the organization (or leave it, for yourself)."""
    await service.remove_member(org_id, current_user.id, user_id)
    await _audit(
        service,
        http_request,
        AuditAction.MEMBER_REMOVED,
        current_user.id,
        org_id,
        "user",
        user_id,
    )


@router.patch("/{org_id}/members/{user_id}/role", response_model=MembershipResponse)
async def update_member_role(
    org_id: str,
    user_id: str,
    request: UpdateMemberRoleRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> MembershipResponse:
    """Change a member's role. Requires owner."""
    membership, user = await service.update_member_role(
        org_id, current_user.id, user_id, request.role
    )
    await _audit(
        service,
        http_request,
        AuditAction.ROLE_CHANGED,
        current_user.id,
        org_id,
        "user",
        user_id,
        {"role": request.role},
    )
    return MembershipResponse(**service.member_dict(membership, user))


# --- Groups ---


@router.post(
    "/{org_id}/groups",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_group(
    org_id: str,
    request: CreateGroupRequest,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> GroupResponse:
    """Create a group within the organization."""
    group = await service.create_group(
        org_id=org_id,
        creator_id=current_user.id,
        name=request.name,
        department=request.department,
        description=request.description,
    )
    return GroupResponse(
        id=group.id,
        organization_id=group.organization_id,
        name=group.name,
        department=group.department,
        description=group.description,
        member_count=0,
        created_at=group.created_at,
    )


@router.get("/{org_id}/groups", response_model=list[GroupResponse])
async def list_groups(
    org_id: str,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> list[GroupResponse]:
    """List all groups in the organization."""
    await service.require_membership(current_user.id, org_id)
    groups = await service.list_groups(org_id)
    return [GroupResponse(**g) for g in groups]


@router.delete("/{org_id}/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    org_id: str,
    group_id: str,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> None:
    """Delete a group and every document grant made to it."""
    await service.delete_group(org_id, current_user.id, group_id)


@router.get("/{org_id}/groups/{group_id}/members", response_model=list[GroupMemberResponse])
async def list_group_members(
    org_id: str,
    group_id: str,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> list[GroupMemberResponse]:
    """List members of a group."""
    await service.require_membership(current_user.id, org_id)
    members = await service.list_group_members(org_id, group_id)
    return [GroupMemberResponse(**m) for m in members]


@router.post(
    "/{org_id}/groups/{group_id}/members",
    status_code=status.HTTP_201_CREATED,
)
async def add_group_member(
    org_id: str,
    group_id: str,
    request: AddGroupMemberRequest,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> dict[str, str]:
    """Add a user to a group. Requires admin or owner."""
    await service.add_group_member(
        org_id=org_id,
        admin_id=current_user.id,
        group_id=group_id,
        user_id=request.user_id,
    )
    return {"status": "added"}


@router.delete(
    "/{org_id}/groups/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_group_member(
    org_id: str,
    group_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_org_service),
) -> None:
    """Remove a user from a group. Requires admin or owner."""
    await service.remove_group_member(org_id, current_user.id, group_id, user_id)
