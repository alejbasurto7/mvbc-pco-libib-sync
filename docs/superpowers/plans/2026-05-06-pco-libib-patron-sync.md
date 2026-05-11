# PCO → Libib Patron Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python sync system that polls Planning Center People every 15 minutes, detects membership-related changes for MVBC, holds them through a 24-hour stability gate, and propagates create/freeze/update operations to Libib — with an attached library card and welcome email for new patrons.

**Architecture:** Single Python script (`run.py`) invoked by a GitHub Actions cron. State lives as JSON files committed to a `state` branch of the repo. No databases, no servers. Pure-function core (`decide.py`, `reconcile.py`) is the testable cornerstone; thin API client wrappers handle PCO and Libib HTTP. A one-shot `migrate_patron_ids.py` script aligns Libib's `patron_id` field with PCO's IDs before the live sync goes online.

**Tech Stack:** Python 3.11+ · `requests` (HTTP) · `responses` (HTTP test mocking) · `pytest` (testing) · `Pillow` + `qrcode` (library card image) · `resend` (Resend Python SDK) · `python-dotenv` (local env loading) · GitHub Actions (cron + CI).

**Source spec:** [`docs/superpowers/specs/2026-05-06-pco-libib-patron-sync-design.md`](../specs/2026-05-06-pco-libib-patron-sync-design.md). Read it before starting; this plan presumes familiarity with §3 eligibility rules, §4 action types, §5 stability gate, §16 migration script.

---

## How this plan is organized

The plan follows the spec's phased delivery (§13). Each phase is a coherent slice that produces working, testable software. Phases earlier than 6 can be done locally with no external dependencies beyond test fixtures; Phase 6 onwards involves production deployment.

Tasks are TDD-style where the code is testable: write the failing test first, run it to confirm it fails, write minimal code to pass, run again to confirm pass, commit. Manual phases (0, 7) are checklists.

**Frequent commits.** Each task ends with a commit. If a task is interrupted, the commit keeps progress visible.

---

## Phase 0: Pre-build verification (manual checklist)

These are setup tasks that don't produce code but unblock the rest of the plan. Do them before starting Phase 0.5.

### Task 0.1: Sign up for Resend and decide sender domain

- [ ] Sign up at https://resend.com (free, no credit card)
- [ ] Create an API key: Dashboard → API Keys → Create API Key. Save the `re_...` value to a password manager.
- [ ] Decide on a sender domain. Two paths:
  - **Preferred:** Add the DNS records Resend gives you (TXT, MX, etc.) to `mvbchurch.org`, then verify the domain in Resend. Sender becomes `library@mvbchurch.org`.
  - **Fallback:** Verify a personal domain you control. Sender becomes `library@yourdomain.com` (or similar). Plan to migrate to mvbchurch.org sender later.
- [ ] Once verified, send a test email via Resend's "Test" UI to confirm delivery to your inbox.
- [ ] Record the verified sender domain and `EMAIL_FROM` value (e.g. `"MVBC Library <library@mvbchurch.org>"`) in your password manager / notes for use in Phase 6 configuration.

### Task 0.2: Verify Libib `UPDATE_EMAIL` round-trip behavior

The spec assumes that calling `POST /patrons/{old_email}?email={new_email}` updates a patron's email while preserving `patron_id` and loan history. Confirm this manually before designing around it.

- [ ] In a Libib test/sandbox account, create a test patron with email `test-pre@example.com` and patron_id `test-001`. Note the patron_id Libib stores.
- [ ] Update the email: `curl -X POST -H 'x-api-key: ...' -H 'x-api-user: ...' 'https://api.libib.com/patrons/test-pre@example.com?email=test-post@example.com'`
- [ ] Fetch by new email: `curl -H 'x-api-key: ...' -H 'x-api-user: ...' 'https://api.libib.com/patrons/test-post@example.com'`
- [ ] Confirm the response shows `patron_id: test-001` and any loan history is intact.
- [ ] If the round-trip works as expected: record success in your notes and proceed.
- [ ] If the round-trip fails (creates a new patron, loses patron_id, drops history): pause and consult; the design needs adjustment.

### Task 0.3: Verify Libib's behavior when creating a patron without a password

The spec says CREATE_PATRON sends no password. Confirm what Libib does (sends its own onboarding email? leaves the patron passwordless? requires password reset?).

- [ ] Create a test patron via API with no `password` field: `curl -X POST -H 'x-api-key: ...' -H 'x-api-user: ...' 'https://api.libib.com/patrons?first_name=Test&last_name=NoPwd&email=test-nopwd@example.com&patron_id=test-002'`
- [ ] Check the email inbox for `test-nopwd@example.com` (use a real address you can read). Does Libib send a welcome/onboarding email automatically?
- [ ] Record the answer in your notes. If Libib does NOT send its own email: our welcome email is the patron's only signal; consider including "use forgot-password if you want to log in to the catalog" in the copy. If Libib DOES send one: ours and theirs both arrive; design the copy to be complementary.

### Task 0.4: Capture sample PCO + Libib payloads as test fixtures

We'll need realistic payloads for unit tests in Phase 1. Capture them now while you have credentials handy.

