# PCO → Libib Patron Sync — Design

**Status:** Draft for review
**Date:** 2026-05-06
**Supersedes:** `build-plan.md` (initial Claude Chat draft, Azure-flavored)

---

## 1. Goal

Keep MVBC's Libib patron list automatically aligned with Planning Center People (PCO):

- A new PCO **Member** or **Associate Member** gets a Libib patron account and a welcome email.
- A patron whose PCO status leaves the member set (or who is destroyed in PCO) is **frozen** in Libib (no checkouts, but loan history preserved).
- A patron's `last_name` or primary `email` updates in PCO propagate to Libib.

The system runs unattended on a schedule. Every change must clear a 24-hour stability gate before being executed, so accidental or reversed PCO edits never hit Libib.

## 2. Architecture

```
┌──────────────────┐          ┌────────────────────────────────────────┐
│ GitHub Actions   │ */15 * * │ run.py (single entry point)            │
│ scheduled cron   ├──────────▶│  1. fetch PCO members                  │
└──────────────────┘          │  2. fetch Libib patrons                │
                              │  3. determine desired actions          │
                              │  4. reconcile vs pending.json          │
                              │  5. execute matured actions            │
                              │  6. write audit log                    │
                              │  7. commit state changes               │
                              └────────┬───────────────────┬───────────┘
                                       │                   │
                              ┌────────▼─────────┐ ┌───────▼────────┐
                              │ Libib API        │ │ Resend API     │
                              │ (create/freeze/  │ │ (welcome email)│
                              │  update)         │ └────────────────┘
                              └──────────────────┘
                                       │
                              ┌────────▼─────────┐
                              │ state branch     │
                              │  pending.json    │
                              │  sync_log/*.jsonl│
                              └──────────────────┘
```

**Single process, single repo, no servers.**

### Why this shape

- Every 15 minutes is plenty of cadence given a 24-hour stability gate. Polling latency is invisible next to the gate.
- Storing pending state and the audit log as committed JSON files gives a free, human-readable, queryable history with no external database.
- Recomputing desired actions from live PCO and live Libib state every run means we never carry stale snapshot data between runs. Drift cannot accumulate silently.

## 3. Eligibility rules

A PCO person should have an active (unfrozen) Libib patron account when **all** of these hold:

1. `membership` ∈ `{"Member", "Associate Member"}`
2. Person has a primary `email` (Libib uses email as the patron key)
3. Person has not been destroyed in PCO

If any condition flips false, the patron should be frozen.

## 4. Action types

**Patron correspondence** is established by `patron_id`, never by email. After the one-time migration described in §16, every Libib patron's `patron_id` equals the PCO person's `id`. The canonical lookup is then trivially:

```python
patron_id = pco_person.id
```

Pre-migration historical context: Libib's `patron_id` values were populated by a prior CCB ↔ Libib sync system that this project replaces. That earlier sync used CCB Person IDs as Libib patron IDs. MVBC has since moved their congregation database from CCB to PCO; PCO carries each migrated person's original CCB ID forward in the `remote_id` field. The §16 migration script rewrites every Libib `patron_id` from its CCB value to the corresponding PCO `id`, eliminating the dual-namespace situation. The sync code is written assuming the migration has completed; running sync against an unmigrated Libib roster is unsupported.

Email is a synced attribute, not a key. This is what makes `UPDATE_EMAIL` safe — without it, an email change in PCO would look like "person disappeared, new person appeared" and we'd duplicate-create.

| Action | Trigger | Libib call |
|---|---|---|
| `CREATE_PATRON` | Eligible AND no Libib patron with `patron_id == person.id` | `POST /patrons` with first_name, last_name, email, `patron_id=person.id` (no password sent — Libib handles patron-side credential setup) |
| `FREEZE_PATRON` | Matching Libib patron exists AND not eligible AND not already frozen | `POST /patrons/{email}?freeze=1` |
| `UPDATE_FIRST_NAME` | Eligible matching Libib patron exists AND `first_name` differs | `POST /patrons/{email}?first_name=...` |
| `UPDATE_LAST_NAME` | Eligible matching Libib patron exists AND `last_name` differs | `POST /patrons/{email}?last_name=...` |
| `UPDATE_EMAIL` | Eligible matching Libib patron exists AND `email` differs | See §4.1 |

