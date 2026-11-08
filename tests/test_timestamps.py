"""Every timestamp is stored as UTC and read back with its zone, so the times
sent to the browser end in +00:00 (one without a zone is read as local)."""
import time

from sqlalchemy import DateTime

import podcasts
from models import Episode, User, db


def test_every_timestamp_column_is_utc():
    plain = [f"{t.name}.{c.name}" for t in db.metadata.tables.values() for c in t.columns if isinstance(c.type, DateTime)]
    assert plain == []


def test_an_episode_is_sent_with_its_zone(client):
    client.get("/")
    feed_time = time.strptime("2026-11-07 23:30", "%Y-%m-%d %H:%M")   # feedparser's struct_time, in UTC
    ep = Episode(user_id=User.query.one().id, title="Pilot", source_url="http://x/1.mp3", source_type="rss",
                 status="new", published_at=podcasts._struct_to_dt(feed_time))
    db.session.add(ep)
    db.session.commit()
    db.session.expire_all()
    assert ep.to_dict()["published_at"] == "2026-11-07T23:30:00+00:00"
