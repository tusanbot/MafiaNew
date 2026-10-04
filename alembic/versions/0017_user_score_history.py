from alembic import op
import sqlalchemy as sa

revision = "0017_user_score_history"
down_revision = "0016_tournament_game"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "user_score_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id", ondelete="SET NULL"), nullable=True),
        sa.Column("score_before", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score_delta", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score_after", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rank_position", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_score_history_user_id", "user_score_history", ["user_id"])
    op.create_index("ix_user_score_history_game_id", "user_score_history", ["game_id"])
    op.create_index("ix_user_score_history_created_at", "user_score_history", ["created_at"])

def downgrade():
    op.drop_index("ix_user_score_history_created_at", table_name="user_score_history")
    op.drop_index("ix_user_score_history_game_id", table_name="user_score_history")
    op.drop_index("ix_user_score_history_user_id", table_name="user_score_history")
    op.drop_table("user_score_history")
