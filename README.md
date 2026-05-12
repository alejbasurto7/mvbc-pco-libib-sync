# PCO → Libib Sync

Automated sync of MVBC's Planning Center People (PCO) membership data to Libib patrons. Runs every 15 minutes as a GitHub Actions cron in `alejbasurto7/mvbc-pco-libib-sync`.

See [the design spec](docs/superpowers/specs/2026-05-06-pco-libib-patron-sync-design.md) for full architecture, edge-case rationale, and decisions.

## What it does

On each run:

1. **Pull** current PCO People and Libib patron state.
2. **Decide** what actions reconcile Libib to PCO. Action types: `CREATE_PATRON`, `FREEZE_PATRON`, `UNFREEZE_PATRON`, `UPDATE_FIRST_NAME`, `UPDATE_LAST_NAME`, `UPDATE_EMAIL`.
3. **Queue** new actions in `state/pending.json` with a `detected_at` timestamp. Actions only execute after **24 hours** of stable detection (the stability gate) so reversals don't trigger Libib writes.
4. **Execute** matured actions. `CREATE_PATRON` also generates a branded library-card PNG and sends a welcome email via Gmail SMTP.

Eligible for Libib: PCO membership = `Member` or `Associate Member`, has an email, not destroyed, not tagged with a protected tag (default `ssm`).

## Architecture

- **`main` branch** — code, tests, workflow.
- **`state` branch** — operational state only (`state/pending.json`, `state/sync_log/YYYY-MM.jsonl`). The workflow checks out `main` for code and `state` for state, runs sync, commits state changes back to `state`. **Never merge `state` into `main`.**
- **`run.py`** — entry point. Calls `truststore.inject_into_ssl()` so corporate networks with TLS interception work.
- **`lib/`** — decision logic (`decide.py`), Libib + PCO clients with retry/backoff (`libib_client.py`, `pco_client.py`), executor, email sender, library-card generator.

### Why a separate `state` branch?

The sync runs every 15 minutes and needs to remember things between runs:

- **`state/pending.json`** — every action ever detected, its `detected_at` timestamp, the number of attempts, and its current status (`pending`, `succeeded`, `failed`). This is what enforces the 24-hour stability gate: a row must sit here unchanged for 24h before it's allowed to execute.
- **`state/sync_log/YYYY-MM.jsonl`** — append-only audit log. One line per notable event: `ORPHAN_DETECTED` (a Libib patron with no matching PCO person), `SKIPPED` (e.g., `reason=shared_email`), and execution outcomes. Useful when investigating "what happened on day X".

Keeping that state on a separate branch (rather than `main`) means:

- The workflow can commit state every 15 min with `[skip ci]` without polluting `main`'s commit history or re-triggering CI.
- The audit trail is free and built-in — `git log` on the `state` branch is the history of every run.
- No external database or storage service to manage, secrets to rotate, or bills to pay.
- Code review on `main` stays signal — diffs are real code changes, not state churn.

The first workflow run after a fresh deploy bootstraps the `state` branch automatically (see the "Initialize state branch on first run" step in the workflow). After that, the branch is rewritten by the bot on every successful sync.

### Key behaviors worth remembering

- **Dual-namespace patron lookup.** Libib patrons may be keyed by either the legacy CCB ID or the new PCO ID. The decider tries both `person.id` and `person.remote_id` before concluding a patron is missing.
- **Shared-email skip.** Spouses sharing an email get their `CREATE_PATRON` / `UPDATE_EMAIL` actions skipped (logged as `SKIPPED reason=shared_email`) — one Libib patron per email.
- **Protected tags.** Patrons whose Libib `tags` include any value in `PROTECTED_TAGS` are never frozen, even when PCO membership ends.
- **Baseline mode.** With repo variable `BASELINE_MODE=true`, a run records desired actions in `pending.json` without executing — used at first cutover to avoid mass writes.

## Environment

GitHub Actions **secrets** (`Settings → Secrets and variables → Actions → Secrets`):

| Secret | Purpose |
| --- | --- |
| `PCO_APP_ID`, `PCO_SECRET` | Planning Center personal access token |
| `LIBIB_API_KEY`, `LIBIB_API_USER` | Libib API headers (`x-api-key`, `x-api-user`) |
| `GMAIL_USER`, `GMAIL_APP_PASSWORD` | Gmail SMTP creds (16-char App Password, 2FA-generated) |
| `EMAIL_FROM`, `EMAIL_REPLY_TO` | Headers on welcome emails |

GitHub Actions **variables** (`Settings → Secrets and variables → Actions → Variables`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `BASELINE_MODE` | `false` | Set `true` for dry-record runs (no Libib writes, no emails) |
| `PROTECTED_TAGS` | `ssm` | Comma-separated Libib tags exempt from `FREEZE_PATRON` |

## Operating

### Inspect state

In the GitHub UI: switch the branch dropdown to `state`, browse `state/`.

From the terminal:

```bash
gh api repos/alejbasurto7/mvbc-pco-libib-sync/contents/state/pending.json?ref=state \
  --jq '.content' | base64 -d

gh api repos/alejbasurto7/mvbc-pco-libib-sync/contents/state/sync_log/$(date -u +%Y-%m).jsonl?ref=state \
  --jq '.content' | base64 -d
```

### Trigger manually

GitHub → Actions → `sync` workflow → "Run workflow".

### Pause the cron

Comment out the `schedule:` block in `.github/workflows/sync.yml` and push. Manual runs still work via `workflow_dispatch`.

### Failure alerts

When a run leaves `status="failed"` rows in `pending.json` or logs `ORPHAN_DETECTED` entries, the workflow opens (or comments on) a GitHub issue labeled `sync-alert`. One open issue at a time — repeat alerts append comments.

### Notifications

The workflow emails a summary to `GMAIL_USER` every time a sync run executes one or more actions (silent when nothing changes). To turn this off, delete the `Notify on action executions` step from `.github/workflows/sync.yml` and push.

## Local development

```bash
python -m venv .venv
.venv\Scripts\activate     # Windows
# OR
source .venv/bin/activate  # macOS/Linux

pip install -r requirements.txt
cp .env.example .env       # then fill in values
.venv/Scripts/python.exe -m pytest tests/   # run unit tests
python run.py --dry-run    # check action plan against live APIs without writing
```

Local runs read/write `state/` in the working tree — same shape as the `state` branch. Do not commit `state/` changes to `main`.
