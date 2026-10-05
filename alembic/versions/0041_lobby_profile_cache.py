"""Cache group profile photo file_id for lobby fallback.
Revision ID: 0041_lobby_profile_cache
Revises: 0040_lobby_media
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0041_lobby_profile_cache"
down_revision: Union[str, Sequence[str], None] = "0040_lobby_media"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column(
        "group_settings",
        sa.Column("lobby_profile_file_id", sa.String(length=255), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("group_settings", "lobby_profile_file_id")