### 4.1 Email-change handling

Libib's update endpoint is keyed by email or barcode (`POST /patrons/{email_or_barcode}`). To change a patron's email we call `POST /patrons/{old_email}?email={new_email}`. The patron's `patron_id` and history are preserved because we're updating an attribute, not creating a new patron. Phase 0 still includes a one-time verification with a test patron to confirm the round-trip behavior matches expectations (GET by new email returns the same patron_id, no loan-history loss).

### 4.2 Patron_id is not unique in Libib

Libib's API documents `patron_id` as "Custom ID (non-unique)." Libib does not enforce uniqueness. Our system must enforce it on its side:

- When indexing Libib's roster by `patron_id`, detect duplicates and refuse to act on any person whose `patron_id` matches more than one Libib patron. Log the collision and surface it for manual cleanup.
- The migration script (§16) explicitly checks for `patron_id` collisions before and after migration as a sanity step.

### 4.3 Orphan detection

The CCB → PCO migration is believed complete: every Libib patron has a matching PCO person. The algorithm therefore treats orphans (Libib patrons whose `patron_id` matches no PCO `person.id` after the §16 migration) as anomalies rather than normal state. On each run the script counts orphans and:

- Logs each orphan to `sync_log` with `action="ORPHAN_DETECTED"`
- Takes no action against them (no automatic freeze or delete — too dangerous if the cause is e.g. PCO API pagination missed a page)
- The Phase 8 alerting workflow surfaces orphans alongside `status="failed"` rows

This costs nothing if the assumption holds and gives an early warning if it doesn't.

## 5. Stability gate

A desired action is only executed when:
1. The action has been continuously desired for at least `STABILITY_HOURS` (default 24, configurable via env var for testing), AND
2. It is still desired in the current run (i.e., not reverted)

**Reconciliation algorithm (per run):**

```
desired = compute_desired_actions(pco_people, libib_patrons)
pending = load_pending_json()

for action in desired:
    key = (person_id, action_type)
    if key in pending:
        if same target value:
            keep existing detected_at        # change still holding
        else:
            update target value, reset detected_at  # target shifted
    else:
        pending[key] = action with detected_at = now

for key in list(pending):
    if key not in desired:
        del pending[key]                     # reverted before action

mature = [p for p in pending.values() if now - p.detected_at >= STABILITY_HOURS]
for action in mature:
    execute(action)                          # see §6
    log_to_audit(action, result)
    if success: del pending[(action.person_id, action.type)]

save_pending_json(pending)
```

The "execute then delete on success" pattern keeps failed actions in pending state for the retry policy (§6).

## 6. Execution and retries

Each pending row tracks `attempts` and `last_attempt_at`. On execution:

- Success → remove from `pending.json`, append success entry to `sync_log/YYYY-MM.jsonl`
- Failure → increment `attempts`, set `last_attempt_at`, append failure entry to log
  - `attempts < 3` → leave in pending; next run will retry
  - `attempts >= 3` → set `status = "failed"`; do not retry until manually reset

Failures are visible in the GitHub Actions run log and in committed log files. Phase 7 adds an alerting hook (e.g., a workflow step that opens a GitHub issue when any `status="failed"` rows exist).

## 7. Welcome email and library card

On successful `CREATE_PATRON`, send a welcome email with a library card image attached.

The MVBC workflow is kiosk-based: patrons identify at the iPad kiosk by email or by scanning a barcoded library card. Libib login (and Libib passwords) are not part of the user-facing flow.

### 7.1 Welcome email

The legacy CCB-era email template at `templates/welcome.html` is the starting point but **the copy is open for revision** as part of this project. The structural shape is fixed:

