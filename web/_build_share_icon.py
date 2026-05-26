"""One-off generator for the Safari Share button glyph used in welcome emails.

Outputs:
  - web/share-icon.png      (48x48, navy stroke on transparent — visual reference)

Also prints the base64 data URI to stdout so the value can be pasted into
``templates/welcome_card_section.html``. The PWA card itself uses an inline
SVG version of the same glyph (see ``templates/web_card.html``); email is a
PNG because Gmail strips inline SVG.

Run once whenever the glyph changes.
"""
from __future__ import annotations

import base64
from pathlib import Path

from PIL import Image, ImageDraw

OUTPUT = Path(__file__).resolve().parent / "share-icon.png"

SIZE = 48
STROKE = 3
NAVY = (17, 51, 85, 255)  # #113355


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Tray: U-shape, open at top. Single polyline so the bottom corners
    # are rounded via joint="curve".
    d.line(
        [(12, 22), (12, 42), (36, 42), (36, 22)],
        fill=NAVY, width=STROKE, joint="curve",
    )
    # Arrow shaft.
    d.line([(24, 6), (24, 30)], fill=NAVY, width=STROKE)
    # Arrow head — chevron meeting the shaft at the apex.
    d.line(
        [(16, 14), (24, 6), (32, 14)],
        fill=NAVY, width=STROKE, joint="curve",
    )

    img.save(OUTPUT, "PNG", optimize=True)
    print(f"wrote {OUTPUT} ({SIZE}x{SIZE})")

    b64 = base64.b64encode(OUTPUT.read_bytes()).decode()
    print()
    print("Paste this data URI into welcome_card_section.html:")
    print(f"data:image/png;base64,{b64}")


if __name__ == "__main__":
    main()
