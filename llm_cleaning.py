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
  - Enriches the album, but ONLY when it lists "album" in `enriched` (its own
    high-confidence signal); otherwise album comes back null and is left alone.
    Enrichment fills a blank album; it never overwrites an existing tag.

Two entry points share one request shape:
  correct_track(meta)           -> one synchronous call (per rip)
  correct_tracks_batch(items)   -> Message Batches API, 50% cost (flask retag --llm)

Structured output is via a forced tool call, so the model must return a typed
object — no free-text parsing.
"""
import os
import time

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
                "description": (
                    "Original studio/EP album for THIS exact recording, only if you are "
                    "highly confident from your own knowledge; otherwise null. Never guess."
                ),
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
        "required": ["title", "artist", "album", "confidence", "enriched"],
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
    "their VEVO/'- Topic'/label channel), the source playlist name, and yt-dlp's own "
    "parsed track/artist/album/year. Treat these as evidence — the channel is a strong "
    "artist hint and yt-dlp's album is usually reliable — but still never invent.\n"
    "Enrichment (album): fill it ONLY when you are confident from the signals above or "
    "your own knowledge of this exact recording. If unsure, set album to null and leave "
    "`enriched` empty. Prefer null over a plausible-but-uncertain guess.\n"
    "Always call the corrected_metadata tool exactly once."
)


def _client():
    """Anthropic client, or None when ANTHROPIC_API_KEY is unset (→ caller falls back)."""
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

    return {
        "title": _str("title"),
        "artist": _str("artist"),
        "confidence": raw.get("confidence") or "low",
        "album": _str("album") if "album" in enriched else None,
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
    except Exception:  # noqa: BLE001 — any failure → deterministic fallback
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
