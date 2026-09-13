# MagicBooking → Google Calendar Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily-scheduled AWS Lambda that logs into the MagicBooking parent
portal, scrapes the user's child's booked sessions, and reconciles a
dedicated Google Calendar to match them exactly (create/update/delete),
using Google Calendar's own extended-properties as the sync state — no
database.

**Architecture:** EventBridge Scheduler triggers a Python Lambda daily. The
Lambda logs into the ASP.NET-based portal with `httpx`, parses the bookings
HTML with BeautifulSoup, diffs against existing tagged Google Calendar
events, and applies create/update/delete via the Calendar REST API using an
OAuth refresh token. Terraform provisions the Lambda, EventBridge schedule,
IAM role, SSM parameter placeholders, and CloudWatch log group + error alarm.

**Tech Stack:** Python 3.12, httpx, beautifulsoup4, google-auth, boto3
(Lambda-provided), pytest, Terraform (AWS provider).

**Spec:** [docs/superpowers/specs/2026-09-13-magicbooking-calendar-sync-design.md](../specs/2026-09-13-magicbooking-calendar-sync-design.md)

## Global Constraints

- One-way sync only: MagicBooking is the source of truth; the Google
  Calendar is fully derived from it on every run (create/update/delete to
  match).
- No database/state store — sync state lives entirely in each Google
  Calendar event's `extendedProperties.private` (`source=magicbooking`,
  `bookingId=<hash>`).
- Runs on a daily EventBridge Scheduler cron; no other trigger.
- All secrets (MagicBooking credentials, Google OAuth client id/secret/
  refresh token, target calendar id) live in AWS SSM Parameter Store as
  `SecureString`, under path prefix `/magicbooking-calendar-sync/`.
- Terraform manages the SSM parameter *resources* with
  `lifecycle { ignore_changes = [value] }` — real secret values are set
  out-of-band (CLI), never committed to `.tf`/`.tfvars` in plaintext.
- Fail loudly: login, parsing, or Calendar API errors must propagate and
  fail the Lambda invocation (no swallowing), so the CloudWatch alarm
  fires rather than silently syncing nothing.
- CloudWatch Log Group retention: 14 days. CloudWatch Alarm on Lambda
  `Errors` → SNS topic → email (email address supplied as a Terraform
  variable at apply time, never hardcoded in `.tf` files).
- Automated tests cover only pure logic (the HTML parser against a saved
  fixture, and the reconciliation/diff logic). Real login and real Google
  Calendar API calls are exercised manually against the live portal/account,
  not in CI — there is no safe way to CI-test against a live personal
  site/account.
- IaC tool: Terraform. Language: Python.

---

## Task 1: Project scaffolding + Booking model

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `src/magicbooking_sync/__init__.py`
- Create: `src/magicbooking_sync/models.py`
- Create: `tests/__init__.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Booking` dataclass (`date: str`, `start_time: str`,
  `end_time: str`, `session_name: str`, `child_name: str`) with a
  `.booking_id` property returning a 16-char stable hex hash of
  `date|session_name|child_name`. Used by every later task.

- [ ] **Step 1: Create project scaffolding**

`pyproject.toml`:
```toml
[project]
name = "magicbooking-calendar-sync"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "lxml>=5.2",
    "google-auth>=2.29",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "google-auth-oauthlib>=1.2",
]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

`requirements.txt`:
```
httpx>=0.27
beautifulsoup4>=4.12
lxml>=5.2
google-auth>=2.29
```

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
build/
infra/lambda.zip
infra/.terraform/
infra/terraform.tfstate
infra/terraform.tfstate.backup
infra/.terraform.lock.hcl
infra/terraform.tfvars
.env
*.env
```

`src/magicbooking_sync/__init__.py`: empty file.

`tests/__init__.py`: empty file.

- [ ] **Step 2: Write the failing test for `Booking`**

```python
# tests/test_models.py
from magicbooking_sync.models import Booking


def test_booking_id_is_stable_for_same_inputs():
    a = Booking(
        date="2026-09-15",
        start_time="15:15",
        end_time="17:45",
        session_name="After School Club",
        child_name="Alex",
    )
    b = Booking(
        date="2026-09-15",
        start_time="15:15",
        end_time="17:45",
        session_name="After School Club",
        child_name="Alex",
    )
    assert a.booking_id == b.booking_id
    assert len(a.booking_id) == 16


def test_booking_id_differs_when_date_changes():
    base = dict(
        start_time="15:15",
        end_time="17:45",
        session_name="After School Club",
        child_name="Alex",
    )
    a = Booking(date="2026-09-15", **base)
    b = Booking(date="2026-09-16", **base)
    assert a.booking_id != b.booking_id


def test_booking_id_ignores_time_changes():
    """Time is not part of the identity: a booking whose time changed is
    the same booking (update), not a different one."""
    a = Booking(
        date="2026-09-15",
        start_time="15:15",
        end_time="17:45",
        session_name="After School Club",
        child_name="Alex",
    )
    b = Booking(
        date="2026-09-15",
        start_time="16:00",
        end_time="18:00",
        session_name="After School Club",
        child_name="Alex",
    )
    assert a.booking_id == b.booking_id
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pip install -e ".[dev]" && pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'magicbooking_sync.models'` (or ImportError).

- [ ] **Step 4: Implement `Booking`**

```python
# src/magicbooking_sync/models.py
import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Booking:
    """A single booked session for a child, scraped from MagicBooking."""

    date: str  # ISO format: YYYY-MM-DD
    start_time: str  # HH:MM, 24h
    end_time: str  # HH:MM, 24h
    session_name: str  # e.g. "Breakfast Club"
    child_name: str

    @property
    def booking_id(self) -> str:
        """Stable identifier for this booking, independent of time.

        Used as the Google Calendar extendedProperties.private.bookingId
        marker so re-runs are idempotent and a time change is treated as
        an update to the same event rather than a new one.
        """
        raw = f"{self.date}|{self.session_name}|{self.child_name}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt .gitignore src tests
git commit -m "feat: add project scaffolding and Booking model"
```

---

## Task 2: Reconciliation / diff logic

**Files:**
- Create: `src/magicbooking_sync/reconcile.py`
- Test: `tests/test_reconcile.py`

