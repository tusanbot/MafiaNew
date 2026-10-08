"""add group birthday defaults

Revision ID: 0045
Revises: 0044_birthday_user_content
"""

from alembic import op
import sqlalchemy as sa

revision = "0045_group_birthday_defaults"
down_revision = "0044_birthday_user_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("group_settings", sa.Column("birthday_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("group_settings", sa.Column("birthday_media_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("group_settings", sa.Column("birthday_media_type", sa.String(length=16), nullable=True))
    op.add_column("group_settings", sa.Column("birthday_media_file_id", sa.String(length=255), nullable=True))
    op.add_column("group_settings", sa.Column("birthday_default_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("group_settings", "birthday_default_message")
    op.drop_column("group_settings", "birthday_media_file_id")
    op.drop_column("group_settings", "birthday_media_type")
    op.drop_column("group_settings", "birthday_media_enabled")
    op.drop_column("group_settings", "birthday_enabled")
