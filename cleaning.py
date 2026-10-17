"""Deterministic metadata cleanup for ripped tracks.

Pure string work — no network, no fuzzy matching against a music DB, so it can
never mistag the way an autotagger can. Shared by the download worker (cleans
each new rip) and the `flask retag` command (cleans the existing library).
"""
import re
import unicodedata

# Words that, on their own, are just YouTube noise — used to decide whether a
# bracketed group or a trailing segment is pure cruft.
_CRUFT_WORDS = {
    "official", "offical", "music", "video", "videos", "audio", "lyric", "lyrics",
    "lyrical", "visualizer", "visualiser", "hd", "hq", "uhd", "fhd", "4k", "8k",
    "mv", "explicit", "clean", "stereo", "mono", "pcm", "remaster", "remastered",
    "only", "full", "album", "version", "vevo",
    "oficial", "officiel", "vídeo", "clip", "clipe", "animated", "vinyl",
    "reimagined", "performance", "m/v",
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
_TITLE_SPLIT = re.compile(r"^(.{1,60}?)(?:\s+[-–—_]\s+|(?<=\w)[-–—]\s+|\s+[-–—](?=\w))(.+)$")
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
        if m and (_is_trailing_cruft(m.group(1)) or not re.search(r"\w", m.group(1))):
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
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))      # "ROSALÍA" = "Rosalia"
    s = re.sub(r"(vevo|official|music|tv|records|hq|hd)$", "", s.lower().strip())
    return re.sub(r"[^0-9a-z一-鿿]+", "", s)


def _same_artist(a, b):
    """Same act, allowing channel spellings: 'EminemMusic', 'Fred again . .',
    'AdeleVEVO' and 'Official Arctic Monkeys' all match the plain name. Exact
    after normalising — 'Bad Bunny - Tití Me Preguntó' is not 'Bad Bunny'."""
    na, nb = _norm_artist(a), _norm_artist(b)
    na, nb = re.sub(r"^official", "", na), re.sub(r"^official", "", nb)
    return bool(na) and na == nb


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


# ---------- clean_meta: the full title/artist pipeline ----------
#
# A video title arrives in many shapes. The pipeline peels it in order:
#   1. upload cruft in brackets — "(Official Audio)", "[가사해석]", "(2018)",
#      "(2004 Remaster)", "(1080p)" — and trailing "| Lyrics" / "| Channel" bits;
#   2. leading noise — "【和訳】", "[가사 번역]", a translated tagline ending ":";
#   3. structure — "Artist - Song" or "Song - Artist" (decided by which side names
#      a known artist), "Artist | Song", "Artist "Song"", "Artist: Song";
#   4. tidy — "feat." spelled one way, an alias in another script dropped from
#      the artist ("NewJeans (뉴진스)"), channel suffixes off the artist.
# `known_artists` are names we already trust (the library's artists, the
# playlist's artist); with them, reversed and noisy titles resolve correctly.

# Brackets whose content is a lyric/translation/subtitle note, in the languages
# these uploads come in.
_NOTE_WORDS = re.compile(
    r"(lyric|letra|legend|tradu|subt|sub\b|vietsub|thaisub|engsub|indo\s?sub|terjemah|lirik|"
    r"가사|해석|번역|자막|한글|中字|中文|翻譯|翻译|歌詞|歌词|和訳|日本語|แปล|перевод|текст)",
    re.I)
