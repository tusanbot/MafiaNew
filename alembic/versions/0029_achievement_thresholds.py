from alembic import op
import sqlalchemy as sa

revision = "0029_achievement_thresholds"
down_revision = "0028_group_settings_custom_emoji"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Rename legacy achievement keys so existing earned rows remain attached
    # to the same achievement record while the progression rules change.
    renames = {
        "challenge_10": "challenge_100",
        "challenge_50": "challenge_games_50",
        "mafia_master": "mafia_20",
        "citizen_master": "citizen_20",
        "independent_master": "independent_3",
        "army_one": "independent_5",
    }
    for old_key, new_key in renames.items():
        bind.execute(
            sa.text(
                "UPDATE achievements SET key = :new_key "
                "WHERE key = :old_key AND NOT EXISTS "
                "(SELECT 1 FROM achievements WHERE key = :new_key)"
            ),
            {"old_key": old_key, "new_key": new_key},
        )


def downgrade():
    bind = op.get_bind()
    renames = {
        "challenge_100": "challenge_10",
        "challenge_games_50": "challenge_50",
        "mafia_20": "mafia_master",
        "citizen_20": "citizen_master",
        "independent_3": "independent_master",
        "independent_5": "army_one",
    }
    for new_key, old_key in renames.items():
        bind.execute(
            sa.text(
                "UPDATE achievements SET key = :old_key "
                "WHERE key = :new_key AND NOT EXISTS "
                "(SELECT 1 FROM achievements WHERE key = :old_key)"
            ),
            {"old_key": old_key, "new_key": new_key},
        )
