"""Per-attempt detail of the latest heartbeat each collector sent for a check (#check-attempts): the
``check_heartbeats`` table. One row per (check, server), replaced on every report; ``attempts`` is NULL when the
reporting collector is older and sent no detail, so the API can say "no details" instead of inventing a success.

Revision 0004, after 0003.
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "check_heartbeats" not in tables:
        op.create_table(
            'check_heartbeats',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('check_id', sa.Integer(), nullable=False),
            sa.Column('server_id', sa.Integer(), nullable=False),
            sa.Column('time', sa.DateTime(timezone=True), nullable=False),
            sa.Column('ok', sa.Boolean(), nullable=False),
            sa.Column('attempts', sa.Text(), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['check_id'], ['checks.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('check_id', 'server_id'),
        )
        op.create_index('ix_check_heartbeats_check', 'check_heartbeats', ['check_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_check_heartbeats_check', table_name='check_heartbeats')
    op.drop_table('check_heartbeats')
