"""Add result viewer storage and group tab cooldown settings.

Revision ID: 0034_result_viewer_cooldown
Revises: 0033_group_settings_defaults
"""
from alembic import op
import sqlalchemy as sa

revision = "0034_result_viewer_cooldown"
down_revision = "0033_group_settings_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "group_settings",
        sa.Column("result_tab_last_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "group_settings",
        sa.Column("result_tab_cooldown_seconds", sa.Integer(), nullable=False, server_default="10"),
    )
    op.create_table(
        "game_result_viewers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("current_view", sa.String(20), nullable=False, server_default="result"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("game_id", "user_id", name="uq_game_result_viewer"),
    )


def downgrade() -> None:
    op.drop_table("game_result_viewers")
    op.drop_column("group_settings", "result_tab_cooldown_seconds")
    op.drop_column("group_settings", "result_tab_last_changed_at")
