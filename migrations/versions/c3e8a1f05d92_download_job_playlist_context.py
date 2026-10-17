"""download job playlist context

Revision ID: c3e8a1f05d92
Revises: b7d1e2f3a4c5
Create Date: 2026-10-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3e8a1f05d92'
down_revision = 'b7d1e2f3a4c5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('download_jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_playlist', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('playlist_index', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('download_jobs', schema=None) as batch_op:
        batch_op.drop_column('playlist_index')
        batch_op.drop_column('source_playlist')
