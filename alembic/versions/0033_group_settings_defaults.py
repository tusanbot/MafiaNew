"""Expand group settings into persistent game, player and notification defaults.

Revision ID: 0033_group_settings_defaults
Revises: 0032_substitute_queue
"""
from alembic import op
import sqlalchemy as sa

revision = "0033_group_settings_defaults"
down_revision = "0032_substitute_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("group_settings", sa.Column("default_scenario_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_group_settings_default_scenario",
        "group_settings",
        "scenarios",
        ["default_scenario_id"],
        ["id"],
        ondelete="SET NULL",
    )
    columns = [
        ("default_auto_play", sa.Boolean(), False),
        ("default_reserve_enabled", sa.Boolean(), True),
        ("default_challenge_enabled", sa.Boolean(), True),
        ("default_challenge_mode", sa.String(20), "limited"),
        ("default_challenge_limit", sa.Integer(), 1),
        ("default_turn_seconds", sa.Integer(), 120),
        ("default_challenge_seconds", sa.Integer(), 60),
        ("default_extra_challenge_seconds", sa.Integer(), 60),
        ("default_next_host_enabled", sa.Boolean(), True),
        ("default_next_player_enabled", sa.Boolean(), True),
        ("default_next_auto_enabled", sa.Boolean(), False),
        ("default_auto_silence_warnings", sa.Boolean(), False),
        ("default_auto_kick_warnings", sa.Boolean(), False),
        ("default_turn_color", sa.String(50), "پیش‌فرض"),
        ("default_challenge_color", sa.String(50), "پیش‌فرض"),
        ("default_turn_color_enabled", sa.Boolean(), True),
        ("default_voting_pre_delay_seconds", sa.Integer(), 10),
        ("default_vote_seconds", sa.Integer(), 10),
        ("default_voting_mode", sa.String(20), "manual"),
        ("default_vote2_selection_mode", sa.String(20), "manual"),
        ("allow_player_join", sa.Boolean(), True),
        ("allow_reserve_queue", sa.Boolean(), True),
        ("allow_substitute_queue", sa.Boolean(), True),
        ("max_warnings", sa.Integer(), 3),
        ("auto_silence_on_max_warning", sa.Boolean(), False),
        ("auto_kick_on_max_warning", sa.Boolean(), False),
    ]
    for name, typ, default in columns:
        op.add_column("group_settings", sa.Column(name, typ, nullable=False, server_default=sa.text(str(default).lower() if isinstance(default, bool) else repr(default))))
    op.add_column(
        "group_settings",
        sa.Column(
            "default_emoji_settings",
            sa.Text(),
            nullable=False,
            server_default='{"death": true, "kick": true, "slaughter": true, "challenge": true, "silence": true, "extra_turn": true, "warning": true}',
        ),
    )
    op.add_column(
        "group_settings",
        sa.Column(
            "notification_settings",
            sa.Text(),
            nullable=False,
            server_default='{"game_start": true, "game_end": true, "role_distribution": true, "player_join_leave": true, "turn": true, "challenge": true, "vote": true, "night": true, "reserve_substitute": true}',
        ),
    )


def downgrade() -> None:
    op.drop_column("group_settings", "notification_settings")
    op.drop_column("group_settings", "default_emoji_settings")
    for name in [
        "auto_kick_on_max_warning", "auto_silence_on_max_warning", "max_warnings",
        "allow_substitute_queue", "allow_reserve_queue", "allow_player_join",
        "default_vote2_selection_mode", "default_voting_mode", "default_vote_seconds",
        "default_voting_pre_delay_seconds", "default_turn_color_enabled",
        "default_challenge_color", "default_turn_color", "default_auto_kick_warnings",
        "default_auto_silence_warnings", "default_next_auto_enabled",
        "default_next_player_enabled", "default_next_host_enabled",
        "default_extra_challenge_seconds", "default_challenge_seconds",
        "default_turn_seconds", "default_challenge_limit", "default_challenge_mode",
        "default_challenge_enabled", "default_reserve_enabled", "default_auto_play",
    ]:
        op.drop_column("group_settings", name)
    op.drop_constraint("fk_group_settings_default_scenario", "group_settings", type_="foreignkey")
    op.drop_column("group_settings", "default_scenario_id")
