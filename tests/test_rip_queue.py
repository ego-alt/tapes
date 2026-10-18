"""The rip queue with more than one worker process: each job runs once."""
import downloader
from models import DownloadJob, User, db


def _job(status="queued"):
    user = User.query.first()
    job = DownloadJob(user_id=user.id, url="https://www.youtube.com/watch?v=x", status=status)
    db.session.add(job)
    db.session.commit()
    return job.id


def test_only_one_worker_claims_a_job(app, client):
    client.get("/")                      # attaches the local user
    job_id = _job()
    assert downloader._claim(job_id) is True
    assert downloader._claim(job_id) is False          # the other worker skips it
    assert db.session.get(DownloadJob, job_id).status == "running"


def test_a_claimed_job_is_not_processed_twice(app, client, monkeypatch):
    client.get("/")
    job_id = _job()
    ran = []
    monkeypatch.setattr(downloader, "_find_existing", lambda url: ran.append(url) or None)
    monkeypatch.setattr(downloader, "_rip", lambda *a: None)
    downloader._process(app, job_id)
    downloader._process(app, job_id)
    assert len(ran) == 1


def test_recovery_requeues_only_interrupted_jobs(app, client):
    client.get("/")
    running, queued, done = _job("running"), _job("queued"), _job("done")
    assert downloader.recover_interrupted_jobs() == 1
    states = {i: db.session.get(DownloadJob, i).status for i in (running, queued, done)}
    assert states == {running: "queued", queued: "queued", done: "done"}
