"""Generate a handful of tagged sample MP3s (with embedded cover art) so the
cassette deck has something to play before you point it at a real library.

    uv run python scripts/generate_samples.py

Writes into ./music/<Artist>/<Album>/NN title.mp3. Requires ffmpeg on PATH.
"""

import pathlib
import subprocess
from io import BytesIO

from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TRCK
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
MUSIC = ROOT / "music"

# (title, artist, album, track_no, freq_hz, seconds, (r,g,b))
SAMPLES = [
    ("Warm Static", "The Reels", "Analog Hearts", 1, 220, 8, (254, 128, 25)),
    ("Spool & Thread", "The Reels", "Analog Hearts", 2, 277, 7, (211, 134, 155)),
    ("Tape Hiss Lullaby", "The Reels", "Analog Hearts", 3, 330, 9, (104, 157, 106)),
    ("Midnight Rip", "DJ Orphan", None, None, 440, 6, (131, 165, 152)),
    ("Single Loop", "DJ Orphan", None, None, 392, 7, (250, 189, 47)),
]


def make_cover(title: str, color: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (500, 500), color)
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 480, 480], outline=(20, 20, 20), width=6)
    d.text((40, 230), title, fill=(20, 20, 20))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def main():
    for title, artist, album, no, freq, secs, color in SAMPLES:
        folder = MUSIC / artist / (album or "Singles")
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{no:02d} {title}.mp3" if no else f"{title}.mp3"
        path = folder / name

        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"sine=frequency={freq}:duration={secs}",
             "-codec:a", "libmp3lame", "-qscale:a", "5", str(path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        tags = ID3()
        tags.add(TIT2(encoding=3, text=title))
        tags.add(TPE1(encoding=3, text=artist))
        if album:
            tags.add(TALB(encoding=3, text=album))
        if no:
            tags.add(TRCK(encoding=3, text=str(no)))
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover",
                      data=make_cover(title, color)))
        tags.save(path)
        print(f"  {path.relative_to(ROOT)}")

    print(f"Done. {len(SAMPLES)} tracks under {MUSIC.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
