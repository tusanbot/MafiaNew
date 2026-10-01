from alembic import op
import sqlalchemy as sa

revision = "0008_game_management"
down_revision = "0007_registration_schema_sync"
branch_labels = None
depends_on = None


def _add(table, column):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if column.name not in {c["name"] for c in inspector.get_columns(table)}:
        op.add_column(table, column)


def upgrade():
    for column in (
        sa.Column("challenge_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_host_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_player_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_auto_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_silence_warnings", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_kick_warnings", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("turn_color_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("emoji_settings", sa.Text(), nullable=False, server_default='{"death": true, "kick": true, "challenge": true, "silence": true, "extra_turn": true, "warning": true}'),
    ):
        _add("games", column)

    for column in (
        sa.Column("exit_type", sa.String(length=30), nullable=True),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("silence_until_round", sa.Integer(), nullable=True),
        sa.Column("extra_turn_round", sa.Integer(), nullable=True),
    ):
        _add("game_players", column)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    game_columns = {c["name"] for c in inspector.get_columns("games")}
    player_columns = {c["name"] for c in inspector.get_columns("game_players")}
    for name in ("extra_turn_round", "silence_until_round", "warning_count", "exit_type"):
        if name in player_columns:
            op.drop_column("game_players", name)
    for name in ("emoji_settings", "turn_color_enabled", "auto_kick_warnings", "auto_silence_warnings", "next_auto_enabled", "next_player_enabled", "next_host_enabled", "challenge_enabled"):
        if name in game_columns:
            op.drop_column("games", name)
