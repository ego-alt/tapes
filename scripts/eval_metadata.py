"""Score metadata cleanup against the real YouTube cases in tests/fixtures.

    uv run python scripts/eval_metadata.py            # deterministic only
    uv run python scripts/eval_metadata.py --llm      # also the LLM (needs ANTHROPIC_API_KEY; uses the Batch API)
    uv run python scripts/eval_metadata.py --llm -v   # list every miss

Titles are compared ignoring case, spacing and punctuation, so the LLM fixing
capitalisation doesn't count as a miss.
"""
import json
import pathlib
import re
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from albums import album_from_playlist  # noqa: E402
from cleaning import clean_meta  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def norm(s):
    s = unicodedata.normalize("NFKC", (s or "").replace("’", "'")).lower()
    return re.sub(r"[\W_]+", "", s)


def main():
    use_llm, verbose = "--llm" in sys.argv, "-v" in sys.argv
    titles = json.loads((FIXTURES / "yt_titles.json").read_text())
    albums = json.loads((FIXTURES / "yt_album_playlists.json").read_text())

    items = []
    for i, c in enumerate(titles):
        t, a = clean_meta(c["title"], c["channel"], c["known"])
        items.append((f"t{i}", {"filename": c["title"], "title": t, "artist": a, "channel": c["channel"]}))
    for i, c in enumerate(albums):
        pl = c["playlist"]
        t, a = clean_meta(c["track"], c["artist"])
        items.append((f"a{i}", {"filename": c["track"], "title": t, "artist": c["artist"], "playlist": pl["title"], "playlist_id": pl["id"],
                                "playlist_owner": pl["owner"], "playlist_album": album_from_playlist(pl, c["artist"])}))

    results = {}
    if use_llm:
        from llm_cleaning import correct_tracks_batch
        results = correct_tracks_batch(items, on_status=lambda b: print("batch:", b.processing_status, file=sys.stderr))
        if not results:
            sys.exit("LLM unavailable: set ANTHROPIC_API_KEY")

    def score(name, rows):
        ok = sum(1 for r in rows if r[0])
        print(f"{name}: {ok}/{len(rows)} ({100 * ok / max(1, len(rows)):.0f}%)")
        if verbose:
            for good, label in rows:
                if not good:
                    print("   ", label)

    det_t, llm_t, det_a, llm_a = [], [], [], []
    for i, c in enumerate(titles):
        want_t, want_a = c["want"]
        _, meta = items[i]
        det_t.append((norm(meta["title"]) == norm(want_t) and norm(meta["artist"]) == norm(want_a), f'{c["title"]} → {meta["title"]} / {meta["artist"]}'))
        r = results.get(f"t{i}")
        if use_llm:
            got = (r or {}).get("title"), (r or {}).get("artist")
            llm_t.append((r is not None and norm(got[0]) == norm(want_t) and norm(got[1]) == norm(want_a), f'{c["title"]} → {got[0]} / {got[1]}  (want {want_t} / {want_a})'))
    for i, c in enumerate(albums):
        want = c["want"]
        _, meta = items[len(titles) + i]
        det_a.append((norm(meta["playlist_album"]) == norm(want), f'{c["playlist"]["title"]} → {meta["playlist_album"]!r}  (want {want!r})'))
        r = results.get(f"a{i}")
        if use_llm:
            got = (r or {}).get("album")
            # When the playlist isn't the album, the LLM may still know the track's album; only taking the playlist for one is a miss.
            good = norm(got) == norm(want) if want else (not got or norm(got) not in norm(c["playlist"]["title"]))
            llm_a.append((r is not None and good, f'{c["playlist"]["title"]} | {c["track"]} → {got!r}  (want {want!r})'))

    score("titles, deterministic", det_t)
    if use_llm:
        score("titles, LLM", llm_t)
    score("albums, deterministic", det_a)
    if use_llm:
        score("albums, LLM", llm_a)


if __name__ == "__main__":
    main()
