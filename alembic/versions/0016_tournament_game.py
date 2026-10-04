from alembic import op
import sqlalchemy as sa

revision = "0016_tournament_game"
down_revision = "0015_tournaments"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("games", sa.Column("tournament_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_games_tournament_id", "games", "tournaments", ["tournament_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_games_tournament_id", "games", ["tournament_id"])

def downgrade():
    op.drop_index("ix_games_tournament_id", table_name="games")
    op.drop_constraint("fk_games_tournament_id", "games", type_="foreignkey")
    op.drop_column("games", "tournament_id")
