"""Audit 2.2, 2.3, 2.5: rips report what happened, in plain language, as JSON."""
from datetime import datetime, timedelta

import pytest

from downloader import _finish, friendly_rip_error
from models import DownloadJob, User, db


@pytest.mark.parametrize("output, expected", [
    ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", "This video is private."),
    ("ERROR: Sign in to confirm your age", "This video is age-restricted, so it can't be ripped."),
    ("ERROR: The uploader has not made this video available in your country", "This video isn't available in this region."),
    ("ERROR: Unsupported URL: https://example.com/x", "That site or link isn't supported."),
    ("ERROR: [youtube] abc: Video unavailable", "This video is no longer available."),
    ("ERROR: [youtube] abc: This video is unavailable", "This video is no longer available."),
    ("ERROR: Unable to download webpage: <urlopen error timed out>", "Couldn't reach that site. Check the connection and try again."),
    ("/usr/bin/python: No module named yt_dlp", "Ripping isn't set up on this server (yt-dlp is missing)."),
    ("something odd", "Couldn't rip that link. It may be private, region-locked or not a video."),
])
def test_friendly_rip_errors(output, expected):
    assert friendly_rip_error(output) == expected


def _job(user, **kw):
    j = DownloadJob(user_id=user.id, url="https://www.youtube.com/watch?v=x", **kw)
    db.session.add(j)
    db.session.commit()
    return j


def test_finished_jobs_stay_in_the_panel_until_dismissed(client, add_track):
    client.get("/")  # creates the standalone user
    user = User.query.one()
    t = add_track(title="Warm Static")
    running = _job(user, status="running")
    added = _job(user, status="queued")
    _finish(added, "added", "Warm Static")
    added.track_id = t.id
    failed = _job(user, status="queued")
    _finish(failed, "error", "This video is private.")
    old = _job(user, status="queued")
    _finish(old, "added", "Old")
    old.finished_at = datetime.now() - timedelta(hours=2)
    db.session.commit()

    jobs = {j["id"]: j for j in client.get("/api/downloads").get_json()}
    assert set(jobs) == {running.id, added.id, failed.id}
    assert jobs[added.id]["outcome"] == "added"
    assert jobs[added.id]["track"]["title"] == "Warm Static"
    assert jobs[failed.id] | {} and jobs[failed.id]["message"] == "This video is private."

    assert client.delete(f"/api/downloads/{failed.id}").status_code == 204
    assert failed.id not in {j["id"] for j in client.get("/api/downloads").get_json()}


def test_api_errors_are_json_with_human_messages(client):
    r = client.post("/api/downloads", json={"url": "not a link"})
    assert r.status_code == 400
    assert r.get_json() == {"error": "Paste a full link starting with https://"}
    r = client.post("/api/playlists", json={"name": " "})
    assert r.get_json() == {"error": "Give the tape a name."}
    assert client.get("/api/playlists/999/tracks").status_code == 404
    assert client.get("/api/playlists/999/tracks").is_json
