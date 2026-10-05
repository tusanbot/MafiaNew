"""Add user birthdays and birthday announcement tracking.

Revision ID: 0038_birthdays
Revises: 0037_merge_heads
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0038_birthdays"
down_revision: Union[str, Sequence[str], None] = "0037_merge_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("birthday", sa.DateTime(timezone=False), nullable=True))
    op.create_table(
        "birthday_announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("birthday_key", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("group_id", "user_id", "birthday_key", name="uq_birthday_announcement"),
    )
    op.create_index("ix_birthday_announcements_group_id", "birthday_announcements", ["group_id"])
    op.create_index("ix_birthday_announcements_user_id", "birthday_announcements", ["user_id"])
    op.create_index("ix_birthday_announcements_birthday_key", "birthday_announcements", ["birthday_key"])


def downgrade() -> None:
    op.drop_index("ix_birthday_announcements_birthday_key", table_name="birthday_announcements")
    op.drop_index("ix_birthday_announcements_user_id", table_name="birthday_announcements")
    op.drop_index("ix_birthday_announcements_group_id", table_name="birthday_announcements")
    op.drop_table("birthday_announcements")
    op.drop_column("users", "birthday")
