"""Library card image generator.

Produces a PNG with the patron's name, email, barcode text, and a QR code
encoding the barcode. Pure Pillow + qrcode — no headless browser, no CDN.

The visual design here is intentionally simple. Iterate on this template
during Phase 4 in collaboration with the user.
"""
from __future__ import annotations

import io

import qrcode
from PIL import Image, ImageDraw, ImageFont


CARD_WIDTH = 800
CARD_HEIGHT = 480
PADDING = 30
HEADER_HEIGHT = 80

BG_COLOR = (248, 249, 250)
HEADER_BG = (10, 28, 50)
HEADER_FG = (255, 255, 255)
BODY_FG = (32, 32, 32)
LABEL_FG = (100, 100, 100)


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try a few common system fonts; fall back to PIL's default."""
    candidates = (
        ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
    )
    for name in candidates:
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
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Header bar
    draw.rectangle([(0, 0), (CARD_WIDTH, HEADER_HEIGHT)], fill=HEADER_BG)
    header_font = _load_font(36, bold=True)
    draw.text((PADDING, 20), "MVBC Library", fill=HEADER_FG, font=header_font)

    # QR code on the right
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(barcode)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=HEADER_BG, back_color=BG_COLOR).convert("RGB")
    qr_size = CARD_HEIGHT - HEADER_HEIGHT - PADDING * 2
    qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
    img.paste(qr_img, (CARD_WIDTH - qr_size - PADDING, HEADER_HEIGHT + PADDING))

    # Patron text rows on the left
    label_font = _load_font(18)
    value_font = _load_font(28, bold=True)
    small_font = _load_font(20)

    left_x = PADDING
    y = HEADER_HEIGHT + PADDING

    full_name = f"{first_name} {last_name}".strip()
    draw.text((left_x, y), "NAME", fill=LABEL_FG, font=label_font)
    draw.text((left_x, y + 22), full_name, fill=BODY_FG, font=value_font)

    y += 90
    draw.text((left_x, y), "EMAIL", fill=LABEL_FG, font=label_font)
    draw.text((left_x, y + 22), email, fill=BODY_FG, font=small_font)

    y += 80
    draw.text((left_x, y), "BARCODE", fill=LABEL_FG, font=label_font)
    draw.text((left_x, y + 22), barcode, fill=BODY_FG, font=small_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
