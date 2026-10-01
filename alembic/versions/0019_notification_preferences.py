from alembic import op
import sqlalchemy as sa

revision = "0019_notification_preferences"
down_revision = "0018_seed_scenario_roles"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    for name in ("notify_game_result","notify_achievements","notify_rank_changes","notify_challenges","notify_turns"):
        if name not in cols:
            op.add_column("users", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()))
    for name in ("notify_game_result","notify_achievements","notify_rank_changes","notify_challenges","notify_turns"):
        op.alter_column("users", name, server_default=None)

def downgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    for name in ("notify_turns","notify_challenges","notify_rank_changes","notify_achievements","notify_game_result"):
        if name in cols:
            op.drop_column("users", name)
