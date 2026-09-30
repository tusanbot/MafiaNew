from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='0001_initial'; down_revision=None; branch_labels=None; depends_on=None

def upgrade():
    op.create_table('users',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('telegram_id',sa.BigInteger(),nullable=False),sa.Column('username',sa.String(255)),sa.Column('first_name',sa.String(255),nullable=False),sa.Column('last_name',sa.String(255)),sa.Column('display_name',sa.String(255),nullable=False),sa.Column('bio',sa.Text()),sa.Column('games_played',sa.Integer(),nullable=False,server_default='0'),sa.Column('games_won',sa.Integer(),nullable=False,server_default='0'),sa.Column('mafia_wins',sa.Integer(),nullable=False,server_default='0'),sa.Column('citizen_wins',sa.Integer(),nullable=False,server_default='0'),sa.Column('independent_wins',sa.Integer(),nullable=False,server_default='0'),sa.Column('challenges',sa.Integer(),nullable=False,server_default='0'),sa.Column('achievements_count',sa.Integer(),nullable=False,server_default='0'),sa.Column('is_active',sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now()),sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now()))
    op.create_index('ix_users_telegram_id','users',['telegram_id'],unique=True)
    op.create_table('groups',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('telegram_id',sa.BigInteger(),nullable=False),sa.Column('title',sa.String(255),nullable=False),sa.Column('username',sa.String(255)),sa.Column('type',sa.String(32),nullable=False),sa.Column('is_active',sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now()),sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now()))
    op.create_index('ix_groups_telegram_id','groups',['telegram_id'],unique=True)

def downgrade():
    op.drop_index('ix_groups_telegram_id',table_name='groups'); op.drop_table('groups'); op.drop_index('ix_users_telegram_id',table_name='users'); op.drop_table('users')
