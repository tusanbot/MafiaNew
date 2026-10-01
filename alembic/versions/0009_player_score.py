from alembic import op
import sqlalchemy as sa

revision = "0009_player_score"
down_revision = "0008_game_management"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "score" not in cols:
        op.add_column("users", sa.Column("score", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "score" in cols:
        op.drop_column("users", "score")