- Personalized greeting using `{first_name}`
- Self-checkout kiosk instructions referencing the patron's `{email}`
- Catalog browse link (currently `https://www.libib.com/u/mvbchurch`)
- Self-renewal instructions PDF link
- Library location reminder
- Signature

The catalog URL, signature name/title, and any other stable strings are embedded directly in the template — not parameterized. Editing the template file is the way to change them.

**Placeholders:** `{first_name}` and `{email}`. Substitution via `str.format(**kwargs)` — no Jinja2 dependency.

**Final copy:** to be authored with the user before Phase 4 ships. The legacy template is committed as a starting point in `templates/welcome.html`.

### 7.2 Library card

Generated as a PNG image and attached to the welcome email. The legacy card design (650×380 PNG, name + email + barcode text + QR code, Bootstrap-styled) is **not preserved** — this project is an opportunity to redesign it.

**Implementation:** `lib/card.py` builds the card image directly with Pillow and the `qrcode` library. No headless browser, no external CDN, no third-party QR service. The QR encodes the patron's `barcode` value (sourced from Libib's response on `CREATE_PATRON`).

**Card content (minimum):**
- Patron's full name
- Patron's email
- QR code encoding the barcode value
- "MVBC Library" header

**Visual design:** to be designed with the user before Phase 4 ships. A simple PIL-rendered card with a clean header, the patron text rows, and a QR code is the working baseline.

### 7.3 Email backend

**Backend:** Resend API. The email module is a `Sender` protocol with concrete implementations:
- `ResendSender` — initial implementation; supports attachments
- `MicrosoftGraphSender` — placeholder for future migration if/when `library@mvbchurch.org` exists

The active sender is selected via `EMAIL_BACKEND` env var, defaulting to `resend`.

**Sender domain — open Phase-0 question:** if `mvbchurch.org` DNS records can be added, verify it on Resend and send from `library@mvbchurch.org`. Otherwise verify a temporary sender domain. Decision deferred; the module is pluggable.

### 7.4 Failure handling

If the email send fails, the Libib patron is **not** rolled back. We log the failure and surface it for manual follow-up. Better to have a created patron with no welcome email than to lose the create entirely.

If card generation fails, the welcome email is sent without an attachment and the failure is logged. The patron can still check out using their email at the kiosk.

## 8. Module layout

```
pco-libib-sync/
├── README.md
├── pyproject.toml                  # or requirements.txt
├── .gitignore
├── .env.example
├── run.py                          # CLI entry point (live sync)
├── migrate_patron_ids.py           # one-time migration script (§16)
├── lib/
│   ├── __init__.py
│   ├── config.py                   # env vars, MEMBER_STATUSES, STABILITY_HOURS
│   ├── pco_client.py               # PCO People API wrapper (paginated list, primary email)
│   ├── libib_client.py             # Libib API wrapper (list, create, freeze, update)
│   ├── sender.py                   # EmailSender protocol + ResendSender
│   ├── card.py                     # Pillow + qrcode card image generator
│   ├── decide.py                   # PURE: compute_desired_actions(pco, libib) -> list[Action]
│   ├── reconcile.py                # PURE: reconcile(desired, pending, now) -> (new_pending, mature)
│   ├── state.py                    # load/save pending.json, append sync_log
│   └── execute.py                  # dispatch actions to Libib + email + log
├── state/                          # written/read by the workflow on the `state` branch
│   ├── pending.json
│   └── sync_log/
│       └── YYYY-MM.jsonl
├── templates/
│   └── welcome.html                # email template (legacy CCB version, copy revisable)
├── tests/
│   ├── test_decide.py              # the cornerstone test file
│   ├── test_reconcile.py
│   ├── test_card.py                # smoke test: card renders, PNG is valid
│   ├── fixtures/
│   │   ├── pco_member_list.json
│   │   └── libib_patron_list.json
│   └── conftest.py
└── .github/
    └── workflows/
        ├── sync.yml                # cron + checkout + run.py + commit state
        └── test.yml                # CI: run pytest on every push/PR
```

