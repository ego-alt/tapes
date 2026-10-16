"""What the player needs to know about each MP3 to play it well.

- Loudness (EBU R128, the measure behind ReplayGain 2.0 and Spotify's
  levelling): integrated loudness in LUFS and true peak in dBTP, measured once
  with ffmpeg. The player turns these into a gain per song (or per album).
- Gapless info: the encoder's delay and padding (silent samples it adds at the
  start and end), read from the LAME/Info tag in the first frame, so the player
  can trim them and join songs without a gap.

Nothing here changes the audio. `write_replaygain_tags` only adds standard
ReplayGain tags so other players (and future apps) can use the same numbers.
"""

from __future__ import annotations

import logging
import math
import pathlib
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass

log = logging.getLogger("tapes.audio")

# ReplayGain 2.0's reference level. Tags are written against it; the player
# picks its own target (it's just an offset).
RG_REFERENCE_LUFS = -18.0

# An MP3 decoder outputs this many samples before the encoder's first one
# (MPEG-1 Layer III). Players add it to the LAME tag's encoder delay.
DECODER_DELAY = 529

_I_RE = re.compile(r"I:\s+(-?[\d.]+|-inf)\s+LUFS")
_PEAK_RE = re.compile(r"True peak:\s+Peak:\s+(-?[\d.]+|-inf)\s+dBFS")


@dataclass
class Loudness:
    lufs: float    # integrated loudness
    peak_db: float  # true peak, dBTP


@dataclass
class Gapless:
    sample_rate: int
    delay: int      # encoder delay, samples (add DECODER_DELAY when trimming)
    padding: int    # encoder padding at the end, samples
    samples: int    # real audio samples (excluding delay and padding)


