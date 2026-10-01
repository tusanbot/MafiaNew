from alembic import op
import sqlalchemy as sa

revision = "0010_challenge_mode"
down_revision = "0009_player_score"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("games")}
    if "challenge_mode" not in cols:
        op.add_column("games", sa.Column("challenge_mode", sa.String(length=20), nullable=False, server_default="limited"))


def downgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("games")}
    if "challenge_mode" in cols:
        op.drop_column("games", "challenge_mode")
