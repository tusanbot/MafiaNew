from alembic import op
import sqlalchemy as sa

revision = "0016_detailed_stats"
down_revision = "0015_achievements"
branch_labels = None
depends_on = None

USER_COLUMNS = (
    ("kills", "INTEGER NOT NULL DEFAULT 0"),
    ("saves", "INTEGER NOT NULL DEFAULT 0"),
    ("investigations", "INTEGER NOT NULL DEFAULT 0"),
    ("investigation_hits", "INTEGER NOT NULL DEFAULT 0"),
    ("correct_votes", "INTEGER NOT NULL DEFAULT 0"),
    ("challenges_accepted", "INTEGER NOT NULL DEFAULT 0"),
    ("faceoffs", "INTEGER NOT NULL DEFAULT 0"),
    ("faceoff_wins", "INTEGER NOT NULL DEFAULT 0"),
    ("kicks", "INTEGER NOT NULL DEFAULT 0"),
    ("games_survived", "INTEGER NOT NULL DEFAULT 0"),
    ("win_streak", "INTEGER NOT NULL DEFAULT 0"),
    ("best_win_streak", "INTEGER NOT NULL DEFAULT 0"),
)

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    for name, ddl in USER_COLUMNS:
        if name not in user_columns:
            op.add_column("users", sa.Column(name, sa.Integer(), nullable=False, server_default="0"))

    tables = set(inspector.get_table_names())
    if "user_role_stats" not in tables:
        op.create_table(
            "user_role_stats",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("games", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("wins", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("kills", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("saves", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("investigations", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("investigation_hits", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint("user_id", "role_id", name="uq_user_role_stat"),
        )

def downgrade():
    bind = op.get_bind()
    if "user_role_stats" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("user_role_stats")
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("users")}
    for name, _ in reversed(USER_COLUMNS):
        if name in existing:
            op.drop_column("users", name)
