from alembic import op
import sqlalchemy as sa

revision = "0006_lobby_reserve_positions"
down_revision = "0005_group_registration_game_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("game_players", sa.Column("is_reserved", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("game_players", sa.Column("reserve_position", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("game_players", "reserve_position")
    op.drop_column("game_players", "is_reserved")
