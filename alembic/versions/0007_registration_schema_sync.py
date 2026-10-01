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


def _has_fk(table_name: str, column_name: str, referred_table: str, referred_column: str) -> bool:
    bind = op.get_bind()
    for fk in inspect(bind).get_foreign_keys(table_name):
        if fk.get("referred_table") != referred_table:
            continue
        if fk.get("constrained_columns") == [column_name] and fk.get("referred_columns") == [referred_column]:
            return True
    return False


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

    if not _has_fk("users", "registered_by_user_id", "users", "id"):
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

    if not _has_fk("groups", "registered_by_user_id", "users", "id"):
        op.create_foreign_key(
            "fk_groups_registered_by_user_id",
            "groups",
            "users",
            ["registered_by_user_id"],
            ["id"],
        )


def downgrade():
    bind = op.get_bind()
    for fk in inspect(bind).get_foreign_keys("groups"):
        if fk.get("referred_table") == "users" and fk.get("constrained_columns") == ["registered_by_user_id"] and fk.get("name"):
            op.drop_constraint(fk["name"], "groups", type_="foreignkey")
            break
    group_columns = _columns("groups")
    if "registered_by_user_id" in group_columns:
        op.drop_column("groups", "registered_by_user_id")
    if "registered_at" in group_columns:
        op.drop_column("groups", "registered_at")

    bind = op.get_bind()
    for fk in inspect(bind).get_foreign_keys("users"):
        if fk.get("referred_table") == "users" and fk.get("constrained_columns") == ["registered_by_user_id"] and fk.get("name"):
            op.drop_constraint(fk["name"], "users", type_="foreignkey")
            break
    user_columns = _columns("users")
    if "registered_by_user_id" in user_columns:
        op.drop_column("users", "registered_by_user_id")
    if "registered_at" in user_columns:
        op.drop_column("users", "registered_at")
