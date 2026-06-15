"""Deterministic metadata cleanup for ripped tracks.

Pure string work — no network, no fuzzy matching, so it can never mistag the
way an autotagger can. Shared by the download worker (cleans each new rip) and
the `flask retag` command (cleans the existing library).
"""
import re

# Bracketed YouTube cruft → stripped from titles, e.g. "(Official Video)", "[Audio]".
# offic(?:ial|al) tolerates the common "Offical" misspelling.
_CRUFT = re.compile(
    r"\s*[\(\[]\s*(?:offic(?:ial|al)\s*)?(?:music\s*)?"
    r"(?:audio|video|lyric[s]?|lyric\s*video|visuali[sz]er|hd|hq|4k|mv|m/v|"
    r"full\s*album|offic(?:ial|al)|explicit)\s*[\)\]]",
    re.I,
)
# Same cruft without brackets at the end of a title, e.g. "… Official Video".
# Requires a qualifier (official/lyric/music) before audio/video so plain titles
# ending in "Video" aren't touched.
_CRUFT_TRAIL = re.compile(
    r"\s+(?:offic(?:ial|al)|lyrics?|music)\s+(?:music\s+)?(?:audio|video)\s*$",
    re.I,
)
# YouTube auto-generated "Topic" channels: "Eason Chan - Topic" → "Eason Chan".
_TOPIC = re.compile(r"\s*-\s*topic$", re.I)
# A leading track number like "01 -" or "3." — not an artist.
_NUM_PREFIX = re.compile(r"^\d+[.)]?$")
# "Artist - Song" shape (any dash variant); prefix capped so it reads as a name.
_TITLE_SPLIT = re.compile(r"^(.{1,60}?)\s+[-–—]\s+(.+)$")


def _unwrap_quotes(s: str) -> str:
    # Drop a single pair of wrapping quotes: 'Riptide' / "Song" → Riptide / Song.
    m = re.match(r"^(['\"])(.*)\1$", s)
    return m.group(2).strip() if m else s


def clean_title(title: str) -> str:
    if not title:
        return title
    out = _CRUFT.sub("", title)
    out = _CRUFT_TRAIL.sub("", out)
    out = _TOPIC.sub("", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" -–—")
    return _unwrap_quotes(out)


def clean_meta(title: str, artist: str):
    """Return cleaned (title, artist).

    Strips title cruft and "- Topic" from the artist, then splits an
    "Artist - Song" title: the prefix becomes the artist — YouTube's most
    reliable artist signal, more so than the embedded artist, which is often the
    uploader or label — unless the prefix is just a track number.
    """
    title = clean_title(title or "")
    artist = _TOPIC.sub("", (artist or "")).strip()
    m = _TITLE_SPLIT.match(title)
    if m:
        prefix, rest = m.group(1).strip(), m.group(2).strip()
        if rest:
            if _NUM_PREFIX.fullmatch(prefix):
                title = rest                      # "01 - Song" → "Song"
            elif re.search(r"[^\W\d_]", prefix):  # prefix has letters → treat as artist
                title, artist = rest, prefix
    # The split can expose wrapping quotes (rest = "'Riptide'").
    return _unwrap_quotes(title.strip()), artist.strip()
