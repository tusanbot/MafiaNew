"""Add per-group lobby media settings.
Revision ID: 0040_lobby_media
Revises: 0039_birthday_content
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0040_lobby_media"
down_revision: Union[str, Sequence[str], None] = "0039_birthday_content"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "group_settings",
        sa.Column(
            "lobby_media_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "group_settings",
        sa.Column(
            "lobby_media_type",
            sa.String(length=20),
            nullable=True,
        ),
    )
    op.add_column(
        "group_settings",
        sa.Column(
            "lobby_media_file_id",
            sa.String(length=255),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("group_settings", "lobby_media_file_id")
    op.drop_column("group_settings", "lobby_media_type")
    op.drop_column("group_settings", "lobby_media_enabled")