def measure_loudness(path: str, timeout: int = 600) -> Loudness | None:
    """Integrated loudness and true peak of a file, or None if ffmpeg fails
    or the file is silent."""
    # At low priority: measuring must never make playback stutter on the Pi.
    nice = ["nice", "-n", "15"] if shutil.which("nice") else []
    cmd = nice + [
        "ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0",
        "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stderr
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("loudness: ffmpeg failed on %s: %s", path, e)
        return None
    # The summary comes last; take the final match of each.
    i = _I_RE.findall(out)
    peak = _PEAK_RE.findall(re.sub(r"\s+", " ", out))
    if not i or not peak or "inf" in i[-1]:
        return None
    peak_db = float(peak[-1]) if "inf" not in peak[-1] else -70.0
    return Loudness(lufs=float(i[-1]), peak_db=peak_db)


def album_loudness(tracks: list[tuple[float, float, float]]) -> Loudness | None:
    """Combine (lufs, peak_db, duration_s) of an album's tracks: loudness as the
    duration-weighted energy mean (what measuring the tracks back to back gives,
    gating aside), peak as the loudest peak."""
    rows = [(lufs, peak, dur) for lufs, peak, dur in tracks if lufs is not None and dur]
    if not rows:
        return None
    total = sum(d for _, _, d in rows)
    energy = sum(d * 10 ** (lufs / 10) for lufs, _, d in rows) / total
    return Loudness(lufs=10 * math.log10(energy), peak_db=max(p for _, p, _ in rows))


def read_gapless(path: str) -> Gapless | None:
    """Encoder delay and padding from the LAME/Info tag (written by LAME and by
    ffmpeg's libmp3lame), or None when the file has no such tag (then the
    player falls back to plain playback for it)."""
    try:
        with open(path, "rb") as f:
            head = f.read(16384)
    except OSError:
        return None
    start = 0
    if head[:3] == b"ID3" and len(head) >= 10:   # skip the ID3v2 tag
        size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
        start = 10 + size + (10 if head[5] & 0x10 else 0)
        try:
            with open(path, "rb") as f:
                f.seek(start)
                head = f.read(4096)
        except OSError:
            return None
        start = 0
    # The first MPEG frame header.
    sync = next((i for i in range(start, len(head) - 4)
                 if head[i] == 0xFF and (head[i + 1] & 0xE0) == 0xE0), None)
    if sync is None:
        return None
    b1, b2 = head[sync + 1], head[sync + 2]
    version_bits = (b1 >> 3) & 0x03            # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5
    rate_idx = (b2 >> 2) & 0x03
    rates = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
    if version_bits not in rates or rate_idx == 3:
        return None
    sample_rate = rates[version_bits][rate_idx]
    samples_per_frame = 1152 if version_bits == 3 else 576

    tag = max(head.find(b"Xing", sync, sync + 64), head.find(b"Info", sync, sync + 64))
    if tag < 0:
        return None
    flags = struct.unpack(">I", head[tag + 4:tag + 8])[0]
    p, frames = tag + 8, None
    if flags & 1:
        frames = struct.unpack(">I", head[p:p + 4])[0]
        p += 4
    if flags & 2:
        p += 4
    if flags & 4:
        p += 100
    if flags & 8:
        p += 4
    lame = head[p:p + 36]
    if frames is None or len(lame) < 24 or not lame[:4].isalpha():
        return None
    d = lame[21:24]
    delay = (d[0] << 4) | (d[1] >> 4)
    padding = ((d[1] & 0x0F) << 8) | d[2]
    samples = frames * samples_per_frame - delay - padding
    if samples <= 0:
        return None
    return Gapless(sample_rate=sample_rate, delay=delay, padding=padding, samples=samples)


def write_replaygain_tags(path: str, track: Loudness, album: Loudness | None) -> bool:
    """Standard ReplayGain 2.0 tags (TXXX frames, as foobar2000/rsgain write
    them). Tags only: the audio is untouched."""
    from mutagen.id3 import ID3, TXXX, ID3NoHeaderError

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    except Exception as e:  # noqa: BLE001 — unreadable tag: leave the file alone
        log.warning("replaygain: can't read tags of %s: %s", path, e)
        return False

    def put(key, value):
        tags.delall(f"TXXX:{key}")
        tags.add(TXXX(encoding=3, desc=key, text=[value]))

    put("REPLAYGAIN_TRACK_GAIN", f"{RG_REFERENCE_LUFS - track.lufs:+.2f} dB")
    put("REPLAYGAIN_TRACK_PEAK", f"{10 ** (track.peak_db / 20):.6f}")
    if album:
        put("REPLAYGAIN_ALBUM_GAIN", f"{RG_REFERENCE_LUFS - album.lufs:+.2f} dB")
        put("REPLAYGAIN_ALBUM_PEAK", f"{10 ** (album.peak_db / 20):.6f}")
    try:
        tags.save(path)
    except Exception as e:  # noqa: BLE001
        log.warning("replaygain: can't write tags to %s: %s", path, e)
        return False
    return True


# ---------- the library: measure tracks, keep album figures current ----------

def analyze_track(track, music_dir) -> bool:
    """Measure one track and store loudness + gapless info on it (no commit).
    Returns True when loudness was measured."""
    from datetime import datetime

    path = str(pathlib.Path(music_dir) / track.file_path)
    loud = measure_loudness(path)
    gap = read_gapless(path)
    track.loudness_lufs = loud.lufs if loud else None
    track.true_peak_db = loud.peak_db if loud else None
    track.sample_rate = gap.sample_rate if gap else None
    track.enc_delay = gap.delay if gap else None
    track.enc_padding = gap.padding if gap else None
    track.audio_samples = gap.samples if gap else None
    track.audio_analyzed_at = datetime.now()
    return loud is not None


def refresh_album(album: str | None, music_dir=None, *, write_tags: bool = False) -> None:
    """Recompute an album's loudness from its tracks' stored figures (cheap: no
    ffmpeg) and copy it onto each of them; optionally rewrite their ReplayGain
    tags. Tracks without an album have no album figures. No commit."""
    from models import Track

    if not album:
        return
    tracks = Track.query.filter(Track.album == album).all()
    agg = album_loudness([(t.loudness_lufs, t.true_peak_db, t.duration_s) for t in tracks])
    for t in tracks:
        t.album_loudness_lufs = agg.lufs if agg else None
        t.album_peak_db = agg.peak_db if agg else None
        if write_tags and music_dir and t.loudness_lufs is not None:
            write_replaygain_tags(str(pathlib.Path(music_dir) / t.file_path),
                                  Loudness(t.loudness_lufs, t.true_peak_db), agg)


def analyze_new_track(track, music_dir) -> None:
    """A freshly ripped or added track: measure it, refresh its album, tag it."""
    analyze_track(track, music_dir)
    if track.album:
        refresh_album(track.album, music_dir, write_tags=True)
    elif track.loudness_lufs is not None:
        write_replaygain_tags(str(pathlib.Path(music_dir) / track.file_path),
                              Loudness(track.loudness_lufs, track.true_peak_db), None)


def claim_next(session):
    """Atomically claim one unmeasured track (so two server workers never
    measure the same one), or None when there's nothing left."""
    from datetime import datetime

    from sqlalchemy import update

    from models import Track

    while True:
        t = (Track.query.filter(Track.audio_analyzed_at.is_(None))
             .order_by(Track.id).first())
        if t is None:
            return None
        claimed = session.execute(
            update(Track).where(Track.id == t.id, Track.audio_analyzed_at.is_(None))
            .values(audio_analyzed_at=datetime.now())
        ).rowcount
        session.commit()
        if claimed:
            return t


def backfill(app, *, pause_s: float = 0.5, idle_s: float = 600) -> None:
    """Background loop: measure every track that hasn't been, a few at a time,
    forever (new hand-added files get picked up on the next pass). Albums are
    refreshed, and tags written, once a pass finishes."""
    import time

    from models import db

    while True:
        albums = set()
        with app.app_context():
            while True:
                t = claim_next(db.session)
                if t is None:
                    break
                try:
                    analyze_track(t, app.config["MUSIC_DIR"])
                    if t.album:
                        albums.add(t.album)
                    elif t.loudness_lufs is not None:   # a single: tag it now
                        path = pathlib.Path(app.config["MUSIC_DIR"]) / t.file_path
                        loud = Loudness(t.loudness_lufs, t.true_peak_db)
                        write_replaygain_tags(str(path), loud, None)
                    db.session.commit()
                except Exception as e:  # noqa: BLE001 — never kill the loop
                    log.warning("backfill: %s failed: %s", t.file_path, e)
                    db.session.rollback()
                time.sleep(pause_s)
            for album in albums:
                try:
                    refresh_album(album, app.config["MUSIC_DIR"], write_tags=True)
                    db.session.commit()
                except Exception as e:  # noqa: BLE001
                    log.warning("backfill: album %r failed: %s", album, e)
                    db.session.rollback()
            if albums:
                log.info("backfill: measured tracks in %d album(s)", len(albums))
        time.sleep(idle_s)
