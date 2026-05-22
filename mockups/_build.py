"""One-shot builder for design prototype HTML files.

Generates 4 self-contained mockups + an index page in this folder.
Patron data is hardcoded test data (Joseph Shanahan, ID 12345).
Run from project root: .venv/Scripts/python.exe mockups/_build.py
"""
from __future__ import annotations

import base64
import io
import pathlib

import qrcode

# Brand palette (matches lib/card.py)
CREAM = "#F3F0EB"
NAVY = "#113355"
BRONZE = "#C3AA7C"
CHARCOAL = "#2C2A2B"

# Test patron data (longest name in db — stress-test for line wrapping)
FIRST = "Sebastian"
LAST = "Parra-Diaz"
FULL = f"{FIRST} {LAST}"
MEMBER_ID = "2020000006497"
QR_DATA = "2020000006497"


def make_qr_data_uri(data: str, fill: str = NAVY, back: str = CREAM) -> str:
    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fill, back_color=back)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


QR_URI = make_qr_data_uri(QR_DATA)


def png_data_uri(path: pathlib.Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


# MVBC emblems from sibling project (read once, inlined into each mockup)
_EMBLEM_DIR = pathlib.Path(
    r"c:\Users\T0226129\Claude\Projects\MVBC-PCO-Directory"
    r"\src\mvbc_directory\web\static\images"
)
EMBLEM_URI = png_data_uri(_EMBLEM_DIR / "MVBC-Emblem-Navy.png")
EMBLEM_100_URI = png_data_uri(_EMBLEM_DIR / "MVBC-Emblem-Navy-100.png")

OUT_DIR = pathlib.Path(__file__).parent

FONT_FACES = """
  @font-face {
    font-family: 'Geometria';
    src: url('../fonts/Geometria-Medium.woff') format('woff');
    font-weight: 500; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Geometria';
    src: url('../fonts/Geometria-Bold.woff') format('woff');
    font-weight: 700; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Geometria';
    src: url('../fonts/Geometria-ExtraBold.woff') format('woff');
    font-weight: 800; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Open Sans';
    src: url('../fonts/OpenSans-Regular.ttf') format('truetype');
    font-weight: 400; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Open Sans';
    src: url('../fonts/OpenSans-SemiBold.ttf') format('truetype');
    font-weight: 600; font-style: normal; font-display: swap;
  }
  @font-face {
    font-family: 'Open Sans';
    src: url('../fonts/OpenSans-Bold.ttf') format('truetype');
    font-weight: 700; font-style: normal; font-display: swap;
  }
"""

COMMON_HEAD = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="{navy}">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="robots" content="noindex,nofollow">
<title>MVBC Library Card — {full}</title>
""".format(navy=NAVY, full=FULL)


# MOCKUP_B (Editorial v1, all-Geometria) and MOCKUP_D (Illustrated v1, all-Geometria)
# along with the v2 OFL-serif variants were dropped in favor of the v3 hybrids.
# See Git history if you need to recover them.

# -------------------------------------------------------------------------
# MOCKUP C v2 — Same badge layout as C but sized to match B (380px wide,
# 32px horizontal padding). Type, QR, and emblem scaled up proportionally.
# -------------------------------------------------------------------------
MOCKUP_C_V2 = """<!doctype html>
<html lang="en">
<head>
""" + COMMON_HEAD + f"""
<style>
  {FONT_FACES}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ height: 100%; }}
  body {{
    background: #E7E2D6;
    color: {NAVY};
    font-family: 'Geometria', system-ui, sans-serif;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
    min-height: 100vh;
  }}
  .badge {{
    width: 100%;
    max-width: 380px;
    background: {CREAM};
    border-radius: 16px;
    border: 1px solid rgba(17,51,85,0.12);
    box-shadow: 0 12px 32px rgba(17,51,85,0.22);
    padding: 0 32px 36px;
    position: relative;
    overflow: hidden;
  }}
  .badge-stripe {{
    background: {NAVY};
    color: {CREAM};
    text-align: center;
    padding: 22px 32px 20px;
    margin: 0 -32px 36px;
    border-radius: 16px 16px 0 0;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }}
  .badge-stripe::after {{
    content: "";
    position: absolute;
    bottom: -1px; left: 0; right: 0;
    height: 3px;
    background: {BRONZE};
  }}
  .stripe-emblem {{
    width: 36px;
    height: auto;
    flex-shrink: 0;
    filter: brightness(0) invert(1) sepia(0.1) hue-rotate(180deg);
  }}
  .stripe-text {{ text-align: left; }}
  .org {{
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    white-space: nowrap;
  }}
  .role {{
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 6px;
    text-transform: uppercase;
    margin-top: 3px;
    color: {BRONZE};
    white-space: nowrap;
  }}
  .rule {{
    width: 40px;
    height: 2px;
    background: {BRONZE};
    margin: 12px auto 28px;
    border-radius: 1px;
  }}
  .name {{
    text-align: center;
    font-size: 30px;
    font-weight: 700;
    color: {NAVY};
    margin-bottom: 8px;
    letter-spacing: -0.3px;
    line-height: 1.2;
  }}
  .id {{
    text-align: center;
    font-family: 'Open Sans', sans-serif;
    font-size: 12px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: {CHARCOAL};
    opacity: 0.6;
    margin-bottom: 32px;
  }}
  .qr-wrap {{
    background: white;
    padding: 12px;
    border-radius: 12px;
    margin: 0 auto;
    width: 280px;
    height: 280px;
  }}
  .qr-wrap img {{ width: 100%; height: 100%; display: block; image-rendering: pixelated; }}
  .scan-hint {{
    text-align: center;
    font-size: 11px;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: {CHARCOAL};
    opacity: 0.5;
    margin-top: 20px;
  }}
