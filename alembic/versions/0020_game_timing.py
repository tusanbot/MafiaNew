from alembic import op
import sqlalchemy as sa

revision = "0020_game_timing"
down_revision = "0019_notification_preferences"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    scenario_cols = {c["name"] for c in sa.inspect(bind).get_columns("scenarios")}
    game_cols = {c["name"] for c in sa.inspect(bind).get_columns("games")}

    for name, default in (
        ("turn_seconds", 120),
        ("challenge_seconds", 60),
        ("extra_challenge_seconds", 60),
    ):
        if name not in scenario_cols:
            op.add_column("scenarios", sa.Column(name, sa.Integer(), nullable=False, server_default=str(default)))
    for name, default in (
        ("turn_seconds", 120),
        ("challenge_seconds", 60),
        ("extra_challenge_seconds", 60),
    ):
        if name not in game_cols:
            op.add_column("games", sa.Column(name, sa.Integer(), nullable=False, server_default=str(default)))

    for name in ("turn_seconds", "challenge_seconds", "extra_challenge_seconds"):
        if name in scenario_cols:
            op.alter_column("scenarios", name, server_default=None)
        if name in game_cols:
            op.alter_column("games", name, server_default=None)

def downgrade():
    bind = op.get_bind()
    for table in ("games", "scenarios"):
        cols = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        for name in ("extra_challenge_seconds", "challenge_seconds", "turn_seconds"):
            if name in cols:
                op.drop_column(table, name)
