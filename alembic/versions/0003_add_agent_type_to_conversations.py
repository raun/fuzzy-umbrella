"""add agent_type to conversations

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add agent_type VARCHAR(20) NULL column to conversations."""
    op.add_column(
        "conversations",
        sa.Column("agent_type", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    """Drop agent_type column from conversations."""
    op.drop_column("conversations", "agent_type")
