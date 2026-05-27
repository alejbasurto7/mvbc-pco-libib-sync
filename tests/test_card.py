import io

from PIL import Image

from lib.card import generate_card_png, generate_vip_card_png, select_png_generator
from lib.web_card import VIP_BARCODES

JOSEPH_BARCODE = next(iter(VIP_BARCODES))


def test_generate_card_returns_valid_png_bytes():
    png_bytes = generate_card_png(
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        barcode="BC-12345",
    )
    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 0
    # Validate it's a real PNG by opening
    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG"
    # Sanity dimensions
    assert img.size[0] >= 400  # width
    assert img.size[1] >= 200  # height


def test_generate_card_with_long_name_does_not_crash():
    png_bytes = generate_card_png(
        first_name="VeryLongFirstNameIndeed",
        last_name="EquallyLongLastNameForReal",
        email="this-is-an-extremely-long-email-address@example.com",
        barcode="BC-12345-67890",
    )
    Image.open(io.BytesIO(png_bytes))  # parses OK


# --- select_png_generator ----------------------------------------------------


def test_select_png_generator_returns_vip_for_joseph():
    assert select_png_generator(barcode=JOSEPH_BARCODE) is generate_vip_card_png


def test_select_png_generator_returns_standard_for_non_vip():
    assert select_png_generator(barcode="2020000000001") is generate_card_png


def test_select_png_generator_returns_standard_for_empty_barcode():
    # Empty/missing barcode must NEVER accidentally opt into VIP. The
    # standard generator will surface the bad input downstream.
    assert select_png_generator(barcode="") is generate_card_png
