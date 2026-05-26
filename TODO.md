# TODO

## Blast email with two templates (+ per-recipient PWA card)

Send a one-off blast email that branches by recipient segment, including a PWA library card per recipient (same flow as the welcome email — digital card primary, PNG attachment as backup):

- **Regular patrons** (active checkouts, no card yet) → `templates/regulars.{html,txt}`
- **Members who have not visited the library** (existing patrons, dormant) → `templates/reminder.{html,txt}`

Both templates now have a `{card_section}` placeholder and the same "Our Libraries" + PNG-as-backup framing as the welcome email. They will not render correctly until the blast pipeline supplies per-recipient PWA card URLs.

### Segmentation + recipient list

- [ ] Define the segmentation query: what counts as a "regular patron" vs. a "non-visiting member"? (e.g. checkouts in last N days, last visit date threshold)
- [ ] Decide the source of truth for segmentation — Libib activity, PCO list, or a join of both
- [ ] Build/identify the recipient list per segment (dedupe across segments; non-visitors take precedence if a member somehow lands in both)
- [ ] Suppression list handling (opt-outs, bounces) before send

### Per-recipient PWA card generation (new — was missing from the original plan)

Each recipient needs their own card token, published card page on `gh-pages`, and PNG attachment — same as `CREATE_PATRON` does for new patrons. Reuses existing primitives: `lib.web_card.{new_card_token, build_card_html, build_card_manifest, card_url}`, `lib.card.generate_card_png`, and the `web_card_publisher` pattern from `run.py:_make_web_card_publisher`.

- [ ] Persist per-recipient card tokens (new field on a per-patron record, or a separate `card_tokens.json` keyed by `patron_id` — decide which) so re-runs don't churn out fresh URLs for the same person
- [ ] For each recipient: mint token if absent, publish `cards/<token>.{html,webmanifest}` to gh-pages
- [ ] Render template with `card_url=...` injecting the per-recipient `{card_section}` snippet (reuse `lib.sender.render_welcome_email`'s splice pattern — extract into a shared helper that takes a base template path)
- [ ] Generate per-recipient PNG card via `generate_card_png(barcode=patron.barcode, …)` and attach to the message
- [ ] Decide what happens if a recipient has no Libib barcode (skip them? log and continue?) — same edge case as `CREATE_PATRON`

### Sending

- [ ] Wire up a sender path (Resend is already a project dep) with both HTML and plaintext alternatives per segment
- [ ] Subject lines per template (regulars vs. reminder)
- [ ] Dry-run / preview mode: print recipient list + rendered HTML/text + would-be card URL per recipient, no send, no gh-pages push
- [ ] Add a baseline/safety guard so we don't accidentally blast on first run (consistent with the project's baseline-mode discipline)
- [ ] Throttle / rate-limit (Resend has per-account caps; gh-pages commits also serialize)

## PWA library card — go-live

The hosted PWA card (Mockup C "The Credential") is built end-to-end and tested. What's left is manual verification before issuing cards to members. See [[project-pwa-card-design-phase]] for context on what's already wired.

### Open questions / sub-tasks

- [ ] Trigger the sync workflow with a test patron and confirm the per-patron card page publishes under `CARD_BASE_URL`
- [ ] Real-iPhone smoke: install via "Add to Home Screen", confirm the standalone display-mode rule hides the install instructions, scan the QR at the kiosk, and verify the page works offline after first load
- [ ] Android smoke: same flow via Chrome's "Install app" prompt
- [ ] Confirm the welcome email's `{card_section}` renders correctly in Gmail (HTML + plaintext) and that the Gmail-in-app-browser callout is visible
- [ ] Clean up `mockups/_render_smoke.html` and `mockups/_render-sebastian-parra.{html,png}` once verified
