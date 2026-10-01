from alembic import op
import sqlalchemy as sa

revision = "0012_game_challenge_limit"
down_revision = "0011_legacy_scenarios"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("games", sa.Column("challenge_limit", sa.Integer(), nullable=True, server_default="1"))
    op.execute(sa.text("""
        UPDATE games g SET challenge_limit=s.challenge_limit
        FROM scenarios s WHERE s.id=g.scenario_id
    """))

def downgrade():
    op.drop_column("games", "challenge_limit")