_YEAR_ONLY = re.compile(r"^\s*(19|20)\d{2}\s*$")
_REMASTER = re.compile(r"^\s*((19|20)\d{2}\s*)?(digital(ly)?\s*)?remaster(ed)?(\s*version)?(\s*(19|20)\d{2})?\s*$", re.I)
_QUALITY = re.compile(r"^\s*(\d{3,4}p|hd|hq|4k|8k|high\s*quality|best\s*quality|audio(\s*only)?|official|explicit|clean|uncensored|dirty)(\s*(hd|hq|\d{3,4}p))?\s*$", re.I)
_EDITION = re.compile(r"^\s*(deluxe|expanded|anniversary|bonus)(\s+(edition|version|track))?\s*$", re.I)
_PROD = re.compile(r"^\s*(prod\.?|produced)\s+(by\s+)?\S", re.I)
_ANY_BRACKET = re.compile(r"\s*([\(\[【〔（{])([^()\[\]【】〔〕（）{}]*)([\)\]】〕）}])")
_LEADING_BRACKET = re.compile(r"^\s*[\(\[【〔（]([^()\[\]【】〔〕（）]*)[\)\]】〕）]\s*")
_QUOTED = re.compile(r"^(?P<pre>.*?)\s*[\"“”'‘’「『«]\s*(?P<song>[^\"“”‘’」』»]+?)\s*[\"“”'‘’」』»]\s*(?P<post>.*)$")
_FEAT = re.compile(r"\s*[\(\[]?\b(?:ft|feat|featuring)\b\.?\s+([^()\[\]]+?)[\)\]]?\s*$", re.I)
_PIPE = re.compile(r"\s+(?:\||//|•|·)\s+")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯ㄱ-ㆎ]")
_LATIN = re.compile(r"[A-Za-z]")


def _is_note(inner: str) -> bool:
    """A bracketed group that isn't part of the song's name."""
    if _is_all_cruft(inner) or _YEAR_ONLY.match(inner) or _REMASTER.match(inner):
        return True
    if _QUALITY.match(inner) or _EDITION.match(inner) or _PROD.match(inner):
        return True
    if _NOTE_WORDS.search(inner):
        return True
    if re.match(r"\s*(?:by|directed by|dir\.?)\s", inner, re.I):    # "(By Clement Picon)": the video's maker
        return True
    toks = _tokens(inner.replace("°", ""))
    # "(Official Vinyl Video)", "(Video Oficial)", "(Audio/Estudio)", "(360 Visualizer)":
    # a short group that's about the video, not the song.
    videoish = {"official", "oficial", "officiel", "video", "vídeo", "visualizer", "visualiser",
                "audio", "mv", "m/v", "clip", "clipe", "lyric", "lyrics"}
    if toks and len(toks) <= 6 and any(t in videoish for t in toks) and not any(
            t in {"live", "remix", "edit", "mix", "version", "ver", "acoustic", "demo", "cover"} for t in toks):
        return True
    toks = _tokens(inner)
    # "Official Lyric Video", "Official Music Video HD", "MV" …
    return bool(toks) and all(t in _CRUFT_WORDS or t in {"lyric", "lyrics", "m/v", "m", "v", "official"} for t in toks)


_NOTE_TAIL = re.compile(
    r"(?:\s+|(?<=[」』】]))(?:lyrics?|letras?|legendado|traducción|tradução|lirik|가사|해석|번역|자막|한글|中字|中文|中英|翻譯|翻译|歌詞|歌词|和訳|แปล)\S*[^|]*$",
    re.I)
_NOTE_HEAD = re.compile(r"^(?:แปลเพลง|가사해석|가사|中字|和訳|lyrics?:?)\s+", re.I)


_TAIL_WORDS = re.compile(
    r"(?:\s+(?:official|oficial|original|music|lyrics?|video|vídeo|clip|audio|hd|hq|4k|1080p|"
    r"remastered|full\s+song))+\s*$", re.I)
_SYMBOLS_TAIL = re.compile(r"[\s\u200d\ufe0f\U0001F000-\U0001FAFF\u2600-\u27BF]+$")


def _strip_tail_words(s: str) -> str:
    """'Digital Love video oficial HD', 'here comes the sun original video',
    'Vampire 🧛‍♂️' → just the song. Only words that never end a real title,
    and only with something left in front."""
    out = _SYMBOLS_TAIL.sub("", s)
    out = _TAIL_WORDS.sub("", out)
    return out if re.search(r"\w", out) else s