</style>
</head>
<body>
  <article class="badge">
    <div class="badge-stripe">
      <img class="stripe-emblem" src="{EMBLEM_URI}" alt="MVBC emblem">
      <div class="stripe-text">
        <div class="org">Mount Vernon Baptist Church</div>
        <div class="role">Library</div>
      </div>
    </div>
    <div class="rule"></div>
    <div class="name">{FULL}</div>
    <div class="id">{MEMBER_ID}</div>
    <div class="qr-wrap"><img src="{QR_URI}" alt="QR code for user {MEMBER_ID}"></div>
    <div class="scan-hint">Scan at kiosk</div>
  </article>
</body>
</html>
"""


# -------------------------------------------------------------------------
# MOCKUP C v2 — MONTSERRAT variant. Identical layout to MOCKUP_C_V2 but the
# display family is swapped from commercial Geometria (locally hosted) to
# free Montserrat (Google Fonts CDN, OFL-licensed). Used to A/B test font
# fidelity for the public gh-pages deploy.
# -------------------------------------------------------------------------
GOOGLE_FONTS_LINK_MONTSERRAT = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700;800&family=Open+Sans:wght@400;600;700&display=swap" rel="stylesheet">
"""

MOCKUP_C_MONTSERRAT = """<!doctype html>
<html lang="en">
<head>
""" + COMMON_HEAD + GOOGLE_FONTS_LINK_MONTSERRAT + f"""
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ height: 100%; }}
  body {{
    background: #E7E2D6;
    color: {NAVY};
    font-family: 'Montserrat', system-ui, sans-serif;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
    min-height: 100vh;
  }}
  .badge {{
    width: 100%;
    max-width: 380px;
    background: {CREAM};
    border-radius: 16px;
    border: 1px solid rgba(17,51,85,0.12);
    box-shadow: 0 12px 32px rgba(17,51,85,0.22);
    padding: 0 32px 36px;
    position: relative;
    overflow: hidden;
  }}
  .badge-stripe {{
    background: {NAVY};
    color: {CREAM};
    text-align: center;
    padding: 22px 32px 20px;
    margin: 0 -32px 36px;
    border-radius: 16px 16px 0 0;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }}
  .badge-stripe::after {{
    content: "";
    position: absolute;
    bottom: -1px; left: 0; right: 0;
    height: 3px;
    background: {BRONZE};
  }}
  .stripe-emblem {{
    width: 36px;
    height: auto;
    flex-shrink: 0;
    filter: brightness(0) invert(1) sepia(0.1) hue-rotate(180deg);
  }}
  .stripe-text {{ text-align: left; }}
  .org {{
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    white-space: nowrap;
  }}
  .role {{
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 6px;
    text-transform: uppercase;
    margin-top: 3px;
    color: {BRONZE};
    white-space: nowrap;
  }}
  .rule {{
    width: 40px;
    height: 2px;
    background: {BRONZE};
    margin: 12px auto 28px;
    border-radius: 1px;
  }}
  .name {{
    text-align: center;
    font-size: 30px;
    font-weight: 700;
    color: {NAVY};
    margin-bottom: 8px;
    letter-spacing: -0.3px;
    line-height: 1.2;
  }}
  .id {{
    text-align: center;
    font-family: 'Open Sans', sans-serif;
    font-size: 12px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: {CHARCOAL};
    opacity: 0.6;
    margin-bottom: 32px;
  }}
  .qr-wrap {{
    background: white;
    padding: 12px;
    border-radius: 12px;
    margin: 0 auto;
    width: 280px;
    height: 280px;
  }}
  .qr-wrap img {{ width: 100%; height: 100%; display: block; image-rendering: pixelated; }}
  .scan-hint {{
    text-align: center;
    font-size: 11px;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: {CHARCOAL};
    opacity: 0.5;
    margin-top: 20px;
  }}
</style>
</head>
<body>
  <article class="badge">
    <div class="badge-stripe">
      <img class="stripe-emblem" src="{EMBLEM_URI}" alt="MVBC emblem">
      <div class="stripe-text">
        <div class="org">Mount Vernon Baptist Church</div>
        <div class="role">Library</div>
      </div>
    </div>
    <div class="rule"></div>
    <div class="name">{FULL}</div>
    <div class="id">{MEMBER_ID}</div>
    <div class="qr-wrap"><img src="{QR_URI}" alt="QR code for user {MEMBER_ID}"></div>
    <div class="scan-hint">Scan at kiosk</div>
  </article>
</body>
</html>
"""


