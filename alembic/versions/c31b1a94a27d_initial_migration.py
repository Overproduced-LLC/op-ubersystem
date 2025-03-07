"""Initial migration

Revision ID: c31b1a94a27d
Revises: b4a97b074ef2
Create Date: 2017-09-28 00:09:53.194594

"""


# revision identifiers, used by Alembic.
revision = 'c31b1a94a27d'
down_revision = 'b4a97b074ef2'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
import residue


try:
    is_sqlite = op.get_context().dialect.name == 'sqlite'
except:
    is_sqlite = False

if is_sqlite:
    op.get_context().connection.execute('PRAGMA foreign_keys=ON;')
    utcnow_server_default = "(datetime('now', 'utc'))"
else:
    utcnow_server_default = "timezone('utc', current_timestamp)"

def sqlite_column_reflect_listener(inspector, table, column_info):
    """Adds parenthesis around SQLite datetime defaults for utcnow."""
    if column_info['default'] == "datetime('now', 'utc')":
        column_info['default'] = utcnow_server_default

sqlite_reflect_kwargs = {
    'listeners': [('column_reflect', sqlite_column_reflect_listener)]
}

# ===========================================================================
# HOWTO: Handle alter statements in SQLite
#
# def upgrade():
#     if is_sqlite:
#         with op.batch_alter_table('table_name', reflect_kwargs=sqlite_reflect_kwargs) as batch_op:
#             batch_op.alter_column('column_name', type_=sa.Unicode(), server_default='', nullable=False)
#     else:
#         op.alter_column('table_name', 'column_name', type_=sa.Unicode(), server_default='', nullable=False)
#
# ===========================================================================


def upgrade():
    op.create_table('mits_team',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('panel_interest', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('want_to_sell', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('address', sa.Unicode(), server_default='', nullable=False),
    sa.Column('submitted', residue.UTCDateTime(), nullable=True),
    sa.Column('applied', residue.UTCDateTime(), server_default=sa.text(utcnow_server_default), nullable=False),
    sa.Column('status', sa.Integer(), server_default='196944751', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mits_team'))
    )
    op.create_table('mits_game',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('team_id', residue.UUID(), nullable=False),
    sa.Column('name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('promo_blurb', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.Column('genre', sa.Unicode(), server_default='', nullable=False),
    sa.Column('phase', sa.Integer(), nullable=False),
    sa.Column('min_age', sa.Integer(), nullable=False),
    sa.Column('min_players', sa.Integer(), server_default='2', nullable=False),
    sa.Column('max_players', sa.Integer(), server_default='4', nullable=False),
    sa.Column('personally_own', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('unlicensed', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('professional', sa.Boolean(), server_default='False', nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['mits_team.id'], name=op.f('fk_mits_game_team_id_mits_team')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mits_game'))
    )
    op.create_table('mits_picture',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('team_id', residue.UUID(), nullable=False),
    sa.Column('filename', sa.Unicode(), server_default='', nullable=False),
    sa.Column('content_type', sa.Unicode(), server_default='', nullable=False),
    sa.Column('extension', sa.Unicode(), server_default='', nullable=False),
    sa.Column('description', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['mits_team.id'], name=op.f('fk_mits_picture_team_id_mits_team')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mits_picture'))
    )
    op.create_table('mits_times',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('team_id', residue.UUID(), nullable=False),
    sa.Column('availability', sa.Unicode(), server_default='', nullable=False),
    sa.Column('multiple_tables', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['mits_team.id'], name=op.f('fk_mits_times_team_id_mits_team')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mits_times'))
    )
    op.create_table('mits_applicant',
    sa.Column('id', residue.UUID(), nullable=False),
    sa.Column('team_id', residue.UUID(), nullable=False),
    sa.Column('attendee_id', residue.UUID(), nullable=True),
    sa.Column('primary_contact', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('first_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('last_name', sa.Unicode(), server_default='', nullable=False),
    sa.Column('email', sa.Unicode(), server_default='', nullable=False),
    sa.Column('cellphone', sa.Unicode(), server_default='', nullable=False),
    sa.Column('contact_method', sa.Integer(), server_default='42059704', nullable=False),
    sa.Column('declined_hotel_space', sa.Boolean(), server_default='False', nullable=False),
    sa.Column('requested_room_nights', sa.Unicode(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['attendee_id'], ['attendee.id'], name=op.f('fk_mits_applicant_attendee_id_attendee')),
    sa.ForeignKeyConstraint(['team_id'], ['mits_team.id'], name=op.f('fk_mits_applicant_team_id_mits_team')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mits_applicant'))
    )


def downgrade():
    op.drop_table('mits_applicant')
    op.drop_table('mits_times')
    op.drop_table('mits_picture')
    op.drop_table('mits_game')
    op.drop_table('mits_team')
