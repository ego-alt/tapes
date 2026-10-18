"""playlist trash

Revision ID: d41f7b2c9e10
Revises: c3e8a1f05d92
Create Date: 2026-10-18 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd41f7b2c9e10'
down_revision = 'c3e8a1f05d92'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('playlists', schema=None) as batch_op:
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f('ix_playlists_deleted_at'), ['deleted_at'], unique=False)


def downgrade():
    with op.batch_alter_table('playlists', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_playlists_deleted_at'))
        batch_op.drop_column('deleted_at')
