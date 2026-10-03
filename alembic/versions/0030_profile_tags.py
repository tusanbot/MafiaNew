from alembic import op
import sqlalchemy as sa

revision = "0030_profile_tags"
down_revision = "0029_achievement_thresholds"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    achievement_columns = {c["name"] for c in inspector.get_columns("achievements")}

    if "name_base" not in user_columns:
        op.add_column("users", sa.Column("name_base", sa.String(255), nullable=True))
    if "display_name_custom" not in user_columns:
        op.add_column("users", sa.Column("display_name_custom", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "active_tag_key" not in user_columns:
        op.add_column("users", sa.Column("active_tag_key", sa.String(100), nullable=True))

    if "tag_key" not in achievement_columns:
        op.add_column("achievements", sa.Column("tag_key", sa.String(100), nullable=True))
    if "tag_name" not in achievement_columns:
        op.add_column("achievements", sa.Column("tag_name", sa.String(255), nullable=True))
    if "tag_emoji" not in achievement_columns:
        op.add_column("achievements", sa.Column("tag_emoji", sa.String(20), nullable=True))

    op.execute(sa.text("UPDATE users SET name_base = COALESCE(NULLIF(name_base, ''), display_name) WHERE name_base IS NULL OR name_base = ''"))

    tag_rows = [
        ("first_game", "تازه‌کار", "🎮"),
        ("first_win", "برنده", "🏆"),
        ("ten_games", "باتجربه", "⭐"),
        ("ten_wins", "حرفه‌ای", "🥇"),
        ("mafia_20", "مافیای کارکشته", "🩸"),
        ("citizen_20", "شهروند کارکشته", "🛡️"),
        ("independent_3", "مستقل", "🧭"),
        ("challenge_100", "چالش‌گر", "⚔️"),
        ("five_win_streak", "استرایکر", "⚡"),
    ]
    for key, name, emoji in tag_rows:
        op.execute(
            sa.text("UPDATE achievements SET tag_key=:key, tag_name=:name, tag_emoji=:emoji WHERE key=:key"),
            {"key": key, "name": name, "emoji": emoji},
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    achievement_columns = {c["name"] for c in inspector.get_columns("achievements")}
    if "active_tag_key" in user_columns:
        op.drop_column("users", "active_tag_key")
    if "display_name_custom" in user_columns:
        op.drop_column("users", "display_name_custom")
    if "name_base" in user_columns:
        op.drop_column("users", "name_base")
    if "tag_emoji" in achievement_columns:
        op.drop_column("achievements", "tag_emoji")
    if "tag_name" in achievement_columns:
        op.drop_column("achievements", "tag_name")
    if "tag_key" in achievement_columns:
        op.drop_column("achievements", "tag_key")
