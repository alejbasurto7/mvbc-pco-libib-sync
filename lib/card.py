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


def generate_vip_card_png(
    *,
    first_name: str,
    last_name: str,
    email: str,
    barcode: str,
    background: str = "navy",
) -> bytes:
    """Special-edition dark-mode VIP card.

    Inverts the standard layout: a dark surface fills the whole card,
    Bronze becomes the structural accent (inset frame + labels + badge),
    text shifts to White/Cream, and the QR is rendered Cream-on-dark.
    A Bronze "VIP PATRON" badge sits top-right per the brand's display
    pairing rule (Bronze on dark is display-only, 3:1 large-text).

    background: "navy" (default) uses MVBC Navy #113355. "charcoal" swaps
    to Charcoal #2C2A2B — the brand's stand-in for black, per spec §6
    (no pure #000 on this warm-toned system).
    """
    bg_color = {"navy": NAVY, "charcoal": CHARCOAL}.get(background, NAVY)
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), bg_color)
    draw = ImageDraw.Draw(img)

    # 1. Bronze inset frame — the "special edition" tell. Two thin rules,
    #    inset from the edge, give the card a presentation-piece feel.
    frame_inset = 14
    frame_thickness = 2
    draw.rectangle(
        [
            (frame_inset, frame_inset),
            (CARD_WIDTH - frame_inset - 1, CARD_HEIGHT - frame_inset - 1),
        ],
        outline=BRONZE,
        width=frame_thickness,
    )

    # 2. Wordmark — same two-line lockup, white on navy
    church_font = _load_font(28, bold=True, display=True)
    kicker_font = _load_font(14, display=True)
    draw.text((PADDING, 36), "MOUNT VERNON BAPTIST CHURCH", fill=WHITE, font=church_font)
    draw.text((PADDING, 78), "LIBRARY", fill=BRONZE, font=kicker_font)

    # 3. VIP PATRON badge — top-right corner, Bronze outlined pill with
    #    Bronze text. Sits on the Navy bg as display-only Bronze (large enough
    #    to clear 3:1 contrast). The ★ ornaments render in a system font
    #    (Arial Bold) since Geometria's character set omits U+2605; the
    #    VIP PATRON wordmark stays in the brand display face.
    badge_font = _load_font(14, bold=True, display=True)
    ornament_font: ImageFont.FreeTypeFont | ImageFont.ImageFont = ImageFont.load_default()
    # ★ (U+2605) isn't in Arial's character set on every Windows install,
    # so prefer Segoe UI Symbol — Microsoft's broad-coverage symbol face —
    # before falling back to system Arial and DejaVu.
    for ornament_candidate in (
        "seguisym.ttf", "seguisymbol.ttf",
        "segoeuisymbol.ttf", "SegoeUISymbol.ttf",
        "DejaVuSans-Bold.ttf", "DejaVuSans.ttf",
        "arialbd.ttf", "arial.ttf",
    ):
        try:
            ornament_font = ImageFont.truetype(ornament_candidate, 14)
            break
        except OSError:
            continue
    star = "★"
    gap = "  "
    label = "VIP PATRON"
    star_bbox = draw.textbbox((0, 0), star, font=ornament_font)
    star_w = star_bbox[2] - star_bbox[0]
    label_bbox = draw.textbbox((0, 0), label, font=badge_font)
    label_w = label_bbox[2] - label_bbox[0]
    gap_bbox = draw.textbbox((0, 0), gap, font=badge_font)
    gap_w = gap_bbox[2] - gap_bbox[0]
    badge_text_w = star_w + gap_w + label_w + gap_w + star_w
    badge_text_h = max(
        star_bbox[3] - star_bbox[1],
        label_bbox[3] - label_bbox[1],
    )
    badge_pad_x = 14
    badge_pad_y = 8
    badge_w = badge_text_w + badge_pad_x * 2
    badge_h = badge_text_h + badge_pad_y * 2
    badge_x1 = CARD_WIDTH - PADDING - badge_w
    badge_y1 = 36
    badge_x2 = badge_x1 + badge_w
    badge_y2 = badge_y1 + badge_h
    draw.rounded_rectangle(
        [(badge_x1, badge_y1), (badge_x2, badge_y2)],
        radius=6,
        outline=BRONZE,
        width=2,
    )
    # Baseline-align the star and label by anchoring each from the badge's
    # top-padding edge, offset by the glyph's own top-bearing.
    cursor_x = badge_x1 + badge_pad_x
    text_y = badge_y1 + badge_pad_y
    draw.text((cursor_x, text_y - star_bbox[1]), star, fill=BRONZE, font=ornament_font)
    cursor_x += star_w + gap_w
    draw.text((cursor_x, text_y - label_bbox[1]), label, fill=BRONZE, font=badge_font)
    cursor_x += label_w + gap_w
    draw.text((cursor_x, text_y - star_bbox[1]), star, fill=BRONZE, font=ornament_font)

    # 4. Bronze rule separating header from patron block
    rule_y = HEADER_HEIGHT
    draw.rectangle(
        [(PADDING, rule_y), (CARD_WIDTH - PADDING, rule_y + BRONZE_RULE_HEIGHT)],
        fill=BRONZE,
    )

    # 5. QR code — Cream on Navy (inverse of standard card)
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(barcode)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=CREAM, back_color=bg_color).convert("RGB")
    qr_size = CARD_HEIGHT - HEADER_HEIGHT - PADDING * 2 - frame_inset
    qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
    qr_x = CARD_WIDTH - qr_size - PADDING
    qr_y = HEADER_HEIGHT + PADDING + BRONZE_RULE_HEIGHT
    img.paste(qr_img, (qr_x, qr_y))

    # 6. Patron rows on the left — labels in Bronze, values in White/Cream
    label_font = _load_font(12, display=True)
    name_font = _load_font(32, bold=True, display=True)
    value_font = _load_font(18)
    barcode_font = _load_font(16)

    left_x = PADDING
    y = HEADER_HEIGHT + PADDING + BRONZE_RULE_HEIGHT + 4

    full_name = f"{first_name} {last_name}".strip()
    draw.text((left_x, y), "NAME", fill=BRONZE, font=label_font)
    draw.text((left_x, y + 18), full_name, fill=WHITE, font=name_font)

    y += 80
    draw.text((left_x, y), "EMAIL", fill=BRONZE, font=label_font)
    draw.text((left_x, y + 18), email, fill=CREAM, font=value_font)

    y += 70
    draw.text((left_x, y), "BARCODE", fill=BRONZE, font=label_font)
    draw.text((left_x, y + 18), barcode, fill=CREAM, font=barcode_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
