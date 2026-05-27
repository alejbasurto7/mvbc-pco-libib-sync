# TODO

## Blast email with three templates (+ per-recipient PWA card)

One-shot local blast that delivers a digital library card + PNG attachment to existing patrons. Segments by Libib Patron Status (CSV-driven; see [[project-blast-email-segmentation]]):

- **active** → `regulars.{html,txt}` (or `regulars_vip.{html,txt}` if barcode ∈ VIP_BARCODES)
- **inactive** + **new** → `reminder.{html,txt}`
- **frozen** → skip (not a member anymore)

### Foundation (DONE 2026-05-27)

- [x] `lib/blast.py` — CSV reader, `CsvRow` / `Recipient` / `Skipped` dataclasses, `assign_segment()`, `partition()`. Pure logic, 18 tests.
- [x] `lib/sender.py::render_reminder_email` — third render helper, shares `_render_card_section` with welcome/regulars.
- [x] `blast.py` CLI at repo root — `--dry-run` mode writes `state/blast_<DATE>/blast_state.json` (keyed by **barcode**) + one preview HTML per segment.
- [x] Subject lines confirmed (see [[project-blast-email-segmentation]]).

### Per-recipient PWA card generation

Reuses `lib.web_card.{select_card_builders, card_url}`, `lib.card.{generate_card_png, generate_vip_card_png}`.

- [x] `state/card_tokens.json` registry, keyed by **barcode**. [[lib/card_tokens.py]] (load / save / get_or_mint), 10 tests. Wired into `blast.py`, `publish_test_card.py`, and `run.py::_make_web_card_publisher` (so CREATE_PATRON also persists tokens after success). First blast run seeded 410 entries.
- [x] Publish step: [[publish_blast_cards.py]] walks every recipient in `blast_state.json`, renders via `select_card_builders`, pushes `cards/<token>.{html,webmanifest}` to gh-pages. Dry-run by default; `--apply` to push; `--force` to overwrite existing; `--limit N` for staged rollouts. Idempotent (skips already-published tokens). 4 dry-run tests.
- [x] PNG generator dispatch: `select_png_generator(barcode)` in [[lib/card.py]], symmetric to `select_card_builders`. 3 tests. Wired into the `--apply` send loop below.

### Real-send path

- [x] `blast.py --apply <blast_state.json>` — reads the JSON manifest (not the CSV), sends only to rows with `status` in {pending, failed}, marks each row in place. Persists state JSON after every attempt (crash mid-loop preserves what's sent). 12 CLI tests covering happy path, baseline guard, idempotency, retry-on-failed, --limit, mode mutex.
- [x] Uses existing `lib.sender.GmailSMTPSender`; reads `GMAIL_USER` / `GMAIL_APP_PASSWORD` (+ optional `EMAIL_FROM` / `EMAIL_REPLY_TO`) from env via dotenv.
- [x] Pacing: `--pace SECONDS` flag (default 1.5s). Configurable per the user's earlier "Gmail-friendly, not spammy" constraint.
- [x] Idempotency: only rows with status in {pending, failed} are picked up. `status=sent` rows are skipped — user explicit constraint upheld.
- [x] Baseline guard: `--confirm <YYYYMMDD>` is required and must match the manifest directory's date suffix (`blast_<YYYYMMDD>/`). A stray `--apply` against yesterday's manifest is rejected with rc=2.

### Pre-production gates (manual)

- [x] Run `python publish_blast_cards.py state/blast_<DATE>/blast_state.json --apply --limit 5` and eyeball five real URLs on iPhone + Android before going full 410.
- [x] Run `python blast.py --apply state/blast_<DATE>/blast_state.json --confirm <DATE> --limit 1` against your own row first and inspect the delivered email + attachment before opening the floodgates.

### Known environment issue

- [ ] Local SSL cert verification fails against `api.libib.com` on the user's Windows machine (corporate TLS interception). Workaround: set `REQUESTS_CA_BUNDLE` to the corp CA chain, OR run from WSL/different network. Does not affect GitHub Actions runs.

## PWA library card — go-live

The hosted PWA card (Mockup C "The Credential") is built end-to-end and tested. What's left is manual verification before issuing cards to members. See [[project-pwa-card-design-phase]] for context on what's already wired.

### Open questions / sub-tasks

- [ ] Trigger the sync workflow with a test patron and confirm the per-patron card page publishes under `CARD_BASE_URL`
- [ ] Real-iPhone smoke: install via "Add to Home Screen", confirm the standalone display-mode rule hides the install instructions, scan the QR at the kiosk, and verify the page works offline after first load
- [ ] Android smoke: same flow via Chrome's "Install app" prompt
- [ ] Confirm the welcome email's `{card_section}` renders correctly in Gmail (HTML + plaintext) and that the Gmail-in-app-browser callout is visible
- [ ] Clean up `mockups/_render_smoke.html` and `mockups/_render-sebastian-parra.{html,png}` once verified
