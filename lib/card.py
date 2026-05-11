"""Library card image generator — MVBC branded.

Produces an 800x480 PNG library card following spec §7 of brand-identity.md:
- Cream (#F3F0EB) background
- Navy (#113355) header bar (~25% of card height) with white wordmark
- Bronze (#C3AA7C) 2-3px accent rule beneath the header (brand signature)
- Patron name in Geometria Bold equivalent, Navy
- Email + barcode in Open Sans equivalent, Charcoal
- Navy QR code on Cream, right side

Font loading: prefers brand fonts (Geometria, Montserrat as licensed-free
substitute for Geometria, Open Sans) from the project's `fonts/` directory if
present, then falls back to common system fonts, then PIL's default. To upgrade
visual fidelity, drop TTF files into `fonts/` at the project root.
"""
from __future__ import annotations

import io
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont


CARD_WIDTH = 800
CARD_HEIGHT = 480
PADDING = 32
HEADER_HEIGHT = 120  # ~25% of card height per brand spec
BRONZE_RULE_HEIGHT = 3

# MVBC brand palette (hex values from brand-identity.md §2)
CREAM = (243, 240, 235)       # #F3F0EB — card background
NAVY = (17, 51, 85)           # #113355 — header bar, primary text, QR code
BRONZE = (195, 170, 124)      # #C3AA7C — accent rule, brand signature
CHARCOAL = (44, 42, 43)       # #2C2A2B — body text
MID_GRAY = (118, 118, 118)    # #767676 — label captions
WHITE = (255, 255, 255)

# Optional project-local fonts directory. Drop TTFs (e.g. Geometria-Bold.ttf,
# Montserrat-Bold.ttf, OpenSans-Regular.ttf) here to upgrade rendering beyond
# system defaults.
_PROJECT_FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"


def _load_font(
    size: int,
    *,
    bold: bool = False,
    display: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a brand-appropriate font for the requested role.

    display=True picks the headline family (Geometria preferred, Montserrat
    as licensed-free fallback). display=False picks the body family
    (Open Sans preferred, system sans-serif as fallback).
    """
    if display:
        if bold:
            candidates = [
                "Geometria-Bold.woff", "Geometria-Bold.ttf",
                "Geometria-ExtraBold.woff", "Geometria-ExtraBold.ttf",
                "Montserrat-Bold.ttf", "Montserrat-ExtraBold.ttf",
                "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
            ]
        else:
            candidates = [
                "Geometria-Medium.woff", "Geometria-Medium.ttf",
                "Montserrat-Medium.ttf", "Montserrat-Regular.ttf",
                "arial.ttf", "Arial.ttf", "DejaVuSans.ttf",
            ]
    else:
        if bold:
            candidates = [
                "OpenSans-Bold.ttf", "OpenSans-SemiBold.ttf",
                "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
            ]
        else:
            candidates = [
                "OpenSans-Regular.ttf",
                "arial.ttf", "Arial.ttf", "DejaVuSans.ttf",
            ]

    for name in candidates:
        if _PROJECT_FONTS_DIR.is_dir():
            local = _PROJECT_FONTS_DIR / name
            if local.is_file():
                try:
                    return ImageFont.truetype(str(local), size)
                except OSError:
                    pass
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def generate_card_png(
    *,
    first_name: str,
    last_name: str,
    email: str,
    barcode: str,
) -> bytes:
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), CREAM)
    draw = ImageDraw.Draw(img)

    # 1. Navy header bar
    draw.rectangle([(0, 0), (CARD_WIDTH, HEADER_HEIGHT)], fill=NAVY)

    # 2. Bronze accent rule directly beneath the header — the brand signature
    draw.rectangle(
        [(0, HEADER_HEIGHT), (CARD_WIDTH, HEADER_HEIGHT + BRONZE_RULE_HEIGHT)],
        fill=BRONZE,
    )

    # 3. Wordmark — two-line lockup: church name + "LIBRARY" kicker in Bronze
    church_font = _load_font(28, bold=True, display=True)
    kicker_font = _load_font(14, display=True)
    draw.text((PADDING, 28), "MOUNT VERNON BAPTIST CHURCH", fill=WHITE, font=church_font)
    draw.text((PADDING, 70), "LIBRARY", fill=BRONZE, font=kicker_font)

    # 4. QR code on the right, Navy on Cream
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(barcode)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=NAVY, back_color=CREAM).convert("RGB")
    qr_size = CARD_HEIGHT - HEADER_HEIGHT - PADDING * 2
    qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
    qr_x = CARD_WIDTH - qr_size - PADDING
    qr_y = HEADER_HEIGHT + PADDING + BRONZE_RULE_HEIGHT
    img.paste(qr_img, (qr_x, qr_y))

    # 5. Patron text rows on the left — NAME / EMAIL / BARCODE
    label_font = _load_font(12, display=True)
    name_font = _load_font(32, bold=True, display=True)
    value_font = _load_font(18)
    barcode_font = _load_font(16)

    left_x = PADDING
    y = HEADER_HEIGHT + PADDING + BRONZE_RULE_HEIGHT + 4

    full_name = f"{first_name} {last_name}".strip()
    draw.text((left_x, y), "NAME", fill=MID_GRAY, font=label_font)
    draw.text((left_x, y + 18), full_name, fill=NAVY, font=name_font)

    y += 80
    draw.text((left_x, y), "EMAIL", fill=MID_GRAY, font=label_font)
    draw.text((left_x, y + 18), email, fill=CHARCOAL, font=value_font)

    y += 70
    draw.text((left_x, y), "BARCODE", fill=MID_GRAY, font=label_font)
    draw.text((left_x, y + 18), barcode, fill=CHARCOAL, font=barcode_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
