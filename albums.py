"""Album context from the playlist a track was ripped from.

A video carries an album only when YouTube generated it ("Artist - Topic"
uploads). Most album playlists are something else: the artist's own channel
posting "Dominic Fike "3 Nights" (Official Audio)", or a fan's "Dominic Fike -
Sunburn (Full Album)". This module reads the playlist's title and owner, and
the ripped track's artist, to decide whether the playlist *is* an album and,
if so, which one.
"""
import re

from cleaning import _find_artist, _norm_artist, _same_artist

# YouTube Music album playlists ("OLAK5uy_…") are the album, always; a
# channel's uploads (UU…), a mix (RD…) or liked videos (LL…) never are.
_YTM_ALBUM = re.compile(r"^OLAK5uy_")
_NOT_ALBUM_ID = re.compile(r"^(?:UU|RD|LL|FL|UL)")

# Words that say "this playlist is an album".
_ALBUM_MARK = re.compile(
    r"\b(?:full\s+album|album\s+completo|álbum\s+completo|album\s+complet|full\s+lp|"
    r"álbum|album|lp|ep|mixtape|deluxe)\b", re.I)

# Decorations around the album name: "(Full Album)", "[Full Album]", "(Clean)",
# "(Explicit)", "(Lyrics)", "(2015)", "/ New Album 2023", "(Topic) 🅴", "HQ"…
_DECOR_WORDS = (
    r"full\s+album(?:\s+(?:stream|lyrics|hq|in\s+order|clean|explicit|topic))*|full\s+lp|"
    r"album\s+completo|álbum\s+completo|album|álbum|clean|explicit|"
    r"lyrics?|with\s+lyrics|letra|sub\s+español|tradução|legendado|türkçe\s+altyazılı|"
    r"audio|official\s+audio|official\s+videos|(?:lyric|music)\s+videos(?:\s+in\s+order)?|lyrics\s+playlist|"
    r"remaster(?:ed)?(?:\s+(?:19|20)\d{2})?|sub|432\s*hz|hq|hd|topic|playlist|stream|in\s+order|vinyl\s+rip|"
    r"new\s+album\s+(?:19|20)\d{2}|(?:19|20)\d{2}(?:\s+(?:19|20)\d{2})?|disc\s+1\s*(?:&|and)\s*2"
)
_DECOR_BRACKET = re.compile(r"\s*[\(\[]\s*(?:[^()\[\]]*?)\s*[\)\]]", re.I)
_DECOR_TAIL = re.compile(r"(?:\s*[-–—/|•·:]?\s*\b(?:" + _DECOR_WORDS + r")\b\.?)+\s*$", re.I)
_DECOR_HEAD = re.compile(r"^\s*(?:(?:album|álbum|full\s+album)\s*[-–—:]\s+|\d{1,2}\s*[-.]\s*(?=\D)|\[[\d.\s-]+\]\s*)", re.I)
# "4th Album", "2nd EP", "1st Mini Album", "Vol.2": numbering, not the name.
_ORDINAL = re.compile(r"\b(?:\d+(?:st|nd|rd|th)\s+(?:mini\s+|full\s+|studio\s+)?(?:album|ep|lp)|vol\.?\s*\d+)\b", re.I)
# A channel section, not an album, when it's the whole title.
_GENERIC = re.compile(
    r"(?:music\s+videos?|videos?|uploads|popular(?:\s+uploads)?|singles?|live|songs|playlist|mix|"
    r"albums?|eps?|official\s+music\s+videos?|lyric\s+videos?|shorts|new|latest|releases|my\s+music)", re.I)
_EMOJI = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️‍]+")

# Not an album: a mood, an edit, a channel section, a compilation.
_NOT_ALBUM = re.compile(
    r"\b(?:slowed|reverb|sped\s*up|speed\s*up|nightcore|8d|3d\s+spatial|instrumentals?|karaoke|"
    r"covers?|remixes|megamix|dj\s+mix|best\s+of|greatest\s+hits|hits|top\s+\d+|"
    r"essentials|this\s+is|radio|favou?rites|reactions?|color\s+coded|"
    r"liked|songs|playlist\s+of|mood|vibes|chill|workout|study|sleep|1\s*hour|loop|"
    r"for\s+you|on\s+repeat|discover|all\s+tracks|complete\s+discography|discography|"
    r"live\s+at\s+\w+\s+\d{4}\s+full\s+concert|concert|tour|set\s+list|setlist)\b", re.I)

