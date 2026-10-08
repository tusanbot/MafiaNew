"""Add per-user birthday message and media.

Revision ID: 0044_birthday_user_content
Revises: 0043_invitation_button
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0044_birthday_user_content"
down_revision: Union[str, Sequence[str], None] = "0043_invitation_button"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "birthday_message" not in columns:
        op.add_column("users", sa.Column("birthday_message", sa.Text(), nullable=True))
    if "birthday_media_type" not in columns:
        op.add_column("users", sa.Column("birthday_media_type", sa.String(length=16), nullable=True))
    if "birthday_media_file_id" not in columns:
        op.add_column("users", sa.Column("birthday_media_file_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "birthday_media_file_id" in columns:
        op.drop_column("users", "birthday_media_file_id")
    if "birthday_media_type" in columns:
        op.drop_column("users", "birthday_media_type")
    if "birthday_message" in columns:
        op.drop_column("users", "birthday_message")