**Interfaces:**
- Consumes: `Booking` from Task 1 (`src/magicbooking_sync/models.py`).
- Produces: `SyncedEvent` dataclass (`google_event_id: str`,
  `booking_id: str`, `date: str`, `start_time: str`, `end_time: str`,
  `session_name: str`, `child_name: str`) and `ReconcileActions` dataclass
  (`to_create: list[Booking]`, `to_update: list[tuple[SyncedEvent, Booking]]`,
  `to_delete: list[SyncedEvent]`), plus
  `reconcile(scraped_bookings: list[Booking], synced_events: list[SyncedEvent]) -> ReconcileActions`.
  Used by Task 6 (Google Calendar client's caller) and Task 8 (handler).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_reconcile.py
from magicbooking_sync.models import Booking
from magicbooking_sync.reconcile import SyncedEvent, reconcile


def _booking(date="2026-09-15", start="15:15", end="17:45",
             session="After School Club", child="Alex"):
    return Booking(date=date, start_time=start, end_time=end,
                    session_name=session, child_name=child)


def _synced_event_for(booking: Booking, google_event_id="evt-1"):
    return SyncedEvent(
        google_event_id=google_event_id,
        booking_id=booking.booking_id,
        date=booking.date,
        start_time=booking.start_time,
        end_time=booking.end_time,
        session_name=booking.session_name,
        child_name=booking.child_name,
    )


def test_new_booking_with_no_existing_event_is_created():
    booking = _booking()
    actions = reconcile(scraped_bookings=[booking], synced_events=[])
    assert actions.to_create == [booking]
    assert actions.to_update == []
    assert actions.to_delete == []


def test_matching_booking_and_event_with_same_time_is_unchanged():
    booking = _booking()
    event = _synced_event_for(booking)
    actions = reconcile(scraped_bookings=[booking], synced_events=[event])
    assert actions.to_create == []
    assert actions.to_update == []
    assert actions.to_delete == []


def test_matching_booking_id_with_changed_time_is_updated():
    booking = _booking(start="15:15", end="17:45")
    event = _synced_event_for(booking)
    changed_booking = _booking(start="16:00", end="18:00")
    actions = reconcile(scraped_bookings=[changed_booking], synced_events=[event])
    assert actions.to_create == []
    assert actions.to_update == [(event, changed_booking)]
    assert actions.to_delete == []


def test_event_with_no_matching_booking_is_deleted():
    booking = _booking()
    event = _synced_event_for(booking)
    actions = reconcile(scraped_bookings=[], synced_events=[event])
    assert actions.to_create == []
    assert actions.to_update == []
    assert actions.to_delete == [event]


def test_mixed_create_update_delete_in_one_run():
    unchanged = _booking(session="Breakfast Club")
    unchanged_event = _synced_event_for(unchanged, google_event_id="evt-unchanged")

    to_be_updated_old = _booking(session="After School Club", start="15:15")
    to_be_updated_event = _synced_event_for(to_be_updated_old, google_event_id="evt-update")
    to_be_updated_new = _booking(session="After School Club", start="16:00")

    to_be_deleted = _booking(session="Holiday Club", date="2026-09-01")
    to_be_deleted_event = _synced_event_for(to_be_deleted, google_event_id="evt-delete")

    to_be_created = _booking(session="Wraparound Care", date="2026-09-20")

    actions = reconcile(
        scraped_bookings=[unchanged, to_be_updated_new, to_be_created],
        synced_events=[unchanged_event, to_be_updated_event, to_be_deleted_event],
    )

    assert actions.to_create == [to_be_created]
    assert actions.to_update == [(to_be_updated_event, to_be_updated_new)]
    assert actions.to_delete == [to_be_deleted_event]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reconcile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'magicbooking_sync.reconcile'`

- [ ] **Step 3: Implement reconciliation logic**

```python
# src/magicbooking_sync/reconcile.py
from dataclasses import dataclass

from .models import Booking


@dataclass(frozen=True)
class SyncedEvent:
    """A previously-synced Google Calendar event, as read back from the
    Calendar API (see Task 6's GoogleCalendarClient.list_synced_events)."""

    google_event_id: str
    booking_id: str
    date: str
    start_time: str
    end_time: str
    session_name: str
    child_name: str


@dataclass(frozen=True)
class ReconcileActions:
    to_create: list[Booking]
    to_update: list[tuple[SyncedEvent, Booking]]
    to_delete: list[SyncedEvent]


def reconcile(
    scraped_bookings: list[Booking],
    synced_events: list[SyncedEvent],
) -> ReconcileActions:
    """Diff freshly-scraped bookings against previously-synced Calendar
    events, keyed by Booking.booking_id, and return the actions needed to
    make the calendar match the bookings exactly."""
    events_by_id = {event.booking_id: event for event in synced_events}
    bookings_by_id = {booking.booking_id: booking for booking in scraped_bookings}

    to_create: list[Booking] = []
    to_update: list[tuple[SyncedEvent, Booking]] = []
    for booking in scraped_bookings:
        existing_event = events_by_id.get(booking.booking_id)
        if existing_event is None:
            to_create.append(booking)
        elif (existing_event.start_time, existing_event.end_time) != (
            booking.start_time,
            booking.end_time,
        ):
            to_update.append((existing_event, booking))

    to_delete = [
        event for event in synced_events if event.booking_id not in bookings_by_id
    ]

    return ReconcileActions(to_create=to_create, to_update=to_update, to_delete=to_delete)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reconcile.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/magicbooking_sync/reconcile.py tests/test_reconcile.py
git commit -m "feat: add reconciliation/diff logic between bookings and synced events"
```

---

## Task 3: MagicBooking portal login client

**⚠️ Manual/live-system task.** This task requires your real MagicBooking
parent-portal credentials and a live session against
`https://hurstprimary.magicbooking.co.uk/`. It cannot be fully automated or
TDD'd up front because the exact login form field names are unknown until
inspected live. Run this yourself (or have your agent run it while you
supply credentials locally) — do not commit real credentials anywhere.

**Files:**
- Create: `src/magicbooking_sync/portal_client.py`
- Create: `.env.example`
- Create: `docs/superpowers/notes/login-discovery.md`
- Test: manual (documented below), plus `tests/test_portal_client.py` for
  the parts that don't need a live connection (error handling on non-2xx
  response).

**Interfaces:**
- Produces: `PortalLoginError(Exception)` and
  `login(base_url: str, username: str, password: str) -> httpx.Client`
  returning an authenticated client with session cookies set, ready for
  further GET requests. Used by Task 4 and Task 8.

- [ ] **Step 1: Create a local, gitignored `.env` for manual testing**

`.env.example` (committed, no real values):
```
MAGICBOOKING_BASE_URL=https://hurstprimary.magicbooking.co.uk
MAGICBOOKING_USERNAME=
MAGICBOOKING_PASSWORD=
```

Copy it to `.env` (already gitignored by Task 1) and fill in your real
username/password. Load it in your shell for the manual steps below, e.g.:
```bash
export $(grep -v '^#' .env | xargs)
```

- [ ] **Step 2: Inspect the real login form**

With your browser's dev tools (Network tab) or `curl`, load
`https://hurstprimary.magicbooking.co.uk/Identity/Account/Login` and find:
- The hidden antiforgery token field name (ASP.NET Core Identity default is
  `__RequestVerificationToken`).
- The username and password field `name` attributes (ASP.NET Core Identity
  scaffolding commonly uses `Input.Email` or `Input.UserName` and
  `Input.Password` — confirm the actual names on this site, they may
  differ).
- The form's `action` URL (often the same `/Identity/Account/Login` URL,
  possibly with a `?ReturnUrl=` query param — capture it).