def _strip_notes(s: str) -> str:
    prev = None
    while prev != s:
        prev = s
        s = _ANY_BRACKET.sub(lambda m: "" if _is_note(m.group(2)) else m.group(0), s)
    s = re.sub(r"\.(mp3|mp4|m4a|webm|wav|flac)\s*$", "", s, flags=re.I)   # "Song.mp4"
    s = re.sub(r"\s+@\S.*$", "", s)                                        # "Song @Inkigayo 230115"
    s = _NOTE_HEAD.sub("", s)                                               # "แปลเพลง Song"
    # A lyric line quoted after "Artist - Song" — never the song itself, as in
    # 'Dominic Fike "King Of Everything"'.
    s = re.sub(r"(\s[-–—]\s.*?\S)\s+[\"“][^\"“”]{18,}[\"”]\s*$", r"\1", s)
    m = _NOTE_TAIL.search(s)                                                # "Song 가사해석", "Song lyrics 中英歌詞"
    if m and m.start() > 0:
        s = s[:m.start()]
        if _LATIN.search(s):
            s = re.sub(r"[\s\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+$", "", s)   # its translated title
    return s


def _matches(name: str, hints) -> bool:
    return bool(name) and any(h and _same_artist(name, h) for h in hints)


def _find_artist(side: str, hints):
    """The hinted artist named by `side`, allowing noise around it: a leading
    tagline ("그냥 미친 … SZA"), the name in two scripts ("酷娃恰莉 Charli XCX",
    "맥 밀러 (Mac Miller)"), a trailing year. Returns the hint's spelling as
    written in `side`, or None."""
    if not side:
        return None
    side = re.sub(r"\s*[\[【][^\]】]*[\]】]\s*$", "", side).strip()   # "NewJeans [Music Bank]"
    side = re.sub(r"\s*\((?:speed|sped|slowed|lyrics?|audio)[^)]*\)\s*$", "", side, flags=re.I).strip()
    alias = _strip_alias(side)
    latin = " ".join(w for w in alias.split() if not _CJK.search(w) and not re.fullmatch(r"\W+", w))
    if latin and latin != alias and _LATIN.search(latin) and _matches(latin, hints):
        return latin                             # "周杰倫 Jay Chou", "그냥 … ㄷㄷ SZA"
    # Only Latin letters may be dropped by normalising; a Hangul tagline before
    # the name ("인생에서 … ,Frank Ocean") is noise to cut, not part of the name.
    if not (_CJK.search(alias) and _LATIN.search(alias)) and _matches(alias, hints):
        return alias
    words = side.split()
    for h in hints:
        nh = _norm_artist(h)
        if not nh:
            continue
        for i in range(1, len(words)):           # the longest tail that is the artist
            tail = re.sub(r"\s+(19|20)\d{2}$", "", " ".join(words[i:])).strip(" ,:")
            if not re.match(r"\w", tail) or (_CJK.search(tail) and not _CJK.search(h) and _strip_alias(tail) == tail):
                continue
            if _norm_artist(tail) == nh or _norm_artist(_strip_alias(tail)) == nh:
                before = " ".join(words[:i]).lower()
                if re.search(r"(&|\bx|\band|\bwith|,|\+|/|\by|\bft\.?|\bfeat\.?)$", before):
                    return side                  # "Dua Lipa & Arctic Monkeys": a duet
                return _strip_alias(tail)
    if _matches(alias, hints):
        return alias
    return None


def _strip_alias(name: str) -> str:
    """'NewJeans (뉴진스)' → 'NewJeans'; '뉴진스(NewJeans)' → 'NewJeans'. A name
    given twice in two scripts keeps the Latin one (what the channel uses)."""
    m = re.match(r"^\s*(.+?)\s*[\(（]([^()（）]+)[\)）]\s*$", name or "")
    if not m:
        return (name or "").strip()
    outer, inner = m.group(1).strip(), m.group(2).strip()
    if bool(_CJK.search(outer)) != bool(_CJK.search(inner)):
        return outer if _LATIN.search(outer) else inner
    return name.strip()