- [ ] Run: `curl -u "${PCO_APP_ID}:${PCO_SECRET}" 'https://api.planningcenteronline.com/people/v2/people?include=emails&per_page=5' > pco_sample.json`
- [ ] Inspect `pco_sample.json` and confirm it shows: `id`, `attributes.first_name`, `attributes.last_name`, `attributes.membership`, `attributes.remote_id`, and `included` array with email records linked via relationships. If the payload structure differs from what the spec assumes, flag it before writing client code.
- [ ] Run: `curl -H "x-api-key: ${LIBIB_API_KEY}" -H "x-api-user: ${LIBIB_API_USER}" 'https://api.libib.com/patrons?page=1' > libib_sample.json`
- [ ] Inspect `libib_sample.json` and confirm it shows: `patron_id`, `first_name`, `last_name`, `email`, `barcode`, `freeze` for each patron. Confirm `max_per_page=50` per spec.
- [ ] Save both files somewhere safe (NOT yet committed — these contain real congregant data and barcodes; we'll redact them and turn them into fixtures in Phase 1).

### Phase 0 deliverables

- [ ] Resend account + API key + verified sender domain
- [ ] UPDATE_EMAIL round-trip confirmed working (or documented divergence)
- [ ] Libib's no-password create-patron behavior documented
- [ ] PCO + Libib sample JSON payloads captured locally for redaction in Phase 1

---

## Phase 0.5: Project setup

Cleans up the stale TypeScript scaffold and initializes the Python project. This phase MUST complete before any Python tasks.

### Task 0.5.1: Remove stale TypeScript scaffold

The existing `src/`, `package.json`, `tsconfig.json`, `README.md`, and `.env.example` were a TS exploration that's been retired. They go.

**Files:**
- Delete: `src/`, `package.json`, `tsconfig.json`, `README.md`, `.env.example`

- [ ] **Step 1: List what's there**

Run: `ls -la`
Expected: shows `.env.example`, `.gitignore`, `README.md`, `build-plan.md`, `docs/`, `package.json`, `src/`, `templates/`, `tsconfig.json`. (`build-plan.md` and `docs/` and `templates/` are spec/asset artifacts to keep.)

- [ ] **Step 2: Delete the TS scaffold and the stale README/env example**

Run: `rm -rf src/ package.json tsconfig.json README.md .env.example`

- [ ] **Step 3: Confirm what's left**

Run: `ls -la`
Expected: `.gitignore`, `build-plan.md`, `docs/`, `templates/`. (`build-plan.md` is preserved as historical context per the spec's "Supersedes" note.)

- [ ] **Step 4: No commit yet** — we'll commit after the next task initializes Python project files.

### Task 0.5.2: Initialize git repository

The spec assumes the project is a git repository (state branch, GitHub Actions). It currently is not.

- [ ] **Step 1: Initialize git**

Run: `git init -b main`
Expected: "Initialized empty Git repository in ..."

- [ ] **Step 2: Configure local git identity for this repo**

Run: `git config user.email "alejandrobasurto7@gmail.com"` and `git config user.name "Alex Basurto"`

- [ ] **Step 3: Stage and commit the spec + plan + build-plan + template assets so far**

```bash
git add .gitignore build-plan.md docs/ templates/
git commit -m "chore: initial commit — spec, plan, and welcome email template"
```

Expected: a single commit on `main`.

### Task 0.5.3: Create Python project files

**Files:**
- Create: `requirements.txt`, `.gitignore` (overwrite), `.env.example`, `README.md`, `pytest.ini`

- [ ] **Step 1: Overwrite `.gitignore` with Python-appropriate ignores**

Replace the contents of `.gitignore` with:

```
# Secrets & local config
.env
*.env.local

# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.venv/
venv/
build/
dist/

# Editor / OS
.vscode/
.idea/
.DS_Store
Thumbs.db

# Phase-0 captured payloads (raw, with PII)
pco_sample.json
libib_sample.json

# Local migration artifacts
migration_log.jsonl
cards/
```

- [ ] **Step 2: Create `requirements.txt`**

```
requests>=2.31,<3
resend>=2.0,<3
Pillow>=10.0,<12
qrcode[pil]>=7.4,<9
python-dotenv>=1.0,<2

# Test dependencies
pytest>=8.0,<9
responses>=0.25,<1
pytest-mock>=3.12,<4
```

- [ ] **Step 3: Create `.env.example`**

```
# PCO Personal Access Token (Basic auth)
PCO_APP_ID=
PCO_SECRET=

# Libib API credentials
LIBIB_API_KEY=
LIBIB_API_USER=

# Resend (welcome email backend)
RESEND_API_KEY=
EMAIL_FROM="MVBC Library <library@mvbchurch.org>"
EMAIL_REPLY_TO=
EMAIL_BACKEND=resend

# Behavior
STABILITY_HOURS=24
LIBIB_LOGIN_URL=https://www.libib.com/u/mvbchurch
BASELINE_MODE=false
```

- [ ] **Step 4: Create a minimal `README.md`**

```markdown
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
```

- [ ] **Step 5: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --strict-markers
```

- [ ] **Step 6: Verify file layout**

Run: `ls -la`
Expected: `.env.example`, `.gitignore`, `README.md`, `build-plan.md`, `docs/`, `pytest.ini`, `requirements.txt`, `templates/`.

- [ ] **Step 7: Commit**

```bash
git add .gitignore .env.example README.md pytest.ini requirements.txt
git commit -m "chore: initialize Python project skeleton"
```

### Task 0.5.4: Set up Python virtual environment and install dependencies

- [ ] **Step 1: Create venv** — Run: `python -m venv .venv`
- [ ] **Step 2: Activate venv** — Run: `.venv\Scripts\Activate.ps1` (PowerShell) or `.venv\Scripts\activate.bat` (cmd) or `source .venv/bin/activate` (bash)
- [ ] **Step 3: Install dependencies** — Run: `pip install -r requirements.txt`
- [ ] **Step 4: Verify pytest runs** — Run: `pytest`. Expected: `no tests ran` (no test files yet — that's fine).
- [ ] **Step 5: No commit needed** — venv directory is gitignored.

### Task 0.5.5: Create the directory skeleton

**Files:**
- Create: `lib/__init__.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/fixtures/.gitkeep`, `state/sync_log/.gitkeep`

- [ ] **Step 1: Create directories and stub files**

```bash
mkdir -p lib tests/fixtures state/sync_log
touch lib/__init__.py tests/__init__.py tests/fixtures/.gitkeep state/sync_log/.gitkeep
```

(On Windows PowerShell: `New-Item -Path lib/__init__.py, tests/__init__.py, tests/fixtures/.gitkeep, state/sync_log/.gitkeep -ItemType File -Force`)

- [ ] **Step 2: Create a minimal `tests/conftest.py`**

```python
"""Shared pytest fixtures."""
```

- [ ] **Step 3: Create a stub `state/pending.json`**

```json
{"version": 1, "updated_at": null, "rows": []}
```

- [ ] **Step 4: Verify**

Run: `pytest`
Expected: `no tests ran` (still no tests; just confirming pytest discovers the layout).

- [ ] **Step 5: Commit**

```bash
git add lib tests state
git commit -m "chore: scaffold lib/, tests/, state/ directories"
```

---

## Phase 1: Pure logic — types, decide.py, reconcile.py

Pure functions only. No I/O. Strict TDD: tests first, then implementation. Each task adds tests that fail, then code that makes them pass.

### Task 1.1: Define core data types

**Files:**
- Create: `lib/types.py`
- Create: `tests/test_types.py`

- [ ] **Step 1: Write a sanity test that the types are importable and constructible**

Create `tests/test_types.py`:

```python
from datetime import datetime, timezone

from lib.types import Action, ActionType, PendingChange, Patron, Person


def test_person_minimal_construction():
    p = Person(
        id="123",
        remote_id="ccb-456",
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        membership="Member",
        is_destroyed=False,
    )
    assert p.id == "123"
    assert p.remote_id == "ccb-456"


def test_person_destroyed_defaults_to_false():
    p = Person(id="1", remote_id=None, first_name="A", last_name="B", email=None, membership=None)
    assert p.is_destroyed is False


def test_patron_minimal_construction():
    pat = Patron(
        patron_id="123",
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        barcode="BC-001",
        is_frozen=False,
    )
    assert pat.is_frozen is False


def test_action_type_literals():
    a = Action(person_id="1", action_type="CREATE_PATRON", target={"email": "x@y"})
    assert a.action_type == "CREATE_PATRON"


def test_pending_change_construction():
    pc = PendingChange(
        person_id="1",
        action_type="CREATE_PATRON",
        target={"email": "x@y"},
        detected_at=datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        attempts=0,
        last_attempt_at=None,
        status="pending",
    )
    assert pc.attempts == 0
    assert pc.status == "pending"
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_types.py -v`
Expected: ImportError — `lib.types` doesn't exist yet.

- [ ] **Step 3: Implement `lib/types.py`**

```python
"""Shared dataclasses. Pure data — no behavior."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

ActionType = Literal[
    "CREATE_PATRON",
    "FREEZE_PATRON",
    "UPDATE_FIRST_NAME",
    "UPDATE_LAST_NAME",
    "UPDATE_EMAIL",
]

PendingStatus = Literal["pending", "baseline", "failed"]


@dataclass(frozen=True)
class Person:
    """A person as we model them from PCO."""
    id: str
    remote_id: Optional[str]
    first_name: str
    last_name: str
    email: Optional[str]
    membership: Optional[str]
    is_destroyed: bool = False


@dataclass(frozen=True)
class Patron:
    """A patron as we model them from Libib."""
    patron_id: str
    first_name: str
    last_name: str
    email: str
    barcode: Optional[str]
    is_frozen: bool


@dataclass(frozen=True)
class Action:
    """A desired action (newly computed each run)."""
    person_id: str
    action_type: ActionType
    target: dict[str, Any]


@dataclass
class PendingChange:
    """A row in pending.json. Mutable so we can update attempts/status."""
    person_id: str
    action_type: ActionType
    target: dict[str, Any]
    detected_at: datetime
    attempts: int = 0
    last_attempt_at: Optional[datetime] = None
    status: PendingStatus = "pending"
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_types.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/types.py tests/test_types.py
git commit -m "feat(types): define Person, Patron, Action, PendingChange dataclasses"
```

### Task 1.2: `expected_patron_id` and `is_eligible` helpers

These are the smallest atoms of decide.py. Test them in isolation before building the full action computation.

**Files:**
- Create: `lib/decide.py`
- Create: `tests/test_decide.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_decide.py`:

```python
from lib.decide import MEMBER_STATUSES, expected_patron_id, is_eligible
from lib.types import Person


def make_person(**overrides) -> Person:
    """Default-everything Person factory for tests."""
    base = dict(
        id="pco-1",
        remote_id=None,
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        membership="Member",
        is_destroyed=False,
    )
    base.update(overrides)
    return Person(**base)


class TestExpectedPatronId:
    def test_uses_remote_id_when_present(self):
        p = make_person(id="pco-1", remote_id="ccb-42")
        assert expected_patron_id(p) == "ccb-42"

    def test_falls_back_to_id_when_remote_id_is_none(self):
        p = make_person(id="pco-1", remote_id=None)
        assert expected_patron_id(p) == "pco-1"

    def test_falls_back_to_id_when_remote_id_is_empty_string(self):
        p = make_person(id="pco-1", remote_id="")
        assert expected_patron_id(p) == "pco-1"


class TestIsEligible:
    def test_member_with_email_is_eligible(self):
        assert is_eligible(make_person(membership="Member"))

    def test_associate_member_with_email_is_eligible(self):
        assert is_eligible(make_person(membership="Associate Member"))

    def test_visitor_is_not_eligible(self):
        assert not is_eligible(make_person(membership="Visitor"))

    def test_member_without_email_is_not_eligible(self):
        assert not is_eligible(make_person(membership="Member", email=None))

    def test_destroyed_person_is_not_eligible(self):
        assert not is_eligible(make_person(membership="Member", is_destroyed=True))

    def test_member_statuses_constant(self):
        assert MEMBER_STATUSES == {"Member", "Associate Member"}
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_decide.py -v`
Expected: ImportError on `lib.decide`.

- [ ] **Step 3: Implement just enough of `lib/decide.py`**

```python
"""Pure decision logic. No I/O. No mutation of inputs."""
from lib.types import Person

MEMBER_STATUSES: set[str] = {"Member", "Associate Member"}


def expected_patron_id(person: Person) -> str:
    """The Libib patron_id we expect for this person.

    Post-migration (per spec §16) every Libib patron's patron_id equals the
    PCO person.id; pre-migration the value lives in PCO's remote_id field.
    The `or` covers both populations and people with no remote_id at all.
    """
    return person.remote_id or person.id


def is_eligible(person: Person) -> bool:
    """True if this person should have an active (unfrozen) Libib patron."""
    return (
        person.membership in MEMBER_STATUSES
        and person.email is not None
        and not person.is_destroyed
    )
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_decide.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/decide.py tests/test_decide.py
git commit -m "feat(decide): add expected_patron_id and is_eligible helpers"
```

### Task 1.3: `compute_desired_actions` — CREATE_PATRON path

Now the main function, growing one branch at a time.

- [ ] **Step 1: Add tests for CREATE_PATRON branches** to `tests/test_decide.py`:

```python
from lib.decide import compute_desired_actions
from lib.types import Action, Patron


def make_patron(**overrides) -> Patron:
    base = dict(
        patron_id="pco-1",
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        barcode="BC-1",
        is_frozen=False,
    )
    base.update(overrides)
    return Patron(**base)


class TestComputeDesiredActions_Create:
    def test_eligible_person_with_no_libib_patron_creates(self):
        person = make_person(id="pco-1", remote_id=None)
        actions = compute_desired_actions([person], [])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="CREATE_PATRON",
                target={
                    "first_name": "Ana",
                    "last_name": "Smith",
                    "email": "ana@example.com",
                    "patron_id": "pco-1",
                },
            )
        ]

    def test_visitor_with_no_libib_patron_does_nothing(self):
        person = make_person(membership="Visitor")
        actions = compute_desired_actions([person], [])
        assert actions == []

    def test_member_without_email_does_nothing(self):
        person = make_person(email=None)
        actions = compute_desired_actions([person], [])
        assert actions == []

    def test_create_uses_remote_id_when_present(self):
        person = make_person(id="pco-1", remote_id="ccb-99")
        actions = compute_desired_actions([person], [])
        assert actions[0].target["patron_id"] == "ccb-99"

    def test_existing_eligible_patron_no_diff_returns_empty(self):
        person = make_person(id="pco-1", remote_id=None)
        patron = make_patron(patron_id="pco-1")
        actions = compute_desired_actions([person], [patron])
        assert actions == []
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_decide.py -v`
Expected: ImportError or AttributeError on `compute_desired_actions`.

- [ ] **Step 3: Implement** by appending to `lib/decide.py`:

```python
from lib.types import Action, Patron


def compute_desired_actions(
    pco_people: list[Person],
    libib_patrons: list[Patron],
) -> list[Action]:
    """Compute actions needed to bring Libib in line with PCO.

    Pure: no I/O, no mutation of inputs.

    Lookup: a PCO person matches the Libib patron whose patron_id equals the
    person's expected_patron_id (i.e., remote_id or id).
    """
    patrons_by_id: dict[str, Patron] = {}
    for patron in libib_patrons:
        # patron_id is documented as non-unique by Libib (§4.2). On collision
        # we'd rather no-op than write to the wrong patron, so we skip
        # patrons with conflicting ids by leaving the second one out.
        if patron.patron_id not in patrons_by_id:
            patrons_by_id[patron.patron_id] = patron

    actions: list[Action] = []
    for person in pco_people:
        expected_id = expected_patron_id(person)
        existing = patrons_by_id.get(expected_id)
        if is_eligible(person):
            if existing is None:
                # CREATE: type narrowing — is_eligible guarantees email
                assert person.email is not None
                actions.append(
                    Action(
                        person_id=person.id,
                        action_type="CREATE_PATRON",
                        target={
                            "first_name": person.first_name,
                            "last_name": person.last_name,
                            "email": person.email,
                            "patron_id": expected_id,
                        },
                    )
                )
    return actions
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_decide.py -v`
Expected: 14 passed (5 new + 9 existing).

- [ ] **Step 5: Commit**

```bash
git add lib/decide.py tests/test_decide.py
git commit -m "feat(decide): implement CREATE_PATRON branch of compute_desired_actions"
```

### Task 1.4: FREEZE_PATRON branch

- [ ] **Step 1: Add tests** to `tests/test_decide.py`:

```python
class TestComputeDesiredActions_Freeze:
    def test_member_to_former_member_freezes(self):
        person = make_person(id="pco-1", membership="Former Member")
        patron = make_patron(patron_id="pco-1", is_frozen=False)
        actions = compute_desired_actions([person], [patron])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="FREEZE_PATRON",
                target={"email": "ana@example.com"},
            )
        ]

    def test_already_frozen_no_double_freeze(self):
        person = make_person(membership="Former Member")
        patron = make_patron(is_frozen=True)
        actions = compute_desired_actions([person], [patron])
        assert actions == []

    def test_destroyed_person_freezes_existing_patron(self):
        person = make_person(id="pco-1", is_destroyed=True)
        patron = make_patron(patron_id="pco-1", is_frozen=False)
        actions = compute_desired_actions([person], [patron])
        assert actions[0].action_type == "FREEZE_PATRON"

    def test_freeze_target_uses_libib_email(self):
        # Libib's update endpoint is keyed by current Libib email
        person = make_person(id="pco-1", email="new@example.com", membership="Visitor")
        patron = make_patron(patron_id="pco-1", email="old@example.com")
        actions = compute_desired_actions([person], [patron])
        assert actions[0].target == {"email": "old@example.com"}

    def test_visitor_with_no_libib_patron_does_nothing(self):
        # The CREATE branch test covered this for non-eligible+no-patron, but
        # double-check we don't synthesize a freeze when there's nothing to freeze.
        person = make_person(membership="Visitor")
        actions = compute_desired_actions([person], [])
        assert actions == []
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_decide.py::TestComputeDesiredActions_Freeze -v`
Expected: 4 fail (test_visitor_with_no_libib_patron_does_nothing already passes from existing logic).

- [ ] **Step 3: Add the FREEZE branch** to `compute_desired_actions` in `lib/decide.py`. Replace the loop body's eligibility branch with:

```python
        if is_eligible(person):
            if existing is None:
                assert person.email is not None
                actions.append(
                    Action(
                        person_id=person.id,
                        action_type="CREATE_PATRON",
                        target={
                            "first_name": person.first_name,
                            "last_name": person.last_name,
                            "email": person.email,
                            "patron_id": expected_id,
                        },
                    )
                )
        else:
            if existing is not None and not existing.is_frozen:
                actions.append(
                    Action(
                        person_id=person.id,
                        action_type="FREEZE_PATRON",
                        # Use the patron's *current* email — Libib's update
                        # endpoint is keyed by the email it currently knows.
                        target={"email": existing.email},
                    )
                )
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_decide.py -v`
Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/decide.py tests/test_decide.py
git commit -m "feat(decide): implement FREEZE_PATRON branch"
```

### Task 1.5: UPDATE_* branches

- [ ] **Step 1: Add tests** to `tests/test_decide.py`:

```python
class TestComputeDesiredActions_Updates:
    def test_first_name_change_emits_update(self):
        person = make_person(id="pco-1", first_name="Anna")
        patron = make_patron(patron_id="pco-1", first_name="Ana")
        actions = compute_desired_actions([person], [patron])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="UPDATE_FIRST_NAME",
                target={"first_name": "Anna", "email": "ana@example.com"},
            )
        ]

    def test_last_name_change_emits_update(self):
        person = make_person(id="pco-1", last_name="Smyth")
        patron = make_patron(patron_id="pco-1", last_name="Smith")
        actions = compute_desired_actions([person], [patron])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="UPDATE_LAST_NAME",
                target={"last_name": "Smyth", "email": "ana@example.com"},
            )
        ]

    def test_email_change_emits_update(self):
        person = make_person(id="pco-1", email="new@example.com")
        patron = make_patron(patron_id="pco-1", email="old@example.com")
        actions = compute_desired_actions([person], [patron])
        assert actions == [
            Action(
                person_id="pco-1",
                action_type="UPDATE_EMAIL",
                # Update keyed by *old* email; new email is the target value
                target={"old_email": "old@example.com", "email": "new@example.com"},
            )
        ]

    def test_first_and_last_name_change_emits_two(self):
        person = make_person(id="pco-1", first_name="Anna", last_name="Smyth")
        patron = make_patron(patron_id="pco-1", first_name="Ana", last_name="Smith")
        actions = compute_desired_actions([person], [patron])
        types = [a.action_type for a in actions]
        assert types == ["UPDATE_FIRST_NAME", "UPDATE_LAST_NAME"]

    def test_no_diffs_no_actions(self):
        person = make_person(id="pco-1", first_name="Ana", last_name="Smith", email="ana@example.com")
        patron = make_patron(patron_id="pco-1", first_name="Ana", last_name="Smith", email="ana@example.com")
        assert compute_desired_actions([person], [patron]) == []

    def test_updates_skip_when_patron_already_frozen(self):
        # If the patron is frozen we shouldn't push name/email updates while frozen
        # — they'll un-freeze when the person becomes eligible again.
        person = make_person(id="pco-1", first_name="Anna", membership="Former Member")
        patron = make_patron(patron_id="pco-1", first_name="Ana", is_frozen=True)
        actions = compute_desired_actions([person], [patron])
        # Not eligible AND already frozen → nothing
        assert actions == []
```

- [ ] **Step 2: Run, watch the new tests fail**

Run: `pytest tests/test_decide.py::TestComputeDesiredActions_Updates -v`
Expected: 5 failures (test_no_diffs_no_actions and test_updates_skip_when_patron_already_frozen already pass).

- [ ] **Step 3: Add UPDATE branches** to `compute_desired_actions` in `lib/decide.py`. Replace the inner `if existing is None: ... ` block with:

```python
        if is_eligible(person):
            assert person.email is not None
            if existing is None:
                actions.append(
                    Action(
                        person_id=person.id,
                        action_type="CREATE_PATRON",
                        target={
                            "first_name": person.first_name,
                            "last_name": person.last_name,
                            "email": person.email,
                            "patron_id": expected_id,
                        },
                    )
                )
            else:
                # Use existing.email to key Libib API calls (Libib looks up by current email)
                if person.first_name != existing.first_name:
                    actions.append(
                        Action(
                            person_id=person.id,
                            action_type="UPDATE_FIRST_NAME",
                            target={"first_name": person.first_name, "email": existing.email},
                        )
                    )
                if person.last_name != existing.last_name:
                    actions.append(
                        Action(
                            person_id=person.id,
                            action_type="UPDATE_LAST_NAME",
                            target={"last_name": person.last_name, "email": existing.email},
                        )
                    )
                if person.email != existing.email:
                    actions.append(
                        Action(
                            person_id=person.id,
                            action_type="UPDATE_EMAIL",
                            target={"old_email": existing.email, "email": person.email},
                        )
                    )
```

- [ ] **Step 4: Run all decide tests**

Run: `pytest tests/test_decide.py -v`
Expected: 25 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/decide.py tests/test_decide.py
git commit -m "feat(decide): implement UPDATE_FIRST_NAME, UPDATE_LAST_NAME, UPDATE_EMAIL branches"
```

### Task 1.6: Orphan detection

Spec §4.3: when we find a Libib patron with `patron_id` not matching any PCO person, log it. We model this as a separate function returning the list of orphan patrons.

- [ ] **Step 1: Add tests** to `tests/test_decide.py`:

```python
from lib.decide import find_orphan_patrons


class TestFindOrphanPatrons:
    def test_no_orphans_when_all_match(self):
        person = make_person(id="pco-1", remote_id=None)
        patron = make_patron(patron_id="pco-1")
        assert find_orphan_patrons([person], [patron]) == []

    def test_libib_patron_with_unknown_id_is_orphan(self):
        person = make_person(id="pco-1")
        orphan = make_patron(patron_id="unknown-99")
        result = find_orphan_patrons([person], [orphan])
        assert result == [orphan]

    def test_orphan_detection_uses_expected_patron_id(self):
        # remote_id should match
        person = make_person(id="pco-1", remote_id="ccb-42")
        patron = make_patron(patron_id="ccb-42")
        assert find_orphan_patrons([person], [patron]) == []
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_decide.py::TestFindOrphanPatrons -v`
Expected: ImportError on `find_orphan_patrons`.

- [ ] **Step 3: Implement** in `lib/decide.py`:

```python
def find_orphan_patrons(
    pco_people: list[Person],
    libib_patrons: list[Patron],
) -> list[Patron]:
    """Libib patrons whose patron_id matches no PCO person.

    Per spec §4.3, every Libib patron should have a PCO counterpart.
    Orphans are anomalies worth surfacing but never auto-actioned.
    """
    expected_ids = {expected_patron_id(p) for p in pco_people}
    return [pat for pat in libib_patrons if pat.patron_id not in expected_ids]
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_decide.py -v`
Expected: 28 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/decide.py tests/test_decide.py
git commit -m "feat(decide): add find_orphan_patrons helper"
```

### Task 1.7: Reconcile algorithm — basic shape

Spec §5: given desired actions and a pending state, produce the new pending state plus a list of mature actions ready to execute.

**Files:**
- Create: `lib/reconcile.py`
- Create: `tests/test_reconcile.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_reconcile.py`:

```python
from datetime import datetime, timedelta, timezone

from lib.reconcile import reconcile
from lib.types import Action, PendingChange


def now() -> datetime:
    return datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)


def make_action(action_type="CREATE_PATRON", person_id="pco-1", target=None) -> Action:
    return Action(person_id=person_id, action_type=action_type, target=target or {"email": "x@y"})


def make_pending(action_type="CREATE_PATRON", person_id="pco-1", detected_offset_hours=0,
                 target=None, attempts=0, status="pending") -> PendingChange:
    return PendingChange(
        person_id=person_id,
        action_type=action_type,
        target=target or {"email": "x@y"},
        detected_at=now() - timedelta(hours=detected_offset_hours),
        attempts=attempts,
        last_attempt_at=None,
        status=status,
    )


class TestReconcile:
    def test_brand_new_action_added_with_current_timestamp(self):
        action = make_action()
        new_pending, mature = reconcile([action], [], now=now(), stability_hours=24.0)
        assert len(new_pending) == 1
        assert new_pending[0].person_id == "pco-1"
        assert new_pending[0].detected_at == now()
        assert new_pending[0].status == "pending"
        assert mature == []

    def test_existing_pending_action_target_unchanged_keeps_detected_at(self):
        existing = make_pending(detected_offset_hours=10)  # detected 10h ago
        action = make_action()  # same target as existing
        new_pending, mature = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert new_pending[0].detected_at == existing.detected_at
        assert mature == []

    def test_existing_pending_action_target_changed_resets_detected_at(self):
        existing = make_pending(target={"email": "old@x"}, detected_offset_hours=10)
        action = make_action(target={"email": "new@x"})
        new_pending, mature = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert new_pending[0].detected_at == now()
        assert new_pending[0].target == {"email": "new@x"}

    def test_pending_action_no_longer_desired_is_removed(self):
        existing = make_pending(detected_offset_hours=5)
        new_pending, mature = reconcile([], [existing], now=now(), stability_hours=24.0)
        assert new_pending == []
        assert mature == []

    def test_mature_action_returned_for_execution(self):
        existing = make_pending(detected_offset_hours=25)  # past stability gate
        action = make_action()  # still desired
        new_pending, mature = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert len(mature) == 1
        assert mature[0].person_id == "pco-1"
        # Still in pending until execute() succeeds and removes it
        assert len(new_pending) == 1

    def test_immature_action_not_returned(self):
        existing = make_pending(detected_offset_hours=23)  # not yet mature
        action = make_action()
        new_pending, mature = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert mature == []
        assert len(new_pending) == 1

    def test_failed_status_does_not_re_mature(self):
        existing = make_pending(detected_offset_hours=99, attempts=3, status="failed")
        action = make_action()
        new_pending, mature = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert mature == []
        # But the row stays pending — preserved for manual reset
        assert len(new_pending) == 1
        assert new_pending[0].status == "failed"

    def test_baseline_status_does_not_mature(self):
        existing = make_pending(detected_offset_hours=99, status="baseline")
        action = make_action()
        new_pending, mature = reconcile([action], [existing], now=now(), stability_hours=24.0)
        assert mature == []

    def test_baseline_mode_writes_baseline_status(self):
        action = make_action()
        new_pending, mature = reconcile([action], [], now=now(), stability_hours=24.0, baseline_mode=True)
        assert new_pending[0].status == "baseline"
        assert mature == []
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_reconcile.py -v`
Expected: ImportError on `lib.reconcile`.

- [ ] **Step 3: Implement `lib/reconcile.py`**

```python
"""Pure reconciliation logic.

Given the desired actions for this run and the pending state from last run,
produce the new pending state and the list of actions that are mature
(detected_at >= stability_hours ago) and ready to execute.
"""
from dataclasses import replace
from datetime import datetime, timedelta

from lib.types import Action, PendingChange, PendingStatus


def _key(item) -> tuple[str, str]:
    return (item.person_id, item.action_type)


def reconcile(
    desired: list[Action],
    pending: list[PendingChange],
    *,
    now: datetime,
    stability_hours: float,
    baseline_mode: bool = False,
) -> tuple[list[PendingChange], list[PendingChange]]:
    """Compute (new_pending, mature_actions).

    `new_pending` is the full updated pending list to write back to disk.
    `mature_actions` is a subset of `new_pending` ready to execute now.

    A mature action stays in `new_pending` until execute() succeeds and
    removes it (caller's responsibility, not ours — see lib/execute.py).
    """
    pending_by_key = {_key(p): p for p in pending}
    desired_by_key = {_key(a): a for a in desired}

    new_pending: list[PendingChange] = []

    # Walk desired: keep, refresh, or insert
    for key, action in desired_by_key.items():
        existing = pending_by_key.get(key)
        if existing is None:
            status: PendingStatus = "baseline" if baseline_mode else "pending"
            new_pending.append(
                PendingChange(
                    person_id=action.person_id,
                    action_type=action.action_type,
                    target=action.target,
                    detected_at=now,
                    attempts=0,
                    last_attempt_at=None,
                    status=status,
                )
            )
        else:
            if existing.target == action.target:
                # No change in target — preserve detected_at and counters
                new_pending.append(existing)
            else:
                # Target shifted — reset the gate, preserve attempts? No: a
                # different target means a new clock starts.
                new_pending.append(
                    replace(
                        existing,
                        target=action.target,
                        detected_at=now,
                        attempts=0,
                        last_attempt_at=None,
                        status="pending" if existing.status != "baseline" else "baseline",
                    )
                )

    # Walk pending: drop entries that are no longer desired
    # (we already wrote desired ones above; orphans here are reverts)
    # No further work needed: anything in `pending_by_key` not in
    # `desired_by_key` is implicitly dropped because we built new_pending
    # only from desired keys.

    # Compute mature subset
    threshold = now - timedelta(hours=stability_hours)
    mature = [
        p for p in new_pending
        if p.status == "pending" and p.detected_at <= threshold
    ]

    return new_pending, mature
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_reconcile.py -v`
Expected: 9 passed.

- [ ] **Step 5: Run all tests**

Run: `pytest -v`
Expected: 37 passed.

- [ ] **Step 6: Commit**

```bash
git add lib/reconcile.py tests/test_reconcile.py
git commit -m "feat(reconcile): implement pending-state reconciliation with stability gate"
```

---

## Phase 2: API clients — pco_client.py and libib_client.py

Thin HTTP wrappers around PCO and Libib REST APIs. Tests use the `responses` library to mock HTTP without hitting the network.

### Task 2.1: PCO client — list_all_people pagination

The PCO People API paginates with `links.next` and `meta.next.offset`. We need a generator that walks all pages and yields normalized `Person` objects.

**Files:**
- Create: `lib/pco_client.py`
- Create: `tests/test_pco_client.py`
- Create: `tests/fixtures/pco_page_1.json`, `tests/fixtures/pco_page_2.json` (redacted real fixtures)

- [ ] **Step 1: Build redacted fixtures**

Take the `pco_sample.json` you captured in Task 0.4 and create two trimmed pages with synthetic data. Save as `tests/fixtures/pco_page_1.json`:

```json
{
  "data": [
    {
      "type": "Person",
      "id": "100",
      "attributes": {
        "first_name": "Ana",
        "last_name": "Smith",
        "membership": "Member",
        "remote_id": "42",
        "status": "active"
      },
      "relationships": {
        "primary_email": {
          "data": {"type": "Email", "id": "200"}
        }
      }
    },
    {
      "type": "Person",
      "id": "101",
      "attributes": {
        "first_name": "Bob",
        "last_name": "Jones",
        "membership": "Visitor",
        "remote_id": null,
        "status": "active"
      },
      "relationships": {
        "primary_email": {
          "data": null
        }
      }
    }
  ],
  "included": [
    {
      "type": "Email",
      "id": "200",
      "attributes": {"address": "ana@example.com", "primary": true}
    }
  ],
  "links": {
    "self": "https://api.planningcenteronline.com/people/v2/people?include=emails&per_page=2",
    "next": "https://api.planningcenteronline.com/people/v2/people?include=emails&per_page=2&offset=2"
  },
  "meta": {"total_count": 3, "count": 2, "next": {"offset": 2}}
}
```

And `tests/fixtures/pco_page_2.json`:

```json
{
  "data": [
    {
      "type": "Person",
      "id": "102",
      "attributes": {
        "first_name": "Carol",
        "last_name": "Davis",
        "membership": "Associate Member",
        "remote_id": "55",
        "status": "active"
      },
      "relationships": {
        "primary_email": {
          "data": {"type": "Email", "id": "201"}
        }
      }
    }
  ],
  "included": [
    {
      "type": "Email",
      "id": "201",
      "attributes": {"address": "carol@example.com", "primary": true}
    }
  ],
  "links": {
    "self": "https://api.planningcenteronline.com/people/v2/people?include=emails&per_page=2&offset=2"
  },
  "meta": {"total_count": 3, "count": 1}
}
```

> If the real PCO payload structure differs from these fixtures (you'll know from inspecting `pco_sample.json` in Task 0.4), update the fixtures to match. The shape above is the documented PCO format as of 2026.

- [ ] **Step 2: Write failing test**

Create `tests/test_pco_client.py`:

```python
import json
from pathlib import Path

import pytest
import responses

from lib.pco_client import PCOClient
from lib.types import Person


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def client():
    return PCOClient(app_id="app", secret="sec")


@responses.activate
def test_list_all_people_walks_pagination(client):
    page1 = load_fixture("pco_page_1.json")
    page2 = load_fixture("pco_page_2.json")
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json=page1,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json=page2,
        status=200,
    )

    people = list(client.list_all_people())

    assert len(people) == 3
    assert all(isinstance(p, Person) for p in people)


@responses.activate
def test_list_all_people_extracts_primary_email(client):
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json=load_fixture("pco_page_1.json"),
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json=load_fixture("pco_page_2.json"),
        status=200,
    )
    by_id = {p.id: p for p in client.list_all_people()}
    assert by_id["100"].email == "ana@example.com"
    assert by_id["101"].email is None  # no primary_email relationship
    assert by_id["102"].email == "carol@example.com"


@responses.activate
def test_list_all_people_membership_and_remote_id(client):
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json=load_fixture("pco_page_1.json"),
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json=load_fixture("pco_page_2.json"),
        status=200,
    )
    by_id = {p.id: p for p in client.list_all_people()}
    assert by_id["100"].membership == "Member"
    assert by_id["100"].remote_id == "42"
    assert by_id["101"].remote_id is None
    assert by_id["102"].membership == "Associate Member"


@responses.activate
def test_basic_auth_header_used(client):
    responses.add(
        responses.GET,
        "https://api.planningcenteronline.com/people/v2/people",
        json={"data": [], "included": [], "links": {"self": "..."}, "meta": {"total_count": 0, "count": 0}},
        status=200,
    )
    list(client.list_all_people())
    assert responses.calls[0].request.headers.get("Authorization", "").startswith("Basic ")
```

- [ ] **Step 3: Run, watch fail**

Run: `pytest tests/test_pco_client.py -v`
Expected: ImportError on `lib.pco_client`.

- [ ] **Step 4: Implement `lib/pco_client.py`**

```python
"""Wrapper around Planning Center People API.

Authenticates with a Personal Access Token (App ID + Secret) via HTTP Basic.
Yields normalized Person objects, handling pagination and email lookup.
"""
from typing import Iterator

import requests

from lib.types import Person

API_BASE = "https://api.planningcenteronline.com/people/v2"


class PCOClient:
    def __init__(self, app_id: str, secret: str, session: requests.Session | None = None):
        self.app_id = app_id
        self.secret = secret
        self.session = session or requests.Session()

    def list_all_people(self, per_page: int = 100) -> Iterator[Person]:
        """Yield every PCO person, walking pagination.

        Includes related email records to extract the primary email.
        """
        url = f"{API_BASE}/people"
        params = {"include": "emails", "per_page": per_page}

        while url:
            resp = self.session.get(
                url,
                params=params if "offset" not in url else None,
                auth=(self.app_id, self.secret),
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()

            email_by_id = {
                inc["id"]: inc["attributes"]["address"]
                for inc in payload.get("included", [])
                if inc.get("type") == "Email"
            }

            for item in payload["data"]:
                if item.get("type") != "Person":
                    continue
                attrs = item["attributes"]
                rels = item.get("relationships", {})
                primary_rel = rels.get("primary_email", {}).get("data")
                email = email_by_id.get(primary_rel["id"]) if primary_rel else None

                yield Person(
                    id=item["id"],
                    remote_id=attrs.get("remote_id"),
                    first_name=attrs.get("first_name") or "",
                    last_name=attrs.get("last_name") or "",
                    email=email,
                    membership=attrs.get("membership"),
                    is_destroyed=False,  # PCO does not return destroyed people in list
                )

            url = payload.get("links", {}).get("next")
            params = None  # next URL has its own query
```

- [ ] **Step 5: Run, watch pass**

Run: `pytest tests/test_pco_client.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add lib/pco_client.py tests/test_pco_client.py tests/fixtures/pco_page_1.json tests/fixtures/pco_page_2.json
git commit -m "feat(pco_client): list_all_people with pagination and primary email"
```

### Task 2.2: Libib client — list_all_patrons

**Files:**
- Create: `lib/libib_client.py`
- Create: `tests/test_libib_client.py`
- Create: `tests/fixtures/libib_page_1.json`, `tests/fixtures/libib_page_2.json`

- [ ] **Step 1: Build fixtures**

Save as `tests/fixtures/libib_page_1.json`:

```json
{
  "patrons": [
    {
      "patron_id": "100",
      "first_name": "Ana",
      "last_name": "Smith",
      "email": "ana@example.com",
      "barcode": "BC-100",
      "freeze": 0
    },
    {
      "patron_id": "200",
      "first_name": "Old",
      "last_name": "Member",
      "email": "old@example.com",
      "barcode": "BC-200",
      "freeze": 1
    }
  ],
  "page": 1,
  "max_per_page": 50,
  "total_count": 3
}
```

And `tests/fixtures/libib_page_2.json`:

```json
{
  "patrons": [
    {
      "patron_id": "300",
      "first_name": "Carol",
      "last_name": "Davis",
      "email": "carol@example.com",
      "barcode": "BC-300",
      "freeze": 0
    }
  ],
  "page": 2,
  "max_per_page": 50,
  "total_count": 3
}
```

> Confirm the response shape matches your `libib_sample.json` from Task 0.4 — adjust if the real keys differ.

- [ ] **Step 2: Write failing test**

Create `tests/test_libib_client.py`:

```python
import json
from pathlib import Path

import pytest
import responses

from lib.libib_client import LibibClient
from lib.types import Patron


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def client():
    return LibibClient(api_key="key", api_user="user")


@responses.activate
def test_list_all_patrons_walks_pagination(client):
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json=load_fixture("libib_page_1.json"), status=200,
    )
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json=load_fixture("libib_page_2.json"), status=200,
    )
    patrons = list(client.list_all_patrons())
    assert len(patrons) == 3


@responses.activate
def test_list_all_patrons_normalizes_freeze_to_bool(client):
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json=load_fixture("libib_page_1.json"), status=200,
    )
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json={"patrons": [], "page": 2, "max_per_page": 50, "total_count": 2}, status=200,
    )
    by_id = {p.patron_id: p for p in client.list_all_patrons()}
    assert by_id["100"].is_frozen is False
    assert by_id["200"].is_frozen is True


@responses.activate
def test_list_all_patrons_returns_patron_dataclasses(client):
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json=load_fixture("libib_page_1.json"), status=200,
    )
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json={"patrons": [], "page": 2, "max_per_page": 50, "total_count": 2}, status=200,
    )
    patrons = list(client.list_all_patrons())
    assert all(isinstance(p, Patron) for p in patrons)


@responses.activate
def test_libib_headers_are_sent(client):
    responses.add(
        responses.GET, "https://api.libib.com/patrons",
        json={"patrons": [], "page": 1, "max_per_page": 50, "total_count": 0}, status=200,
    )
    list(client.list_all_patrons())
    headers = responses.calls[0].request.headers
    assert headers["x-api-key"] == "key"
    assert headers["x-api-user"] == "user"
```

- [ ] **Step 3: Run, watch fail**

Run: `pytest tests/test_libib_client.py -v`
Expected: ImportError on `lib.libib_client`.

- [ ] **Step 4: Implement `lib/libib_client.py`**

```python
"""Wrapper around the Libib REST API.

Authenticates via x-api-key and x-api-user headers.
"""
from typing import Iterator

import requests

from lib.types import Patron

API_BASE = "https://api.libib.com"


class LibibClient:
    def __init__(
        self,
        api_key: str,
        api_user: str,
        session: requests.Session | None = None,
    ):
        self.api_key = api_key
        self.api_user = api_user
        self.session = session or requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "x-api-user": api_user,
        })

    def list_all_patrons(self) -> Iterator[Patron]:
        page = 1
        fetched = 0
        while True:
            resp = self.session.get(
                f"{API_BASE}/patrons",
                params={"page": page},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get("patrons", [])
            if not rows:
                break
            for row in rows:
                yield Patron(
                    patron_id=str(row.get("patron_id", "")),
                    first_name=row.get("first_name") or "",
                    last_name=row.get("last_name") or "",
                    email=row.get("email") or "",
                    barcode=row.get("barcode"),
                    is_frozen=bool(row.get("freeze", 0)),
                )
            fetched += len(rows)
            total_count = int(payload.get("total_count", 0))
            # Stop when we've fetched all records (or total_count is 0)
            if total_count == 0 or fetched >= total_count:
                break
            page += 1
```

- [ ] **Step 5: Run, watch pass**

Run: `pytest tests/test_libib_client.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add lib/libib_client.py tests/test_libib_client.py tests/fixtures/libib_page_1.json tests/fixtures/libib_page_2.json
git commit -m "feat(libib_client): list_all_patrons with pagination"
```

### Task 2.3: Libib client — write methods (create / freeze / update)

- [ ] **Step 1: Add tests** to `tests/test_libib_client.py`:

```python
@responses.activate
def test_create_patron_posts_correct_params(client):
    responses.add(
        responses.POST, "https://api.libib.com/patrons",
        json={"patron_id": "pco-1", "barcode": "BC-NEW", "first_name": "Ana",
              "last_name": "Smith", "email": "ana@example.com", "freeze": 0},
        status=201,
    )
    result = client.create_patron(
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        patron_id="pco-1",
    )
    assert result.barcode == "BC-NEW"
    call = responses.calls[0]
    # Libib expects query params, not JSON body
    assert "first_name=Ana" in call.request.url
    assert "last_name=Smith" in call.request.url
    assert "email=ana%40example.com" in call.request.url
    assert "patron_id=pco-1" in call.request.url


@responses.activate
def test_freeze_patron_uses_email_as_id(client):
    responses.add(
        responses.POST, "https://api.libib.com/patrons/ana@example.com",
        json={"patron_id": "pco-1", "email": "ana@example.com", "freeze": 1,
              "first_name": "Ana", "last_name": "Smith", "barcode": "BC-1"},
        status=200,
    )
    result = client.freeze_patron(email="ana@example.com")
    assert result.is_frozen is True
    assert "freeze=1" in responses.calls[0].request.url


@responses.activate
def test_update_patron_first_name(client):
    responses.add(
        responses.POST, "https://api.libib.com/patrons/ana@example.com",
        json={"patron_id": "pco-1", "email": "ana@example.com", "first_name": "Anna",
              "last_name": "Smith", "barcode": "BC-1", "freeze": 0},
        status=200,
    )
    result = client.update_patron(email="ana@example.com", first_name="Anna")
    assert result.first_name == "Anna"
    assert "first_name=Anna" in responses.calls[0].request.url


@responses.activate
def test_update_patron_email_changes_email(client):
    responses.add(
        responses.POST, "https://api.libib.com/patrons/old@example.com",
        json={"patron_id": "pco-1", "email": "new@example.com", "first_name": "Ana",
              "last_name": "Smith", "barcode": "BC-1", "freeze": 0},
        status=200,
    )
    result = client.update_patron(email="old@example.com", new_email="new@example.com")
    assert result.email == "new@example.com"
    assert "email=new%40example.com" in responses.calls[0].request.url


@responses.activate
def test_update_patron_patron_id(client):
    """Used by the migration script."""
    responses.add(
        responses.POST, "https://api.libib.com/patrons/ana@example.com",
        json={"patron_id": "pco-NEW", "email": "ana@example.com", "first_name": "Ana",
              "last_name": "Smith", "barcode": "BC-1", "freeze": 0},
        status=200,
    )
    result = client.update_patron(email="ana@example.com", patron_id="pco-NEW")
    assert result.patron_id == "pco-NEW"
    assert "patron_id=pco-NEW" in responses.calls[0].request.url
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_libib_client.py -v`
Expected: AttributeErrors on missing methods.

- [ ] **Step 3: Add methods** to `lib/libib_client.py`:

```python
    def create_patron(
        self,
        *,
        first_name: str,
        last_name: str,
        email: str,
        patron_id: str,
    ) -> Patron:
        params = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "patron_id": patron_id,
        }
        resp = self.session.post(
            f"{API_BASE}/patrons",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return self._patron_from_dict(resp.json())

    def freeze_patron(self, *, email: str) -> Patron:
        resp = self.session.post(
            f"{API_BASE}/patrons/{email}",
            params={"freeze": 1},
            timeout=30,
        )
        resp.raise_for_status()
        return self._patron_from_dict(resp.json())

    def update_patron(
        self,
        *,
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
        new_email: str | None = None,
        patron_id: str | None = None,
    ) -> Patron:
        """Update fields on a patron, looked up by their current email."""
        params: dict[str, str] = {}
        if first_name is not None:
            params["first_name"] = first_name
        if last_name is not None:
            params["last_name"] = last_name
        if new_email is not None:
            params["email"] = new_email
        if patron_id is not None:
            params["patron_id"] = patron_id
        if not params:
            raise ValueError("update_patron requires at least one field")

        resp = self.session.post(
            f"{API_BASE}/patrons/{email}",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return self._patron_from_dict(resp.json())

    @staticmethod
    def _patron_from_dict(row: dict) -> Patron:
        return Patron(
            patron_id=str(row.get("patron_id", "")),
            first_name=row.get("first_name") or "",
            last_name=row.get("last_name") or "",
            email=row.get("email") or "",
            barcode=row.get("barcode"),
            is_frozen=bool(row.get("freeze", 0)),
        )
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_libib_client.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/libib_client.py tests/test_libib_client.py
git commit -m "feat(libib_client): add create_patron, freeze_patron, update_patron"
```

---

## Phase 3: state.py + execute.py + run.py

State persistence (pending.json + sync_log) and the main run loop.

### Task 3.1: state.py — load/save pending.json

**Files:**
- Create: `lib/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write failing tests**

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lib.state import load_pending, save_pending
from lib.types import PendingChange


@pytest.fixture
def tmp_state_dir(tmp_path):
    return tmp_path


def test_load_pending_missing_file_returns_empty(tmp_state_dir):
    assert load_pending(tmp_state_dir) == []


def test_load_pending_empty_rows_returns_empty(tmp_state_dir):
    (tmp_state_dir / "pending.json").write_text(
        '{"version": 1, "updated_at": null, "rows": []}'
    )
    assert load_pending(tmp_state_dir) == []


def test_load_pending_round_trips_a_row(tmp_state_dir):
    (tmp_state_dir / "pending.json").write_text(json.dumps({
        "version": 1,
        "updated_at": "2026-05-06T18:30:00+00:00",
        "rows": [{
            "person_id": "pco-1",
            "action_type": "CREATE_PATRON",
            "target": {"email": "x@y", "first_name": "Ana", "last_name": "S", "patron_id": "pco-1"},
            "detected_at": "2026-05-06T14:00:00+00:00",
            "attempts": 0,
            "last_attempt_at": None,
            "status": "pending",
        }],
    }))
    rows = load_pending(tmp_state_dir)
    assert len(rows) == 1
    assert rows[0].person_id == "pco-1"
    assert rows[0].detected_at == datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)


def test_save_pending_writes_valid_json(tmp_state_dir):
    row = PendingChange(
        person_id="pco-1",
        action_type="CREATE_PATRON",
        target={"email": "x@y"},
        detected_at=datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc),
        attempts=1,
        last_attempt_at=datetime(2026, 5, 6, 15, 0, tzinfo=timezone.utc),
        status="pending",
    )
    save_pending(tmp_state_dir, [row], now=datetime(2026, 5, 6, 18, 0, tzinfo=timezone.utc))
    data = json.loads((tmp_state_dir / "pending.json").read_text())
    assert data["version"] == 1
    assert data["updated_at"] == "2026-05-06T18:00:00+00:00"
    assert len(data["rows"]) == 1
    assert data["rows"][0]["attempts"] == 1


def test_save_then_load_round_trip(tmp_state_dir):
    rows_in = [
        PendingChange(
            person_id="pco-1",
            action_type="CREATE_PATRON",
            target={"email": "a@b"},
            detected_at=datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc),
            attempts=0,
            last_attempt_at=None,
            status="pending",
        ),
    ]
    save_pending(tmp_state_dir, rows_in, now=datetime(2026, 5, 6, 18, 0, tzinfo=timezone.utc))
    rows_out = load_pending(tmp_state_dir)
    assert rows_out == rows_in
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_state.py -v`
Expected: ImportError on `lib.state`.

- [ ] **Step 3: Implement `lib/state.py`** (load/save only — log functions added in next task)

```python
"""Persistence for pending.json and sync_log/*.jsonl files.

Read/write to a state directory (typically `state/` at repo root). All
timestamps stored as ISO 8601 with timezone offsets.
"""
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from lib.types import PendingChange

PENDING_VERSION = 1


def load_pending(state_dir: Path) -> list[PendingChange]:
    """Read pending.json. Returns empty list if file is missing."""
    pending_file = Path(state_dir) / "pending.json"
    if not pending_file.exists():
        return []
    data = json.loads(pending_file.read_text())
    return [_pending_from_dict(row) for row in data.get("rows", [])]


def save_pending(
    state_dir: Path,
    rows: list[PendingChange],
    *,
    now: datetime,
) -> None:
    """Write pending.json. Overwrites the file."""
    pending_file = Path(state_dir) / "pending.json"
    pending_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": PENDING_VERSION,
        "updated_at": now.isoformat(),
        "rows": [_pending_to_dict(row) for row in rows],
    }
    pending_file.write_text(json.dumps(payload, indent=2))


def _pending_to_dict(row: PendingChange) -> dict:
    d = asdict(row)
    d["detected_at"] = row.detected_at.isoformat()
    d["last_attempt_at"] = (
        row.last_attempt_at.isoformat() if row.last_attempt_at else None
    )
    return d


def _pending_from_dict(d: dict) -> PendingChange:
    return PendingChange(
        person_id=d["person_id"],
        action_type=d["action_type"],
        target=d["target"],
        detected_at=datetime.fromisoformat(d["detected_at"]),
        attempts=d.get("attempts", 0),
        last_attempt_at=(
            datetime.fromisoformat(d["last_attempt_at"])
            if d.get("last_attempt_at")
            else None
        ),
        status=d.get("status", "pending"),
    )
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_state.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/state.py tests/test_state.py
git commit -m "feat(state): load_pending and save_pending for pending.json"
```

### Task 3.2: state.py — append_log

- [ ] **Step 1: Add tests** to `tests/test_state.py`:

```python
from lib.state import append_log


def test_append_log_creates_file_for_month(tmp_state_dir):
    ts = datetime(2026, 5, 6, 18, 30, tzinfo=timezone.utc)
    append_log(tmp_state_dir, ts, {"person_id": "1", "action": "CREATE_PATRON", "success": True})
    log_file = tmp_state_dir / "sync_log" / "2026-05.jsonl"
    assert log_file.exists()
    line = log_file.read_text().strip()
    obj = json.loads(line)
    assert obj["person_id"] == "1"
    assert obj["action"] == "CREATE_PATRON"
    assert obj["ts"] == ts.isoformat()


def test_append_log_appends_to_existing(tmp_state_dir):
    ts = datetime(2026, 5, 6, 18, 30, tzinfo=timezone.utc)
    append_log(tmp_state_dir, ts, {"event": "first"})
    append_log(tmp_state_dir, ts, {"event": "second"})
    log_file = tmp_state_dir / "sync_log" / "2026-05.jsonl"
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "first"
    assert json.loads(lines[1])["event"] == "second"


def test_append_log_separate_file_per_month(tmp_state_dir):
    append_log(tmp_state_dir, datetime(2026, 5, 6, tzinfo=timezone.utc), {"x": 1})
    append_log(tmp_state_dir, datetime(2026, 6, 1, tzinfo=timezone.utc), {"x": 2})
    assert (tmp_state_dir / "sync_log" / "2026-05.jsonl").exists()
    assert (tmp_state_dir / "sync_log" / "2026-06.jsonl").exists()
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_state.py -v`
Expected: 3 ImportError failures.

- [ ] **Step 3: Add `append_log` function** to `lib/state.py`:

```python
def append_log(state_dir: Path, ts: datetime, entry: dict) -> None:
    """Append a JSON entry (one line) to the monthly sync_log file.

    Adds `ts` field automatically.
    """
    month_key = ts.strftime("%Y-%m")
    log_file = Path(state_dir) / "sync_log" / f"{month_key}.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": ts.isoformat(), **entry}
    with log_file.open("a") as f:
        f.write(json.dumps(record) + "\n")
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_state.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/state.py tests/test_state.py
git commit -m "feat(state): append_log to monthly sync_log/YYYY-MM.jsonl"
```

### Task 3.3: config.py — env var loading

**Files:**
- Create: `lib/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Failing tests**

```python
import pytest

from lib.config import Config, load_config


def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("PCO_APP_ID", "app1")
    monkeypatch.setenv("PCO_SECRET", "sec1")
    monkeypatch.setenv("LIBIB_API_KEY", "lkey")
    monkeypatch.setenv("LIBIB_API_USER", "luser")
    monkeypatch.setenv("RESEND_API_KEY", "re_xxx")
    monkeypatch.setenv("EMAIL_FROM", "MVBC <a@b>")
    monkeypatch.setenv("LIBIB_LOGIN_URL", "https://x")

    cfg = load_config()
    assert cfg.pco_app_id == "app1"
    assert cfg.libib_api_key == "lkey"
    assert cfg.email_from == "MVBC <a@b>"
    assert cfg.stability_hours == 24.0  # default
    assert cfg.baseline_mode is False  # default
    assert cfg.email_backend == "resend"  # default


def test_stability_hours_parses_float(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("STABILITY_HOURS", "0.05")
    cfg = load_config()
    assert cfg.stability_hours == 0.05


def test_baseline_mode_parses_truthy(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("BASELINE_MODE", "true")
    assert load_config().baseline_mode is True
    monkeypatch.setenv("BASELINE_MODE", "True")
    assert load_config().baseline_mode is True
    monkeypatch.setenv("BASELINE_MODE", "1")
    assert load_config().baseline_mode is True
    monkeypatch.setenv("BASELINE_MODE", "false")
    assert load_config().baseline_mode is False


def test_missing_required_env_raises(monkeypatch):
    monkeypatch.delenv("PCO_APP_ID", raising=False)
    with pytest.raises(RuntimeError, match="PCO_APP_ID"):
        load_config()


def _set_required(monkeypatch):
    for k in ["PCO_APP_ID", "PCO_SECRET", "LIBIB_API_KEY", "LIBIB_API_USER",
              "RESEND_API_KEY", "EMAIL_FROM", "LIBIB_LOGIN_URL"]:
        monkeypatch.setenv(k, "x")
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_config.py -v`
Expected: ImportError on `lib.config`.

- [ ] **Step 3: Implement `lib/config.py`**

```python
"""Configuration loaded from environment variables.

For local dev, python-dotenv loads .env automatically when imported.
For GitHub Actions, env vars are set by the workflow from secrets.
"""
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv may not be installed in CI for unit tests
    pass


REQUIRED = [
    "PCO_APP_ID",
    "PCO_SECRET",
    "LIBIB_API_KEY",
    "LIBIB_API_USER",
    "RESEND_API_KEY",
    "EMAIL_FROM",
    "LIBIB_LOGIN_URL",
]


@dataclass(frozen=True)
class Config:
    pco_app_id: str
    pco_secret: str
    libib_api_key: str
    libib_api_user: str
    resend_api_key: str
    email_from: str
    email_reply_to: str | None
    email_backend: str
    libib_login_url: str
    stability_hours: float
    baseline_mode: bool


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> Config:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing required env vars: {', '.join(missing)}. "
            f"For local dev, copy .env.example to .env and fill in values."
        )
    return Config(
        pco_app_id=os.environ["PCO_APP_ID"],
        pco_secret=os.environ["PCO_SECRET"],
        libib_api_key=os.environ["LIBIB_API_KEY"],
        libib_api_user=os.environ["LIBIB_API_USER"],
        resend_api_key=os.environ["RESEND_API_KEY"],
        email_from=os.environ["EMAIL_FROM"],
        email_reply_to=os.environ.get("EMAIL_REPLY_TO") or None,
        email_backend=os.environ.get("EMAIL_BACKEND", "resend"),
        libib_login_url=os.environ["LIBIB_LOGIN_URL"],
        stability_hours=float(os.environ.get("STABILITY_HOURS", "24")),
        baseline_mode=_truthy(os.environ.get("BASELINE_MODE")),
    )
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/config.py tests/test_config.py
git commit -m "feat(config): load_config from env with sensible defaults"
```

### Task 3.4: execute.py — dispatch actions to Libib

This module receives mature actions and the LibibClient (and later EmailSender + CardGenerator) and executes each action against Libib. Returns success/failure per action.

**Files:**
- Create: `lib/execute.py`
- Create: `tests/test_execute.py`

- [ ] **Step 1: Failing tests**

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from lib.execute import ExecutionResult, execute_action
from lib.types import PendingChange


def make_pending(action_type, target, status="pending", attempts=0):
    return PendingChange(
        person_id="pco-1",
        action_type=action_type,
        target=target,
        detected_at=datetime(2026, 5, 6, 12, tzinfo=timezone.utc),
        attempts=attempts,
        last_attempt_at=None,
        status=status,
    )


def test_create_patron_calls_libib_create_and_returns_success():
    libib = MagicMock()
    fake_patron = MagicMock(barcode="BC-NEW")
    libib.create_patron.return_value = fake_patron

    pending = make_pending("CREATE_PATRON", {
        "first_name": "Ana", "last_name": "Smith",
        "email": "ana@example.com", "patron_id": "pco-1",
    })
    result = execute_action(pending, libib=libib, sender=None, card_generator=None)

    libib.create_patron.assert_called_once_with(
        first_name="Ana", last_name="Smith",
        email="ana@example.com", patron_id="pco-1",
    )
    assert result.success is True
    assert result.libib_status == 201
    assert result.created_patron is fake_patron


def test_freeze_patron_calls_libib_freeze():
    libib = MagicMock()
    libib.freeze_patron.return_value = MagicMock()
    pending = make_pending("FREEZE_PATRON", {"email": "ana@example.com"})
    result = execute_action(pending, libib=libib, sender=None, card_generator=None)
    libib.freeze_patron.assert_called_once_with(email="ana@example.com")
    assert result.success


def test_update_first_name_calls_libib_update():
    libib = MagicMock()
    libib.update_patron.return_value = MagicMock()
    pending = make_pending("UPDATE_FIRST_NAME", {"first_name": "Anna", "email": "ana@x"})
    execute_action(pending, libib=libib, sender=None, card_generator=None)
    libib.update_patron.assert_called_once_with(email="ana@x", first_name="Anna")


def test_update_email_calls_libib_with_old_email_and_new_email():
    libib = MagicMock()
    libib.update_patron.return_value = MagicMock()
    pending = make_pending("UPDATE_EMAIL", {"old_email": "old@x", "email": "new@x"})
    execute_action(pending, libib=libib, sender=None, card_generator=None)
    libib.update_patron.assert_called_once_with(email="old@x", new_email="new@x")


def test_libib_failure_returns_failure_result():
    import requests
    libib = MagicMock()
    libib.create_patron.side_effect = requests.HTTPError("500", response=MagicMock(status_code=500, text="oops"))
    pending = make_pending("CREATE_PATRON", {
        "first_name": "Ana", "last_name": "Smith",
        "email": "x@y", "patron_id": "pco-1",
    })
    result = execute_action(pending, libib=libib, sender=None, card_generator=None)
    assert result.success is False
    assert result.libib_status == 500
    assert "oops" in (result.libib_error or "")
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_execute.py -v`
Expected: ImportError on `lib.execute`.

- [ ] **Step 3: Implement `lib/execute.py`** (welcome email integration comes in Phase 4)

```python
"""Dispatch a mature pending action to Libib (and email, in Phase 4).

This module is the bridge from pure decision logic to live API calls.
All side effects pass through here. Returns an ExecutionResult per action;
the caller updates pending state and writes the audit log entry.
"""
from dataclasses import dataclass
from typing import Any, Optional

import requests

from lib.types import PendingChange


@dataclass
class ExecutionResult:
    success: bool
    libib_status: Optional[int] = None
    libib_error: Optional[str] = None
    created_patron: Optional[Any] = None  # the Patron returned by create
    email_sent: bool = False
    email_error: Optional[str] = None


def execute_action(
    pending: PendingChange,
    *,
    libib,           # LibibClient — typed loose so tests can MagicMock
    sender,          # EmailSender or None (Phase 4)
    card_generator,  # CardGenerator or None (Phase 4)
) -> ExecutionResult:
    try:
        if pending.action_type == "CREATE_PATRON":
            patron = libib.create_patron(
                first_name=pending.target["first_name"],
                last_name=pending.target["last_name"],
                email=pending.target["email"],
                patron_id=pending.target["patron_id"],
            )
            return ExecutionResult(success=True, libib_status=201, created_patron=patron)

        elif pending.action_type == "FREEZE_PATRON":
            libib.freeze_patron(email=pending.target["email"])
            return ExecutionResult(success=True, libib_status=200)

        elif pending.action_type == "UPDATE_FIRST_NAME":
            libib.update_patron(
                email=pending.target["email"],
                first_name=pending.target["first_name"],
            )
            return ExecutionResult(success=True, libib_status=200)

        elif pending.action_type == "UPDATE_LAST_NAME":
            libib.update_patron(
                email=pending.target["email"],
                last_name=pending.target["last_name"],
            )
            return ExecutionResult(success=True, libib_status=200)

        elif pending.action_type == "UPDATE_EMAIL":
            libib.update_patron(
                email=pending.target["old_email"],
                new_email=pending.target["email"],
            )
            return ExecutionResult(success=True, libib_status=200)

        else:
            return ExecutionResult(
                success=False,
                libib_error=f"unknown action_type {pending.action_type}",
            )

    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None) if e.response is not None else None
        body = getattr(e.response, "text", str(e))[:1000] if e.response is not None else str(e)
        return ExecutionResult(success=False, libib_status=status, libib_error=body)
    except Exception as e:
        return ExecutionResult(success=False, libib_error=f"{type(e).__name__}: {e}"[:1000])
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_execute.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/execute.py tests/test_execute.py
git commit -m "feat(execute): dispatch pending actions to LibibClient"
```

### Task 3.5: run.py — wire it together (no email yet)

The main entrypoint. Pulls live PCO + Libib data, computes desired actions, reconciles, executes mature ones, persists state, logs.

- [ ] **Step 1: Failing test** — Create `tests/test_run.py`:

```python
"""Smoke-test that run.main() walks the pipeline correctly with mocks."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from lib.types import Person, Patron


def test_main_creates_pending_for_new_member(tmp_path, monkeypatch):
    # Mock env
    for k, v in {
        "PCO_APP_ID": "x", "PCO_SECRET": "x",
        "LIBIB_API_KEY": "x", "LIBIB_API_USER": "x",
        "RESEND_API_KEY": "x", "EMAIL_FROM": "x",
        "LIBIB_LOGIN_URL": "https://x",
        "STABILITY_HOURS": "24",
    }.items():
        monkeypatch.setenv(k, v)

    person = Person(
        id="pco-1", remote_id=None, first_name="Ana", last_name="Smith",
        email="ana@example.com", membership="Member", is_destroyed=False,
    )
    fake_pco = MagicMock()
    fake_pco.list_all_people.return_value = iter([person])
    fake_libib = MagicMock()
    fake_libib.list_all_patrons.return_value = iter([])

    fixed_now = datetime(2026, 5, 6, 12, tzinfo=timezone.utc)

    import run
    with patch.object(run, "PCOClient", return_value=fake_pco), \
         patch.object(run, "LibibClient", return_value=fake_libib), \
         patch.object(run, "_now", return_value=fixed_now):
        run.main(state_dir=tmp_path)

    # No mature actions yet (just-detected) — so pending should hold one row
    import json
    data = json.loads((tmp_path / "pending.json").read_text())
    assert len(data["rows"]) == 1
    assert data["rows"][0]["person_id"] == "pco-1"
    assert data["rows"][0]["action_type"] == "CREATE_PATRON"
    fake_libib.create_patron.assert_not_called()
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_run.py -v`
Expected: ImportError on `run` (module doesn't exist) or AttributeError.

- [ ] **Step 3: Implement `run.py`**

```python
"""Entry point for the live PCO ↔ Libib sync.

Invoked every 15 minutes by GitHub Actions. Reads the current state of PCO
and Libib, reconciles against pending changes, executes mature ones, and
writes back state.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from lib.config import load_config
from lib.decide import compute_desired_actions, find_orphan_patrons
from lib.execute import execute_action
from lib.libib_client import LibibClient
from lib.pco_client import PCOClient
from lib.reconcile import reconcile
from lib.state import append_log, load_pending, save_pending


def _now() -> datetime:
    return datetime.now(timezone.utc)


def main(*, state_dir: Path = Path("state"), dry_run: bool = False) -> int:
    cfg = load_config()
    now = _now()

    print(f"[{now.isoformat()}] starting sync (baseline_mode={cfg.baseline_mode}, dry_run={dry_run})")

    pco = PCOClient(app_id=cfg.pco_app_id, secret=cfg.pco_secret)
    libib = LibibClient(api_key=cfg.libib_api_key, api_user=cfg.libib_api_user)

    people = list(pco.list_all_people())
    patrons = list(libib.list_all_patrons())
    print(f"  fetched: {len(people)} PCO people, {len(patrons)} Libib patrons")

    desired = compute_desired_actions(people, patrons)
    pending = load_pending(state_dir)
    new_pending, mature = reconcile(
        desired, pending,
        now=now,
        stability_hours=cfg.stability_hours,
        baseline_mode=cfg.baseline_mode,
    )
    print(f"  desired={len(desired)}  pending_after={len(new_pending)}  mature={len(mature)}")

    orphans = find_orphan_patrons(people, patrons)
    for orphan in orphans:
        append_log(state_dir, now, {
            "action": "ORPHAN_DETECTED",
            "patron_id": orphan.patron_id,
            "email": orphan.email,
        })
    if orphans:
        print(f"  orphans={len(orphans)} (logged)")

    if dry_run:
        print("  --dry-run: skipping execution")
        for action in mature:
            print(f"    would execute: {action.action_type} for {action.person_id}")
        return 0

    # Execute mature actions
    final_pending: list = []
    for row in new_pending:
        if row in mature:
            result = execute_action(row, libib=libib, sender=None, card_generator=None)
            append_log(state_dir, now, {
                "person_id": row.person_id,
                "action": row.action_type,
                "success": result.success,
                "libib_status": result.libib_status,
                "libib_error": result.libib_error,
                "attempts": row.attempts + 1,
            })
            if result.success:
                # Drop from pending — done
                continue
            else:
                # Increment attempts; mark failed if attempts >=3
                attempts = row.attempts + 1
                status = "failed" if attempts >= 3 else row.status
                final_pending.append(replace(
                    row, attempts=attempts, last_attempt_at=now, status=status,
                ))
        else:
            final_pending.append(row)

    save_pending(state_dir, final_pending, now=now)
    print(f"[{_now().isoformat()}] done")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without executing")
    parser.add_argument("--state-dir", default="state",
                        help="Path to state directory")
    args = parser.parse_args()
    sys.exit(main(state_dir=Path(args.state_dir), dry_run=args.dry_run))
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_run.py -v`
Expected: 1 passed.

- [ ] **Step 5: Run all tests**

Run: `pytest -v`
Expected: many passed (60+).

- [ ] **Step 6: Commit**

```bash
git add run.py tests/test_run.py
git commit -m "feat(run): wire pco_client + libib_client + reconcile + execute"
```

### Task 3.6: --dry-run smoke test against real APIs (manual)

Now that everything's wired, do a sanity-check run against your real PCO and Libib environments.

- [ ] **Step 1: Fill in `.env`** with real PCO and Libib credentials.
- [ ] **Step 2: Run** `python run.py --dry-run`
- [ ] **Step 3: Verify output** shows: number of PCO people fetched, number of Libib patrons fetched, count of desired actions. The action plan should be plausible (e.g., "would execute: CREATE_PATRON for pco-XYZ" only for new members not in Libib).
- [ ] **Step 4: If you see surprises** (e.g., 200 unexpected CREATE_PATRON actions), STOP. The cause is likely that the Phase 5 patron_id migration hasn't happened yet — the live sync expects post-migration state. Either run Phase 5 first or manually verify which patron_ids are still CCB IDs vs PCO IDs.
- [ ] **Step 5: No commit needed** — this task is verification only.

---

## Phase 4: Card generation, email sending, integration

Library card image + Resend-backed welcome email + wiring into execute.py.

### Task 4.1: card.py — generate library card PNG with Pillow + qrcode

**Files:**
- Create: `lib/card.py`
- Create: `tests/test_card.py`

- [ ] **Step 1: Failing smoke test**

```python
import io

from PIL import Image

from lib.card import generate_card_png


def test_generate_card_returns_valid_png_bytes():
    png_bytes = generate_card_png(
        first_name="Ana",
        last_name="Smith",
        email="ana@example.com",
        barcode="BC-12345",
    )
    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 0
    # Validate it's a real PNG by opening
    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG"
    # Sanity dimensions
    assert img.size[0] >= 400  # width
    assert img.size[1] >= 200  # height


def test_generate_card_with_long_name_does_not_crash():
    png_bytes = generate_card_png(
        first_name="VeryLongFirstNameIndeed",
        last_name="EquallyLongLastNameForReal",
        email="this-is-an-extremely-long-email-address@example.com",
        barcode="BC-12345-67890",
    )
    Image.open(io.BytesIO(png_bytes))  # parses OK
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_card.py -v`
Expected: ImportError on `lib.card`.

- [ ] **Step 3: Implement `lib/card.py`**

```python
"""Library card image generator.

Produces a PNG with the patron's name, email, barcode text, and a QR code
encoding the barcode. Pure Pillow + qrcode — no headless browser, no CDN.

The visual design here is intentionally simple. Iterate on this template
during Phase 4 in collaboration with the user.
"""
from __future__ import annotations

import io

import qrcode
from PIL import Image, ImageDraw, ImageFont


CARD_WIDTH = 800
CARD_HEIGHT = 480
PADDING = 30
HEADER_HEIGHT = 80

BG_COLOR = (248, 249, 250)
HEADER_BG = (10, 28, 50)
HEADER_FG = (255, 255, 255)
BODY_FG = (32, 32, 32)
LABEL_FG = (100, 100, 100)


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try a few common system fonts; fall back to PIL's default."""
    candidates = (
        ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def generate_card_png(
    *,
    first_name: str,
    last_name: str,
    email: str,
    barcode: str,
) -> bytes:
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Header bar
    draw.rectangle([(0, 0), (CARD_WIDTH, HEADER_HEIGHT)], fill=HEADER_BG)
    header_font = _load_font(36, bold=True)
    draw.text((PADDING, 20), "MVBC Library", fill=HEADER_FG, font=header_font)

    # QR code on the right
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(barcode)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=HEADER_BG, back_color=BG_COLOR).convert("RGB")
    qr_size = CARD_HEIGHT - HEADER_HEIGHT - PADDING * 2
    qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
    img.paste(qr_img, (CARD_WIDTH - qr_size - PADDING, HEADER_HEIGHT + PADDING))

    # Patron text rows on the left
    label_font = _load_font(18)
    value_font = _load_font(28, bold=True)
    small_font = _load_font(20)

    left_x = PADDING
    y = HEADER_HEIGHT + PADDING

    full_name = f"{first_name} {last_name}".strip()
    draw.text((left_x, y), "NAME", fill=LABEL_FG, font=label_font)
    draw.text((left_x, y + 22), full_name, fill=BODY_FG, font=value_font)

    y += 90
    draw.text((left_x, y), "EMAIL", fill=LABEL_FG, font=label_font)
    draw.text((left_x, y + 22), email, fill=BODY_FG, font=small_font)

    y += 80
    draw.text((left_x, y), "BARCODE", fill=LABEL_FG, font=label_font)
    draw.text((left_x, y + 22), barcode, fill=BODY_FG, font=small_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_card.py -v`
Expected: 2 passed.

- [ ] **Step 5: Manual visual check**

Run a quick script in a Python REPL:

```python
from lib.card import generate_card_png
png = generate_card_png(first_name="Ana", last_name="Smith", email="ana@example.com", barcode="BC-12345")
open("preview-card.png", "wb").write(png)
```

Open `preview-card.png` and review. Iterate on the visual design (font sizes, colors, layout) with the user. **Delete `preview-card.png` before committing** (don't commit binary debug artifacts).

- [ ] **Step 6: Commit**

```bash
git add lib/card.py tests/test_card.py
git commit -m "feat(card): generate library card PNG with Pillow and qrcode"
```

### Task 4.2: sender.py — Sender protocol + ResendSender

**Files:**
- Create: `lib/sender.py`
- Create: `tests/test_sender.py`

- [ ] **Step 1: Failing tests**

```python
from unittest.mock import MagicMock, patch

import pytest

from lib.sender import ResendSender


def test_resend_sender_sends_with_attachment():
    sender = ResendSender(api_key="re_test", default_from="MVBC <a@b>")
    with patch("lib.sender.resend") as fake_resend:
        fake_resend.Emails.send.return_value = {"id": "msg-1"}
        result = sender.send(
            to="ana@example.com",
            subject="Welcome",
            body_html="<p>Hi</p>",
            body_text="Hi",
            attachment_bytes=b"\x89PNG...",
            attachment_filename="card.png",
            attachment_content_type="image/png",
        )
        assert result["id"] == "msg-1"
        call_kwargs = fake_resend.Emails.send.call_args[0][0]
        assert call_kwargs["from"] == "MVBC <a@b>"
        assert call_kwargs["to"] == ["ana@example.com"]
        assert call_kwargs["subject"] == "Welcome"
        assert "<p>Hi</p>" in call_kwargs["html"]
        assert call_kwargs["text"] == "Hi"
        assert len(call_kwargs["attachments"]) == 1
        assert call_kwargs["attachments"][0]["filename"] == "card.png"


def test_resend_sender_without_attachment():
    sender = ResendSender(api_key="re_test", default_from="MVBC <a@b>")
    with patch("lib.sender.resend") as fake_resend:
        fake_resend.Emails.send.return_value = {"id": "msg-2"}
        sender.send(
            to="ana@example.com",
            subject="Hi",
            body_html="<p>Hi</p>",
            body_text="Hi",
        )
        call_kwargs = fake_resend.Emails.send.call_args[0][0]
        assert "attachments" not in call_kwargs or call_kwargs["attachments"] == []


def test_resend_sender_includes_reply_to_when_set():
    sender = ResendSender(api_key="re_test", default_from="MVBC <a@b>", reply_to="alex@church.org")
    with patch("lib.sender.resend") as fake_resend:
        fake_resend.Emails.send.return_value = {"id": "x"}
        sender.send(to="x@y", subject="s", body_html="h", body_text="t")
        kwargs = fake_resend.Emails.send.call_args[0][0]
        assert kwargs["reply_to"] == ["alex@church.org"]
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_sender.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `lib/sender.py`**

```python
"""Email sending — Sender protocol + ResendSender implementation.

The protocol exists so we can swap in a MicrosoftGraphSender later when
library@mvbchurch.org becomes a real mailbox. No code change needed in
execute.py; just a different config value.
"""
from __future__ import annotations

import base64
from typing import Optional, Protocol

import resend


class EmailSender(Protocol):
    def send(
        self,
        *,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
        attachment_bytes: Optional[bytes] = None,
        attachment_filename: Optional[str] = None,
        attachment_content_type: Optional[str] = None,
    ) -> dict: ...


class ResendSender:
    def __init__(self, api_key: str, default_from: str, reply_to: Optional[str] = None):
        resend.api_key = api_key
        self.default_from = default_from
        self.reply_to = reply_to

    def send(
        self,
        *,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
        attachment_bytes: Optional[bytes] = None,
        attachment_filename: Optional[str] = None,
        attachment_content_type: Optional[str] = None,
    ) -> dict:
        params: dict = {
            "from": self.default_from,
            "to": [to],
            "subject": subject,
            "html": body_html,
            "text": body_text,
        }
        if self.reply_to:
            params["reply_to"] = [self.reply_to]
        if attachment_bytes is not None:
            params["attachments"] = [{
                "filename": attachment_filename or "attachment.bin",
                "content": base64.b64encode(attachment_bytes).decode("ascii"),
                "content_type": attachment_content_type or "application/octet-stream",
            }]
        return resend.Emails.send(params)
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_sender.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/sender.py tests/test_sender.py
git commit -m "feat(sender): ResendSender with attachment support"
```

### Task 4.3: Welcome email rendering

A small helper that takes the HTML template and patron data and produces the rendered HTML + plaintext. The template is already at `templates/welcome.html`.

**Files:**
- Modify: `lib/sender.py` (add `render_welcome_email` function)
- Modify: `tests/test_sender.py`
- Create: `templates/welcome.txt` (plaintext alternative)

- [ ] **Step 1: Create the plaintext alternative** at `templates/welcome.txt`:

```
{first_name},

Your MVBC Library account is ready. Come and browse our titles and try our self-checkout kiosk:

  1. On the iPad, scan the barcode of every book you want to checkout.
     (The camera is on the back side of the iPad.)
  2. Tap the 'Checkout' button.
  3. Enter your email address ({email}) or, scan your library card (attached) and tap 'OK'.

Once you checkout your books, you have 3 weeks to return them. For return, just drop them into one of the boxes found by the kiosk.

The full catalog of our titles is available at https://www.libib.com/u/mvbchurch . Every book has been tagged in the system to tell you what section to find it at. You can use that same website for self-renewal — see instructions at https://mvbchurch.org/files/Checkout%20Renewal.pdf .

Our library is located next to the Fellowship Hall and contains 1500+ titles.

Let me know if you have any questions.

Regards,

Alex Basurto
MVBC Library Coordinator
```

- [ ] **Step 2: Add tests** to `tests/test_sender.py`:

```python
from pathlib import Path

from lib.sender import render_welcome_email


def test_render_welcome_email_substitutes_placeholders():
    html, text = render_welcome_email(
        first_name="Ana",
        email="ana@example.com",
        templates_dir=Path("templates"),
    )
    assert "Ana," in html
    assert "ana@example.com" in html
    assert "Ana," in text
    assert "ana@example.com" in text


def test_render_welcome_email_does_not_double_substitute():
    # If the template already has the literal "{email}" rendered as user data,
    # we don't want to substitute again. (Defensive; not strictly needed.)
    html, text = render_welcome_email(
        first_name="Bob",
        email="b@x",
        templates_dir=Path("templates"),
    )
    # Just sanity: nothing remaining as a placeholder
    assert "{first_name}" not in html
    assert "{email}" not in html
```

- [ ] **Step 3: Run, watch fail**

Run: `pytest tests/test_sender.py -v`
Expected: ImportError on `render_welcome_email`.

- [ ] **Step 4: Add the function** to `lib/sender.py`:

```python
from pathlib import Path


def render_welcome_email(
    *,
    first_name: str,
    email: str,
    templates_dir: Path,
) -> tuple[str, str]:
    """Read templates/welcome.html and welcome.txt and substitute placeholders.

    Returns (html, text). Uses str.format() with the only placeholders
    being {first_name} and {email}. Any other braces in the templates
    must be doubled to escape (e.g. CSS `{{ ... }}` if used) — but the
    current welcome.html has no such conflicts.
    """
    html_path = Path(templates_dir) / "welcome.html"
    text_path = Path(templates_dir) / "welcome.txt"

    html = html_path.read_text(encoding="utf-8").format(
        first_name=first_name, email=email,
    )
    text = text_path.read_text(encoding="utf-8").format(
        first_name=first_name, email=email,
    )
    return html, text
```

- [ ] **Step 5: Run, watch pass**

Run: `pytest tests/test_sender.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add lib/sender.py tests/test_sender.py templates/welcome.txt
git commit -m "feat(sender): render_welcome_email reads templates and substitutes placeholders"
```

### Task 4.4: Wire welcome email + card into execute.py for CREATE_PATRON

- [ ] **Step 1: Add tests** to `tests/test_execute.py`:

```python
def test_create_patron_sends_welcome_email_with_card():
    libib = MagicMock()
    fake_patron = MagicMock(barcode="BC-NEW", email="ana@example.com",
                            first_name="Ana", last_name="Smith")
    libib.create_patron.return_value = fake_patron

    sender = MagicMock()
    sender.send.return_value = {"id": "msg-1"}

    card_gen = MagicMock()
    card_gen.return_value = b"\x89PNG_FAKE"

    pending = make_pending("CREATE_PATRON", {
        "first_name": "Ana", "last_name": "Smith",
        "email": "ana@example.com", "patron_id": "pco-1",
    })
    result = execute_action(pending, libib=libib, sender=sender, card_generator=card_gen)

    assert result.success
    assert result.email_sent is True
    sender.send.assert_called_once()
    call_kwargs = sender.send.call_args.kwargs
    assert call_kwargs["to"] == "ana@example.com"
    assert call_kwargs["attachment_bytes"] == b"\x89PNG_FAKE"
    assert call_kwargs["attachment_filename"] == "library-card.png"
    assert call_kwargs["attachment_content_type"] == "image/png"
    card_gen.assert_called_once_with(
        first_name="Ana", last_name="Smith",
        email="ana@example.com", barcode="BC-NEW",
    )


def test_create_patron_libib_succeeds_email_fails_does_not_rollback():
    libib = MagicMock()
    fake_patron = MagicMock(barcode="BC-1", email="ana@x",
                            first_name="Ana", last_name="S")
    libib.create_patron.return_value = fake_patron

    sender = MagicMock()
    sender.send.side_effect = RuntimeError("Resend down")

    pending = make_pending("CREATE_PATRON", {
        "first_name": "Ana", "last_name": "S", "email": "ana@x", "patron_id": "pco-1",
    })
    result = execute_action(pending, libib=libib, sender=sender, card_generator=lambda **k: b"x")

    # Libib was successful; overall result.success is True
    assert result.success is True
    assert result.email_sent is False
    assert "Resend down" in (result.email_error or "")


def test_freeze_does_not_send_email():
    libib = MagicMock()
    libib.freeze_patron.return_value = MagicMock()
    sender = MagicMock()
    pending = make_pending("FREEZE_PATRON", {"email": "ana@x"})
    execute_action(pending, libib=libib, sender=sender, card_generator=None)
    sender.send.assert_not_called()
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_execute.py -v`
Expected: 3 new failures.

- [ ] **Step 3: Update `lib/execute.py`** — modify the `CREATE_PATRON` branch to send the welcome email after Libib succeeds:

```python
        if pending.action_type == "CREATE_PATRON":
            patron = libib.create_patron(
                first_name=pending.target["first_name"],
                last_name=pending.target["last_name"],
                email=pending.target["email"],
                patron_id=pending.target["patron_id"],
            )
            result = ExecutionResult(success=True, libib_status=201, created_patron=patron)
            # Best-effort welcome email + card. Failure does not roll back the patron.
            if sender is not None and card_generator is not None:
                try:
                    card_bytes = card_generator(
                        first_name=patron.first_name,
                        last_name=patron.last_name,
                        email=patron.email,
                        barcode=patron.barcode or "",
                    )
                    from pathlib import Path as _P
                    from lib.sender import render_welcome_email
                    html, text = render_welcome_email(
                        first_name=patron.first_name,
                        email=patron.email,
                        templates_dir=_P("templates"),
                    )
                    sender.send(
                        to=patron.email,
                        subject="Welcome to the MVBC Library",
                        body_html=html,
                        body_text=text,
                        attachment_bytes=card_bytes,
                        attachment_filename="library-card.png",
                        attachment_content_type="image/png",
                    )
                    result.email_sent = True
                except Exception as e:
                    result.email_error = f"{type(e).__name__}: {e}"[:1000]
            return result
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_execute.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/execute.py tests/test_execute.py
git commit -m "feat(execute): send welcome email with card attached on CREATE_PATRON"
```

### Task 4.5: Wire sender + card into run.py

- [ ] **Step 1: Modify `tests/test_run.py`** to assert that, when a CREATE_PATRON matures, the sender is invoked.

Add:

```python
def test_main_executes_mature_create_with_email(tmp_path, monkeypatch):
    # Place a pending row from yesterday so it's mature
    import json
    (tmp_path / "pending.json").write_text(json.dumps({
        "version": 1,
        "updated_at": "2026-05-05T12:00:00+00:00",
        "rows": [{
            "person_id": "pco-1",
            "action_type": "CREATE_PATRON",
            "target": {"first_name": "Ana", "last_name": "Smith",
                       "email": "ana@example.com", "patron_id": "pco-1"},
            "detected_at": "2026-05-05T11:00:00+00:00",
            "attempts": 0,
            "last_attempt_at": None,
            "status": "pending",
        }],
    }))
    for k, v in {
        "PCO_APP_ID": "x", "PCO_SECRET": "x", "LIBIB_API_KEY": "x",
        "LIBIB_API_USER": "x", "RESEND_API_KEY": "re_x",
        "EMAIL_FROM": "MVBC <a@b>", "LIBIB_LOGIN_URL": "https://x",
        "STABILITY_HOURS": "24",
    }.items():
        monkeypatch.setenv(k, v)

    person = Person(id="pco-1", remote_id=None, first_name="Ana", last_name="Smith",
                    email="ana@example.com", membership="Member", is_destroyed=False)
    fake_pco = MagicMock(); fake_pco.list_all_people.return_value = iter([person])
    fake_libib = MagicMock(); fake_libib.list_all_patrons.return_value = iter([])
    fake_patron = MagicMock(barcode="BC-1", email="ana@example.com",
                            first_name="Ana", last_name="Smith")
    fake_libib.create_patron.return_value = fake_patron
    fake_sender = MagicMock(); fake_sender.send.return_value = {"id": "x"}

    fixed_now = datetime(2026, 5, 6, 12, tzinfo=timezone.utc)

    import run
    with patch.object(run, "PCOClient", return_value=fake_pco), \
         patch.object(run, "LibibClient", return_value=fake_libib), \
         patch.object(run, "ResendSender", return_value=fake_sender), \
         patch.object(run, "_now", return_value=fixed_now):
        run.main(state_dir=tmp_path)

    fake_libib.create_patron.assert_called_once()
    fake_sender.send.assert_called_once()
    # Pending should now be empty (success → removed)
    import json
    data = json.loads((tmp_path / "pending.json").read_text())
    assert data["rows"] == []
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_run.py::test_main_executes_mature_create_with_email -v`
Expected: AttributeError on `run.ResendSender` or wrong call counts.

- [ ] **Step 3: Update `run.py`** — import sender + card generator and pass to execute_action:

Add imports:
```python
from lib.card import generate_card_png
from lib.sender import ResendSender
```

In `main()`, before the execute loop, add:
```python
    sender = ResendSender(
        api_key=cfg.resend_api_key,
        default_from=cfg.email_from,
        reply_to=cfg.email_reply_to,
    )
    card_generator = generate_card_png
```

Update the execute call inside the loop:
```python
            result = execute_action(row, libib=libib, sender=sender, card_generator=card_generator)
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_run.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run all tests**

Run: `pytest -v`
Expected: ~80+ passing.

- [ ] **Step 6: Commit**

```bash
git add run.py tests/test_run.py
git commit -m "feat(run): wire ResendSender and card generator into execute"
```

### Task 4.6: Iterate on email copy and card design with the user

This is a collaborative content/design task — not test-driven.

- [ ] **Step 1: Generate a sample card** with realistic patron data, share with the user, gather feedback on layout/colors/fonts.
- [ ] **Step 2: Iterate** on `lib/card.py` — adjust colors, fonts, spacing, or add a logo.
- [ ] **Step 3: Review the welcome email copy** in `templates/welcome.html` and `templates/welcome.txt` with the user. Update copy if desired (e.g., remove "or scan your library card" if the kiosk supports email-only, or update Alex's signature if the role title has changed).
- [ ] **Step 4: Send a real test email to yourself** by calling the sender directly:

```python
# scratch/manual_email_test.py (delete after use)
import os
from pathlib import Path
from dotenv import load_dotenv; load_dotenv()
from lib.card import generate_card_png
from lib.sender import ResendSender, render_welcome_email

card = generate_card_png(first_name="Test", last_name="Patron",
                        email="alejandrobasurto7@gmail.com", barcode="BC-TEST-001")
html, text = render_welcome_email(first_name="Test", email="alejandrobasurto7@gmail.com",
                                  templates_dir=Path("templates"))
sender = ResendSender(api_key=os.environ["RESEND_API_KEY"],
                     default_from=os.environ["EMAIL_FROM"],
                     reply_to=os.environ.get("EMAIL_REPLY_TO"))
sender.send(to="alejandrobasurto7@gmail.com", subject="MVBC Library — preview",
            body_html=html, body_text=text,
            attachment_bytes=card, attachment_filename="library-card.png",
            attachment_content_type="image/png")
```

- [ ] **Step 5: Iterate** until you (and any reviewers) are happy.
- [ ] **Step 6: Delete `scratch/`** before committing — it's not part of the codebase.
- [ ] **Step 7: Commit any final design changes**

```bash
git add lib/card.py templates/welcome.html templates/welcome.txt
git commit -m "feat(email/card): finalize design and copy"
```

---

## Phase 5: One-time patron_id migration script

Migrates Libib `patron_id` values from CCB Person IDs to PCO Person IDs (per spec §16). Standalone, separate from `run.py`. Idempotent. Defaults to dry-run.

### Task 5.1: migrate_patron_ids.py — fetch, plan, dry-run report

**Files:**
- Create: `migrate_patron_ids.py`
- Create: `tests/test_migrate.py`

- [ ] **Step 1: Failing tests**

```python
from unittest.mock import MagicMock

from lib.types import Patron, Person
from migrate_patron_ids import plan_migration, MigrationPlan


def make_person(id, remote_id=None, **kw):
    return Person(id=id, remote_id=remote_id, first_name=kw.get("first_name", "F"),
                  last_name=kw.get("last_name", "L"), email=kw.get("email", "x@y"),
                  membership=kw.get("membership", "Member"), is_destroyed=False)


def make_patron(patron_id, **kw):
    return Patron(patron_id=patron_id, first_name=kw.get("first_name", "F"),
                  last_name=kw.get("last_name", "L"), email=kw.get("email", "x@y"),
                  barcode=kw.get("barcode", "BC"), is_frozen=kw.get("is_frozen", False))


def test_plan_skips_libib_patrons_with_empty_patron_id():
    pco = [make_person(id="pco-1", remote_id="ccb-42")]
    libib = [make_patron(patron_id="")]
    plan = plan_migration(pco, libib)
    assert len(plan.missing_id) == 1
    assert len(plan.to_migrate) == 0


def test_plan_skips_already_migrated_when_patron_id_equals_pco_id():
    pco = [make_person(id="pco-1", remote_id="ccb-42")]
    libib = [make_patron(patron_id="pco-1")]
    plan = plan_migration(pco, libib)
    assert len(plan.already_migrated) == 1
    assert len(plan.to_migrate) == 0


def test_plan_marks_orphans_when_no_pco_match():
    pco = [make_person(id="pco-1", remote_id="ccb-42")]
    libib = [make_patron(patron_id="ccb-99")]  # CCB ID with no PCO counterpart
    plan = plan_migration(pco, libib)
    assert len(plan.orphans) == 1
    assert len(plan.to_migrate) == 0


def test_plan_migrates_when_libib_patron_id_matches_pco_remote_id():
    pco = [make_person(id="pco-1", remote_id="ccb-42")]
    libib = [make_patron(patron_id="ccb-42", email="ana@x")]
    plan = plan_migration(pco, libib)
    assert len(plan.to_migrate) == 1
    assert plan.to_migrate[0].old_patron_id == "ccb-42"
    assert plan.to_migrate[0].new_patron_id == "pco-1"
    assert plan.to_migrate[0].email == "ana@x"


def test_plan_detects_pre_migration_collisions():
    pco = [
        make_person(id="pco-1", remote_id="ccb-42"),
        make_person(id="pco-2", remote_id="ccb-99"),
    ]
    libib = [
        make_patron(patron_id="ccb-42", email="a@x"),
        make_patron(patron_id="ccb-42", email="b@x"),  # duplicate patron_id!
    ]
    plan = plan_migration(pco, libib)
    assert len(plan.pre_collisions) > 0


def test_plan_detects_post_migration_collisions():
    # Two PCO people with different remote_ids but identical pco.id collisions
    # are impossible by construction. The post-collision case is when a planned
    # new patron_id would collide with a non-migrating Libib patron_id.
    pco = [make_person(id="pco-1", remote_id="ccb-42")]
    libib = [
        make_patron(patron_id="ccb-42", email="a@x"),  # planned new id = pco-1
        make_patron(patron_id="pco-1", email="b@x"),    # already pco-1, would collide
    ]
    plan = plan_migration(pco, libib)
    assert len(plan.post_collisions) > 0
```

- [ ] **Step 2: Run, watch fail**

Run: `pytest tests/test_migrate.py -v`
Expected: ImportError on `migrate_patron_ids`.

- [ ] **Step 3: Implement `migrate_patron_ids.py`**

```python
"""One-time migration of Libib patron_id values from CCB IDs to PCO IDs.

Run manually after Phase 4, before deploying the live sync (Phase 6).
The live sync expects every Libib patron's patron_id to equal the
corresponding PCO person's id. This script makes that true.

Usage:
    python migrate_patron_ids.py             # dry-run report (default)
    python migrate_patron_ids.py --apply     # actually perform updates
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from lib.config import load_config
from lib.libib_client import LibibClient
from lib.pco_client import PCOClient
from lib.types import Patron, Person


@dataclass
class MigrationItem:
    old_patron_id: str
    new_patron_id: str
    email: str
    first_name: str
    last_name: str


@dataclass
class MigrationPlan:
    to_migrate: list[MigrationItem] = field(default_factory=list)
    already_migrated: list[Patron] = field(default_factory=list)
    orphans: list[Patron] = field(default_factory=list)
    missing_id: list[Patron] = field(default_factory=list)
    pre_collisions: list[tuple[str, list[Patron]]] = field(default_factory=list)
    post_collisions: list[tuple[str, list[str]]] = field(default_factory=list)


def plan_migration(pco_people: list[Person], libib_patrons: list[Patron]) -> MigrationPlan:
    plan = MigrationPlan()

    # Pre-migration collisions: any duplicate patron_ids in current Libib?
    by_id: dict[str, list[Patron]] = defaultdict(list)
    for p in libib_patrons:
        if p.patron_id:
            by_id[p.patron_id].append(p)
    for pid, group in by_id.items():
        if len(group) > 1:
            plan.pre_collisions.append((pid, group))

    # Map CCB ID → PCO id (only for migrated PCO people with non-empty remote_id)
    ccb_to_pco: dict[str, str] = {
        person.remote_id: person.id
        for person in pco_people
        if person.remote_id
    }
    pco_ids: set[str] = {person.id for person in pco_people}

    # Decide each Libib patron's fate
    for patron in libib_patrons:
        if not patron.patron_id:
            plan.missing_id.append(patron)
            continue
        if patron.patron_id in pco_ids:
            plan.already_migrated.append(patron)
            continue
        if patron.patron_id in ccb_to_pco:
            new_id = ccb_to_pco[patron.patron_id]
            plan.to_migrate.append(MigrationItem(
                old_patron_id=patron.patron_id,
                new_patron_id=new_id,
                email=patron.email,
                first_name=patron.first_name,
                last_name=patron.last_name,
            ))
        else:
            plan.orphans.append(patron)

    # Post-migration collisions: do any planned new ids overlap with existing
    # patron_ids that aren't being migrated?
    planned_new_ids = Counter(item.new_patron_id for item in plan.to_migrate)
    untouched_ids = {p.patron_id for p in plan.already_migrated} | \
                    {p.patron_id for p in plan.orphans} | \
                    {p.patron_id for p in plan.missing_id if p.patron_id}
    for new_id, count in planned_new_ids.items():
        sources = []
        if count > 1:
            sources.append(f"{count}x in to_migrate")
        if new_id in untouched_ids:
            sources.append("non-migrating patron")
        if sources:
            plan.post_collisions.append((new_id, sources))

    return plan


def print_report(plan: MigrationPlan) -> None:
    print(f"  to_migrate:       {len(plan.to_migrate)}")
    print(f"  already_migrated: {len(plan.already_migrated)}")
    print(f"  orphans:          {len(plan.orphans)}")
    print(f"  missing_id:       {len(plan.missing_id)}")
    print(f"  pre_collisions:   {len(plan.pre_collisions)}")
    print(f"  post_collisions:  {len(plan.post_collisions)}")
    if plan.pre_collisions:
        print("\n  PRE-COLLISIONS (duplicate patron_ids in Libib already):")
        for pid, group in plan.pre_collisions:
            print(f"    {pid}: {[p.email for p in group]}")
    if plan.post_collisions:
        print("\n  POST-COLLISIONS (planned new ids would clash):")
        for new_id, sources in plan.post_collisions:
            print(f"    {new_id}: {', '.join(sources)}")
    if plan.orphans:
        print(f"\n  ORPHANS (first 10):")
        for p in plan.orphans[:10]:
            print(f"    patron_id={p.patron_id} email={p.email}")


def apply_migration(libib: LibibClient, plan: MigrationPlan, log_path: Path) -> int:
    """Execute updates one at a time. Halts on first non-2xx response."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    successes = 0
    for item in plan.to_migrate:
        try:
            updated = libib.update_patron(email=item.email, patron_id=item.new_patron_id)
        except Exception as e:
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "old_patron_id": item.old_patron_id,
                "new_patron_id": item.new_patron_id,
                "email": item.email,
                "success": False,
                "error": f"{type(e).__name__}: {e}"[:1000],
            }
            with log_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
            print(f"\n  HALTED on {item.email}: {entry['error']}")
            return successes
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "old_patron_id": item.old_patron_id,
            "new_patron_id": item.new_patron_id,
            "email": item.email,
            "success": True,
            "verified_patron_id": updated.patron_id,
        }
        with log_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        successes += 1
        print(f"  migrated: {item.old_patron_id} → {item.new_patron_id} ({item.email})")
    return successes


def main(*, apply: bool, log_path: Path = Path("migration_log.jsonl")) -> int:
    cfg = load_config()
    pco = PCOClient(app_id=cfg.pco_app_id, secret=cfg.pco_secret)
    libib = LibibClient(api_key=cfg.libib_api_key, api_user=cfg.libib_api_user)

    print("Fetching PCO people...")
    people = list(pco.list_all_people())
    print(f"  {len(people)} people")
    print("Fetching Libib patrons...")
    patrons = list(libib.list_all_patrons())
    print(f"  {len(patrons)} patrons")

    plan = plan_migration(people, patrons)
    print("\n=== MIGRATION PLAN ===")
    print_report(plan)

    if plan.pre_collisions or plan.post_collisions:
        print("\nABORT: collisions present. Resolve before retrying.")
        return 2

    if not apply:
        print("\n(dry-run; pass --apply to execute)")
        return 0

    if not plan.to_migrate:
        print("\nNothing to migrate. Done.")
        return 0

    confirm = input(f"\nApply {len(plan.to_migrate)} updates? Type 'yes' to confirm: ")
    if confirm.strip().lower() != "yes":
        print("Aborted by operator.")
        return 1

    successes = apply_migration(libib, plan, log_path)
    print(f"\nApplied {successes}/{len(plan.to_migrate)} successfully.")
    print(f"Audit log: {log_path}")
    return 0 if successes == len(plan.to_migrate) else 3


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually perform updates (default: dry-run)")
    parser.add_argument("--log-path", default="migration_log.jsonl")
    args = parser.parse_args()
    sys.exit(main(apply=args.apply, log_path=Path(args.log_path)))
```

- [ ] **Step 4: Run, watch pass**

Run: `pytest tests/test_migrate.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add migrate_patron_ids.py tests/test_migrate.py
git commit -m "feat(migrate): one-time patron_id migration script (CCB IDs → PCO IDs)"
```

### Task 5.2: Run the migration in dry-run against live data

- [ ] **Step 1: Run** `python migrate_patron_ids.py` (dry-run is default).
- [ ] **Step 2: Inspect the report.** You should expect, given Alex's stated history (clean CCB→PCO migration, complete remote_id population):
  - `to_migrate`: ≈ the count of pre-existing Libib patrons (this is the bulk of the work)
  - `already_migrated`: 0 if you've never run this before
  - `orphans`: 0 (per Phase 0 / spec assumption)
  - `missing_id`: 0
  - `pre_collisions`: 0
  - `post_collisions`: 0
- [ ] **Step 3: If you see orphans, missing_ids, or collisions, STOP.** Investigate before applying. Each orphan represents a Libib patron with no PCO counterpart — could be data the spec didn't anticipate. Consult with Alex before deciding whether to skip them or create the missing PCO records.
- [ ] **Step 4: If the report is clean, proceed to Task 5.3.**

### Task 5.3: Apply the migration

- [ ] **Step 1: Back up the current Libib roster** by saving the JSON output of `python -c "from lib.config import load_config; from lib.libib_client import LibibClient; cfg = load_config(); import json; c = LibibClient(cfg.libib_api_key, cfg.libib_api_user); print(json.dumps([p.__dict__ for p in c.list_all_patrons()], indent=2))" > pre-migration-libib-snapshot.json`
- [ ] **Step 2: Run** `python migrate_patron_ids.py --apply`
- [ ] **Step 3: Type `yes` at the prompt** to confirm.
- [ ] **Step 4: Watch progress.** Each line shows one successful migration. If any line shows HALTED, the script stops; no further updates are attempted. Investigate before resuming.
- [ ] **Step 5: After completion, re-run dry-run** to verify: `python migrate_patron_ids.py`. Expected: `to_migrate=0`, `already_migrated=N` (the count you just migrated), zero collisions, zero orphans.
- [ ] **Step 6: Save the audit log** `migration_log.jsonl` outside the repo for posterity (it's gitignored by default to avoid accidentally committing PII).

---

## Phase 6: GitHub Actions workflows

Deploy the sync to run on a schedule, plus the CI test workflow.

### Task 6.1: Create the test workflow (CI)

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Create the workflow file**

```yaml
name: tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install deps
        run: pip install -r requirements.txt

      - name: Run unit tests
        run: pytest -v
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci: add GitHub Actions test workflow"
```

- [ ] **Step 3: Push and verify the workflow runs** (do this after Task 6.3 when the repo is on GitHub).

### Task 6.2: Create the sync workflow

**Files:**
- Create: `.github/workflows/sync.yml`

- [ ] **Step 1: Create the workflow file**

```yaml
name: sync

on:
  schedule:
    - cron: "*/15 * * * *"   # every 15 minutes
  workflow_dispatch:           # allow manual trigger from the Actions tab

# Only one sync run at a time
concurrency:
  group: sync-${{ github.ref }}
  cancel-in-progress: false

jobs:
  sync:
    runs-on: ubuntu-latest
    permissions:
      contents: write   # to commit state changes back to the state branch
    steps:
      - name: Checkout main (for code)
        uses: actions/checkout@v4
        with:
          ref: main
          path: code

      - name: Checkout state branch
        uses: actions/checkout@v4
        with:
          ref: state
          path: state-checkout
        continue-on-error: true   # branch may not exist on first run

      - name: Initialize state branch on first run
        run: |
          if [ ! -d "state-checkout/.git" ]; then
            mkdir -p state-checkout
            cd state-checkout
            git init -b state
            git config user.email "actions@users.noreply.github.com"
            git config user.name "github-actions[bot]"
            mkdir -p state state/sync_log
            echo '{"version": 1, "updated_at": null, "rows": []}' > state/pending.json
            touch state/sync_log/.gitkeep
            git add .
            git commit -m "chore: initialize state branch"
            git remote add origin "https://x-access-token:${{ secrets.GITHUB_TOKEN }}@github.com/${{ github.repository }}.git"
            git push -u origin state
          fi

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install deps
        working-directory: code
        run: pip install -r requirements.txt

      - name: Move state into code dir
        run: |
          rm -rf code/state
          mv state-checkout/state code/state

      - name: Run sync
        working-directory: code
        env:
          PCO_APP_ID: ${{ secrets.PCO_APP_ID }}
          PCO_SECRET: ${{ secrets.PCO_SECRET }}
          LIBIB_API_KEY: ${{ secrets.LIBIB_API_KEY }}
          LIBIB_API_USER: ${{ secrets.LIBIB_API_USER }}
          RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
          EMAIL_FROM: ${{ secrets.EMAIL_FROM }}
          EMAIL_REPLY_TO: ${{ secrets.EMAIL_REPLY_TO }}
          EMAIL_BACKEND: resend
          STABILITY_HOURS: "24"
          LIBIB_LOGIN_URL: "https://www.libib.com/u/mvbchurch"
          BASELINE_MODE: ${{ vars.BASELINE_MODE || 'false' }}
        run: python run.py

      - name: Commit state changes
        run: |
          # Move state back, commit and push if anything changed
          mv code/state state-checkout/state
          cd state-checkout
          git add state/
          if git diff --staged --quiet; then
            echo "No state changes; skipping commit."
          else
            git config user.email "actions@users.noreply.github.com"
            git config user.name "github-actions[bot]"
            git commit -m "[skip ci] sync state $(date -u +%FT%TZ)"
            git push origin state
          fi
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/sync.yml
git commit -m "ci: add scheduled sync workflow with state branch"
```

### Task 6.3: Push to GitHub and configure secrets

- [ ] **Step 1: Create a private GitHub repo** (`mvbc-pco-libib-sync` or similar) via the GitHub UI or `gh repo create --private`.
- [ ] **Step 2: Add the remote and push**

```bash
git remote add origin https://github.com/<your-username>/mvbc-pco-libib-sync.git
git push -u origin main
```

- [ ] **Step 3: Configure repository secrets** at Settings → Secrets and variables → Actions → New repository secret. Add each of:
  - `PCO_APP_ID`
  - `PCO_SECRET`
  - `LIBIB_API_KEY`
  - `LIBIB_API_USER`
  - `RESEND_API_KEY`
  - `EMAIL_FROM`
  - `EMAIL_REPLY_TO` (optional; can leave blank)
- [ ] **Step 4: Configure repository variable** for baseline mode at Settings → Secrets and variables → Actions → Variables → New repository variable:
  - `BASELINE_MODE` = `true` (we'll change to `false` after the first run; see Phase 7)
- [ ] **Step 5: Verify the test workflow ran** on the push. Go to Actions → tests; should show a passing run.
- [ ] **Step 6: Trigger the sync workflow manually** (Actions → sync → Run workflow). Watch the run logs. Expect it to complete with state-branch initialization on the first run.

---

## Phase 7: Production cutover (manual)

> **Reminder:** the Baseline mode procedure (spec §11 / project memory) must be followed exactly during this phase. Do not skip steps.

### Task 7.1: First scheduled run in BASELINE_MODE

- [ ] **Step 1: Confirm `BASELINE_MODE=true`** in repo Variables (Task 6.3 set this).
- [ ] **Step 2: Wait for or trigger a sync run** (Actions → sync → Run workflow).
- [ ] **Step 3: After it completes**, switch to the `state` branch in your local clone:

```bash
git fetch origin state
git checkout state
cat state/pending.json
```

You should see rows with `status="baseline"` for every action the system would take if running normally.

- [ ] **Step 4: Inspect `state/sync_log/*.jsonl`** for any orphan or failure entries.

### Task 7.2: Validate baseline plan

- [ ] **Step 1: For each `status="baseline"` row**, confirm that the action would be correct:
  - `CREATE_PATRON` for someone who's a current Member but not yet in Libib? Probably correct — they're a recent join.
  - `FREEZE_PATRON` for someone in Libib but no longer a Member? Probably correct — they left.
  - `UPDATE_*` for someone whose data drifted between PCO and Libib? Correct.
- [ ] **Step 2: If anything looks wrong**, do not flip baseline mode off. Investigate. Possible causes: PCO has data we haven't seen; Phase 5 migration was incomplete; spec assumption was wrong.

### Task 7.3: Flip to normal mode

- [ ] **Step 1: Change repo variable** `BASELINE_MODE` to `false` (or delete it — defaults to false).
- [ ] **Step 2: Drop the baseline rows.** On the `state` branch:

```bash
git checkout state
echo '{"version": 1, "updated_at": null, "rows": []}' > state/pending.json
git add state/pending.json
git commit -m "[skip ci] clear baseline rows; ready for normal operation"
git push origin state
```

> **Why empty pending.json instead of just removing baseline rows?** All baseline rows are exactly the actions the system will re-detect on the next normal run. Starting from empty pending guarantees no leftover state confuses the new run. Each detection then needs to wait the full 24-hour stability gate before executing — a built-in safety period.

- [ ] **Step 3: Trigger another sync run** manually from the Actions tab.
- [ ] **Step 4: Watch the next 2-3 scheduled runs** over the following hour. Check `state/pending.json` and `sync_log/*.jsonl` between runs. Confirm:
  - The same desired actions show up as `status="pending"` rows
  - No actions are executed yet (24-hour gate not satisfied)
  - No errors or unexpected behavior

### Task 7.4: Wait for the first execution cycle

- [ ] **Step 1: Wait 24 hours** from the first non-baseline run.
- [ ] **Step 2: Verify** that mature actions started executing in the sync log.
- [ ] **Step 3: Spot-check** a few in Libib directly (web UI) to confirm the data matches expectations. Check that any new patrons received a welcome email with the library card attached.
- [ ] **Step 4: Celebrate.** The system is live.

---

## Phase 8: Failure alerting

Add a workflow step that opens a GitHub issue when `status="failed"` rows or orphans appear.

### Task 8.1: Add an alerting workflow step

**Files:**
- Modify: `.github/workflows/sync.yml`

- [ ] **Step 1: Add a new step** at the end of the `sync` job (after "Commit state changes"):

```yaml
      - name: Open issue on failure
        if: always()
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          cd state-checkout
          # Count failed rows in the latest pending.json
          FAILED=$(python3 -c "import json; d=json.load(open('state/pending.json')); print(sum(1 for r in d['rows'] if r.get('status')=='failed'))")
          # Count orphans logged this run
          MONTH=$(date -u +%Y-%m)
          ORPHANS=$(grep -c '"action": "ORPHAN_DETECTED"' "state/sync_log/${MONTH}.jsonl" 2>/dev/null || echo 0)
          if [ "$FAILED" -gt 0 ] || [ "$ORPHANS" -gt 0 ]; then
            TITLE="sync: $FAILED failed action(s), $ORPHANS orphan(s)"
            BODY="Auto-generated alert from sync workflow. See [the run](${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}) and the state branch's pending.json + sync_log."
            # Only open one issue per condition — search for existing
            EXISTING=$(gh issue list --state open --label sync-alert --json number --jq '.[0].number // empty')
            if [ -z "$EXISTING" ]; then
              gh issue create --title "$TITLE" --body "$BODY" --label sync-alert
            else
              gh issue comment "$EXISTING" --body "Re-alert: $TITLE — $(date -u +%FT%TZ)"
            fi
          fi
```

- [ ] **Step 2: Create the `sync-alert` label** in the GitHub repo: Issues → Labels → New label → name `sync-alert`, color red.

- [ ] **Step 3: Commit**

```bash
git checkout main
git add .github/workflows/sync.yml
git commit -m "ci: open issue on sync failures or orphans"
git push origin main
```

- [ ] **Step 4: Smoke test** by manually inserting a failed row in `state/pending.json` on the `state` branch:

```bash
git checkout state
python -c "
import json
d = json.load(open('state/pending.json'))
d['rows'].append({
    'person_id': 'test-fake',
    'action_type': 'CREATE_PATRON',
    'target': {'email': 'x@y'},
    'detected_at': '2026-05-06T12:00:00+00:00',
    'attempts': 3,
    'last_attempt_at': '2026-05-06T13:00:00+00:00',
    'status': 'failed',
})
json.dump(d, open('state/pending.json', 'w'), indent=2)
"
git add state/pending.json
git commit -m "[skip ci] test: inject failed row to verify alerting"
git push origin state
```

Trigger the workflow manually. Verify a new GitHub issue with label `sync-alert` is opened. Then revert the test row:

```bash
git checkout state
python -c "
import json
d = json.load(open('state/pending.json'))
d['rows'] = [r for r in d['rows'] if r['person_id'] != 'test-fake']
json.dump(d, open('state/pending.json', 'w'), indent=2)
"
git add state/pending.json
git commit -m "[skip ci] revert: remove test failed row"
git push origin state
```

- [ ] **Step 5: Close the test issue** manually.

---

## Final verification checklist

After Phase 8, walk through this list to confirm the full system is working as designed.

- [ ] CI test workflow passes on every push to `main`
- [ ] Sync workflow runs every 15 minutes without errors
- [ ] State branch shows pending.json updating across runs
- [ ] sync_log shows entries for each action taken
- [ ] A test patron created via API triggers CREATE_PATRON, welcome email + card delivered
- [ ] A test patron's PCO membership flipped to "Visitor" triggers FREEZE_PATRON after 24h
- [ ] Reverting a PCO change before the 24h gate removes the pending row (no Libib write)
- [ ] No orphans logged (or, if any, they're explained)
- [ ] No `status="failed"` rows
- [ ] An induced failure opens a `sync-alert` GitHub issue

---

## Open follow-ups (post-v1, not in scope)

These remain on the spec's "Open items" list:

- Resolve Resend sender domain (verify `mvbchurch.org`, swap `EMAIL_FROM` to `library@mvbchurch.org`)
- Migrate Resend → Microsoft Graph when `library@mvbchurch.org` mailbox exists