Save your findings to `docs/superpowers/notes/login-discovery.md`, e.g.:
```markdown
# Login form discovery

- Login page: https://hurstprimary.magicbooking.co.uk/Identity/Account/Login
- Antiforgery hidden field name: __RequestVerificationToken
- Username field name: Input.Email
- Password field name: Input.Password
- Form action: /Identity/Account/Login (POST)
- Post-login redirect target confirming success: <describe what you saw,
  e.g. redirect to /Dashboard or a page containing "Log out">
```
(Replace the example values with what you actually find — this file is the
source of truth for Task 4's implementation too.)

- [ ] **Step 3: Implement `login()` against the real, discovered form**

```python
# src/magicbooking_sync/portal_client.py
import httpx
from bs4 import BeautifulSoup


class PortalLoginError(Exception):
    """Raised when authentication against the MagicBooking portal fails."""


# Field names below reflect standard ASP.NET Core Identity scaffolding.
# Confirm/adjust these against docs/superpowers/notes/login-discovery.md
# for the real, live values before relying on this in production.
ANTIFORGERY_FIELD_NAME = "__RequestVerificationToken"
USERNAME_FIELD_NAME = "Input.Email"
PASSWORD_FIELD_NAME = "Input.Password"
LOGIN_PATH = "/Identity/Account/Login"

# A string that only appears on pages rendered for a logged-in user —
# confirm this against what you saw in Step 2 and adjust if needed.
LOGGED_IN_MARKER = "Log out"


def login(base_url: str, username: str, password: str) -> httpx.Client:
    """Authenticate against the MagicBooking parent portal.

    Returns an httpx.Client with the authenticated session cookies set,
    ready for further requests against `base_url`. Raises
    PortalLoginError if authentication does not succeed.
    """
    client = httpx.Client(base_url=base_url, follow_redirects=True, timeout=30.0)

    login_page = client.get(LOGIN_PATH)
    login_page.raise_for_status()

    soup = BeautifulSoup(login_page.text, "lxml")
    token_input = soup.find("input", {"name": ANTIFORGERY_FIELD_NAME})
    if token_input is None or not token_input.get("value"):
        client.close()
        raise PortalLoginError(
            f"Could not find antiforgery field '{ANTIFORGERY_FIELD_NAME}' on login page"
        )
    antiforgery_token = token_input["value"]

    response = client.post(
        LOGIN_PATH,
        data={
            USERNAME_FIELD_NAME: username,
            PASSWORD_FIELD_NAME: password,
            ANTIFORGERY_FIELD_NAME: antiforgery_token,
        },
    )
    response.raise_for_status()

    if LOGGED_IN_MARKER not in response.text:
        client.close()
        raise PortalLoginError(
            "Login request completed but logged-in marker was not found in "
            "the response — credentials may be wrong, or LOGGED_IN_MARKER "
            "needs updating to match the real portal."
        )

    return client
```

- [ ] **Step 4: Manually verify login works against the live portal**

```bash
python3 -c "
import os
from magicbooking_sync.portal_client import login

client = login(
    base_url=os.environ['MAGICBOOKING_BASE_URL'],
    username=os.environ['MAGICBOOKING_USERNAME'],
    password=os.environ['MAGICBOOKING_PASSWORD'],
)
print('Login succeeded, cookies:', list(client.cookies.keys()))
"
```
Expected: prints `Login succeeded, ...` with no exception. If it raises
`PortalLoginError`, revisit Step 2's field names and Step 3's constants —
this is expected iteration, not a sign the plan is wrong.

If the portal requires a CAPTCHA or JS challenge that blocks this approach
entirely, stop here and treat that as the Risk #1 escalation from the
spec: this task cannot proceed with a plain HTTP client, and the project
needs to switch to a headless-browser approach before continuing to Task 4.

- [ ] **Step 5: Add a unit test for the one part that doesn't need a live connection**

```python
# tests/test_portal_client.py
import httpx
import pytest

from magicbooking_sync.portal_client import PortalLoginError, login


def test_login_raises_when_antiforgery_field_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>no token here</body></html>")

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.Client
    try:
        httpx.Client = lambda *a, **k: real_client_cls(*a, transport=transport, **k)
        with pytest.raises(PortalLoginError, match="antiforgery"):
            login(base_url="https://example.invalid", username="u", password="p")
    finally:
        httpx.Client = real_client_cls
```

- [ ] **Step 6: Run the unit test to verify it passes**

Run: `pytest tests/test_portal_client.py -v`
Expected: PASS (1 test)

- [ ] **Step 7: Commit**

```bash
git add src/magicbooking_sync/portal_client.py .env.example \
        docs/superpowers/notes/login-discovery.md tests/test_portal_client.py
git commit -m "feat: add MagicBooking portal login client"
```

---

## Task 4: Bookings fetch + HTML parser

**⚠️ Manual/live-system task.** Requires the authenticated client from
Task 3 and produces a real (scrubbed) HTML fixture to test against.

**Files:**
- Modify: `src/magicbooking_sync/portal_client.py` (add `fetch_bookings_html`)
- Create: `src/magicbooking_sync/parser.py`
- Create: `tests/fixtures/bookings_page_sample.html`
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: `Booking` from Task 1, authenticated `httpx.Client` from Task 3's `login()`.
- Produces: `fetch_bookings_html(client: httpx.Client) -> str` (in
  `portal_client.py`) and `parse_bookings(html: str) -> list[Booking]` (in
  `parser.py`). Used by Task 8.

- [ ] **Step 1: Find and fetch the real bookings page**

While logged in (browser dev tools, using the session from Task 3's
verified login), identify the URL that shows your child's booked sessions
(e.g. a "My Bookings" or "Sessions" page/tab). Add a constant for it and a
fetch function:

```python
# src/magicbooking_sync/portal_client.py  (add to the existing file)

BOOKINGS_PATH = "/Bookings"  # replace with the real path you found


def fetch_bookings_html(client: httpx.Client) -> str:
    """Fetch the HTML of the parent's booked-sessions page. `client` must
    already be authenticated (see `login()`)."""
    response = client.get(BOOKINGS_PATH)
    response.raise_for_status()
    return response.text
```

- [ ] **Step 2: Save a scrubbed fixture of the real bookings page**

```bash
python3 -c "
import os
from magicbooking_sync.portal_client import login, fetch_bookings_html

client = login(
    base_url=os.environ['MAGICBOOKING_BASE_URL'],
    username=os.environ['MAGICBOOKING_USERNAME'],
    password=os.environ['MAGICBOOKING_PASSWORD'],
)
html = fetch_bookings_html(client)
with open('tests/fixtures/bookings_page_sample.html', 'w') as f:
    f.write(html)
print('Saved', len(html), 'bytes')
"
```

Before committing this file: open it and **scrub anything sensitive** —
your child's full name (replace with a placeholder like `Test Child`),
account email, address, or any other personal detail baked into the page
chrome (nav bars, account menus). Keep the actual bookings table/list
structure intact since that's what the parser needs to match against.

- [ ] **Step 3: Write the failing parser test against the real fixture**

Open the saved fixture and identify how bookings are structured (a
`<table>`, a list of `<div>` cards, etc.) — the exact markup determines the
selectors below; adjust them to match what you actually see in
`tests/fixtures/bookings_page_sample.html`.

```python
# tests/test_parser.py
from pathlib import Path

from magicbooking_sync.parser import parse_bookings

FIXTURE = Path(__file__).parent / "fixtures" / "bookings_page_sample.html"


def test_parse_bookings_returns_expected_count_and_fields():
    html = FIXTURE.read_text()
    bookings = parse_bookings(html)

    assert len(bookings) > 0
    first = bookings[0]
    assert first.date  # non-empty ISO date string, e.g. "2026-09-15"
    assert first.start_time
    assert first.end_time
    assert first.session_name
    assert first.child_name
```
(Once you know the real fixture's content, strengthen this test with exact
expected values for at least one known booking — the placeholder assertions
above are a starting point only, not the final test.)

- [ ] **Step 4: Run the test to verify it fails**

Run: `pytest tests/test_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'magicbooking_sync.parser'`

- [ ] **Step 5: Implement the parser against the real fixture's structure**

```python
# src/magicbooking_sync/parser.py
from bs4 import BeautifulSoup

from .models import Booking


def parse_bookings(html: str) -> list[Booking]:
    """Parse the parent's booked-sessions page HTML into Booking objects.

    The selectors below must match the real page structure captured in
    tests/fixtures/bookings_page_sample.html — adjust the BeautifulSoup
    queries to the actual markup found there.
    """
    soup = BeautifulSoup(html, "lxml")
    bookings: list[Booking] = []

    # Example shape for a table-based layout; replace with the real
    # container/row selectors from the fixture:
    for row in soup.select(".booking-row"):
        bookings.append(
            Booking(
                date=row.select_one(".booking-date").get_text(strip=True),
                start_time=row.select_one(".booking-start").get_text(strip=True),
                end_time=row.select_one(".booking-end").get_text(strip=True),
                session_name=row.select_one(".booking-session").get_text(strip=True),
                child_name=row.select_one(".booking-child").get_text(strip=True),
            )
        )

    return bookings
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/test_parser.py -v`
Expected: PASS. Iterate on Step 5's selectors against the real fixture
until this is green — this is expected iteration given the page structure
was unknown in advance.

- [ ] **Step 7: Commit**

```bash
git add src/magicbooking_sync/portal_client.py src/magicbooking_sync/parser.py \
        tests/fixtures/bookings_page_sample.html tests/test_parser.py
git commit -m "feat: fetch and parse MagicBooking bookings page"
```

---

## Task 5: Google OAuth one-time setup + dedicated calendar

**⚠️ Manual task, run locally by the user (not by an agent).** This
performs real Google OAuth consent under your own Google account and must
be driven by you in your own browser.

**Files:**
- Create: `scripts/google_oauth_setup.py`
- Create: `docs/superpowers/notes/google-setup.md`

**Interfaces:**
- Produces (as documented values, not code): a Google OAuth client id/
  secret (from Google Cloud Console), a refresh token (printed by the
  script), and a target `calendar_id` — all to be stored in SSM in Task 9.

- [ ] **Step 1: Create a Google Cloud OAuth client**

Document these manual steps in `docs/superpowers/notes/google-setup.md`
as you do them:
1. In Google Cloud Console, create (or reuse) a project, enable the
   "Google Calendar API".
2. Under "APIs & Services > Credentials", create an "OAuth client ID" of
   type "Desktop app". Download the client id and client secret.
3. Under "OAuth consent screen", add your own Google account as a test
   user (since this is a personal, unpublished app).

- [ ] **Step 2: Write the local OAuth consent script**

```python
# scripts/google_oauth_setup.py
"""One-time, interactive script: run locally to grant this project access
to your Google Calendar and print a refresh token to store in SSM.

Usage:
    python3 scripts/google_oauth_setup.py --client-id ... --client-secret ...
"""
import argparse

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    args = parser.parse_args()

    client_config = {
        "installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    credentials = flow.run_local_server(port=0)

    print("\nSUCCESS. Store these values in SSM (see Task 9):\n")
    print(f"  google/oauth_client_id     = {args.client_id}")
    print(f"  google/oauth_client_secret = {args.client_secret}")
    print(f"  google/oauth_refresh_token = {credentials.refresh_token}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run it and create the dedicated calendar**

```bash
pip install -e ".[dev]"
python3 scripts/google_oauth_setup.py --client-id <your-client-id> --client-secret <your-client-secret>
```
This opens your browser for Google's consent screen. Approve access. Copy
the printed values somewhere safe (you'll put them in SSM in Task 9 — do
not commit them).

Then, in Google Calendar, create a new calendar named e.g. "Hurst Primary
Club Bookings", open its Settings, and copy its Calendar ID (looks like
`xxxxxxxx@group.calendar.google.com`).

Record in `docs/superpowers/notes/google-setup.md` (values redacted, just
confirm this was done and where the real values are being kept, e.g. "in
my password manager, to be put into SSM in Task 9").

- [ ] **Step 4: Commit the script and notes (no real secrets)**

```bash
git add scripts/google_oauth_setup.py docs/superpowers/notes/google-setup.md
git commit -m "feat: add one-time Google OAuth setup script"
```

---

## Task 6: Google Calendar client wrapper

**Files:**
- Create: `src/magicbooking_sync/google_calendar.py`
- Test: `tests/test_google_calendar.py` (unit tests with a mocked transport;
  manual verification against the real dedicated calendar is a separate
  step below)

**Interfaces:**
- Consumes: `SyncedEvent` and `Booking` from Tasks 1 and 2.
- Produces: `GoogleCalendarConfig` dataclass (`client_id: str`,
  `client_secret: str`, `refresh_token: str`, `calendar_id: str`) and
  `GoogleCalendarClient` with methods `list_synced_events() -> list[SyncedEvent]`,
  `create_event(booking: Booking) -> None`,
  `update_event(event: SyncedEvent, booking: Booking) -> None`,
  `delete_event(event: SyncedEvent) -> None`. Used by Task 8.

- [ ] **Step 1: Write failing unit tests using a mocked HTTP transport**

```python
# tests/test_google_calendar.py
import httpx
import pytest

from magicbooking_sync.google_calendar import GoogleCalendarClient, GoogleCalendarConfig
from magicbooking_sync.models import Booking
from magicbooking_sync.reconcile import SyncedEvent

CONFIG = GoogleCalendarConfig(
    client_id="test-client-id",
    client_secret="test-client-secret",
    refresh_token="test-refresh-token",
    calendar_id="test-calendar@group.calendar.google.com",
)


def _client_with(handler) -> GoogleCalendarClient:
    transport = httpx.MockTransport(handler)
    return GoogleCalendarClient(CONFIG, transport=transport)


def test_list_synced_events_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "privateExtendedProperty" in str(request.url)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "evt-1",
                        "extendedProperties": {
                            "private": {
                                "source": "magicbooking",
                                "bookingId": "abc123",
                                "date": "2026-09-15",
                                "sessionName": "Breakfast Club",
                                "childName": "Alex",
                            }
                        },
                        "start": {"dateTime": "2026-09-15T08:00:00+01:00"},
                        "end": {"dateTime": "2026-09-15T08:30:00+01:00"},
                    }
                ]
            },
        )

    client = _client_with(handler)
    events = client.list_synced_events()

    assert events == [
        SyncedEvent(
            google_event_id="evt-1",
            booking_id="abc123",
            date="2026-09-15",
            start_time="08:00",
            end_time="08:30",
            session_name="Breakfast Club",
            child_name="Alex",
        )
    ]


