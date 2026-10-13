"""org_invitations

Revision ID: a1f3c9d2e7b4
Revises: 6cb39eb41321
Create Date: 2026-10-11 05:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1f3c9d2e7b4"
down_revision: Union[str, None] = "6cb39eb41321"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_invitations",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("organization_id", sa.String(length=26), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("OWNER", "ADMIN", "MEMBER", "VIEWER", name="org_role", create_type=False),
            nullable=False,
        ),
        sa.Column("invited_by", sa.String(length=26), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_org_invitations_email", "org_invitations", ["email"])
    op.create_index(
        "uq_org_invitation_pending",
        "org_invitations",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_org_invitation_pending", table_name="org_invitations")
    op.drop_index("ix_org_invitations_email", table_name="org_invitations")
    op.drop_table("org_invitations")
