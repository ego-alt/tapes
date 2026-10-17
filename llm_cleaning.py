"""LLM-assisted metadata correction (Anthropic Claude — Haiku 4.5).

Layered on top of the deterministic `cleaning.py`, never a replacement for it:
`clean_meta` runs first as a cheap, offline pass *and* as the fallback whenever
the LLM is unavailable (no API key), errors, or returns low confidence — so a
flaky network or a bad model day can never leave a track worse than the
deterministic result.

What the model does:
  - Corrects title/artist (cruft removal, capitalization, Artist/Title split,
    featured-artist handling). It is told NOT to invent — clean input passes
    through unchanged.
  - Decides the album, using the playlist the track was ripped from (its title,
    owner and this track's position) as the main evidence: an artist's own
    playlist, a "Artist - Album (Full Album)" upload or a YouTube Music album
    is that album. Applied only when it lists "album" in `enriched`; it fills a
    blank album and never overwrites YouTube's own.
  - Gives the track number when the playlist is the album in order.

Two entry points share one request shape:
  correct_track(meta)           -> one synchronous call (per rip)
  correct_tracks_batch(items)   -> Message Batches API, 50% cost (flask retag --llm)

Structured output is via a forced tool call, so the model must return a typed
object — no free-text parsing.
"""
import logging
import os
import time

log = logging.getLogger("tapes.llm")

MODEL = "claude-haiku-4-5"

_TOOL = {
    "name": "corrected_metadata",
    "description": "Return corrected, normalized metadata for one music track.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": (
                    "Corrected song title: upload cruft removed, natural title case, "
                    "'(feat. X)' appended if there's a featured artist. Return unchanged "
                    "if already clean. Never invent or translate."
                ),
            },
            "artist": {
                "type": "string",
                "description": (
                    "Corrected primary artist. Strip channel suffixes (VEVO, Official, "
                    "'- Topic', Records). Never invent."
                ),
            },
            "album": {
                "type": ["string", "null"],
                "description": "The album this recording belongs to, spelled as officially released; null if unknown or if the playlist is not an album.",
            },
            "track_no": {
                "type": ["integer", "null"],
                "description": "Track number on that album; null unless you know it or the playlist is the album in order.",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Your confidence in the title/artist correction.",
            },
            "enriched": {
                "type": "array",
                "items": {"type": "string", "enum": ["album"]},
                "description": "Include \"album\" only if you are confident enough to apply it; otherwise leave empty.",
            },
        },
        "required": ["title", "artist", "album", "track_no", "confidence", "enriched"],
        "additionalProperties": False,
    },
}

_SYSTEM = (
    "You normalize music-track metadata from automated rips (often from YouTube).\n"
    "Correct the title and artist:\n"
    "- Strip upload cruft: (Official Video), [Lyrics], Audio, HD, 4K, Visualizer, "
    "VEVO, '- Topic', etc.\n"
    "- Fix capitalization to natural title case.\n"
    "- If the title is 'Artist - Song', split it; the artist is usually the part that "
    "names a real performer (the other part is the song).\n"
    "- Move a featured artist into the title as '(feat. Name)'.\n"
    "- Do NOT invent or translate. If the title/artist are already clean, return them "
    "unchanged.\n"
    "You may also be given the source URL, the uploader/channel (often the artist, or "
    "their VEVO/'- Topic'/label channel), yt-dlp's own parsed track/artist/album/year, "
    "and the playlist the track was downloaded from: its title, its owner, and this "
    "track's position in it. Treat these as evidence — the channel is a strong artist "
    "hint and yt-dlp's album is reliable — but never invent.\n"
    "Album: decide whether the playlist IS an album by this artist. It is when its owner "
    "is the artist (e.g. 'Sunburn' on Dominic Fike's channel), when the title names the "
    "artist and an album ('Dominic Fike - Sunburn (Full Album)', 'SZA 'SOS' Album', "
    "'Sunburn by Dominic Fike'), or when it is a YouTube Music album (id starting "
    "OLAK5uy_). It is NOT when it is a mood or mix ('chill vibes', 'Frank Ocean but "
    "slowed', '8D', 'sped up'), a channel section ('Uploads', 'Music Videos', 'Singles'), "
    "a compilation of several artists, or names a different artist. A parsed guess may be "
    "given; correct it if wrong. Give the album its official name and capitalisation "
    "('don’t forget about me, demos' → \"Don't Forget About Me, Demos\"). If the playlist "
    "is not an album, you may still give the album from your own knowledge of this exact "
    "recording, but only when certain. When the playlist is the album in order, its "
    "position is the track number. List \"album\" in `enriched` only when you are "
    "confident; prefer null over a plausible guess.\n"
    "Always call the corrected_metadata tool exactly once."
)