The `decide.py` and `reconcile.py` modules are pure functions: given inputs, produce outputs, no I/O. They are the testable core.

## 9. Data shapes

### `state/pending.json`

```json
{
  "version": 1,
  "updated_at": "2026-05-06T18:30:00Z",
  "rows": [
    {
      "person_id": "12345",
      "action_type": "CREATE_PATRON",
      "target": {
        "first_name": "Ana",
        "last_name": "Smith",
        "email": "ana@example.com"
      },
      "detected_at": "2026-05-06T14:00:00Z",
      "attempts": 0,
      "last_attempt_at": null,
      "status": "pending"
    }
  ]
}
```

`(person_id, action_type)` is the composite key. At most one pending row per key.

`status` is one of:
- `"pending"` — normal, awaiting maturity or retry
- `"baseline"` — created in baseline mode, never executed (see §11)
- `"failed"` — attempts >= 3, frozen until manual reset

### `state/sync_log/YYYY-MM.jsonl`

One JSON object per line. Append-only.

```json
{"ts":"2026-05-06T18:30:01Z","person_id":"12345","action":"CREATE_PATRON","success":true,"libib_status":201,"email_sent":true}
{"ts":"2026-05-06T18:30:02Z","person_id":"67890","action":"FREEZE_PATRON","success":false,"libib_status":500,"libib_error":"Internal Server Error","attempts":1}
```

## 10. Configuration (env vars / GH Actions secrets)

Local dev: values live in `.env` (gitignored). Production: GitHub Actions repository secrets, exposed to the workflow as env vars.

| Var | Purpose | Where to get it | Required |
|---|---|---|---|
| `PCO_APP_ID` | PCO Personal Access Token App ID (Basic auth username) | api.planningcenteronline.com → Personal Access Tokens → Create new token | yes |
| `PCO_SECRET` | PCO PAT secret (Basic auth password) | Same screen as above; shown once at creation | yes |
| `LIBIB_API_KEY` | Sent as `x-api-key` request header | Libib Pro → Settings → API → Generate Key | yes |
| `LIBIB_API_USER` | Sent as `x-api-user` request header | Same screen as above (the Libib username/email associated with the API key) | yes |
| `RESEND_API_KEY` | Resend API key for sending welcome emails | resend.com → sign up (free) → Dashboard → API Keys → Create API Key. Value starts with `re_`. Free tier: 3,000 emails/month. | yes |
| `EMAIL_FROM` | The `From:` address on welcome emails. Format: `"Display Name <address@verified-domain>"` | Address must be on a domain verified in Resend. Best: `library@mvbchurch.org` once `mvbchurch.org` is verified. See §7.3. | yes |
| `EMAIL_REPLY_TO` | Where replies to the welcome email should go | Optional. Typically Alex's working email. | no |
| `EMAIL_BACKEND` | Which `Sender` implementation to use | Hardcoded value: `resend` (future option: `graph`) | yes (defaults to `resend`) |
| `STABILITY_HOURS` | How long a desired change must hold before it executes | Hardcoded value: `24` in production. Set to a small fraction (e.g., `0.05` = 3 minutes) for dev/test. | yes (defaults to `24`) |
| `LIBIB_LOGIN_URL` | Catalog browse URL embedded in welcome emails | Hardcoded value, currently `https://www.libib.com/u/mvbchurch` | yes |
| `BASELINE_MODE` | Suppress all execution; only populate pending state | Hardcoded value: `true` on first prod run, then unset / set to `false`. See §11. | no (defaults to `false`) |

**For local dev:** copy `.env.example` to `.env` and fill in. `.env` is gitignored.

**For GitHub Actions:** repo Settings → Secrets and variables → Actions → New repository secret. Add each `*_API_KEY` / `*_SECRET` / `PCO_*` / `LIBIB_*` value as a secret. Non-sensitive ones (`STABILITY_HOURS`, `LIBIB_LOGIN_URL`, `EMAIL_BACKEND`, `BASELINE_MODE`) can live in the workflow YAML directly as plaintext `env:` entries.

