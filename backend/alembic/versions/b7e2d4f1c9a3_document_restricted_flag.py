"""document restricted flag

Revision ID: b7e2d4f1c9a3
Revises: a1f3c9d2e7b4
Create Date: 2026-10-11 05:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2d4f1c9a3"
down_revision: Union[str, None] = "a1f3c9d2e7b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("restricted", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # Documents that already carry grants were restricted under the old rule.
    op.execute(
        "UPDATE documents SET restricted = true "
        "WHERE id IN (SELECT DISTINCT document_id FROM document_permissions)"
    )


def downgrade() -> None:
    op.drop_column("documents", "restricted")