_SEPARATORS = [re.compile(r"\s+[-–—•·|｜]\s+|\s*[|｜]\s*"), re.compile(r"(?<=\w)[-–—]\s+|\s+[-–—](?=\w)"),
               re.compile(r"\s*:\s+"), re.compile(r"\s+/\s+"), re.compile(r",\s+"),
               re.compile(r"(?<=\w)[-–—](?=\w)")]


def _strip_decor(title: str) -> tuple[str, bool]:
    """Remove album-ness decorations; also say whether any said "album"."""
    marked = bool(_ALBUM_MARK.search(title or ""))
    t = _EMOJI.sub("", title or "").strip()
    m = re.fullmatch(r"['‘\"“](.+?)['’\"”]\s*(?:by\s+.+)?", t)     # "'Miles Davis - Kind of Blue' by BnF collection"
    if m:
        t = m.group(1)
    t = re.sub(r"\s*[\"“']\s*(?:full\s+album|(?:19|20)\d{2})\s*[\"”']", "", t, flags=re.I)   # "Full Album", "1969"
    t = _DECOR_HEAD.sub("", t)

    def bracket(m):
        inner = m.group(0).strip(" ()[]")
        if not inner or _DECOR_TAIL.fullmatch(" " + inner) or re.fullmatch(_DECOR_WORDS, inner, re.I) \
                or re.fullmatch(r"(?:full\s+album|album)\s*[-–—]\s*(?:clean|explicit|(?:19|20)\d{2})", inner, re.I) \
                or re.match(r"full\s+album\b", inner, re.I):
            return ""
        return m.group(0)

    prev = None
    while prev != t:
        prev = t
        t = _DECOR_BRACKET.sub(bracket, t).strip()
        t = _DECOR_TAIL.sub("", t).strip()
    t = re.sub(r"\s*@\S+", "", t)                         # "@MBS_Playlist"
    t = re.sub(r"\s*\*[\d/\s]*$", "", t)                  # "*2022/2024"
    t = _ORDINAL.sub("", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip(" -–—|•·:/,"), marked


def _unquote(s: str) -> str:
    s = s.strip()
    m = re.fullmatch(r"[\"“”'‘’「『]\s*(.+?)\s*[\"“”'‘’」』]", s)
    return m.group(1) if m else s


def parse_playlist_title(title: str, artist: str):
    """(album, named_artist, marked) read from a playlist title, given the
    artist of the track being ripped.

    - album: the album name the title gives, or None when the title isn't an
      album at all ("Frank Ocean but slowed", "Uploads from Mitski").
    - named_artist: True when the title itself names `artist` ("Dominic Fike -
      Sunburn (Full Album)"); False for a bare album name ("Sunburn").
    - marked: the title said "album" somewhere.
    """
    raw = (title or "").strip()
    if not raw or _NOT_ALBUM.search(raw):
        return None, False, False
    t, marked = _strip_decor(raw)
    if not t or _GENERIC.fullmatch(t):
        return None, False, marked
    hints = [artist] if artist else []

    # Artist 'Album' Album / "channel ORANGE" Full Album - Frank Ocean
    for quote in (r"[「『](?P<album>[^」』]+)[」』]", r"[\"“](?P<album>[^\"“”]+)[\"”]",
                  r"(?:^|(?<=\s))[‘'](?P<album>[^'’]+)['’](?=\s|$)"):
        q = re.match(r"^(?P<pre>.*?)\s*" + quote + r"\s*(?P<post>.*)$", t)
        if not (q and hints):
            continue
        rest = " ".join(x for x in (q.group("pre"), q.group("post")) if x).strip(" -–—:|")
        rest = re.sub(r"['’]s$", "", rest).strip()
        if not rest or _find_artist(rest, hints) or marked:
            return q.group("album").strip(), bool(rest), marked

    # Artist's Album
    m = re.match(r"^(.+?)['’]s\s+(.+)$", t)
    if m and hints and _find_artist(m.group(1), hints):
        return _unquote(m.group(2)), True, marked

    # Album (Artist)
    m = re.match(r"^(.+?)\s*\(([^()]+)\)\s*$", t)
    if m and hints and _find_artist(m.group(2), hints):
        return _unquote(m.group(1)), True, marked

    # Album by Artist
    m = re.match(r"^(.+?)\s+by\s+(.+)$", t, re.I)
    if m and hints and _find_artist(m.group(2), hints):
        return _unquote(m.group(1)), True, marked

    # Artist - Album / Album - Artist / Artist: Album / Artist, Album / Artist • Album
    # Strongest separators first, so "Don't Forget About Me, Demos - Dominic
    # Fike" splits at the dash, never the comma inside the album name.
    for sep_re in _SEPARATORS:
        for sep in sep_re.finditer(t):
            left, right = t[:sep.start()].strip(), t[sep.end():].strip()
            if not (left and right and hints):
                continue
            la, ra = _find_artist(left, hints), _find_artist(right, hints)
            if la and not ra:
                return _unquote(_strip_decor(right)[0] or right), True, marked
            if ra and not la:
                return _unquote(_strip_decor(left)[0] or left), True, marked

    # Artist Album, no separator: "SZA Ctrl Album", "Radiohead In Rainbows Disc 1 and 2"
    if hints:
        for h in hints:
            m = re.match(r"^" + re.escape(h) + r"\s+(.+)$", t, re.I)
            if m:
                rest = re.sub(r"^(?:album\s+completo|álbum\s+completo|full\s+album|album)\s+", "", m.group(1), flags=re.I)
                return _unquote(rest), True, marked
            # loose spelling: "Tyler the Creator - …", "Fred Again"
            words = t.split()
            for i in range(1, len(words)):
                if _norm_artist(" ".join(words[:i])) == _norm_artist(h):
                    return _unquote(" ".join(words[i:])), True, marked

    return _unquote(t), False, marked


def _same_album(a: str, b: str) -> bool:
    n = lambda s: re.sub(r"[\W_]+", "", (s or "").lower().replace("’", "'"))  # noqa: E731
    return bool(n(a)) and n(a) == n(b)


def album_from_playlist(ctx: dict | None, artist: str, *, verify=None):
    """The album this rip belongs to, from its playlist, or None.

    `ctx` is what the downloader captured at submit time: {"id", "title",
    "owner"}. `verify(artist, album)` optionally confirms a guess that the
    title alone can't settle (MusicBrainz); it returns the canonical album
    name or None.

    Trust, strongest first:
      1. a YouTube Music album playlist (OLAK5uy_…);
      2. the title names this track's artist ("Dominic Fike - Sunburn");
      3. the owner is this track's artist ("Sunburn" on Dominic Fike's channel);
      4. the title says it's an album ("In Rainbows (Full Album)");
      5. otherwise only when `verify` confirms it.
    """
    if not ctx or not ctx.get("title"):
        return None
    title, owner, pid = ctx.get("title") or "", ctx.get("owner") or "", ctx.get("id") or ""
    if _YTM_ALBUM.match(pid):
        album = re.sub(r"^(?:album|single|ep)\s*[-–—:]\s*", "", title, flags=re.I).strip()
        return album or None
    if _NOT_ALBUM_ID.match(pid):
        return None

    album, named, marked = parse_playlist_title(title, artist)
    if not album or _GENERIC.fullmatch(album) or (artist and _same_artist(album, artist)):
        return None                              # "Mitski", "Dominic Fike Playlist"
    owner_is_artist = bool(artist and owner and (_same_artist(owner, artist) or _find_artist(owner, [artist])))
    if named or owner_is_artist or marked:
        if verify:
            confirmed = verify(artist, album)
            if confirmed and _same_album(confirmed, album):
                return confirmed                 # canonical spelling/casing
        return album
    if verify:
        confirmed = verify(artist, album)
        if confirmed and _same_album(confirmed, album):
            return confirmed
    return None


def is_album_order(ctx: dict | None, artist: str, album: str | None) -> bool:
    """Whether the playlist's order is the album's track order — true when the
    playlist itself is that album, so its index can be the track number."""
    if not (ctx and album):
        return False
    if _YTM_ALBUM.match(ctx.get("id") or ""):
        return True
    guess = album_from_playlist(ctx, artist)
    return bool(guess) and _same_album(guess, album)


def reconcile_album(album: str | None, existing) -> str | None:
    """Snap `album` onto an existing spelling ("don’t forget about me, demos" →
    "Don't Forget About Me, Demos") so one album doesn't split in two."""
    if not album:
        return album
    for e in existing:
        if e and e != album and _same_album(e, album):
            return e
    return album