## 11. Baseline mode

On first deployment, the system would otherwise see every existing PCO member as needing `CREATE_PATRON`. To prevent a flood:

- Set `BASELINE_MODE=true` for the first run
- The script computes desired actions and writes them to `pending.json` with `status="baseline"`
- No execution happens, no emails sent
- Operator reviews `pending.json` on the `state` branch:
  - For members already manually created in Libib: nothing to do — the next run (with `BASELINE_MODE=false`) will recompute and find them, so no `CREATE_PATRON` is generated
  - For members not yet in Libib: leave them in pending; they'll be created on the next normal run after their `detected_at` matures
- Unset `BASELINE_MODE`. Drop the `status="baseline"` rows by committing an empty `pending.json` (or running the script with a `--clear-baseline` flag, which deletes only those rows)
- Subsequent runs operate normally

## 12. Testing strategy

Two tiers of tests, separated by what they touch.

### 12.1 Unit tests (run automatically on every commit)

`decide.py` and `reconcile.py` are pure functions — given inputs, produce outputs, no network or filesystem. They are the testable core and the place most bugs would hide.

A separate GitHub Actions workflow (`.github/workflows/test.yml`) runs `pytest` on every push and pull request. This is the project's **CI** (Continuous Integration) pipeline: a fast, automated check that prevents broken code from being merged. CI is distinct from the scheduled sync workflow (`sync.yml`); it just runs tests, no live API calls.

Test cases for `decide.py`:
- New person, becomes Member → `[CREATE_PATRON]`
- New person, becomes Visitor → `[]`
- Member → Former Member → `[FREEZE_PATRON]`
- Member → Member, first_name changed → `[UPDATE_FIRST_NAME]`
- Member → Member, last_name changed → `[UPDATE_LAST_NAME]`
- Member → Member, email changed → `[UPDATE_EMAIL]`
- Member → Member, first_name and last_name both changed → `[UPDATE_FIRST_NAME, UPDATE_LAST_NAME]`
- Member destroyed in PCO → `[FREEZE_PATRON]`
- Already frozen, still not eligible → `[]` (no double-freeze)
- Already eligible patron exists, no diffs → `[]`

For `reconcile.py`: action newly desired, action no longer desired (revert), action target shifted, action matured.

For `card.py`: smoke test that calling the generator returns valid PNG bytes (no need to assert visual output in CI).

### 12.2 Integration tests (run manually, not in CI)

The unit tests above never touch PCO, Libib, or Resend. To verify the API client wrappers actually behave correctly, the developer runs **integration tests** locally against a throwaway test patron. These are explicitly *not* part of the CI workflow because:

- They require live API credentials in the test environment (more secrets to manage)
- They mutate real Libib data (create/freeze/delete a sandbox patron), which is messy if a run fails midway
- They're slow (network round-trips per call)

Run them manually before merging anything that changes `pco_client.py`, `libib_client.py`, or `sender.py`.

### 12.3 Local sanity-check runs

`python run.py --dry-run` reads from real PCO and Libib APIs but performs no writes and prints the action plan to stdout. Used for human verification before flipping `BASELINE_MODE` off.

## 13. Phased delivery

| Phase | Goal |
|---|---|
| 0 | Verify `UPDATE_EMAIL` round-trips preserve patron_id and history; resolve Resend sender domain; capture sample PCO + Libib payloads as test fixtures |
| 1 | `decide.py` + `reconcile.py` + tests, all passing locally with hand-crafted fixtures |
| 2 | `pco_client.py` + `libib_client.py`, validated against live APIs in `--dry-run` |
| 3 | `state.py` + `execute.py`; full pipeline runs locally end-to-end against a Libib sandbox patron |
| 4 | `sender.py` (Resend) + `card.py` (Pillow + qrcode) + finalized welcome email copy + finalized card design; integrated into `execute.py` |
| 5 | **One-time patron_id migration** (§16). Run the migration script in `--dry-run`, review report, run for real, verify zero failures and zero collisions. |
| 6 | GitHub Actions workflow + state-branch commit logic; first scheduled run in `BASELINE_MODE=true` |
| 7 | Production cutover: review baseline, clear pending, set `BASELINE_MODE=false`, monitor a few runs |
| 8 | Failure-alerting workflow step (open a GitHub issue if any `status=failed` rows present) |

