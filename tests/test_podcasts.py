from models import Episode, User, db


def test_episode_dict_says_where_it_streams_from(client):
    client.get("/")
    uid = User.query.one().id
    ep = Episode(user_id=uid, title="Pilot", source_url="https://example.com/ep1.mp3",
                 source_type="rss", status="new")
    db.session.add(ep)
    db.session.commit()
    d = ep.to_dict()
    assert d["source_type"] == "rss" and d["source_url"] == "https://example.com/ep1.mp3"



def test_hidden_episode_stays_hidden_after_refresh(app, client):
    """Hiding keeps the row (so a feed refresh can't re-add it) and drops it
    from the show's list and counts; unhide brings it back."""
    import podcasts
    from models import Episode, Show, User, db

    client.get("/api/podcast/shows")   # attaches the local user
    uid = User.query.first().id
    show = Show(user_id=uid, title="Feed", source_type="rss", source_url="http://x/feed")
    db.session.add(show)
    db.session.commit()
    feed = [{"guid": g, "title": t, "source_url": f"http://x/{g}.mp3", "source_type": "rss"}
            for g, t in (("g1", "One"), ("g2", "Two"))]
    podcasts.upsert_episodes(uid, show.id, feed)
    db.session.commit()
    ep = Episode.query.filter_by(guid="g1").first()

    assert client.post(f"/api/podcast/episodes/{ep.id}/hide").status_code == 200
    assert podcasts.upsert_episodes(uid, show.id, feed) == 0   # a refresh adds nothing back
    db.session.commit()
    listed = client.get(f"/api/podcast/shows/{show.id}/episodes").get_json()
    assert [e["title"] for e in listed["episodes"]] == ["Two"]
    assert listed["show"]["count"] == 1

    back = client.post(f"/api/podcast/episodes/{ep.id}/unhide").get_json()
    assert back["title"] == "One" and back["show"] == "Feed"
    assert len(client.get(f"/api/podcast/shows/{show.id}/episodes").get_json()["episodes"]) == 2
