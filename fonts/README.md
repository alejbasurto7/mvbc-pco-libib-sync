# Brand fonts for the library card

`lib/card.py` loads fonts from this directory first, then falls back to system
fonts, then PIL's default.

## What's installed (auto-detected by the card generator)

| Family       | Files                                                                  | License       | Committed? |
|--------------|------------------------------------------------------------------------|---------------|------------|
| Geometria    | `Geometria-Medium.woff`, `Geometria-Bold.woff`, `Geometria-ExtraBold.woff` | Commercial (MVBC site license) | **No** (gitignored) |
| Open Sans    | `OpenSans-Regular.ttf`, `OpenSans-SemiBold.ttf`, `OpenSans-Bold.ttf`   | SIL OFL       | Yes        |

## How to refresh

```bash
# Geometria (from mvbchurch.org WordPress theme)
cd fonts
curl -o Geometria-Medium.woff    https://mvbchurch.org/wp-content/themes/mvbchurch2025/fonts/Geometria-Medium.woff
curl -o Geometria-Bold.woff      https://mvbchurch.org/wp-content/themes/mvbchurch2025/fonts/Geometria-Bold.woff
curl -o Geometria-ExtraBold.woff https://mvbchurch.org/wp-content/themes/mvbchurch2025/fonts/Geometria-ExtraBold.woff

# Open Sans (from Google Fonts, OFL-licensed mirror)
curl -L -o OpenSans-Regular.ttf  https://raw.githubusercontent.com/googlefonts/opensans/main/fonts/ttf/OpenSans-Regular.ttf
curl -L -o OpenSans-SemiBold.ttf https://raw.githubusercontent.com/googlefonts/opensans/main/fonts/ttf/OpenSans-SemiBold.ttf
curl -L -o OpenSans-Bold.ttf     https://raw.githubusercontent.com/googlefonts/opensans/main/fonts/ttf/OpenSans-Bold.ttf
```

## Licensing

- **Open Sans** is SIL Open Font License — safe to commit, redistribute, embed.
- **Geometria** is commercial. MVBC licenses it for the church website. Use on
  other MVBC-internal tools (like the library card) is reasonable; do NOT commit
  the WOFF files to a public repo, and do NOT redistribute outside MVBC. They
  are gitignored. If the repo is private, you can opt to remove the gitignore
  entry and commit them.
- For the GitHub Actions runner (which won't have Geometria), the card
  generator falls back to Montserrat (if dropped in) → Arial → DejaVuSans.
  Functional, not exact-brand. Run the workflow with Geometria files only if
  they're seeded via a private mechanism (e.g., GitHub Actions secret + base64
  decode + write to disk during the workflow). For v1 the fallback is fine.

## Why these formats

- Pillow 9+ loads `.woff` natively (verified on Pillow 11), so no conversion
  needed for the MVBC-served Geometria.
- Open Sans is available as `.ttf` from the canonical Google source.
