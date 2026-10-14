"""
Organizations module — Pydantic schemas.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
RoleName = Literal["owner", "admin", "member", "viewer"]

# --- Organization ---


class CreateOrganizationRequest(BaseModel):
    name: Name
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = Field(default=None, max_length=2000)


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    role: str | None = None  # The caller's role in this organization
    created_at: datetime
    updated_at: datetime


class UpdateOrganizationRequest(BaseModel):
    name: Name | None = None
    description: str | None = Field(default=None, max_length=2000)


# --- Membership ---


class MembershipResponse(BaseModel):
    id: str
    user_id: str
    organization_id: str
    role: str
    status: str
    user_email: str | None = None
    user_name: str | None = None
    created_at: datetime


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=1, max_length=2048)


class InvitationResponse(BaseModel):
    token: str
    id: str
    organization_id: str
    email: str
    role: str
    invited_by: str | None
    invited_by_name: str | None = None
    created_at: datetime


class InviteResultResponse(BaseModel):
    # All new invitations require possession of the signed link.
    status: Literal["added", "invited"]
    member: MembershipResponse | None = None
    invitation: InvitationResponse | None = None


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: RoleName = "member"


class UpdateMemberRoleRequest(BaseModel):
    role: RoleName


# --- Group ---


class CreateGroupRequest(BaseModel):
    name: Name
    department: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class GroupResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    department: str | None
    description: str | None
    member_count: int = 0
    created_at: datetime


class GroupMemberResponse(BaseModel):
    user_id: str
    user_email: str
    user_name: str
    added_at: datetime


class AddGroupMemberRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=26)
