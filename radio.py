"""Keep playing: songs to follow when a tape or album runs out.

Picks from your own listening, nothing outside the library: songs you've
played close in time to the ones just heard (the same sitting, both ways),
then the same artists and albums, then your favourites, with a little chance
so it isn't the same run each time. Songs played in the last couple of hours
and anything already queued are left out, and no artist plays twice in a row
when it can be helped.
"""
import math
import random
from collections import Counter
from datetime import datetime, timedelta

from models import Play, Track, db

SESSION = timedelta(minutes=45)      # plays this close together count as one sitting
RECENT = timedelta(hours=2)          # just heard: skip
WEIGHTS = {"together": 2.0, "artist": 3.0, "album": 1.5, "favourite": 0.6, "chance": 1.0}


def _together(user_id: int, seed_ids: list[int]) -> Counter:
    """How often each song was played within a sitting of a seed song."""
    seed_plays = (db.session.query(Play.played_at).filter(Play.user_id == user_id, Play.track_id.in_(seed_ids))
                  .order_by(Play.played_at.desc()).limit(200).all())
    near = Counter()
    for (at,) in seed_plays:
        if at is None:
            continue
        rows = (db.session.query(Play.track_id).filter(Play.user_id == user_id, Play.played_at.between(at - SESSION, at + SESSION))
                .all())
        near.update(tid for (tid,) in rows)
    return near


def pick(user_id: int, seed_ids: list[int], exclude_ids: list[int], limit: int = 15, rng: random.Random | None = None) -> list[Track]:
    rng = rng or random.Random()
    seeds = Track.query.filter(Track.id.in_(seed_ids)).all() if seed_ids else []
    artists = Counter(t.artist.lower() for t in seeds if t.artist)
    albums = {(t.album.lower(), (t.artist or "").lower()) for t in seeds if t.album}
    together = _together(user_id, seed_ids) if seed_ids else Counter()
    plays = Counter(dict(db.session.query(Play.track_id, db.func.count()).filter(Play.user_id == user_id).group_by(Play.track_id).all()))
    recent = {tid for (tid,) in db.session.query(Play.track_id).filter(Play.user_id == user_id, Play.played_at >= datetime.now() - RECENT)}
    skip = set(exclude_ids) | set(seed_ids) | recent

    scored = []
    for t in Track.query.all():
        if t.id in skip:
            continue
        score = WEIGHTS["chance"] * rng.random()
        score += WEIGHTS["together"] * math.log1p(together.get(t.id, 0))
        if t.artist and t.artist.lower() in artists:
            score += WEIGHTS["artist"] * min(1.0, artists[t.artist.lower()] / max(1, len(seeds)) * 2)
        if t.album and (t.album.lower(), (t.artist or "").lower()) in albums:
            score += WEIGHTS["album"]
        score += WEIGHTS["favourite"] * math.log1p(plays.get(t.id, 0))
        scored.append((score, t))
    scored.sort(key=lambda st: st[0], reverse=True)
    return _spread([t for _, t in scored[: limit * 2]], limit)


def _spread(tracks: list[Track], limit: int) -> list[Track]:
    """Best first, but never the same artist twice running when another will do."""
    out, pool = [], list(tracks)
    while pool and len(out) < limit:
        last = (out[-1].artist or "").lower() if out else None
        i = next((k for k, t in enumerate(pool) if (t.artist or "").lower() != last), 0)
        out.append(pool.pop(i))
    return out
