from alembic import op
import sqlalchemy as sa

revision = "0036_achievement_tag_custom_emoji"
down_revision = "0035_custom_emoji_registry"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("achievements")}
    if "custom_emoji_id" not in columns:
        op.add_column("achievements", sa.Column("custom_emoji_id", sa.String(32), nullable=True))
    if "tag_custom_emoji_id" not in columns:
        op.add_column("achievements", sa.Column("tag_custom_emoji_id", sa.String(32), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("achievements")}
    if "tag_custom_emoji_id" in columns:
        op.drop_column("achievements", "tag_custom_emoji_id")
    if "custom_emoji_id" in columns:
        op.drop_column("achievements", "custom_emoji_id")
