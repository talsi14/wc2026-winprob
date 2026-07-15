"""One-off: build wc2026_bet/assets/entry_photos_b64.json (entry nickname ->
base64 JPEG data URI) from the local photos in wc2026_bet/entries-images/.

Each photo is center-cropped to a square, resized and JPEG-compressed so the
"identity reveal" flip cards on the friends report stay crisp while the page
remains self-contained (no runtime network), mirroring assets/flags_b64.json.
Keyed by the canonical pool entry name (matched case-insensitively to
pool_entries_2026.csv, so guest.jpeg -> "Guest"). Re-run when photos change.

Usage: python3 scripts/_gen_entry_photos_b64.py
"""
from __future__ import annotations

import base64
import csv
import io
import json
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

WC_ROOT = Path(__file__).resolve().parents[1]
IMG_DIR = WC_ROOT / "entries-images"
ENTRIES = WC_ROOT / "data" / "live" / "pool_entries_2026.csv"
OUT = WC_ROOT / "assets" / "entry_photos_b64.json"

SIZE = 448          # square edge in px
QUALITY = 82        # JPEG quality

# Entries whose photo must NOT be cropped (tall selfies where a square center
# crop would cut the face and/or a shirt emblem). For these we keep the WHOLE
# frame ("contain") centered over a blurred, zoomed copy of itself, so the face
# stays fully visible - and for מיסטר לונדון the England crest on the poncho too.
FIT_WHOLE = {"מיסטר לונדון", "הפועל חיפה"}


def _entry_names() -> dict[str, str]:
    """casefold(name) -> canonical entry name, from the pool entries."""
    with ENTRIES.open(encoding="utf-8") as f:
        return {r["name"].casefold(): r["name"] for r in csv.DictReader(f)}


def _cover_square(im: Image.Image) -> Image.Image:
    """Center-crop to a square then resize (fills the frame, may crop edges)."""
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    return im.resize((SIZE, SIZE), Image.LANCZOS)


def _fit_square(im: Image.Image) -> Image.Image:
    """Fit the WHOLE image into a square (no crop): a heavily-blurred, zoomed
    copy fills the background and the fully-contained image sits centered on
    top, so nothing important (face / crest) is ever cut off."""
    bg = ImageOps.fit(im, (SIZE, SIZE), Image.LANCZOS)      # cover-crop fill
    bg = bg.filter(ImageFilter.GaussianBlur(SIZE / 14))
    fg = im.copy()
    fg.thumbnail((SIZE, SIZE), Image.LANCZOS)               # contain (no crop)
    bg.paste(fg, ((SIZE - fg.width) // 2, (SIZE - fg.height) // 2))
    return bg


def _square_jpeg(path: Path, entry: str) -> bytes:
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)            # honour camera orientation
    if im.mode != "RGB":
        im = im.convert("RGB")
    im = _fit_square(im) if entry in FIT_WHOLE else _cover_square(im)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=QUALITY, optimize=True)
    return buf.getvalue()


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    names = _entry_names()
    photos: dict[str, str] = {}
    for path in sorted(IMG_DIR.iterdir()):
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        entry = names.get(path.stem.casefold(), path.stem)
        raw = _square_jpeg(path, entry)
        photos[entry] = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
        print(f"  {entry:22s} <- {path.name:24s} {len(raw)//1024:>4d} KB")
    OUT.write_text(json.dumps(photos, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"\nwrote {OUT}  ({len(photos)} photos, {OUT.stat().st_size//1024} KB)")


if __name__ == "__main__":
    main()
