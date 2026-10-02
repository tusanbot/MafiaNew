from alembic import op
import sqlalchemy as sa

revision = "0028_group_settings_custom_emoji"
down_revision = "0027_vote2_integrity"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "group_settings" not in inspector.get_table_names():
        op.create_table(
            "group_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "group_id",
                sa.Integer(),
                sa.ForeignKey("groups.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("chat_lock", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("night_lock", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("turn_lock", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("custom_emoji", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    else:
        columns = {c["name"] for c in inspector.get_columns("group_settings")}
        if "custom_emoji" not in columns:
            op.add_column(
                "group_settings",
                sa.Column("custom_emoji", sa.Boolean(), nullable=False, server_default=sa.false()),
            )


def downgrade():
    bind = op.get_bind()
    if "group_settings" in sa.inspect(bind).get_table_names():
        op.drop_table("group_settings")
