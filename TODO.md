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
- [ ] Publish step (separate from dry-run): for each recipient with status='pending' in `blast_state.json`, render via `select_card_builders(barcode=...)` and push `cards/<token>.{html,webmanifest}` to gh-pages.
- [ ] PNG generator dispatch: add `select_png_generator(barcode)` symmetric to `select_card_builders` (returns `generate_vip_card_png` for VIP, `generate_card_png` otherwise). Wire into the send loop.

### Real-send path

- [ ] `blast.py --apply <blast_state.json>` — reads the JSON manifest (not the CSV), sends only to rows with `status` in {pending, failed}, marks each row in place (sent / failed / skipped + last_attempt_at + last_error).
- [ ] Use existing `lib.sender.GmailSMTPSender`; pull `GMAIL_USER` / `GMAIL_APP_PASSWORD` from env via dotenv.
- [ ] Pacing: 1–2 second delay between sends (Gmail-friendly, not spammy). Configurable.
- [ ] Idempotency: never re-send to `status=sent` rows. User explicit constraint.
- [ ] Baseline guard: require an explicit `--confirm <YYYYMMDD>` flag matching the manifest date so a stray `--apply` can't fire.

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
