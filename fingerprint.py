"""Acoustic-fingerprint identity via Chromaprint (`fpcalc`) + AcoustID.

`fpcalc` computes a fingerprint from the audio itself, and AcoustID maps it to a
cluster id that is stable across re-encodes and different uploads of the *same
recording* — while a live take, remix, or remaster fingerprints differently, so
distinct versions stay distinct. That cluster id is the content-dedup key.

Needs the `fpcalc` binary (Debian: libchromaprint-tools) and a free
ACOUSTID_API_KEY. Returns None on anything missing/failing so the caller just
rips normally.
"""
import json
import logging
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger("tapes.fpr")

_LOOKUP = "https://api.acoustid.org/v2/lookup"
_MIN_SCORE = 0.5          # AcoustID match confidence (0–1)
_MIN_INTERVAL = 0.34      # AcoustID allows ~3 lookups/sec

_lock = threading.Lock()
_last_call = 0.0


def _throttle():
    global _last_call
    with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _fpcalc(path: str):
    """Return (duration, fingerprint) from fpcalc, or None."""
    try:
        out = subprocess.run(
            ["fpcalc", "-json", path], capture_output=True, text=True, timeout=30
        )
    except FileNotFoundError:
        log.warning("fpcalc not installed — acoustic dedup disabled")
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("fpcalc failed (%s)", e)
        return None
    if out.returncode != 0:
        log.warning("fpcalc error: %s", (out.stderr or "").strip()[:200])
        return None
    try:
        data = json.loads(out.stdout)
        return int(data["duration"]), data["fingerprint"]
    except (ValueError, KeyError):
        return None


def fingerprint_id(path: str) -> str | None:
    """The AcoustID cluster id for this file, or None (no key / no match / failure)."""
    key = os.getenv("ACOUSTID_API_KEY")
    if not key:
        return None
    fp = _fpcalc(path)
    if fp is None:
        return None
    duration, fingerprint = fp

    body = urllib.parse.urlencode({
        "client": key,
        "duration": duration,
        "fingerprint": fingerprint,
        "meta": "recordingids",
    }).encode()
    try:
        _throttle()
        req = urllib.request.Request(
            _LOOKUP, data=body, headers={"User-Agent": "tapes/0.1"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        log.warning("AcoustID lookup failed (%s)", e)
        return None

    if data.get("status") != "ok":
        return None
    results = data.get("results") or []
    if results and (results[0].get("score") or 0) >= _MIN_SCORE:
        return results[0].get("id")
    return None
