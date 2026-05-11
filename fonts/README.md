# Optional brand fonts

`lib/card.py` looks for these TTF files in this directory before falling back
to system fonts. Drop them here to upgrade card rendering fidelity to the MVBC
brand.

## Display family (headlines, wordmark)

The brand calls for **Geometria** (commercial — licensed from MyFonts /
Fontspring). If you have the license, drop these files in:

- `Geometria-Medium.ttf`
- `Geometria-Bold.ttf`
- `Geometria-ExtraBold.ttf`

If Geometria isn't licensed, use **Montserrat** as the free substitute (close
geometric sans, available from Google Fonts):

- `Montserrat-Regular.ttf`
- `Montserrat-Medium.ttf`
- `Montserrat-Bold.ttf`
- `Montserrat-ExtraBold.ttf`

Download Montserrat: https://fonts.google.com/specimen/Montserrat

## Body family

The brand uses **Open Sans** (free, Google Fonts):

- `OpenSans-Regular.ttf`
- `OpenSans-SemiBold.ttf`
- `OpenSans-Bold.ttf`

Download Open Sans: https://fonts.google.com/specimen/Open+Sans

## Why optional

The card generator works without any of these files — it falls back to system
Arial (Windows/macOS) or DejaVuSans (Linux/Ubuntu, e.g., GitHub Actions). The
fallback is functional but visually generic. Adding the brand TTFs makes the
rendered card match the MVBC brand exactly.

## Licensing note

Commit only fonts whose license permits redistribution. Open Sans and Montserrat
are SIL Open Font License (safe to commit). Geometria is commercial — do **not**
commit its TTFs to a public GitHub repo; if you want production rendering to
use Geometria, install it via the GitHub Actions workflow from a private source
instead.
