from alembic import op
import sqlalchemy as sa

revision = "0003_game_host_seed"
down_revision = "0002_game_core"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("games", sa.Column("host_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))

    scenarios = sa.table(
        "scenarios",
        sa.column("key", sa.String),
        sa.column("name_fa", sa.String),
        sa.column("min_players", sa.Integer),
        sa.column("max_players", sa.Integer),
        sa.column("enabled", sa.Boolean),
    )
    op.bulk_insert(
        scenarios,
        [{
            "key": "classic",
            "name_fa": "کلاسیک",
            "min_players": 7,
            "max_players": 20,
            "enabled": True,
        }],
    )

    roles = sa.table(
        "roles",
        sa.column("key", sa.String),
        sa.column("name_fa", sa.String),
        sa.column("team", sa.String),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(
        roles,
        [
            {"key": "godfather", "name_fa": "پدرخوانده", "team": "mafia", "description": "رهبر تیم مافیا"},
            {"key": "mafia", "name_fa": "مافیا", "team": "mafia", "description": "عضو تیم مافیا"},
            {"key": "doctor", "name_fa": "دکتر", "team": "citizen", "description": "نقش حمایتی شهروند"},
            {"key": "detective", "name_fa": "کارآگاه", "team": "citizen", "description": "نقش اطلاعاتی شهروند"},
            {"key": "citizen", "name_fa": "شهروند", "team": "citizen", "description": "شهروند عادی"},
        ],
    )

def downgrade():
    op.drop_column("games", "host_user_id")