def test_create_event_posts_expected_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["body"] = request.read()
        return httpx.Response(200, json={"id": "new-evt"})

    client = _client_with(handler)
    booking = Booking(
        date="2026-09-15",
        start_time="08:00",
        end_time="08:30",
        session_name="Breakfast Club",
        child_name="Alex",
    )
    client.create_event(booking)

    assert captured["method"] == "POST"
    assert b"magicbooking" in captured["body"]
    assert booking.booking_id.encode() in captured["body"]


def test_delete_event_calls_delete_on_event_id():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        return httpx.Response(204)

    client = _client_with(handler)
    event = SyncedEvent(
        google_event_id="evt-1",
        booking_id="abc123",
        date="2026-09-15",
        start_time="08:00",
        end_time="08:30",
        session_name="Breakfast Club",
        child_name="Alex",
    )
    client.delete_event(event)

    assert captured["method"] == "DELETE"
    assert captured["path"].endswith("/events/evt-1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_google_calendar.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'magicbooking_sync.google_calendar'`

- [ ] **Step 3: Implement the Google Calendar client**

```python
# src/magicbooking_sync/google_calendar.py
from dataclasses import dataclass

import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials

from .models import Booking
from .reconcile import SyncedEvent

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


@dataclass(frozen=True)
class GoogleCalendarConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    calendar_id: str


def _time_to_hhmm(iso_datetime: str) -> str:
    # "2026-09-15T08:00:00+01:00" -> "08:00"
    return iso_datetime.split("T")[1][:5]


class GoogleCalendarClient:
    def __init__(self, config: GoogleCalendarConfig, transport: httpx.BaseTransport | None = None):
        self._config = config
        self._http = httpx.Client(transport=transport, timeout=30.0)

    def _access_token(self) -> str:
        credentials = Credentials(
            token=None,
            refresh_token=self._config.refresh_token,
            client_id=self._config.client_id,
            client_secret=self._config.client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        credentials.refresh(GoogleAuthRequest())
        return credentials.token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token()}"}

    def list_synced_events(self) -> list[SyncedEvent]:
        response = self._http.get(
            f"{CALENDAR_API_BASE}/calendars/{self._config.calendar_id}/events",
            headers=self._headers(),
            params={
                "privateExtendedProperty": "source=magicbooking",
                "singleEvents": "true",
            },
        )
        response.raise_for_status()
        items = response.json().get("items", [])

        events = []
        for item in items:
            props = item["extendedProperties"]["private"]
            events.append(
                SyncedEvent(
                    google_event_id=item["id"],
                    booking_id=props["bookingId"],
                    date=props["date"],
                    start_time=_time_to_hhmm(item["start"]["dateTime"]),
                    end_time=_time_to_hhmm(item["end"]["dateTime"]),
                    session_name=props["sessionName"],
                    child_name=props["childName"],
                )
            )
        return events

    def _event_body(self, booking: Booking) -> dict:
        return {
            "summary": f"{booking.session_name} ({booking.child_name})",
            "start": {
                "dateTime": f"{booking.date}T{booking.start_time}:00",
                "timeZone": "Europe/London",
            },
            "end": {
                "dateTime": f"{booking.date}T{booking.end_time}:00",
                "timeZone": "Europe/London",
            },
            "extendedProperties": {
                "private": {
                    "source": "magicbooking",
                    "bookingId": booking.booking_id,
                    "date": booking.date,
                    "sessionName": booking.session_name,
                    "childName": booking.child_name,
                }
            },
        }

    def create_event(self, booking: Booking) -> None:
        response = self._http.post(
            f"{CALENDAR_API_BASE}/calendars/{self._config.calendar_id}/events",
            headers=self._headers(),
            json=self._event_body(booking),
        )
        response.raise_for_status()

    def update_event(self, event: SyncedEvent, booking: Booking) -> None:
        response = self._http.put(
            f"{CALENDAR_API_BASE}/calendars/{self._config.calendar_id}/events/{event.google_event_id}",
            headers=self._headers(),
            json=self._event_body(booking),
        )
        response.raise_for_status()

    def delete_event(self, event: SyncedEvent) -> None:
        response = self._http.delete(
            f"{CALENDAR_API_BASE}/calendars/{self._config.calendar_id}/events/{event.google_event_id}",
            headers=self._headers(),
        )
        response.raise_for_status()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_google_calendar.py -v`
Expected: PASS (3 tests). Note the `_access_token` call will attempt a real
token refresh against Google's token endpoint even in these tests — since
`transport` here only mocks the Calendar API host, not
`oauth2.googleapis.com`. Adjust: inject a second transport/mock for
`GoogleAuthRequest`, or (simpler) refactor `_access_token` to accept an
injectable token-fetcher. Use this approach:

```python
    def __init__(self, config: GoogleCalendarConfig, transport: httpx.BaseTransport | None = None,
                 access_token_provider=None):
        self._config = config
        self._http = httpx.Client(transport=transport, timeout=30.0)
        self._access_token_provider = access_token_provider or self._fetch_access_token

    def _fetch_access_token(self) -> str:
        credentials = Credentials(
            token=None,
            refresh_token=self._config.refresh_token,
            client_id=self._config.client_id,
            client_secret=self._config.client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        credentials.refresh(GoogleAuthRequest())
        return credentials.token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token_provider()}"}
```

And in each test, pass `access_token_provider=lambda: "test-token"` to
`GoogleCalendarClient(...)`. Update Step 3's code with this shape, update
the tests in Step 1 to pass `access_token_provider=lambda: "test-token"`,
then re-run.

- [ ] **Step 5: Manually verify against the real dedicated calendar**

Using the refresh token, client id/secret, and calendar id from Task 5:
```bash
python3 -c "
from magicbooking_sync.google_calendar import GoogleCalendarClient, GoogleCalendarConfig
from magicbooking_sync.models import Booking

config = GoogleCalendarConfig(
    client_id='...', client_secret='...', refresh_token='...',
    calendar_id='...@group.calendar.google.com',
)
client = GoogleCalendarClient(config)
client.create_event(Booking(
    date='2026-09-20', start_time='08:00', end_time='08:30',
    session_name='Test Event', child_name='Test Child',
))
print('Created. Check your Google Calendar, then list:')
print(client.list_synced_events())
"
```
Confirm the event appears in the real "Hurst Primary Club Bookings"
calendar, then delete it manually (or via `client.delete_event(...)` using
the returned `SyncedEvent`) to clean up test data.

- [ ] **Step 6: Commit**

```bash
git add src/magicbooking_sync/google_calendar.py tests/test_google_calendar.py
git commit -m "feat: add Google Calendar client wrapper"
```

---

## Task 7: Secrets/config loader

**Files:**
- Create: `src/magicbooking_sync/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `GoogleCalendarConfig` from Task 6.
- Produces: `AppConfig` dataclass (`magicbooking_base_url: str`,
  `magicbooking_username: str`, `magicbooking_password: str`,
  `google: GoogleCalendarConfig`) and `load_config() -> AppConfig`. Used by
  Task 8.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
import pytest

from magicbooking_sync.config import load_config


def test_load_config_reads_from_environment(monkeypatch):
    monkeypatch.setenv("MAGICBOOKING_BASE_URL", "https://hurstprimary.magicbooking.co.uk")
    monkeypatch.setenv("MAGICBOOKING_USERNAME", "parent@example.com")
    monkeypatch.setenv("MAGICBOOKING_PASSWORD", "hunter2")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "cal@group.calendar.google.com")

    config = load_config()

    assert config.magicbooking_base_url == "https://hurstprimary.magicbooking.co.uk"
    assert config.magicbooking_username == "parent@example.com"
    assert config.magicbooking_password == "hunter2"
    assert config.google.client_id == "client-id"
    assert config.google.client_secret == "client-secret"
    assert config.google.refresh_token == "refresh-token"
    assert config.google.calendar_id == "cal@group.calendar.google.com"


def test_load_config_falls_back_to_ssm_when_env_vars_missing(monkeypatch):
    class FakeSSMClient:
        def get_parameters_by_path(self, Path, WithDecryption, Recursive):
            assert Path == "/magicbooking-calendar-sync/"
            assert WithDecryption is True
            assert Recursive is True
            return {
                "Parameters": [
                    {"Name": "/magicbooking-calendar-sync/magicbooking/username", "Value": "u"},
                    {"Name": "/magicbooking-calendar-sync/magicbooking/password", "Value": "p"},
                    {"Name": "/magicbooking-calendar-sync/google/oauth_client_id", "Value": "cid"},
                    {"Name": "/magicbooking-calendar-sync/google/oauth_client_secret", "Value": "csecret"},
                    {"Name": "/magicbooking-calendar-sync/google/oauth_refresh_token", "Value": "rtoken"},
                    {"Name": "/magicbooking-calendar-sync/google/calendar_id", "Value": "cal@x"},
                ]
            }

    monkeypatch.delenv("MAGICBOOKING_USERNAME", raising=False)
    monkeypatch.setenv("MAGICBOOKING_BASE_URL", "https://hurstprimary.magicbooking.co.uk")

    import magicbooking_sync.config as config_module
    monkeypatch.setattr(config_module, "_ssm_client", lambda: FakeSSMClient())

    config = load_config()

    assert config.magicbooking_username == "u"
    assert config.magicbooking_password == "p"
    assert config.google.client_id == "cid"
    assert config.google.calendar_id == "cal@x"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'magicbooking_sync.config'`

- [ ] **Step 3: Implement the config loader**

```python
# src/magicbooking_sync/config.py
import os
from dataclasses import dataclass

from .google_calendar import GoogleCalendarConfig

SSM_PATH_PREFIX = "/magicbooking-calendar-sync/"


@dataclass(frozen=True)
class AppConfig:
    magicbooking_base_url: str
    magicbooking_username: str
    magicbooking_password: str
    google: GoogleCalendarConfig


def _ssm_client():
    import boto3

    return boto3.client("ssm")


def _load_from_ssm() -> dict:
    client = _ssm_client()
    response = client.get_parameters_by_path(
        Path=SSM_PATH_PREFIX, WithDecryption=True, Recursive=True
    )
    values = {}
    for param in response["Parameters"]:
        key = param["Name"][len(SSM_PATH_PREFIX):]  # e.g. "magicbooking/username"
        values[key] = param["Value"]
    return values


def load_config() -> AppConfig:
    """Load configuration, preferring environment variables (used for local
    manual testing) and falling back to SSM Parameter Store (used in
    Lambda) for anything not set in the environment."""
    base_url = os.environ.get("MAGICBOOKING_BASE_URL")
    username = os.environ.get("MAGICBOOKING_USERNAME")
    password = os.environ.get("MAGICBOOKING_PASSWORD")
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN")
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")

    if not all([username, password, client_id, client_secret, refresh_token, calendar_id]):
        ssm_values = _load_from_ssm()
        username = username or ssm_values["magicbooking/username"]
        password = password or ssm_values["magicbooking/password"]
        client_id = client_id or ssm_values["google/oauth_client_id"]
        client_secret = client_secret or ssm_values["google/oauth_client_secret"]
        refresh_token = refresh_token or ssm_values["google/oauth_refresh_token"]
        calendar_id = calendar_id or ssm_values["google/calendar_id"]

    if not base_url:
        base_url = "https://hurstprimary.magicbooking.co.uk"

    return AppConfig(
        magicbooking_base_url=base_url,
        magicbooking_username=username,
        magicbooking_password=password,
        google=GoogleCalendarConfig(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            calendar_id=calendar_id,
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/magicbooking_sync/config.py tests/test_config.py
git commit -m "feat: add config loader with SSM Parameter Store and env fallback"
```

---

## Task 8: Lambda handler (orchestration)

**Files:**
- Create: `src/magicbooking_sync/handler.py`
- Test: `tests/test_handler.py`

**Interfaces:**
- Consumes: `load_config` (Task 7), `login`/`fetch_bookings_html` (Task 3/4),
  `parse_bookings` (Task 4), `GoogleCalendarClient` (Task 6),
  `reconcile` (Task 2).
- Produces: `SyncSummary` dataclass (`created: int`, `updated: int`,
  `deleted: int`, `unchanged: int`), `run_sync(config: AppConfig, *,
  portal_login=login, portal_fetch=fetch_bookings_html,
  parse=parse_bookings, calendar_client_factory=GoogleCalendarClient) ->
  SyncSummary`, and `lambda_handler(event, context)` as the Lambda entrypoint.

- [ ] **Step 1: Write the failing test using fakes for all I/O**

```python
# tests/test_handler.py
from magicbooking_sync.config import AppConfig
from magicbooking_sync.google_calendar import GoogleCalendarConfig
from magicbooking_sync.handler import run_sync
from magicbooking_sync.models import Booking
from magicbooking_sync.reconcile import SyncedEvent

CONFIG = AppConfig(
    magicbooking_base_url="https://hurstprimary.magicbooking.co.uk",
    magicbooking_username="parent@example.com",
    magicbooking_password="hunter2",
    google=GoogleCalendarConfig(
        client_id="cid", client_secret="csecret",
        refresh_token="rtoken", calendar_id="cal@x",
    ),
)


class FakeCalendarClient:
    def __init__(self, config):
        self.config = config
        self.created = []
        self.updated = []
        self.deleted = []
        self._existing_events = []

    def list_synced_events(self):
        return self._existing_events

    def create_event(self, booking):
        self.created.append(booking)

    def update_event(self, event, booking):
        self.updated.append((event, booking))

    def delete_event(self, event):
        self.deleted.append(event)


def test_run_sync_creates_new_booking_and_reports_summary():
    fake_client_holder = {}

    def fake_calendar_client_factory(config):
        client = FakeCalendarClient(config)
        fake_client_holder["client"] = client
        return client

    booking = Booking(
        date="2026-09-15", start_time="08:00", end_time="08:30",
        session_name="Breakfast Club", child_name="Alex",
    )

    summary = run_sync(
        CONFIG,
        portal_login=lambda base_url, username, password: object(),
        portal_fetch=lambda client: "<html>irrelevant, parse is faked</html>",
        parse=lambda html: [booking],
        calendar_client_factory=fake_calendar_client_factory,
    )

    assert summary.created == 1
    assert summary.updated == 0
    assert summary.deleted == 0
    assert summary.unchanged == 0
    assert fake_client_holder["client"].created == [booking]


def test_run_sync_leaves_unchanged_bookings_alone():
    booking = Booking(
        date="2026-09-15", start_time="08:00", end_time="08:30",
        session_name="Breakfast Club", child_name="Alex",
    )
    existing_event = SyncedEvent(
        google_event_id="evt-1", booking_id=booking.booking_id,
        date=booking.date, start_time=booking.start_time,
        end_time=booking.end_time, session_name=booking.session_name,
        child_name=booking.child_name,
    )

    def fake_calendar_client_factory(config):
        client = FakeCalendarClient(config)
        client._existing_events = [existing_event]
        return client

    summary = run_sync(
        CONFIG,
        portal_login=lambda base_url, username, password: object(),
        portal_fetch=lambda client: "<html></html>",
        parse=lambda html: [booking],
        calendar_client_factory=fake_calendar_client_factory,
    )

    assert summary.created == 0
    assert summary.updated == 0
    assert summary.deleted == 0
    assert summary.unchanged == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_handler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'magicbooking_sync.handler'`

- [ ] **Step 3: Implement the handler**

```python
# src/magicbooking_sync/handler.py
import logging
from dataclasses import dataclass

from .config import AppConfig, load_config
from .google_calendar import GoogleCalendarClient
from .parser import parse_bookings
from .portal_client import fetch_bookings_html, login
from .reconcile import reconcile

logger = logging.getLogger("magicbooking_sync")
logger.setLevel(logging.INFO)


@dataclass(frozen=True)
class SyncSummary:
    created: int
    updated: int
    deleted: int
    unchanged: int


def run_sync(
    config: AppConfig,
    *,
    portal_login=login,
    portal_fetch=fetch_bookings_html,
    parse=parse_bookings,
    calendar_client_factory=GoogleCalendarClient,
) -> SyncSummary:
    """Run one full sync: scrape MagicBooking, reconcile against the
    dedicated Google Calendar, and apply create/update/delete actions.

    Dependencies are injectable (portal_login, portal_fetch, parse,
    calendar_client_factory) so this can be unit-tested without any real
    network access; production callers (lambda_handler) use the defaults.
    """
    client = portal_login(
        config.magicbooking_base_url,
        config.magicbooking_username,
        config.magicbooking_password,
    )
    html = portal_fetch(client)
    bookings = parse(html)
    logger.info("scraped %d bookings", len(bookings))

    calendar_client = calendar_client_factory(config.google)
    existing_events = calendar_client.list_synced_events()

    actions = reconcile(scraped_bookings=bookings, synced_events=existing_events)

    for booking in actions.to_create:
        calendar_client.create_event(booking)
    for event, booking in actions.to_update:
        calendar_client.update_event(event, booking)
    for event in actions.to_delete:
        calendar_client.delete_event(event)

    unchanged = len(bookings) - len(actions.to_create) - len(actions.to_update)
    summary = SyncSummary(
        created=len(actions.to_create),
        updated=len(actions.to_update),
        deleted=len(actions.to_delete),
        unchanged=unchanged,
    )
    logger.info(
        "sync complete: created=%d updated=%d deleted=%d unchanged=%d",
        summary.created, summary.updated, summary.deleted, summary.unchanged,
    )
    return summary


def lambda_handler(event, context):
    """AWS Lambda entrypoint. Any exception here propagates and fails the
    invocation on purpose (see Global Constraints: fail loudly)."""
    config = load_config()
    summary = run_sync(config)
    return {
        "created": summary.created,
        "updated": summary.updated,
        "deleted": summary.deleted,
        "unchanged": summary.unchanged,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_handler.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/magicbooking_sync/handler.py tests/test_handler.py
git commit -m "feat: add Lambda handler orchestrating scrape, reconcile, and sync"
```

---

## Task 9: Terraform infrastructure + Lambda packaging

**Files:**
- Create: `scripts/build_lambda.sh`
- Create: `infra/main.tf`
- Create: `infra/variables.tf`
- Create: `infra/lambda.tf`
- Create: `infra/eventbridge.tf`
- Create: `infra/ssm.tf`
- Create: `infra/cloudwatch.tf`
- Create: `infra/outputs.tf`

**Interfaces:**
- Consumes: the built Lambda package (from `scripts/build_lambda.sh`,
  producing `build/`), invoking `magicbooking_sync.handler.lambda_handler`.
- Produces: deployed AWS resources; no Python interfaces.

- [ ] **Step 1: Write the Lambda packaging script**

```bash
#!/usr/bin/env bash
# scripts/build_lambda.sh
set -euo pipefail

cd "$(dirname "$0")/.."

rm -rf build
mkdir -p build

pip install -r requirements.txt -t build/ --no-cache-dir
cp -r src/magicbooking_sync build/

echo "Lambda build artifact ready in build/"
```

```bash
chmod +x scripts/build_lambda.sh
```

- [ ] **Step 2: Write core Terraform config**

```hcl
# infra/main.tf
terraform {
  required_version = ">= 1.7"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
```

```hcl
# infra/variables.tf
variable "aws_region" {
  type    = string
  default = "eu-west-2"
}

variable "alert_email" {
  description = "Email address to receive sync-failure alerts. Pass with -var or a gitignored terraform.tfvars — never hardcode."
  type        = string
}

variable "schedule_expression" {
  description = "EventBridge Scheduler cron expression for the daily sync."
  type        = string
  default     = "cron(0 3 * * ? *)"
}
```

- [ ] **Step 3: Write Lambda + IAM Terraform config**

```hcl
# infra/lambda.tf
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../build"
  output_path = "${path.module}/lambda.zip"
}

resource "aws_iam_role" "lambda_exec" {
  name = "magicbooking-calendar-sync-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_exec" {
  name = "magicbooking-calendar-sync-lambda-policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["ssm:GetParameter", "ssm:GetParametersByPath"]
        Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/magicbooking-calendar-sync/*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "arn:aws:kms:${var.aws_region}:*:alias/aws/ssm"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "sync" {
  function_name    = "magicbooking-calendar-sync"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "magicbooking_sync.handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  depends_on = [aws_cloudwatch_log_group.lambda]
}
```

- [ ] **Step 4: Write EventBridge Scheduler Terraform config**

```hcl
# infra/eventbridge.tf
resource "aws_iam_role" "scheduler" {
  name = "magicbooking-calendar-sync-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  name = "magicbooking-calendar-sync-scheduler-invoke"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.sync.arn
    }]
  })
}

resource "aws_scheduler_schedule" "daily_sync" {
  name = "magicbooking-calendar-sync-daily"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = "Europe/London"

  target {
    arn      = aws_lambda_function.sync.arn
    role_arn = aws_iam_role.scheduler.arn
  }
}
```

- [ ] **Step 5: Write SSM parameter placeholder Terraform config**

```hcl
# infra/ssm.tf
locals {
  ssm_secret_names = [
    "magicbooking/username",
    "magicbooking/password",
    "google/oauth_client_id",
    "google/oauth_client_secret",
    "google/oauth_refresh_token",
    "google/calendar_id",
  ]
}

resource "aws_ssm_parameter" "secrets" {
  for_each = toset(local.ssm_secret_names)

  name  = "/magicbooking-calendar-sync/${each.value}"
  type  = "SecureString"
  value = "placeholder-set-out-of-band"

  lifecycle {
    ignore_changes = [value]
  }
}
```

- [ ] **Step 6: Write CloudWatch log group + alarm Terraform config**

```hcl
# infra/cloudwatch.tf
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/magicbooking-calendar-sync"
  retention_in_days = 14
}

resource "aws_sns_topic" "alerts" {
  name = "magicbooking-calendar-sync-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "magicbooking-calendar-sync-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 86400
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.sync.function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}
```

- [ ] **Step 7: Write outputs**

```hcl
# infra/outputs.tf
output "lambda_function_name" {
  value = aws_lambda_function.sync.function_name
}

output "ssm_parameter_names" {
  value = [for p in aws_ssm_parameter.secrets : p.name]
}
```

- [ ] **Step 8: Validate the Terraform config**

```bash
cd infra
terraform init
terraform fmt -check
terraform validate
```
Expected: `terraform validate` reports `Success! The configuration is
valid.` (No `terraform apply` yet — that's Task 10, after real secrets and
a built Lambda package exist.)

- [ ] **Step 9: Commit**

```bash
cd ..
git add scripts/build_lambda.sh infra
git commit -m "feat: add Terraform infrastructure for Lambda, schedule, and alerting"
```

---

## Task 10: Deployment guide + end-to-end manual verification

**⚠️ Manual task.** Real deployment, real secrets, real first run — this
is inherently something you run yourself, not something automatically
tested.

**Files:**
- Create: `README.md` (replace the placeholder one-liner)

**Interfaces:** none — this is documentation plus a live deployment
checklist.

- [ ] **Step 1: Write the deployment guide**

```markdown
# magicbooking-calendar-sync

Daily sync of MagicBooking (hurstprimary.magicbooking.co.uk) booked
sessions into a dedicated Google Calendar. See
`docs/superpowers/specs/2026-09-13-magicbooking-calendar-sync-design.md`
for the design and
`docs/superpowers/plans/2026-09-13-magicbooking-calendar-sync.md` for how
it was built.

## Deploy

1. Build the Lambda package:
   \`\`\`bash
   ./scripts/build_lambda.sh
   \`\`\`
2. Provision infrastructure:
   \`\`\`bash
   cd infra
   terraform init
   terraform apply -var="alert_email=you@example.com"
   \`\`\`
3. Populate real secret values (placeholders were created by Terraform
   but ignored on subsequent applies):
   \`\`\`bash
   aws ssm put-parameter --name /magicbooking-calendar-sync/magicbooking/username --type SecureString --overwrite --value "..."
   aws ssm put-parameter --name /magicbooking-calendar-sync/magicbooking/password --type SecureString --overwrite --value "..."
   aws ssm put-parameter --name /magicbooking-calendar-sync/google/oauth_client_id --type SecureString --overwrite --value "..."
   aws ssm put-parameter --name /magicbooking-calendar-sync/google/oauth_client_secret --type SecureString --overwrite --value "..."
   aws ssm put-parameter --name /magicbooking-calendar-sync/google/oauth_refresh_token --type SecureString --overwrite --value "..."
   aws ssm put-parameter --name /magicbooking-calendar-sync/google/calendar_id --type SecureString --overwrite --value "..."
   \`\`\`
   (Get the Google values by running `scripts/google_oauth_setup.py` — see
   `docs/superpowers/notes/google-setup.md`.)
4. Confirm the SNS email subscription (check your inbox for a confirmation
   link from AWS after `terraform apply`).

## Run

Runs automatically daily via EventBridge Scheduler. To trigger manually:
\`\`\`bash
aws lambda invoke --function-name magicbooking-calendar-sync /tmp/out.json && cat /tmp/out.json
\`\`\`

## Tests

\`\`\`bash
pip install -e ".[dev]"
pytest
\`\`\`
```

- [ ] **Step 2: Deploy for real**

Follow the guide's Deploy steps 1–4 against your own AWS account.

- [ ] **Step 3: Run one real end-to-end sync and verify**

```bash
aws lambda invoke --function-name magicbooking-calendar-sync /tmp/out.json
cat /tmp/out.json
```
Expected: a JSON summary like `{"created": N, "updated": 0, "deleted": 0,
"unchanged": 0}` with no error. Then open the "Hurst Primary Club
Bookings" Google Calendar and confirm the events match your actual
MagicBooking bookings.

Check CloudWatch Logs (`/aws/lambda/magicbooking-calendar-sync`) for the
structured summary line to confirm logging works as designed.

- [ ] **Step 4: Commit the README**

```bash
git add README.md
git commit -m "docs: add deployment guide and mark project ready for first real sync"
```

---

## Self-Review Notes

- **Spec coverage:** login+scrape (Tasks 3–4), Google Calendar sync with
  extendedProperties idempotency (Tasks 2, 6), SSM secrets with
  `ignore_changes` (Task 9), OAuth refresh-token flow via a one-time local
  script (Task 5), Terraform-managed Lambda/EventBridge/IAM/CloudWatch
  (Task 9), fail-loud error handling + alarm→SNS→email (Tasks 8–9), unit
  tests for parser/reconcile only, manual verification for login/Calendar
  API (Tasks 3, 4, 6, 10), deployment guide (Task 10) — all spec sections
  are covered.
- **Placeholder scan:** Tasks 3 and 4 contain provisional selector/field
  names that the executing engineer must confirm/adjust against a live,
  unseen page — this is called out explicitly as an inherent constraint of
  scraping an external, undocumented site (see spec Risk #2), not a
  deferred "fill in later." Every other task's code is complete and
  concrete.
- **Type/interface consistency:** `Booking`, `SyncedEvent`,
  `ReconcileActions`, `GoogleCalendarConfig`, `AppConfig`, and
  `GoogleCalendarClient`'s method signatures are defined once (Tasks 1, 2,
  6, 7) and reused with matching names/fields in every later task
  (verified: Task 8's fakes match Task 6's real interface; Task 7's
  `AppConfig.google` matches Task 6's `GoogleCalendarConfig`).
