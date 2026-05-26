"""One-off icon generator for the PWA card.

Renders the Bootstrap "book" glyph (web/icons/_book.svg, navy fill) onto a
cream square at the three sizes the manifest references:

  - icons/touch-180.png   (180x180, Apple home-screen — 88% safe area)
  - icons/icon-192.png    (192x192 maskable — 80% safe area for Android crop)
  - icons/icon-512.png    (512x512 maskable — same proportions as 192)

Run once whenever the glyph or colors change. Output is committed to the repo
and served from the gh-pages branch; production never runs this script, so
``resvg-py`` is intentionally not in requirements.txt.

Setup (one-time, in this venv):
    pip install resvg-py

Run:
    python web/_build_icons.py
"""
from __future__ import annotations

import io
from pathlib import Path

import resvg_py
from PIL import Image

_HERE = Path(__file__).resolve().parent
SOURCE_SVG = _HERE / "icons" / "_book.svg"
OUTPUT_DIR = _HERE / "icons"

CREAM = (243, 240, 235, 255)  # #F3F0EB — matches manifest background_color
NAVY_HEX = "#113355"           # matches manifest theme_color


def _render_glyph(side: int) -> Image.Image:
    """Rasterize the book SVG at `side`x`side` with navy fill, transparent bg."""
    svg = SOURCE_SVG.read_text(encoding="utf-8").replace("currentColor", NAVY_HEX)
    png_bytes = bytes(resvg_py.svg_to_bytes(svg_string=svg, width=side, height=side))
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def _render(size: int, *, safe_fraction: float, out: Path) -> None:
    """Cream square, navy book centered at `safe_fraction` of the side."""
    canvas = Image.new("RGBA", (size, size), CREAM)

    glyph_side = max(1, int(size * safe_fraction))
    glyph = _render_glyph(glyph_side)

    offset = (size - glyph_side) // 2
    canvas.paste(glyph, (offset, offset), glyph)

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "PNG", optimize=True)
    print(f"wrote {out} ({size}x{size})")


def main() -> None:
    _render(180, safe_fraction=0.60, out=OUTPUT_DIR / "touch-180.png")
    _render(192, safe_fraction=0.52, out=OUTPUT_DIR / "icon-192.png")
    _render(512, safe_fraction=0.52, out=OUTPUT_DIR / "icon-512.png")


if __name__ == "__main__":
    main()
