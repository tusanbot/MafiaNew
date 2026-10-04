"""Store configurable Telegram Custom Emoji IDs for groups and games."""

from alembic import op
import sqlalchemy as sa

revision = "0035_custom_emoji_registry"
down_revision = "0034_result_viewer_cooldown"
branch_labels = None
depends_on = None

_DEFAULT_IDS = "{}"


def upgrade() -> None:
    op.add_column(
        "group_settings",
        sa.Column("custom_emoji_ids", sa.Text(), nullable=False, server_default=_DEFAULT_IDS),
    )
    op.add_column(
        "games",
        sa.Column("custom_emoji_ids", sa.Text(), nullable=False, server_default=_DEFAULT_IDS),
    )
    op.add_column(
        "games",
        sa.Column("custom_emoji_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("games", "custom_emoji_enabled")
    op.drop_column("games", "custom_emoji_ids")
    op.drop_column("group_settings", "custom_emoji_ids")