def _client():
    """Anthropic client, or None when unavailable (no key / package → caller falls back)."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic()


def _user_content(meta: dict) -> str:
    # Only non-empty fields are sent. Per-rip calls carry the source signals;
    # the bulk retag path has just filename + current tags.
    fields = [
        ("Filename", meta.get("filename")),
        ("Source URL", meta.get("url")),
        ("Source channel/uploader", meta.get("channel")),
        ("Source playlist", meta.get("playlist")),
        ("Playlist id", meta.get("playlist_id")),
        ("Playlist owner", meta.get("playlist_owner")),
        ("Position in playlist", meta.get("playlist_index")),
        ("Album parsed from the playlist", meta.get("playlist_album")),
        ("Current title", meta.get("title")),
        ("Current artist", meta.get("artist")),
        ("Current album", meta.get("album")),
        ("yt-dlp track", meta.get("yt_track")),
        ("yt-dlp artist", meta.get("yt_artist")),
        ("yt-dlp album", meta.get("yt_album")),
        ("yt-dlp release year", meta.get("year")),
    ]
    return "\n".join(f"{label}: {val}" for label, val in fields if val)


def _params(meta: dict) -> dict:
    return dict(
        model=MODEL,
        max_tokens=512,
        temperature=0,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "corrected_metadata"},
        messages=[{"role": "user", "content": _user_content(meta)}],
    )


def _normalize(raw: dict) -> dict:
    """Sanitize the tool output; only keep the album when the model flagged it in `enriched`."""
    enriched = set(raw.get("enriched") or [])

    def _str(key):
        v = raw.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else None

    track_no = raw.get("track_no")
    album = _str("album") if "album" in enriched else None
    return {
        "title": _str("title"),
        "artist": _str("artist"),
        "confidence": raw.get("confidence") or "low",
        "album": album,
        "track_no": track_no if album and isinstance(track_no, int) and 0 < track_no < 1000 else None,
    }


def _parse(message) -> dict | None:
    for block in getattr(message, "content", []):
        if getattr(block, "type", None) == "tool_use" and block.name == "corrected_metadata":
            return _normalize(block.input)
    return None


def correct_track(meta: dict) -> dict | None:
    """One synchronous correction. Returns the normalized dict, or None on any failure
    (no key, network error, bad response) so the caller can fall back to deterministic."""
    client = _client()
    if client is None:
        return None
    try:
        msg = client.messages.create(**_params(meta))
    except Exception as e:  # noqa: BLE001 — any failure → deterministic fallback
        # Key set but the call failed (e.g. insufficient credit, rate limit, auth).
        log.warning("LLM tag correction failed (%s); using deterministic cleanup", e)
        return None
    return _parse(msg)


def correct_tracks_batch(items, *, poll_secs: int = 15, on_status=None) -> dict:
    """Correct many tracks via the Message Batches API (50% cheaper, async).

    items: iterable of (custom_id, meta). Returns {custom_id: corrected_dict | None}.
    Returns {} immediately if the API key is missing.
    """
    client = _client()
    if client is None:
        return {}

    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    item_list = list(items)
    requests = [
        Request(custom_id=str(cid), params=MessageCreateParamsNonStreaming(**_params(meta)))
        for cid, meta in item_list
    ]
    if not requests:
        return {}

    try:
        batch = client.messages.batches.create(requests=requests)
        while True:
            b = client.messages.batches.retrieve(batch.id)
            if b.processing_status == "ended":
                break
            if on_status:
                on_status(b)
            time.sleep(poll_secs)

        results: dict = {}
        for r in client.messages.batches.results(batch.id):
            results[r.custom_id] = _parse(r.result.message) if r.result.type == "succeeded" else None
        return results
    except Exception as e:  # noqa: BLE001 — whole-batch failure → caller falls back
        # e.g. insufficient credit, auth, or a network drop mid-poll.
        log.warning("LLM batch failed (%s); falling back to deterministic", e)
        return {}
