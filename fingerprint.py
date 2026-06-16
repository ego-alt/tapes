"""Acoustic fingerprinting via Chromaprint (`fpcalc`).

`fpcalc` turns audio into a fingerprint: a list of 32-bit sub-fingerprints, one
per ~0.12s frame, derived from the music's harmonic content. It's robust to
re-encoding / bitrate / loudness, but differs for a different performance (live,
remix, cover). We store it per track and compare new rips against the library
ourselves — `similarity()` slides one fingerprint over the other and counts
frames that match within a few bits. Requires the `fpcalc` binary (Debian:
libchromaprint-tools).

Different songs essentially never match (random 32-bit frames agreeing within 3
bits is a ~1e-6 event), so the match fraction is near 0 for unrelated audio and
high for the same recording — a wide, safe margin around DUP_THRESHOLD.
"""
import logging
import subprocess

log = logging.getLogger("tapes.fpr")

_BIT_THRESH = 3       # a frame "matches" if <= this many of its 32 bits differ
_MAX_OFFSET = 80      # alignment search window in frames (~0.12s each, so ~10s)
_MIN_OVERLAP = 50     # need at least this many overlapping frames to judge
DUP_THRESHOLD = 0.30  # min matching-frame fraction to call it the same recording


def compute(path: str):
    """Return (duration_seconds, [uint32, ...]) for the file, or None on failure."""
    try:
        out = subprocess.run(
            ["fpcalc", "-raw", path], capture_output=True, text=True, timeout=30
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

    duration, fp = 0, None
    for line in out.stdout.splitlines():
        if line.startswith("DURATION="):
            try:
                duration = int(line[len("DURATION="):])
            except ValueError:
                pass
        elif line.startswith("FINGERPRINT="):
            try:
                fp = [int(x) for x in line[len("FINGERPRINT="):].split(",") if x]
            except ValueError:
                fp = None
    return (duration, fp) if fp else None


def encode(fp: list) -> str:
    """Serialize a fingerprint for DB storage."""
    return ",".join(map(str, fp))


def decode(s: str):
    if not s:
        return None
    try:
        return [int(x) for x in s.split(",") if x]
    except ValueError:
        return None


def similarity(a: list, b: list) -> float:
    """Best-offset fraction of frames that match within _BIT_THRESH bits (0–1)."""
    best = 0.0
    for off in range(-_MAX_OFFSET, _MAX_OFFSET + 1):
        aa, bb = (a[off:], b) if off >= 0 else (a, b[-off:])
        n = min(len(aa), len(bb))
        if n < _MIN_OVERLAP:
            continue
        matches = sum(1 for x, y in zip(aa, bb) if (x ^ y).bit_count() <= _BIT_THRESH)
        best = max(best, matches / n)
    return best
