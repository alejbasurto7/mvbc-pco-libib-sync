import io

from PIL import Image

from lib.card import generate_card_png


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
