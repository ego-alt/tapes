"""baseline schema

The schema as it stood when tapes moved to Flask-Migrate. Earlier versions
built tables with create_all() and patched old databases with best-effort
ALTER TABLE statements that swallowed errors. This revision does both jobs
explicitly:

- a fresh database gets every table;
- an existing pre-migration database gets whichever tables, columns and
  indexes it's missing (each one checked first, so nothing is silently
  skipped: if an ALTER fails, the upgrade fails and the app doesn't start),
  plus the one-off copy of the old single-row `playstate` into
  `playback_sessions`.

Revision ID: 5f68c7bf669f
Revises:
Create Date: 2026-10-15 12:42:36.868965

"""
from alembic import op
import sqlalchemy as sa


revision = "5f68c7bf669f"
down_revision = None
branch_labels = None
depends_on = None

NOW = sa.text("(CURRENT_TIMESTAMP)")
meta = sa.MetaData()

sa.Table(
    "tracks", meta,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("file_path", sa.String(), nullable=False, unique=True),
    sa.Column("file_hash", sa.String(), index=True),
    sa.Column("title", sa.String(), nullable=False),
    sa.Column("artist", sa.String(), index=True),
    sa.Column("album", sa.String(), index=True),
    sa.Column("source_url", sa.String(), index=True),
    sa.Column("needs_llm", sa.Boolean(), server_default=sa.text("0")),
    sa.Column("fingerprint", sa.Text()),
    sa.Column("track_no", sa.Integer()),
    sa.Column("duration_s", sa.Float()),
    sa.Column("bitrate", sa.Integer()),
    sa.Column("size_bytes", sa.Integer()),
    sa.Column("has_cover", sa.Boolean()),
    sa.Column("mtime", sa.Float()),
    sa.Column("added_at", sa.DateTime(), server_default=NOW),
    sa.Column("deleted_at", sa.DateTime(), index=True),
)
sa.Table(
    "users", meta,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("username", sa.String(), nullable=False, unique=True),
    sa.Column("password_hash", sa.String()),
    sa.Column("created_at", sa.DateTime(), server_default=NOW),
)
sa.Table(
    "playback_sessions", meta,
    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
    sa.Column("context", sa.String(), primary_key=True),
    sa.Column("queue_json", sa.Text()),
    sa.Column("cursor", sa.Integer()),
    sa.Column("position_s", sa.Float()),
    sa.Column("updated_at", sa.DateTime(), server_default=NOW),
)
sa.Table(
    "playlists", meta,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("name", sa.String(), nullable=False),
    sa.Column("created_at", sa.DateTime(), server_default=NOW),
)
sa.Table(
    "plays", meta,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=False),
    sa.Column("played_at", sa.DateTime(), server_default=NOW, index=True),
)
sa.Table(
    "shows", meta,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("title", sa.String(), nullable=False),
    sa.Column("source_type", sa.String(), nullable=False),
    sa.Column("source_url", sa.String(), nullable=False),
    sa.Column("channel_id", sa.String(), index=True),
    sa.Column("description", sa.Text()),
    sa.Column("has_image", sa.Boolean()),
    sa.Column("created_at", sa.DateTime(), server_default=NOW),
    sa.Column("last_refreshed_at", sa.DateTime()),
)
sa.Table(
    "episodes", meta,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("show_id", sa.Integer(), sa.ForeignKey("shows.id"), index=True),
    sa.Column("guid", sa.String(), index=True),
    sa.Column("title", sa.String(), nullable=False),
    sa.Column("source_url", sa.String(), nullable=False),
    sa.Column("source_type", sa.String(), nullable=False),
    sa.Column("channel_id", sa.String()),
    sa.Column("file_path", sa.String()),
    sa.Column("status", sa.String(), nullable=False),
    sa.Column("duration_s", sa.Float()),
    sa.Column("description", sa.Text()),
    sa.Column("published_at", sa.DateTime(), index=True),
    sa.Column("added_at", sa.DateTime(), server_default=NOW),
    sa.Column("position_s", sa.Float()),
    sa.Column("played", sa.Boolean(), index=True),
)
sa.Table(
    "playlist_tracks", meta,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("playlist_id", sa.Integer(), sa.ForeignKey("playlists.id"), nullable=False, index=True),
    sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=False),
    sa.Column("position", sa.Integer(), nullable=False),
)
sa.Table(
    "download_jobs", meta,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("url", sa.String(), nullable=False),
    sa.Column("status", sa.String(), nullable=False),
    sa.Column("progress", sa.Float()),
    sa.Column("message", sa.String()),
    sa.Column("kind", sa.String(), nullable=False, server_default="music"),
    sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id")),
    sa.Column("playlist_id", sa.Integer(), sa.ForeignKey("playlists.id")),
    sa.Column("episode_id", sa.Integer(), sa.ForeignKey("episodes.id")),
    sa.Column("created_at", sa.DateTime(), server_default=NOW, index=True),
    sa.Column("outcome", sa.String()),
    sa.Column("finished_at", sa.DateTime(), index=True),
    sa.Column("dismissed", sa.Boolean(), server_default=sa.text("0")),
)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())
    adopted = "tracks" in existing   # a database from before migrations

    for table in meta.sorted_tables:
        if table.name not in existing:
            table.create(bind)   # with its indexes
            continue
        have_cols = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in have_cols:
                op.add_column(table.name, col._copy())
        have_ix = {i["name"] for i in insp.get_indexes(table.name)}
        for ix in table.indexes:
            if ix.name not in have_ix:
                op.create_index(ix.name, table.name, [c.name for c in ix.columns])

    # The old single-row playstate becomes the 'music' playback session
    # (the old table is left in place; it's no longer read).
    if adopted and "playstate" in existing:
        bind.execute(sa.text(
            'INSERT OR IGNORE INTO playback_sessions (user_id, context, queue_json, "cursor", position_s) '
            'SELECT user_id, \'music\', queue_json, COALESCE("index", 0), COALESCE(position_s, 0) FROM playstate'))


def downgrade():
    for table in reversed(meta.sorted_tables):
        op.drop_table(table.name)