## 14. Open items

- **Resend sender domain.** Resolve in Phase 0.
- **Future: migrate Resend → Microsoft Graph** when `library@mvbchurch.org` mailbox exists. No code change beyond config + new `MicrosoftGraphSender` class.

## 15. Explicitly not building (YAGNI)

- Webhook receiver / HMAC verification
- Snapshots table (state recomputed each run)
- Processed-events dedup table
- Separate daily reconcile (the polling cadence is the reconcile)
- Three-function split with timer triggers (one script does it all)
- Azure infrastructure
- ngrok local-dev tooling
- Hard-deleting Libib patrons on PCO destroy
- Slack/Teams notifications, SMS notifications, monthly digests (post-v1 if desired)

## 16. One-time patron_id migration

The Libib roster was created during the CCB era, so every existing patron has `patron_id == CCB Person ID`. PCO carries the same value forward in `remote_id`. We rewrite every Libib `patron_id` to the corresponding PCO `person.id`, after which the sync code can assume the simple key `patron_id == person.id`.

### Why a script, not gradual migration in the live sync

A gradual approach (migrate as part of normal operation) would only touch patrons that already have another reason to be updated, leaving stable patrons stuck with CCB IDs forever. A one-time script converges cleanly and lets us verify the result before the live sync ever runs.

### Script: `migrate_patron_ids.py`

Standalone, separate from `run.py`. Run manually with explicit human approval at each step.

**Inputs:**
- PCO PAT, Libib API credentials (same env vars as the sync)
- Flags: `--dry-run` (default true), `--apply`, `--report-path`

**Algorithm:**
1. Fetch all PCO people with non-empty `remote_id`. Build map `ccb_id → pco_person`.
2. Fetch all Libib patrons (paginated, 50/page).
3. For each Libib patron `p`:
   - If `p.patron_id` is empty → log as `MISSING_ID`, skip.
   - If `p.patron_id` not in the PCO map → log as `ORPHAN_LIBIB`, skip.
   - If the PCO match's `id` already equals `p.patron_id` → log as `ALREADY_MIGRATED`, skip.
   - Else → plan an update: `POST /patrons/{p.email}?patron_id={pco_person.id}`.
4. Compute pre-migration collision check: any two Libib patrons with the same `patron_id`? If yes → abort, dump the colliding rows for manual resolution.
5. Compute post-migration collision check: do any of the planned new `patron_id` values collide with each other or with non-migrating Libib patrons? If yes → abort.
6. Print a report: `N to migrate, M already migrated, K orphans, J missing IDs, X collisions`.
7. If `--dry-run` (default), stop here. If `--apply`, prompt for explicit confirmation, then execute updates one at a time:
   - Each update is logged to `migration_log.jsonl` (timestamp, old patron_id, new patron_id, email, libib response code/body).
   - On any non-2xx response, halt and require operator review before resuming.
8. After applying, re-fetch the Libib roster and verify every expected `patron_id` is now in place. Output a final report.

### Idempotency

The script is safe to re-run. The `ALREADY_MIGRATED` skip path means a partial run can be completed by re-running with `--apply`. The collision checks re-run from the current Libib state each time.

### Hard prerequisite for sync

The live sync code in `run.py` assumes the migration is complete. Phase 6 (workflow deploy) cannot happen until Phase 5 (migration) reports zero `MISSING_ID` and zero `ORPHAN_LIBIB` rows that we have not consciously decided to leave alone.
