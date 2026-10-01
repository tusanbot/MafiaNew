from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0007_registration_schema_sync"
down_revision = "0006_lobby_reserve_positions"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {column["name"] for column in inspect(bind).get_columns(table_name)}


def _foreign_keys(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {
        fk.get("name")
        for fk in inspect(bind).get_foreign_keys(table_name)
        if fk.get("name")
    }


def upgrade():
    # Reconcile the live Railway schema with the current ORM models.
    # This is intentionally idempotent so it is safe for databases that already
    # passed 0005/0006 as well as fresh databases.
    user_columns = _columns("users")
    if "registered_at" not in user_columns:
        op.add_column(
            "users",
            sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "registered_by_user_id" not in user_columns:
        op.add_column(
            "users",
            sa.Column("registered_by_user_id", sa.Integer(), nullable=True),
        )

    user_fks = _foreign_keys("users")
    if "fk_users_registered_by_user_id" not in user_fks:
        op.create_foreign_key(
            "fk_users_registered_by_user_id",
            "users",
            "users",
            ["registered_by_user_id"],
            ["id"],
        )

    group_columns = _columns("groups")
    if "registered_at" not in group_columns:
        op.add_column(
            "groups",
            sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "registered_by_user_id" not in group_columns:
        op.add_column(
            "groups",
            sa.Column("registered_by_user_id", sa.Integer(), nullable=True),
        )

    group_fks = _foreign_keys("groups")
    if "fk_groups_registered_by_user_id" not in group_fks:
        op.create_foreign_key(
            "fk_groups_registered_by_user_id",
            "groups",
            "users",
            ["registered_by_user_id"],
            ["id"],
        )


def downgrade():
    group_fks = _foreign_keys("groups")
    if "fk_groups_registered_by_user_id" in group_fks:
        op.drop_constraint("fk_groups_registered_by_user_id", "groups", type_="foreignkey")
    group_columns = _columns("groups")
    if "registered_by_user_id" in group_columns:
        op.drop_column("groups", "registered_by_user_id")
    if "registered_at" in group_columns:
        op.drop_column("groups", "registered_at")

    user_fks = _foreign_keys("users")
    if "fk_users_registered_by_user_id" in user_fks:
        op.drop_constraint("fk_users_registered_by_user_id", "users", type_="foreignkey")
    user_columns = _columns("users")
    if "registered_by_user_id" in user_columns:
        op.drop_column("users", "registered_by_user_id")
    if "registered_at" in user_columns:
        op.drop_column("users", "registered_at")
