from alembic import op
import sqlalchemy as sa

revision = "0003_game_host_seed"
down_revision = "0002_game_core"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("games", sa.Column("host_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))

    op.execute(sa.text("""
        INSERT INTO scenarios (key, name_fa, min_players, max_players, enabled)
        VALUES ('classic', 'کلاسیک', 7, 20, TRUE)
        ON CONFLICT (key) DO NOTHING
    """))

    op.execute(sa.text("""
        INSERT INTO roles (key, name_fa, team, description)
        VALUES
          ('godfather', 'پدرخوانده', 'mafia', 'رهبر تیم مافیا'),
          ('mafia', 'مافیا', 'mafia', 'عضو تیم مافیا'),
          ('doctor', 'دکتر', 'citizen', 'نقش حمایتی شهروند'),
          ('detective', 'کارآگاه', 'citizen', 'نقش اطلاعاتی شهروند'),
          ('citizen', 'شهروند', 'citizen', 'شهروند عادی')
        ON CONFLICT (key) DO NOTHING
    """))

def downgrade():
    op.drop_column("games", "host_user_id")
