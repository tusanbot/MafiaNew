from alembic import op
import sqlalchemy as sa

revision = "0004_scenario_challenge_mode"
down_revision = "0003_game_host_seed"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("scenarios", sa.Column("challenge_mode", sa.String(length=20), nullable=False, server_default="limited"))
    op.execute(sa.text("UPDATE scenarios SET challenge_mode='limited' WHERE key='classic'"))


def downgrade():
    op.drop_column("scenarios", "challenge_mode")