# -------------------------------------------------------------------------
# Font A/B comparison page — same card, two display fonts, side by side.
# -------------------------------------------------------------------------
COMPARE_FONTS_INDEX = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MVBC Library Card — Font Comparison (Geometria vs Montserrat)</title>
<style>
  {FONT_FACES}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Open Sans', system-ui, sans-serif;
    background: #ECE6DA;
    color: {NAVY};
    padding: 32px 16px;
  }}
  h1 {{
    font-family: 'Geometria', system-ui, sans-serif;
    font-weight: 800;
    font-size: 24px;
    letter-spacing: 2px;
    text-transform: uppercase;
    text-align: center;
    color: {NAVY};
    margin-bottom: 8px;
  }}
  .lede {{
    text-align: center;
    max-width: 720px;
    margin: 0 auto 32px;
    font-size: 14px;
    color: {CHARCOAL};
    opacity: 0.78;
    line-height: 1.5;
  }}
  .lede strong {{ color: {NAVY}; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 24px;
    max-width: 1100px;
    margin: 0 auto;
  }}
  @media (max-width: 760px) {{
    .grid {{ grid-template-columns: 1fr; }}
  }}
  .tile {{
    background: white;
    border-radius: 16px;
    box-shadow: 0 6px 18px rgba(17,51,85,0.1);
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }}
  .tile header {{
    padding: 16px 20px;
    background: {NAVY};
    color: {CREAM};
  }}
  .tile header .letter {{
    font-family: 'Geometria', system-ui, sans-serif;
    font-weight: 800;
    font-size: 14px;
    letter-spacing: 4px;
    color: {BRONZE};
  }}
  .tile header .label {{
    font-family: 'Geometria', system-ui, sans-serif;
    font-weight: 600;
    font-size: 18px;
    margin-top: 2px;
  }}
  .tile header .note {{
    font-size: 12px;
    opacity: 0.78;
    margin-top: 4px;
    line-height: 1.5;
  }}
  .tile iframe {{
    width: 100%;
    height: 680px;
    border: 0;
    background: #E7E2D6;
  }}
  .tile footer {{
    padding: 12px 20px;
    border-top: 1px solid #eee;
    font-size: 13px;
  }}
  .tile footer a {{
    color: {NAVY};
    font-weight: 600;
    text-decoration: none;
  }}
  .tile footer a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
  <h1>Mockup C — Geometria vs Montserrat</h1>
  <p class="lede">
    Same card, two display fonts. <strong>Geometria</strong> is the commercial brand font already used on the printed PNG and the church website; it can't be committed to a public gh-pages branch. <strong>Montserrat</strong> is the closest free OFL substitute available on Google Fonts. Compare the wordmark on the navy stripe and the patron's name — those are the most visible places the choice shows up.
  </p>
  <div class="grid">
    <div class="tile">
      <header><div class="letter">A</div><div class="label">Geometria</div><div class="note">The locally-hosted commercial font. Slightly more geometric — sharper "M", subtle "rounded square" feel on uppercase letters. Used by the printed PNG card and mvbchurch.org.</div></header>
      <iframe src="mockup-c-badge-v2.html" title="Mockup C with Geometria"></iframe>
      <footer><a href="mockup-c-badge-v2.html" target="_blank">Open standalone →</a></footer>
    </div>
    <div class="tile">
      <header><div class="letter">B</div><div class="label">Montserrat (Google Fonts)</div><div class="note">Free, OFL-licensed, served from Google's CDN. Slightly more rounded — softer "M", a touch more humanist. Closest free substitute and the safe choice for the public gh-pages site.</div></header>
      <iframe src="mockup-c-montserrat.html" title="Mockup C with Montserrat"></iframe>
      <footer><a href="mockup-c-montserrat.html" target="_blank">Open standalone →</a></footer>
    </div>
  </div>
