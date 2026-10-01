from alembic import op
import sqlalchemy as sa

revision = "0005_group_registration_game_settings"
down_revision = "0004_scenario_challenge_mode"
branch_labels = None
depends_on = None


def upgrade():
    # Alembic's default version_num column may have been created as VARCHAR(32).
    # This revision id is longer than 32 characters, so widen it before Alembic
    # attempts to persist the new revision number.
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")
    op.add_column("groups", sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("groups", sa.Column("registered_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("games", sa.Column("auto_play", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("games", sa.Column("turn_color", sa.String(length=50), nullable=False, server_default="پیش‌فرض"))
    op.add_column("games", sa.Column("challenge_color", sa.String(length=50), nullable=False, server_default="پیش‌فرض"))
    op.add_column("games", sa.Column("reserve_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column("games", "reserve_enabled")
    op.drop_column("games", "challenge_color")
    op.drop_column("games", "turn_color")
    op.drop_column("games", "auto_play")
    op.drop_column("groups", "registered_by_user_id")
    op.drop_column("groups", "registered_at")
