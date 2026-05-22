"""One-off icon generator for the PWA card.

Reads the MVBC navy emblem and produces:
  - icons/touch-180.png   (180x180, Apple home-screen — emblem on cream, edge-to-edge with safe padding)
  - icons/icon-192.png    (192x192 maskable — emblem on cream with 80% safe zone)
  - icons/icon-512.png    (512x512 maskable — same proportions as 192)

Run once whenever the source emblem changes. Output is committed to the repo.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

_REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_EMBLEM = _REPO_ROOT / "lib" / "assets" / "MVBC-Emblem-Navy.png"
OUTPUT_DIR = Path(__file__).resolve().parent / "icons"

CREAM = (243, 240, 235, 255)


def _render(size: int, *, safe_fraction: float, out: Path) -> None:
    """Render a square icon: cream background, emblem centered at `safe_fraction` of the side."""
    canvas = Image.new("RGBA", (size, size), CREAM)

    emblem = Image.open(SOURCE_EMBLEM).convert("RGBA")
    # Fit emblem to safe area while preserving aspect ratio.
    safe = int(size * safe_fraction)
    ew, eh = emblem.size
    scale = min(safe / ew, safe / eh)
    tw, th = max(1, int(ew * scale)), max(1, int(eh * scale))
    emblem = emblem.resize((tw, th), Image.LANCZOS)

    x = (size - tw) // 2
    y = (size - th) // 2
    canvas.paste(emblem, (x, y), emblem)

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "PNG", optimize=True)
    print(f"wrote {out} ({size}x{size})")


def main() -> None:
    # Apple touch icon: ~88% (Apple applies its own corner mask; little padding needed)
    _render(180, safe_fraction=0.88, out=OUTPUT_DIR / "touch-180.png")
    # Android maskable: 80% safe zone (Android crops to a circle/squircle/rounded square)
    _render(192, safe_fraction=0.80, out=OUTPUT_DIR / "icon-192.png")
    _render(512, safe_fraction=0.80, out=OUTPUT_DIR / "icon-512.png")


if __name__ == "__main__":
    main()
