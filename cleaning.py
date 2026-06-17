"""Deterministic metadata cleanup for ripped tracks.

Pure string work — no network, no fuzzy matching against a music DB, so it can
never mistag the way an autotagger can. Shared by the download worker (cleans
each new rip) and the `flask retag` command (cleans the existing library).
"""
import re

# Words that, on their own, are just YouTube noise — used to decide whether a
# bracketed group or a trailing segment is pure cruft.
_CRUFT_WORDS = {
    "official", "offical", "music", "video", "videos", "audio", "lyric", "lyrics",
    "lyrical", "visualizer", "visualiser", "hd", "hq", "uhd", "fhd", "4k", "8k",
    "mv", "explicit", "clean", "stereo", "mono", "pcm", "remaster", "remastered",
    "only", "full", "album", "version", "vevo",
}
# Single words safe to strip from the END of a title (no brackets). Excludes
# ambiguous ones like "music"/"video"/"audio" that can be real titles
# (e.g. Madonna - Music) — those only count as cruft inside brackets.
_TRAIL_SOLO = {
    "lyric", "lyrics", "lyrical", "vevo", "hd", "hq", "uhd", "fhd", "4k", "8k",
    "mv", "visualizer", "visualiser", "remaster", "remastered",
}

_TOPIC = re.compile(r"\s*-\s*topic$", re.I)
_NUM_PREFIX = re.compile(r"^\d+[.)]?$")                 # a whole "3" / "01)" prefix
_LEAD_NUM = re.compile(r"^\s*\d+\s*[.)]\s+")            # leading "1. " / "01) "
_TITLE_SPLIT = re.compile(r"^(.{1,60}?)\s+[-–—]\s+(.+)$")
_BRACKET = re.compile(r"\s*[\(\[]([^()\[\]]*)[\)\]]")
_TOKEN_SEP = re.compile(r"[\s\-–—_/|,.]+")
_TRAIL_SEG = re.compile(r"\s*[-–—+|]\s*([^-–—+|]+?)\s*$")


def _tokens(s):
    return [t for t in _TOKEN_SEP.split(s.strip().lower()) if t]


def _is_all_cruft(inner):
    toks = _tokens(inner)
    return bool(toks) and all(t in _CRUFT_WORDS for t in toks)


def _is_trailing_cruft(seg):
    toks = _tokens(seg)
    if not toks:
        return False
    if len(toks) == 1:
        return toks[0] in _TRAIL_SOLO
    return all(t in _CRUFT_WORDS for t in toks)


def _strip_bracket_cruft(s):
    # Drop "(…)" / "[…]" groups whose contents are entirely cruft words.
    return _BRACKET.sub(lambda m: "" if _is_all_cruft(m.group(1)) else m.group(0), s)


def _strip_trailing_cruft(s):
    while True:
        m = _TRAIL_SEG.search(s)
        if m and _is_trailing_cruft(m.group(1)):
            s = s[:m.start()].rstrip()
        else:
            return s


def _unwrap_quotes(s):
    m = re.match(r"^(['\"])(.*)\1$", s)
    return m.group(2).strip() if m else s


def clean_title(title: str) -> str:
    if not title:
        return title
    out = _strip_bracket_cruft(title)
    out = _strip_trailing_cruft(out)
    out = _TOPIC.sub("", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" -–—")
    return _unwrap_quotes(out)


def _norm_artist(s):
    s = re.sub(r"(vevo|official|music|tv|records|hq|hd)$", "", (s or "").lower().strip())
    return re.sub(r"[^0-9a-z一-鿿]+", "", s)


def _same_artist(a, b):
    """Loose match so a channel name ('EminemMusic') still equals the real one."""
    na, nb = _norm_artist(a), _norm_artist(b)
    if len(na) < 3 or len(nb) < 3:
        return na != "" and na == nb
    return na == nb or na.startswith(nb) or nb.startswith(na)


def reconcile_artist(name: str, existing) -> str:
    """Snap an artist name onto an existing library spelling when the two normalize
    identically — so casing/punctuation variants ("my little airport" vs
    "My Little Airport") collapse onto one artist instead of splitting the shelf.

    `existing` is an iterable of current artist strings, earliest-seen first; the
    first normalized-exact match wins, which keeps the result stable and idempotent
    (first-seen spelling becomes canonical). Returns `name` unchanged when nothing
    matches. Normalized-exact only — no fuzzy matching, so genuinely distinct
    artists are never merged by accident. The caller supplies the candidates, so
    this stays a pure function with no DB dependency.
    """
    if not name:
        return name
    key = _norm_artist(name)
    if not key:
        return name
    for other in existing:
        if other and other != name and _norm_artist(other) == key:
            return other
    return name


def clean_meta(title: str, artist: str):
    """Return cleaned (title, artist).

    Strips cruft, drops a leading track number, then splits an "Artist - Song"
    title. The prefix usually becomes the artist (more reliable than the embedded
    artist, which is often the uploader/label) — but if the embedded artist
    instead matches the suffix, the file is "Title - Artist" and we keep the
    artist. A dash inside an unbalanced bracket is never treated as a separator.
    """
    title = clean_title(title or "")
    artist = _TOPIC.sub("", (artist or "")).strip()
    title = _LEAD_NUM.sub("", title)        # "1. Blue Swede - X" -> "Blue Swede - X"
    artist = _LEAD_NUM.sub("", artist)      # repair artists already mangled to "1. …"

    m = _TITLE_SPLIT.match(title)
    if m:
        prefix, rest = m.group(1).strip(), m.group(2).strip()
        balanced = prefix.count("(") == prefix.count(")") and prefix.count("[") == prefix.count("]")
        if rest and balanced:
            if _NUM_PREFIX.fullmatch(prefix):
                title = rest                                  # "01 - Song" -> "Song"
            elif re.search(r"[^\W\d_]", prefix):              # prefix has letters
                if artist and _same_artist(artist, rest) and not _same_artist(artist, prefix):
                    title = prefix                            # reversed "Title - Artist"
                else:
                    title, artist = rest, prefix              # normal "Artist - Title"
    return _unwrap_quotes(title.strip()), artist.strip()
