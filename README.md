# PCO ↔ Libib Sync

Automated sync of MVBC's Planning Center People membership data to Libib patrons.

See [the design spec](docs/superpowers/specs/2026-05-06-pco-libib-patron-sync-design.md) for the architecture.

## Local development

```bash
python -m venv .venv
.venv\Scripts\activate     # Windows
# OR
source .venv/bin/activate  # macOS/Linux

pip install -r requirements.txt
cp .env.example .env       # then fill in values
pytest                     # run unit tests
python run.py --dry-run    # check action plan against live APIs without writing
```

## Production

Runs as a GitHub Actions cron every 15 minutes. See `.github/workflows/sync.yml`.
