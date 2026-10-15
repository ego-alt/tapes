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