</body>
</html>
"""


# -------------------------------------------------------------------------
# MOCKUP B v3 — Editorial hybrid (Geometria wordmark, Playfair patron name)
# Same layout as v1; only the .name swaps to Playfair for a "diploma" effect.
# -------------------------------------------------------------------------
GOOGLE_FONTS_LINK_B_V3 = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&display=swap" rel="stylesheet">
"""

MOCKUP_B_V3 = """<!doctype html>
<html lang="en">
<head>
""" + COMMON_HEAD + GOOGLE_FONTS_LINK_B_V3 + f"""
<style>
  {FONT_FACES}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ height: 100%; }}
  body {{
    background: linear-gradient(180deg, {CREAM} 0%, #ECE6DA 100%);
    color: {NAVY};
    font-family: 'Open Sans', system-ui, sans-serif;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px;
    min-height: 100vh;
  }}
  .card {{
    width: 100%;
    max-width: 380px;
    background: {CREAM};
    border-radius: 24px;
    box-shadow: 0 18px 48px rgba(17,51,85,0.18), 0 2px 6px rgba(17,51,85,0.08);
    padding: 36px 32px 32px;
    position: relative;
    overflow: hidden;
  }}
  .card::before {{
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 6px;
    background: linear-gradient(90deg, {NAVY} 0%, {NAVY} 70%, {BRONZE} 70%, {BRONZE} 100%);
  }}
  .head {{
    text-align: center;
    margin-bottom: 28px;
    padding-top: 12px;
  }}
  .emblem {{
    width: 56px;
    height: auto;
    display: block;
    margin: 0 auto 14px;
  }}
  .wordmark {{
    font-family: 'Geometria', system-ui, sans-serif;
    font-weight: 800;
    font-size: 17px;
    line-height: 1.1;
    color: {NAVY};
    letter-spacing: -0.2px;
    text-transform: uppercase;
    white-space: nowrap;
  }}
  .sub {{
    font-family: 'Geometria', sans-serif;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 8px;
    text-transform: uppercase;
    color: {BRONZE};
    margin-top: 8px;
  }}
  .name-block {{
    text-align: center;
    margin: 0 0 4px;
  }}
  .name {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 30px;
    font-weight: 700;
    color: {NAVY};
    line-height: 1.15;
    letter-spacing: -0.3px;
  }}
  .qr-wrap {{
    background: {CREAM};
    padding: 12px;
    border: 2px solid {BRONZE};
    border-radius: 14px;
    margin: 0 auto 20px;
    width: 260px;
    height: 260px;
  }}
  .qr-wrap img {{ width: 100%; height: 100%; display: block; image-rendering: pixelated; }}
  .id {{
    text-align: center;
    font-family: 'Geometria', sans-serif;
    font-size: 10px;
    letter-spacing: 4px;
    text-transform: uppercase;
    color: {CHARCOAL};
    opacity: 0.6;
    font-weight: 700;
    margin-bottom: 22px;
  }}
  .motto {{
    text-align: center;
    margin-top: 18px;
    font-family: 'Geometria', system-ui, sans-serif;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 4px;
    text-transform: uppercase;
    color: {BRONZE};
    line-height: 1.5;
  }}
</style>
</head>
<body>
  <article class="card">
    <header class="head">
      <img class="emblem" src="{EMBLEM_URI}" alt="MVBC emblem">
      <div class="wordmark">Mount Vernon Baptist Church</div>
      <div class="sub">Library</div>
    </header>
    <div class="name-block">
      <div class="name">{FULL}</div>
    </div>
    <div class="id">User No. {MEMBER_ID}</div>
    <div class="qr-wrap"><img src="{QR_URI}" alt="QR code for user {MEMBER_ID}"></div>
    <div class="motto">Scan at kiosk</div>
  </article>
</body>
</html>
"""


