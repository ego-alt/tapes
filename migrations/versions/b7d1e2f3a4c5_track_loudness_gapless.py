"""track loudness + gapless info

Revision ID: b7d1e2f3a4c5
Revises: aa3300c382ff
Create Date: 2026-10-16 14:30:00

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b7d1e2f3a4c5'
down_revision = 'aa3300c382ff'
branch_labels = None
depends_on = None

COLUMNS = [
    ('loudness_lufs', sa.Float()),
    ('true_peak_db', sa.Float()),
    ('album_loudness_lufs', sa.Float()),
    ('album_peak_db', sa.Float()),
    ('sample_rate', sa.Integer()),
    ('enc_delay', sa.Integer()),
    ('enc_padding', sa.Integer()),
    ('audio_samples', sa.Integer()),
    ('audio_analyzed_at', sa.DateTime()),
]


def upgrade():
    with op.batch_alter_table('tracks', schema=None) as batch_op:
        for name, type_ in COLUMNS:
            batch_op.add_column(sa.Column(name, type_, nullable=True))


def downgrade():
    with op.batch_alter_table('tracks', schema=None) as batch_op:
        for name, _ in reversed(COLUMNS):
            batch_op.drop_column(name)
