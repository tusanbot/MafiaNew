"""Add group invitation settings and exceptions.
Revision ID: 0042_group_invitation
Revises: 0041_lobby_profile_cache
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0042_group_invitation"
down_revision: Union[str, Sequence[str], None] = "0041_lobby_profile_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "group_invitation_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("default_message", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("group_id", name="uq_group_invitation_setting"),
    )
    op.create_index(
        "ix_group_invitation_settings_group_id",
        "group_invitation_settings",
        ["group_id"],
        unique=True,
    )
    op.create_table(
        "group_invitation_exceptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint(
            "group_id",
            "user_id",
            name="uq_group_invitation_exception",
        ),
    )
    op.create_index(
        "ix_group_invitation_exceptions_group_id",
        "group_invitation_exceptions",
        ["group_id"],
    )
    op.create_index(
        "ix_group_invitation_exceptions_user_id",
        "group_invitation_exceptions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_group_invitation_exceptions_user_id", table_name="group_invitation_exceptions")
    op.drop_index("ix_group_invitation_exceptions_group_id", table_name="group_invitation_exceptions")
    op.drop_table("group_invitation_exceptions")
    op.drop_index("ix_group_invitation_settings_group_id", table_name="group_invitation_settings")
    op.drop_table("group_invitation_settings")