def _tidy_artist(a: str) -> str:
    a = _TOPIC.sub("", (a or "")).strip()
    a = _LEAD_NUM.sub("", a)
    a = re.sub(r"^@", "", a)
    a = re.sub(r"\s*vevo$", "", a, flags=re.I) if not re.fullmatch(r"vevo", a, re.I) else a
    a = re.sub(r"^(official)\s+|\s+(official)$", "", a, flags=re.I)
    return _strip_alias(a).strip(" -–—|:")


def _tidy_title(t: str) -> str:
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—|:·•/")
    m = _FEAT.search(t)
    if m and m.start() > 0:
        t = f"{t[:m.start()].rstrip(' -–—')} (feat. {m.group(1).strip()})"
    return _unwrap_quotes(t.strip())


def _orient(left: str, right: str, hints):
    """(title, artist) from two halves around a separator: the half that names a
    known artist is the artist; otherwise the usual "Artist - Song"."""
    la, ra = _find_artist(left, hints), _find_artist(right, hints)
    if ra and not la:
        return left, ra
    return right, la or left


def clean_meta(title: str, artist: str, known_artists=()):
    """Return cleaned (title, artist).

    `artist` is the uploader-derived tag (often the channel). `known_artists`
    are trusted names — the library's artists and the playlist's artist — used to
    tell "Song - Artist" from "Artist - Song" and to see past leading noise.
    A dash inside an unbalanced bracket is never treated as a separator.
    """
    channel = _tidy_artist(artist)
    hints = [h for h in [channel, *known_artists] if h]

    t = (title or "").replace(" ", " ").strip()
    m = re.fullmatch(r"[「『【]\s*(.+?)\s*[」』】]", t)        # 「coffee - beabadoobee (lyrics)」
    if m:
        t = m.group(1)
    t = _strip_notes(t)
    t = re.sub(r"\s+[-–—]\s+(?:[-–—]\s+)+", " - ", t)      # "Song - (Video Oficial) - Artist"
    t = _strip_tail_words(t)
    t = _strip_trailing_cruft(t)
    t = _TOPIC.sub("", t)
    m = re.match(r"^(.+?)\s+[-–—|]\s+([^-–—|]+?)(?:\s+(?:19|20)\d{2})?$", t)   # "… - DEL Records 2023": the uploader
    if m and channel and _same_artist(m.group(2), channel) and _TITLE_SPLIT.match(m.group(1)):
        t = m.group(1)
    t = _LEAD_NUM.sub("", t)                     # "1. Blue Swede - X"

    # Leading noise: "【和訳】Radiohead – Reckoner", "[가사 번역] 맥 밀러 (Mac Miller) - Good News".
    while True:
        m = _LEADING_BRACKET.match(t)
        if not m or not t[m.end():].strip():
            break
        t = t[m.end():]
    # A tagline before "Artist - Song": "나랑 같이 3일 밤새워: Dominic Fike - 3 Nights".
    m = re.match(r"^(.{1,80}?)[:：,]\s+(.+?\s[-–—]\s.+)$", t)
    if m and not _matches(m.group(1), hints):
        t = m.group(2)

    # Trailing "| Lyrics" / "| One Lyric" / "| Verified" after the song.
    parts = _PIPE.split(t)
    if len(parts) > 1:
        keep = [p for p in parts if not (_is_note(p) or _is_trailing_cruft(p) or _matches(p, [channel])
                                         or p.strip().lower() in {"verified", "lyrics", "official"})]
        artist_parts = [p for p in keep if _matches(p, hints)]
        others = [p for p in keep if not _matches(p, hints)]
        if artist_parts and others:              # "Weird Fishes | Radiohead | From The Basement"
            channel, t = _tidy_artist(artist_parts[0]), others[0]
            hints = [channel, *hints]
        elif keep:
            # "Kate Bush - Running Up That Hill | From Stranger Things 4": the part
            # shaped "Artist - Song" is the song; a show or album name is not.
            shaped = [p for p in keep if _TITLE_SPLIT.match(p.strip()) or _QUOTED.match(p.strip())]
            t = (shaped or keep)[0]

    new_artist = channel
    m = _TITLE_SPLIT.match(t)
    q = _QUOTED.match(t)
    quote_after_split = m and q and q.start("song") > m.end(1)
    if q and q.group("song").strip() and not quote_after_split:
        # Artist "Song" — the quotes mark the song; what's before is the artist.
        pre = q.group("pre").strip(" -–—|:")
        title_out = q.group("song")
        if pre:
            pre = re.sub(r"\s+(performs|presents|sings)$", "", pre, flags=re.I)
            new_artist = _tidy_artist(_find_artist(pre, hints) or pre)
        t = title_out + (" " + q.group("post") if q.group("post") and _FEAT.match(" " + q.group("post")) else "")
    elif m:
        left, right = m.group(1).strip(), m.group(2).strip()
        balanced = left.count("(") == left.count(")") and left.count("[") == left.count("]")
        if right and balanced:
            if _NUM_PREFIX.fullmatch(left):
                t = right                                       # "01 - Song"
            elif re.search(r"[^\W\d_]", left):
                t, a = _orient(left, right, hints)
                new_artist = _tidy_artist(a)
    else:
        # Short names ("Love", "Air") would split ordinary titles; only names
        # distinctive enough to be the artist count without a real separator.
        loose = [h for h in (known_artists or hints) if len(_norm_artist(h)) >= 4]
        # Separators that only count after a known artist: "Peso Pluma: Ella Baila
        # Sola", "Mac Miller-Good News", "Burial, Archangel", "Burial   Archangel",
        # and no separator at all, "Karol G PROVENZA".
        for pat in (r"^(.{1,60}?)[:：]\s+(.+)$", r"^(.{1,60}?)[-–—](.+)$", r"^(.{1,60}?),\s+(.+)$",
                    r"^(.{1,60}?)\s{2,}(.+)$", r"^(.{1,60}?)\s*[/／_]\s*(.+)$", r"^(.+?)\s+by\s+(.+)$"):
            m = re.match(pat, t)
            if not (m and m.group(1).strip() and m.group(2).strip()):
                continue
            left, right = m.group(1).strip(), m.group(2).strip()
            # A comma, spaces or a slash also occur inside ordinary titles
            # ("Love, Actually"), so they need a longer name than ":" or "-".
            names = loose if pat.startswith(r"^(.{1,60}?)[:") or "[-–—]" in pat else \
                [h for h in loose if len(_norm_artist(h)) >= 6]
            la = _find_artist(left, names)
            ra = _find_artist(right, names)
            if "by" in pat or "/" in pat:          # "Coffee by Beabadoobee", "Lemon/ Kenshi Yonezu"
                if ra and not la:
                    new_artist, t = _tidy_artist(ra), left
                    break
                if "by" in pat:
                    continue
            if la:
                new_artist, t = _tidy_artist(la), right
                break
        else:
            for h in (h for h in loose if len(_norm_artist(h)) >= 6):
                m = re.match(r"^" + re.escape(h) + r"\s+(.+)$", t, re.I)
                if m:
                    new_artist, t = h, m.group(1)
                    break

    t = _strip_notes(t)
    t = _strip_trailing_cruft(t)
    t = _strip_tail_words(t)
    t = _tidy_title(t)
    if not re.search(r"\w", t):                # never lose the title entirely
        t = _tidy_title(title or "")
    return t, new_artist.strip()