# -------------------------------------------------------------------------
# Index page — side-by-side tile view of the remaining mockups
# -------------------------------------------------------------------------
INDEX = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MVBC Library Card — Design Prototypes</title>
<style>
  {FONT_FACES}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Open Sans', system-ui, sans-serif;
    background: #ECE6DA;
    color: {NAVY};
    padding: 32px 16px;
  }}
  h1 {{
    font-family: 'Geometria', system-ui, sans-serif;
    font-weight: 800;
    font-size: 24px;
    letter-spacing: 2px;
    text-transform: uppercase;
    text-align: center;
    color: {NAVY};
    margin-bottom: 8px;
  }}
  .lede {{
    text-align: center;
    max-width: 640px;
    margin: 0 auto 32px;
    font-size: 14px;
    color: {CHARCOAL};
    opacity: 0.75;
    line-height: 1.5;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 24px;
    max-width: 1100px;
    margin: 0 auto;
  }}
  @media (max-width: 760px) {{
    .grid {{ grid-template-columns: 1fr; }}
  }}
  .tile {{
    background: white;
    border-radius: 16px;
    box-shadow: 0 6px 18px rgba(17,51,85,0.1);
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }}
  .tile header {{
    padding: 16px 20px;
    background: {NAVY};
    color: {CREAM};
  }}
  .tile header .letter {{
    font-family: 'Geometria', system-ui, sans-serif;
    font-weight: 800;
    font-size: 14px;
    letter-spacing: 4px;
    color: {BRONZE};
  }}
  .tile header .label {{
    font-family: 'Geometria', system-ui, sans-serif;
    font-weight: 600;
    font-size: 18px;
    margin-top: 2px;
  }}
  .tile header .note {{
    font-size: 12px;
    opacity: 0.7;
    margin-top: 4px;
  }}
  .tile iframe {{
    width: 100%;
    height: 680px;
    border: 0;
    background: {CREAM};
  }}
  .tile footer {{
    padding: 12px 20px;
    border-top: 1px solid #eee;
    font-size: 13px;
  }}
  .tile footer a {{
    color: {NAVY};
    font-weight: 600;
    text-decoration: none;
  }}
  .tile footer a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
  <h1>MVBC Library Card — Design Prototypes</h1>
  <p class="lede">
    Each tile shows the card as it would render on a patron's phone after they tap “Add to Home Screen” and launch the icon. Pick the direction you like best (or mix elements) and reply with your choice.
  </p>
  <div class="grid">
    <div class="tile">
      <header><div class="letter">B</div><div class="label">The Membership Card</div><div class="note">Reads as a keepsake. The Playfair serif on the patron's name elevates it like an engraved diploma or museum membership — the card honors the person, not just the function. Centered layout, bronze-framed QR, warmer and more personal. Choose this if you want patrons to feel they belong.</div></header>
      <iframe src="mockup-b-editorial-v3.html" title="Mockup B"></iframe>
      <footer><a href="mockup-b-editorial-v3.html" target="_blank">Open standalone →</a></footer>
    </div>
    <div class="tile">
      <header><div class="letter">C</div><div class="label">The Credential</div><div class="note">Reads as a utility. The full-bleed navy stripe is an unmistakable institutional signal — like a conference badge or staff ID. The 280px QR (the largest of the two) is more reliable at the kiosk, and the sans-serif name keeps the focus on function. Choose this if you want patrons to feel it's official and frictionless.</div></header>
      <iframe src="mockup-c-badge-v2.html" title="Mockup C"></iframe>
      <footer><a href="mockup-c-badge-v2.html" target="_blank">Open standalone →</a></footer>
    </div>
  </div>
</body>
</html>
"""


_STALE_FILES = (
    "mockup-a-minimalist.html",
    "mockup-b-editorial.html",
    "mockup-b-editorial-v2.html",
    "mockup-c-badge.html",
    "mockup-c-badge-v3.html",
    "mockup-d-illustrated.html",
    "mockup-d-illustrated-v2.html",
    "mockup-d-illustrated-v3.html",
)


def main() -> None:
    for name in _STALE_FILES:
        stale = OUT_DIR / name
        if stale.exists():
            stale.unlink()
    (OUT_DIR / "mockup-b-editorial-v3.html").write_text(MOCKUP_B_V3, encoding="utf-8")
    (OUT_DIR / "mockup-c-badge-v2.html").write_text(MOCKUP_C_V2, encoding="utf-8")
    (OUT_DIR / "mockup-c-montserrat.html").write_text(MOCKUP_C_MONTSERRAT, encoding="utf-8")
    (OUT_DIR / "index.html").write_text(INDEX, encoding="utf-8")
    (OUT_DIR / "compare-fonts.html").write_text(COMPARE_FONTS_INDEX, encoding="utf-8")
    print("Wrote 5 files to", OUT_DIR)


if __name__ == "__main__":
    main()
