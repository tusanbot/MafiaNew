from alembic import op
import sqlalchemy as sa

revision = "0015_tournaments"
down_revision = "0014_godfather_maverick"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("tournaments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("emoji", sa.String(20), nullable=False, server_default="🏆"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prize_points", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("group_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tournaments_group_id", "tournaments", ["group_id"])
    op.create_table("tournament_players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_no", sa.Integer(), nullable=True),
        sa.Column("final_rank", sa.Integer(), nullable=True),
        sa.Column("awarded_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tournament_id", "user_id", name="uq_tournament_player"))
    op.create_index("ix_tournament_players_tournament_id", "tournament_players", ["tournament_id"])
    op.create_index("ix_tournament_players_user_id", "tournament_players", ["user_id"])
    op.create_table("tournament_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_no", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tournament_id", "group_no", name="uq_tournament_group_no"))
    op.create_index("ix_tournament_groups_tournament_id", "tournament_groups", ["tournament_id"])

def downgrade():
    op.drop_table("tournament_groups")
    op.drop_table("tournament_players")
    op.drop_table("tournaments")
