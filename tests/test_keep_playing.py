import random
from datetime import datetime, timedelta

import radio
from models import Play, User, db


def _uid(client):
    client.get("/api/playlists")   # standalone mode attaches the local user on first request
    return User.query.filter_by(username="local").one().id


def test_follows_with_the_same_artist_first_and_skips_the_queue(client, add_track):
    seed = add_track(title="A1", artist="Halcyon")
    same = add_track(title="A2", artist="Halcyon")
    queued = add_track(title="A3", artist="Halcyon")
    others = [add_track(title=f"X{i}", artist=f"Other {i}") for i in range(5)]
    r = client.post("/api/keep-playing", json={"seed": [seed.id], "exclude": [seed.id, queued.id]})
    ids = [t["id"] for t in r.get_json()]
    assert ids[0] == same.id
    assert seed.id not in ids and queued.id not in ids
    assert set(ids) == {same.id, *(o.id for o in others)}


def test_songs_heard_together_come_before_strangers(app, client, add_track):
    uid = _uid(client)
    seed, friend = add_track(title="S", artist="A"), add_track(title="F", artist="B")
    strangers = [add_track(title=f"Z{i}", artist=f"C{i}") for i in range(6)]
    long_ago = datetime.now() - timedelta(days=3)
    for k in range(4):   # four evenings where S and F were played back to back
        at = long_ago - timedelta(days=k)
        db.session.add_all([Play(user_id=uid, track_id=seed.id, played_at=at), Play(user_id=uid, track_id=friend.id, played_at=at + timedelta(minutes=4))])
    db.session.commit()
    picked = radio.pick(uid, [seed.id], [seed.id], rng=random.Random(1))
    assert picked[0].id == friend.id
    assert {t.id for t in picked} == {friend.id, *(s.id for s in strangers)}


def test_just_heard_songs_wait(app, client, add_track):
    uid = _uid(client)
    seed, recent = add_track(title="S", artist="A"), add_track(title="R", artist="A")
    db.session.add(Play(user_id=uid, track_id=recent.id, played_at=datetime.now() - timedelta(minutes=20)))
    db.session.commit()
    assert recent.id not in [t.id for t in radio.pick(uid, [seed.id], [])]


def test_no_artist_twice_running_when_avoidable(app, client, add_track):
    uid = _uid(client)
    seed = add_track(title="S", artist="A")
    for i in range(4):
        add_track(title=f"A{i}", artist="A")
        add_track(title=f"B{i}", artist="B")
    picked = radio.pick(uid, [seed.id], [seed.id], rng=random.Random(2))
    artists = [t.artist for t in picked]
    assert all(a != b for a, b in zip(artists, artists[1:], strict=False))

