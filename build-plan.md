# PCO → Libib Sync: Build Plan

**Project:** Automated synchronization between Planning Center People (MVBC Church) and Libib library management.
**Architecture:** Webhook-driven, Azure Functions (Python), Azure Table Storage, Microsoft Graph (email).
**Goal:** When PCO membership changes are stable for 48 hours, propagate to Libib (create/freeze/update) and email new patrons.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Trigger Logic](#trigger-logic)
3. [External Services & Credentials](#external-services--credentials)
4. [Data Model](#data-model)
5. [Project Structure](#project-structure)
6. [Phased Build Plan](#phased-build-plan)
7. [Phase 0: Pre-Build Verification](#phase-0-pre-build-verification)
8. [Phase 1: Local Scaffolding](#phase-1-local-scaffolding)
9. [Phase 2: Webhook Receiver](#phase-2-webhook-receiver)
10. [Phase 3: Delayed Sync Worker](#phase-3-delayed-sync-worker)
11. [Phase 4: Daily Reconciliation](#phase-4-daily-reconciliation)
12. [Phase 5: Welcome Email Module](#phase-5-welcome-email-module)
13. [Phase 6: Azure Deployment](#phase-6-azure-deployment)
14. [Phase 7: Production Cutover](#phase-7-production-cutover)
15. [Operational Runbook](#operational-runbook)

---

## System Overview

```
┌─────────────┐                    ┌──────────────────────────────────┐
│  PCO People │ ──webhook POST──▶  │ Azure Function: webhook_receiver │
└─────────────┘                    │ - Verifies HMAC                  │
                                   │ - Diffs vs snapshot              │
                                   │ - Writes pending_changes         │
                                   └──────────┬───────────────────────┘
                                              │
                                              ▼
                                   ┌──────────────────────────────────┐
                                   │ Azure Table Storage              │
                                   │ - snapshots                      │
                                   │ - pending_changes                │
                                   │ - sync_log                       │
                                   └──────────┬───────────────────────┘
                                              │
                          ┌───────────────────┴────────────────────┐
                          │                                        │
                          ▼                                        ▼
              ┌───────────────────────┐              ┌──────────────────────┐
              │ delayed_sync_worker   │              │ daily_reconcile      │
              │ (hourly timer)        │              │ (3am daily timer)    │
              │ - Confirms 48hr hold  │              │ - Full PCO sweep     │
              │ - Calls Libib API     │              │ - Catches missed     │
              │ - Sends email         │              │   webhooks           │
              └───────────────────────┘              └──────────────────────┘
                          │
                          ├─────▶  Libib API  (create / update / freeze)
                          └─────▶  Gmail SMTP (welcome email)
```

### Key Design Principles

- **Webhooks for real-time detection, polling for safety net.** Webhooks can be missed; daily reconciliation catches drift.
- **48-hour stability gate.** Changes are only acted on after they hold steady for 2 days, preventing whipsaw on accidental edits.
- **Re-verify before acting.** Worker re-fetches PCO state right before calling Libib in case the change was reverted.
- **Idempotent.** All operations safe to retry. Use `X-PCO-Webhooks-Event-ID` for dedup.
- **Auditable.** Every action logged to `sync_log` table.

---

## Trigger Logic

### Watched Fields
- `membership` (native PCO Person attribute — string)
- `last_name` (native)
- Primary `email` (separate resource, fetched on demand)

### Member Set
```python
MEMBER_STATUSES = {"Member", "Associate Member"}
```

### Action Rules

```python
was_member = previous_membership in MEMBER_STATUSES
is_member  = current_membership  in MEMBER_STATUSES

if not was_member and is_member:
    action = "CREATE_LIBIB"          # New patron + welcome email
elif was_member and not is_member:
    action = "FREEZE_LIBIB"          # Set freeze=1
elif is_member and was_member:
    if last_name_changed:
        action = "UPDATE_LAST_NAME"
    if email_changed:
        action = "UPDATE_EMAIL"
else:
    action = None                    # Non-member edited → ignore
```

### 48-Hour Stability Gate

A pending change is **only executed** when:
1. `now() - detected_at >= 48 hours`, AND
2. Re-fetch from PCO confirms the change still holds (i.e., current value matches `new_value` recorded when detected)

If reversed before the gate, delete the pending row.

### `directory_status: no_export` Decision
**Honor this flag.** If `directory_status == "no_export"`, do NOT create a Libib patron. Library access is treated like directory inclusion. Log skipped person for manual review.

---

## External Services & Credentials

| Service | Auth Method | Where Stored |
|---|---|---|
| PCO People API | Personal Access Token (PAT) — App ID + Secret | Azure Function App Settings (encrypted) |
| PCO Webhook signing | Webhook secret (per subscription) | Azure Function App Settings |
| Libib API | `x-api-key` + `x-api-user` headers | Azure Function App Settings |
| Gmail SMTP | App Password (initial) | Azure Function App Settings |
| Azure Table Storage | Connection string | Azure Function App Settings (auto-injected) |

**Future migration:** Gmail SMTP → Microsoft Graph (`familyministry@mvbchurch.org`) once mailbox exists. Module designed with adapter pattern to swap.

---

## Data Model

### Azure Table: `snapshots`
Last-known state of every PCO person we've seen.

| Column | Type | Notes |
|---|---|---|
| PartitionKey | string | Always `"person"` |
| RowKey | string | PCO person ID |
| first_name | string | |
| last_name | string | |
| email | string | Primary email (nullable) |
| membership | string | Nullable |
| directory_status | string | `no_export` or other |
| pco_updated_at | string | PCO's `updated_at` ISO timestamp |
| last_seen_at | string | When we last saw this person |

### Azure Table: `pending_changes`
Changes detected, waiting for 48hr gate.

| Column | Type | Notes |
|---|---|---|
| PartitionKey | string | PCO person ID |
| RowKey | string | Change type: `CREATE_LIBIB`, `FREEZE_LIBIB`, `UPDATE_LAST_NAME`, `UPDATE_EMAIL` |
| old_value | string | Previous value (for revert detection) |
| new_value | string | New value (target) |
| detected_at | datetime | When first detected |
| attempts | int | Retry count |
| last_attempt_at | datetime | Nullable |
| status | string | `pending`, `failed`, `synced` |

### Azure Table: `sync_log`
Append-only audit trail.

| Column | Type | Notes |
|---|---|---|
| PartitionKey | string | `YYYYMM` |
| RowKey | string | `{timestamp}_{person_id}_{action}` |
| person_id | string | |
| action | string | |
| libib_response_code | int | |
| libib_response_body | string | Truncated to 1KB |
| email_sent | bool | |
| email_error | string | Nullable |
| success | bool | |
| executed_at | datetime | |

### Azure Table: `processed_events`
Idempotency — dedup webhook deliveries.

| Column | Type | Notes |
|---|---|---|
| PartitionKey | string | `YYYYMM` |
| RowKey | string | PCO Event ID from `X-PCO-Webhooks-Event-ID` header |
| received_at | datetime | |

TTL: 30 days (manual cleanup or table refresh).

---

## Project Structure

```
pco-libib-sync/
├── README.md
├── requirements.txt
├── host.json                          # Azure Functions host config
├── local.settings.json                # Local dev secrets (gitignored)
├── .gitignore
├── .funcignore
├── shared/
│   ├── __init__.py
│   ├── config.py                      # Env var loading, MEMBER_STATUSES
│   ├── pco_client.py                  # PCO API wrapper
│   ├── libib_client.py                # Libib API wrapper
│   ├── email_sender.py                # Gmail SMTP (swap-ready for Graph)
│   ├── storage.py                     # Azure Table Storage helpers
│   ├── signature.py                   # PCO HMAC verification
│   └── sync_engine.py                 # Core diff/decide logic (testable)
├── webhook_receiver/
│   ├── __init__.py                    # HTTP trigger function
│   └── function.json
├── delayed_sync_worker/
│   ├── __init__.py                    # Timer trigger (hourly)
│   └── function.json
├── daily_reconcile/
│   ├── __init__.py                    # Timer trigger (3am)
│   └── function.json
└── tests/
    ├── test_sync_engine.py            # Pure unit tests of decision logic
    ├── test_signature.py
    ├── fixtures/
    │   └── pco_webhook_sample.json
    └── conftest.py
```

---

## Phased Build Plan

| Phase | Goal | Deliverable | Time Estimate |
|---|---|---|---|
| 0 | Pre-build verification | Confirmed Libib `freeze` writability, captured real PCO webhook payload | 1 hr |
| 1 | Local scaffolding | Project structure, deps installed, Azurite running, sync_engine + tests passing | 2 hrs |
| 2 | Webhook receiver | Local HTTPS endpoint via ngrok receives + verifies + diffs PCO webhooks | 2 hrs |
| 3 | Delayed sync worker | Worker processes 48hr-aged changes against Libib (sandbox account) | 2 hrs |
| 4 | Daily reconcile | Full PCO sweep detects drift, inserts pending rows | 1 hr |
| 5 | Welcome email | Gmail SMTP integration with template substitution | 1 hr |
| 6 | Azure deployment | Function App live, secrets configured, App Insights connected | 2 hrs |
| 7 | Production cutover | Real PCO webhook subscription, baseline snapshot, monitoring | 1 hr |

**Total: ~12 hours of focused work.** Recommend splitting across 2 weekends.

---

## Phase 0: Pre-Build Verification

**Goal:** Eliminate two unknowns before writing real code.

### 0.1 Verify Libib `freeze` field is API-writable

Libib docs confirm `freeze` is **returned** by GET, but don't explicitly list it as a writable POST update parameter. Test before designing around it.

**Steps:**
1. Generate Libib API key + user (Settings > API in Libib Pro account)
2. Create a throwaway test patron via API
3. Attempt `POST /patrons/{email}?freeze=1`
4. GET the patron back, verify `freeze: 1`
5. If NOT writable, fall back plan: use `tags` field — set tag `frozen-former-member` instead

**Expected outcome:** Document which mechanism works (`freeze=1` direct OR `tags` workaround).

### 0.2 Capture real PCO webhook payload

Don't guess at payload structure. Capture an actual delivery.

**Steps:**
1. Sign up for free webhook inspection at `webhook.site` (gives a temp URL)
2. In PCO: `api.planningcenteronline.com/webhooks` → Add Subscription
3. URL = the webhook.site URL
4. Subscribe to `people.v2.events.person.updated`
5. Edit a test person in PCO (change membership)
6. Save the captured JSON to `tests/fixtures/pco_webhook_sample.json`
7. Note the exact header names and HMAC algorithm
8. Delete the webhook.site subscription afterward

**Expected outcome:** Real payload sample drives the parser code, no guessing.

### 0.3 Confirm PCO PAT works

```bash
curl -u "APP_ID:SECRET" https://api.planningcenteronline.com/people/v2/me
```
Should return your user record.

### Deliverables
- [ ] `notes/libib_freeze_test_results.md` — confirmed working method
- [ ] `tests/fixtures/pco_webhook_sample.json` — real payload
- [ ] All four credentials confirmed working: PCO PAT, Libib key, Gmail app password (later), Azure account

---

## Phase 1: Local Scaffolding

**Goal:** Project skeleton + core decision logic, fully tested locally without any cloud dependencies.

### 1.1 Tools needed
- Python 3.11+
- Azure Functions Core Tools v4 (`npm i -g azure-functions-core-tools@4`)
- Azurite (local Azure Storage emulator): `npm i -g azurite`
- ngrok (for Phase 2 webhook testing)

### 1.2 Initialize project

```bash
func init pco-libib-sync --python
cd pco-libib-sync
```

### 1.3 `requirements.txt`

```
azure-functions
azure-data-tables>=12.4.0
requests>=2.31
python-dotenv
pytest
pytest-mock
```

### 1.4 `local.settings.json` (gitignored — for local dev)

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "PCO_APP_ID": "your_app_id",
    "PCO_SECRET": "your_secret",
    "PCO_WEBHOOK_SECRET": "from_pco_subscription",
    "LIBIB_API_KEY": "your_key",
    "LIBIB_API_USER": "your_user",
    "GMAIL_USER": "you@gmail.com",
    "GMAIL_APP_PASSWORD": "16_char_app_password",
    "EMAIL_FROM_NAME": "MVBC Library",
    "EMAIL_REPLY_TO": "you@personal.com",
    "STABILITY_HOURS": "48"
  }
}
```

### 1.5 Build `shared/sync_engine.py` first (TDD)

This is the heart of the system. Write tests before implementation.

**Function signature:**
```python
def determine_action(
    previous: PersonSnapshot | None,
    current: PersonSnapshot,
    member_statuses: set[str]
) -> list[PendingChange]:
    """Pure function: returns 0+ pending changes given before/after states."""
```

**Test cases to write:**
- New person, becomes Member → returns `[CREATE_LIBIB]`
- New person, becomes Visitor → returns `[]`
- Member → Former Member → returns `[FREEZE_LIBIB]`
- Member → Member, last_name changed → returns `[UPDATE_LAST_NAME]`
- Member → Member, email changed → returns `[UPDATE_EMAIL]`
- Member → Member, both changed → returns `[UPDATE_LAST_NAME, UPDATE_EMAIL]`
- Visitor → Visitor, name changed → returns `[]` (not a member, ignore)
- Member → Member, `directory_status` changed to `no_export` → returns `[FREEZE_LIBIB]`? Decide.
- Null → Member with `directory_status: no_export` → returns `[]` (skip create)

### 1.6 Build `shared/storage.py`

Wrappers around `azure.data.tables.TableServiceClient`:
- `get_snapshot(person_id) -> PersonSnapshot | None`
- `upsert_snapshot(snapshot)`
- `add_pending_change(change)`
- `get_pending_change(person_id, change_type)`
- `delete_pending_change(person_id, change_type)`
- `list_aged_pending(hours=48) -> list[PendingChange]`
- `log_sync(log_entry)`
- `is_event_processed(event_id) -> bool`
- `mark_event_processed(event_id)`

### Deliverables
- [ ] Project initializes with `func start` (no functions yet, just config)
- [ ] `pytest tests/` passes with all sync_engine cases
- [ ] Azurite running locally, storage helpers tested against it

---

## Phase 2: Webhook Receiver

**Goal:** Receive real PCO webhooks locally via ngrok, verify signatures, populate snapshot + pending tables.

### 2.1 `shared/signature.py`

```python
def verify_pco_signature(
    raw_body: bytes,
    received_signature: str,
    secret: str
) -> bool:
    """HMAC-SHA256 verification per PCO spec."""
```

Tests with real captured signature from Phase 0.

### 2.2 `shared/pco_client.py`

Methods needed:
- `get_person(person_id, include_emails=True) -> dict`
- `list_all_people(updated_since=None) -> Iterator[dict]` (paginated, for daily reconcile)
- `extract_primary_email(person_dict) -> str | None`

Auth: Basic auth with PAT (App ID + Secret).

### 2.3 `webhook_receiver/__init__.py` (HTTP trigger)

Flow:
```
1. Read raw body + headers
2. Check X-PCO-Webhooks-Event-ID against processed_events → if dup, return 200 immediately
3. Verify HMAC signature → reject 403 if mismatch
4. Parse outer envelope, extract stringified payload
5. Parse inner payload → person attributes
6. If event is person.* → fetch primary email via PCO API
7. If event is email.* → resolve person_id via relationship, fetch full person
8. Build current_snapshot
9. Get previous_snapshot from storage
10. Run sync_engine.determine_action()
11. For each PendingChange returned:
    - If matching pending row exists with same new_value → leave it (don't reset timer)
    - If matching pending row exists with different new_value → update with new detected_at
    - If reverting (current matches a pre-pending baseline) → delete pending row
    - Else → insert new pending row
12. Upsert snapshot
13. Mark event processed
14. Return 200
```

Keep total response time under 5 seconds (PCO retry threshold ~10s, leave margin).

### 2.4 Local testing with ngrok

```bash
# Terminal 1
azurite

# Terminal 2
func start

# Terminal 3
ngrok http 7071
```

Update PCO webhook subscription URL to the ngrok HTTPS URL temporarily. Trigger changes in PCO, verify:
- Snapshot row appears in Azurite
- Pending change row appears
- Reverting the change in PCO removes the pending row
- Re-firing the same event ID returns 200 without reprocessing

### Deliverables
- [ ] Webhook handler responds 200 to valid signed PCO requests
- [ ] Returns 403 to invalid signatures
- [ ] Snapshot + pending tables populate correctly through real PCO test events
- [ ] Idempotency verified (replay safe)

---

## Phase 3: Delayed Sync Worker

**Goal:** Hourly job that processes aged pending changes against Libib (test account).

### 3.1 `shared/libib_client.py`

Methods:
- `create_patron(first_name, last_name, email, patron_id, password=None) -> dict`
- `update_patron(email_or_barcode, **fields) -> dict`
- `freeze_patron(email_or_barcode) -> dict` (uses method confirmed in Phase 0)
- `get_patron(email_or_barcode) -> dict | None`

Note Libib's quirk: query params, not JSON body. Use `requests.post(url, params=...)`.

Use PCO `person_id` as Libib `patron_id` for cross-system linking.

Generate random initial password for new patrons (16 chars, mixed). Include in welcome email.

### 3.2 `delayed_sync_worker/__init__.py` (Timer trigger, `0 0 * * * *` — hourly at top of hour)

Flow:
```
1. List pending_changes where status='pending' AND detected_at <= now - STABILITY_HOURS
2. For each row:
    a. Re-fetch person from PCO
    b. Build current_snapshot
    c. Re-run sync_engine to confirm same action still applies
    d. If action no longer applies → delete pending row, continue
    e. Skip if directory_status='no_export' AND action='CREATE_LIBIB'
    f. Dispatch to Libib API based on change_type
    g. If CREATE_LIBIB → also queue welcome email
    h. Mark row 'synced', append to sync_log
    i. On Libib failure: increment attempts, set status='failed' if attempts >= 3
```

### 3.3 Retry policy
- Attempt 1: immediate
- Attempt 2: next hourly run
- Attempt 3: next hourly run
- After 3 failures: status='failed', alert via App Insights, requires manual review

### Deliverables
- [ ] Worker creates Libib patron when a CREATE_LIBIB pending row ages out
- [ ] Worker freezes Libib patron correctly
- [ ] Worker updates name/email correctly
- [ ] Failed Libib calls increment attempts, eventually mark failed
- [ ] sync_log shows full audit trail

---

## Phase 4: Daily Reconciliation

**Goal:** Catch anything missed by webhooks (downtime, signature failures, race conditions).

### 4.1 `daily_reconcile/__init__.py` (Timer trigger, `0 0 8 * * *` — 8am UTC = 3am Eastern)

Flow:
```
1. Iterate all PCO people via paginated list_all_people()
2. For each person:
    a. Build current_snapshot from PCO data
    b. Get previous_snapshot from storage
    c. Run sync_engine.determine_action()
    d. For each PendingChange:
        - Check if matching row already in pending_changes
        - If not → insert (this is a missed change)
    e. Upsert snapshot
3. Identify "stranded" pending rows (person no longer matches any current state) → log for manual review
```

### 4.2 First-run baseline mode

On very first deploy, the snapshot table is empty. We do NOT want to mass-create Libib patrons for every existing member.

**Strategy:**
- Add env var `RECONCILE_MODE` = `baseline` | `normal`
- In `baseline` mode: populate snapshots WITHOUT creating any pending rows
- After first run, manually flip env var to `normal`

### Deliverables
- [ ] Daily reconcile fully populates snapshots on first run (baseline mode)
- [ ] Subsequent runs detect drift and create pending rows
- [ ] Stranded rows logged but don't block runs

---

## Phase 5: Welcome Email Module

**Goal:** Send branded welcome email to new Libib patrons.

### 5.1 `shared/email_sender.py`

**Adapter pattern** for easy swap from Gmail to Microsoft Graph later:

```python
class EmailSender(Protocol):
    def send(self, to: str, subject: str, body_html: str, body_text: str) -> None: ...

class GmailSMTPSender:
    """Initial implementation."""

class MicrosoftGraphSender:
    """Future implementation when familyministry@mvbchurch.org exists."""

def get_sender() -> EmailSender:
    """Factory based on EMAIL_BACKEND env var."""
```

### 5.2 Gmail SMTP setup
- Enable 2FA on personal Gmail
- Generate App Password: https://myaccount.google.com/apppasswords
- Use `smtp.gmail.com:587` with STARTTLS

### 5.3 Email template

Defer content — Alex will provide. Module accepts:
- `template_path: str` — path to HTML template with `{{first_name}}`, `{{libib_login_url}}`, `{{password}}` placeholders
- Substitution via simple `str.format()` or Jinja2

### 5.4 Integration with worker

In `delayed_sync_worker`, after successful CREATE_LIBIB:
```python
if libib_response.success:
    email_sender.send(
        to=person.email,
        subject="Welcome to the MVBC Library",
        body_html=render_template(...),
        body_text=render_template_text(...)
    )
    log_entry.email_sent = True
```

### Deliverables
- [ ] Welcome email sends via Gmail with template substitution
- [ ] Email failures logged but don't block Libib creation (patron still exists)
- [ ] Architecture supports future Graph swap with one config change

---

## Phase 6: Azure Deployment

**Goal:** Get everything running in production Azure.

### 6.1 Azure resources to create

```
Resource Group: rg-mvbc-libib-sync
├── Function App: func-mvbc-libib-sync (Linux, Python 3.11, Consumption plan)
├── Storage Account: stmvbclibibsync (general-purpose v2)
│   └── Tables: snapshots, pending_changes, sync_log, processed_events
└── Application Insights: appi-mvbc-libib-sync
```

### 6.2 Deployment method

**Option A (recommended): VS Code Azure Functions extension**
- Install Azure Tools extension pack
- Sign in to Azure
- Right-click project → Deploy to Function App

**Option B: Azure CLI**
```bash
az login
az functionapp create ...
func azure functionapp publish func-mvbc-libib-sync
```

### 6.3 Configure App Settings (Function App → Configuration)

Migrate all values from `local.settings.json` to Function App Configuration. Mark sensitive ones as Key Vault references if you create a Key Vault (optional, $0).

### 6.4 Verify Application Insights

After first request, confirm:
- Logs visible in Live Metrics
- Custom dimensions logged (person_id, action, etc.)
- Failure alerts configurable on `traces | where severity >= 'error'`

### 6.5 Get the Function URL

After deploy:
```
https://func-mvbc-libib-sync.azurewebsites.net/api/webhook_receiver?code=<function_key>
```

The `code` is the function-level auth key. Add this to PCO subscription URL as query param.

### Deliverables
- [ ] All three functions deployed and visible in Azure portal
- [ ] App Settings populated with production secrets
- [ ] Application Insights receiving logs
- [ ] Test webhook from PCO test environment (or webhook.site replay) reaches the deployed endpoint

---

## Phase 7: Production Cutover

**Goal:** Go live with real PCO webhook subscription.

### 7.1 Run baseline reconciliation
1. Set `RECONCILE_MODE=baseline` in App Settings
2. Manually trigger `daily_reconcile` from Azure portal
3. Verify all current PCO members now have snapshots
4. Confirm zero pending_changes rows
5. Set `RECONCILE_MODE=normal`

### 7.2 Subscribe PCO webhooks
At `api.planningcenteronline.com/webhooks`:
- URL: `https://func-mvbc-libib-sync.azurewebsites.net/api/webhook_receiver?code=<key>`
- Events:
  - `people.v2.events.person.updated`
  - `people.v2.events.person.created`
  - `people.v2.events.person.destroyed`
  - `people.v2.events.email.created`
  - `people.v2.events.email.updated`
- Save the webhook secret → update App Setting `PCO_WEBHOOK_SECRET`

### 7.3 End-to-end live test
1. In PCO, change a test person's membership from Visitor → Member
2. Watch App Insights for webhook receipt
3. Verify pending_changes row created
4. Wait ~48 hours (or temporarily lower STABILITY_HOURS to 0.05 = 3 minutes for testing, then revert)
5. Verify Libib patron created
6. Verify welcome email received
7. Revert PCO change, verify subsequent freeze flow

### 7.4 Set up alerts
Application Insights → Alerts:
- Email Alex if any function fails 3+ times in 1 hour
- Email Alex if `pending_changes` has rows with `status='failed'`
- Weekly summary email of activity (optional)

### Deliverables
- [ ] Live PCO webhook subscription active
- [ ] Baseline snapshot complete
- [ ] End-to-end test successful
- [ ] Alerts configured
- [ ] README updated with operational notes

---

## Operational Runbook

### How to manually re-run a failed sync
1. Azure portal → Storage Account → Tables → pending_changes
2. Find row with `status='failed'`
3. Reset `status='pending'`, `attempts=0`
4. Manually trigger `delayed_sync_worker` from Azure portal

### How to skip a person (don't create Libib account)
1. Add their PCO `person_id` to env var `SKIP_PERSONS` (comma-separated)
2. Restart Function App
3. (Future enhancement: move to a `skip_list` table)

### How to swap Gmail → Microsoft Graph
1. Create app registration in Azure AD with `Mail.Send` permission
2. Grant access to `familyministry@mvbchurch.org` mailbox
3. Update App Settings: `EMAIL_BACKEND=graph`, add `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`
4. Restart Function App
5. No code changes needed (adapter pattern)

### How to add a new watched field
1. Add field to `PersonSnapshot` dataclass
2. Add detection logic to `sync_engine.determine_action()`
3. Add tests
4. Deploy
5. Run reconcile in baseline mode briefly to backfill snapshots, then normal mode

### Cost monitoring
- Azure Cost Management → set $5/mo budget alert as safety net
- Should never approach this with current usage

---

## Open Items / Future Enhancements

- [ ] Welcome email content (Alex to provide)
- [ ] Migration to `familyministry@mvbchurch.org` mailbox
- [ ] Optional: SMS notification when patrons are frozen?
- [ ] Optional: Slack/Teams notification on failures
- [ ] Optional: monthly digest of all sync activity
- [ ] Decision: what to do when PCO person is destroyed? (Currently: do nothing — Libib patron remains. Alternative: freeze.)
- [ ] Decision: handle household merges in PCO (could change `person_id`?)

---

## References

- PCO API: https://developer.planning.center/docs/
- PCO Webhooks: https://api.planningcenteronline.com/webhooks
- Libib REST API: https://support.libib.com/rest-api/patrons.html
- Azure Functions Python: https://learn.microsoft.com/azure/azure-functions/functions-reference-python
- Azure Table Storage Python SDK: https://learn.microsoft.com/python/api/overview/azure/data-tables-readme