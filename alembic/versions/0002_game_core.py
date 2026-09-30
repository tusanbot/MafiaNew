from alembic import op
import sqlalchemy as sa
revision='0002_game_core'
down_revision='0001_initial'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('group_settings',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('group_id',sa.Integer(),sa.ForeignKey('groups.id',ondelete='CASCADE'),unique=True,nullable=False),
        sa.Column('chat_lock',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('night_lock',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('turn_lock',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('custom_emoji',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now()),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now()))
    op.create_table('scenarios',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('key',sa.String(100),unique=True,nullable=False),
        sa.Column('name_fa',sa.String(255),nullable=False),
        sa.Column('min_players',sa.Integer(),nullable=False),
        sa.Column('max_players',sa.Integer(),nullable=False),
        sa.Column('enabled',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('roles',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('key',sa.String(100),unique=True,nullable=False),
        sa.Column('name_fa',sa.String(255),nullable=False),
        sa.Column('team',sa.String(50),nullable=False),
        sa.Column('description',sa.Text(),nullable=False,server_default=''))
    op.create_table('games',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('game_key',sa.String(100),unique=True,nullable=False),
        sa.Column('group_id',sa.Integer(),sa.ForeignKey('groups.id',ondelete='CASCADE'),nullable=False),
        sa.Column('scenario_id',sa.Integer(),sa.ForeignKey('scenarios.id'),nullable=False),
        sa.Column('status',sa.String(30),nullable=False,server_default='waiting'),
        sa.Column('phase',sa.String(30),nullable=False,server_default='lobby'),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now()),
        sa.Column('started_at',sa.DateTime(timezone=True)),
        sa.Column('finished_at',sa.DateTime(timezone=True)))
    op.create_index('ix_games_game_key','games',['game_key'],unique=True)
    op.create_table('game_players',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('game_id',sa.Integer(),sa.ForeignKey('games.id',ondelete='CASCADE'),nullable=False),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('seat',sa.Integer(),nullable=False),
        sa.Column('role_id',sa.Integer(),sa.ForeignKey('roles.id')),
        sa.Column('alive',sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column('joined_at',sa.DateTime(timezone=True),server_default=sa.func.now()))
    op.create_table('game_events',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('game_id',sa.Integer(),sa.ForeignKey('games.id',ondelete='CASCADE'),nullable=False),
        sa.Column('actor_user_id',sa.Integer(),sa.ForeignKey('users.id')),
        sa.Column('event_type',sa.String(50),nullable=False),
        sa.Column('payload',sa.Text(),nullable=False,server_default='{}'),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now()))
    op.create_table('votes',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('game_id',sa.Integer(),sa.ForeignKey('games.id',ondelete='CASCADE'),nullable=False),
        sa.Column('voter_user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('target_user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('round_no',sa.Integer(),nullable=False,server_default='1'),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now()))

def downgrade():
    for t in ['votes','game_events','game_players','games','roles','scenarios','group_settings']:
        op.drop_table(t)
