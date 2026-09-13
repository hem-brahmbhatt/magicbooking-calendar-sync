# MagicBooking → Google Calendar Sync — Design

**Date:** 2026-09-13
**Status:** Approved for planning

## Purpose

Automatically keep a dedicated Google Calendar in sync with the child's booked
sessions (breakfast club, after-school club, wraparound care, etc.) shown on
the parent's MagicBooking portal at
`https://hurstprimary.magicbooking.co.uk/`, so bookings are visible alongside
the rest of the family's calendars without manually re-checking the portal.

## Scope

**In scope:** the parent's own booked sessions for their child(ren), as shown
after logging into the portal. One-way sync: MagicBooking is the source of
truth; the Google Calendar is fully derived from it (created/updated/deleted
to match on every run).

**Out of scope:** broader school-wide calendar entries (INSET days, trips,
general school events) not tied to the parent's own bookings. Two-way sync
(creating a booking in MagicBooking from a Google Calendar event) is not
needed.

## Architecture

```
EventBridge Scheduler (daily, cron)
        │
        ▼
   AWS Lambda (Python)
        │
        ├─ 1. Log into MagicBooking (httpx, cookie session,
        │      ASP.NET Identity form login)
        ├─ 2. Fetch + parse booked-sessions HTML (BeautifulSoup)
        ├─ 3. List existing synced events in the dedicated Google
        │      Calendar (filtered by a private extendedProperty marker)
        ├─ 4. Diff scraped bookings vs existing synced events
        └─ 5. Create / update / delete events via Google Calendar API
```

No database. Google Calendar itself holds the sync state via
`extendedProperties.private` on each event:
- `source: magicbooking`
- `bookingId: <stable hash of date + session type + child>`

This makes each run idempotent and self-healing: a full reconciliation
against reality every time, no drift-prone local state to maintain.

### Why no DynamoDB / state store

YAGNI for a single-family, single-schedule sync: Google Calendar's own
extended-properties search (`privateExtendedProperty` query param on
`events.list`) is sufficient to answer "what have I already synced" without
another moving part to provision, pay for, and keep consistent.

### Why Lambda + plain HTTP (not a headless browser / container)

The portal is a traditional server-rendered ASP.NET app (confirmed via
`curl`: IIS server, redirect to `/Identity/Account/Login`, cookie + antiforgery
token based auth) — not a JS-heavy SPA. A plain HTTP client scripted login
should work and is far cheaper/faster/simpler than running a headless browser
in Lambda.

**Risk:** if the login form turns out to require JS execution or CAPTCHA
(not yet confirmed — untested without real credentials), this assumption
breaks and the implementation would need to move to a headless-browser
approach (e.g. Playwright in a Lambda container image). See Risks below —
this should be the first thing validated during implementation, before
building the rest.

## Data flow detail

1. **Login:** GET the login page, extract the ASP.NET antiforgery token and
   session cookies, POST credentials, follow redirects, confirm an
   authenticated session (e.g. by checking for a logged-in-only page element).
2. **Scrape bookings:** GET the parent's bookings/sessions page(s), parse
   with BeautifulSoup into a list of `Booking { date, start_time, end_time,
   session_name, child_name }`.
3. **Compute stable booking ID:** `sha256(date + session_name + child_name)`,
   truncated — used as the extended-property marker and as the basis for
   Google event summary/description so re-runs are deterministic.
4. **Reconcile with Google Calendar:**
   - List current events where `privateExtendedProperty=source=magicbooking`.
   - Bookings present in scrape but not in Calendar → **create**.
   - Bookings present in both but with changed time/details → **update**.
   - Events present in Calendar but no longer in scrape → **delete**
     (booking was cancelled).
5. **Log a summary** (counts created/updated/deleted/unchanged) to
   CloudWatch.

## Secrets & configuration

All secrets in **AWS SSM Parameter Store** (SecureString, KMS-encrypted):

| Parameter | Purpose |
|---|---|
| `/magicbooking-calendar-sync/magicbooking/username` | Portal login |
| `/magicbooking-calendar-sync/magicbooking/password` | Portal login |
| `/magicbooking-calendar-sync/google/oauth_client_id` | Google OAuth client |
| `/magicbooking-calendar-sync/google/oauth_client_secret` | Google OAuth client |
| `/magicbooking-calendar-sync/google/oauth_refresh_token` | Google OAuth, long-lived |
| `/magicbooking-calendar-sync/google/calendar_id` | Target dedicated calendar ID |

**Google Calendar auth:** personal Gmail account, so a Workspace service
account with domain-wide delegation is not available. Uses standard **OAuth
2.0 refresh-token flow**:
- A one-time **local, interactive** script (run by the user, not by Claude)
  drives the standard Google OAuth consent screen, requesting
  `https://www.googleapis.com/auth/calendar` scope on a **new dedicated
  calendar** created for this purpose (e.g. "Hurst Primary Club Bookings").
- The resulting refresh token is stored in Parameter Store by the user
  (via `aws ssm put-parameter` or a Terraform var applied out-of-band —
  never committed to source or `.tfvars` in plaintext).
- The Lambda exchanges the refresh token for short-lived access tokens on
  each run.

**Terraform manages:**
- Lambda function, execution IAM role (least privilege: `ssm:GetParameter`
  on the specific parameter path, `logs:*` for its own log group).
- EventBridge Scheduler rule — daily cron (e.g. 03:00 Europe/London).
- SSM parameter *resources* as placeholders, with
  `lifecycle { ignore_changes = [value] }` so Terraform never holds real
  secret values in state/diffs — actual values are set out-of-band after
  `apply`.
- CloudWatch Log Group (14-day retention).
- CloudWatch Alarm on Lambda `Errors` metric → SNS topic → email
  subscription (user's email, subscribed out-of-band via console/CLI to
  avoid committing a personal email into `.tf` files — or passed as a
  Terraform variable at apply time, not hardcoded).

## Error handling & observability

- Structured (JSON) log lines per run: bookings scraped, events
  created/updated/deleted, and any failure with context.
- Fail loudly: login failure, parse failure (e.g. page structure changed),
  or Google API failure all raise, causing the Lambda invocation to error —
  this trips the CloudWatch alarm rather than silently syncing nothing.
- No automatic retries beyond Lambda's default async-invoke retry behavior
  (EventBridge Scheduler → Lambda is treated as async); a failed run is
  caught by the next day's scheduled run in the common case, with the alarm
  as the safety net for anything persistent.

## Testing strategy

- **Unit tests, no network:**
  - HTML parser: saved sample fixture HTML (a real logged-in bookings page,
    credentials redacted/irrelevant) → expected `Booking` list.
  - Reconciliation/diff logic: given a set of "current Google events" and a
    set of "freshly scraped bookings" → expected create/update/delete sets.
    Pure function, fully covered including edge cases (booking cancelled,
    time changed, no changes).
- **Not automated in CI:** the real login flow and real Google Calendar API
  calls. These are thin, mockable wrapper functions, exercised manually
  against the real portal/account once during setup and whenever the site
  layout is suspected to have changed.

## Risks & open assumptions

1. **Login bot-detection (unvalidated):** confirmed only that the portal is
   server-rendered ASP.NET; login form JS requirements or CAPTCHA are
   untested without real credentials. **First implementation step:** a
   throwaway spike script confirming scripted login succeeds, before
   building the rest of the Lambda around that assumption. If it fails,
   fall back to a headless-browser (Playwright) approach in a Lambda
   container image.
2. **HTML fragility:** the booking page's markup is not a stable, versioned
   API — a MagicBooking UI change can break the parser at any time. The
   CloudWatch alarm is the mitigation (fast notification), not a fix
   (parser will need occasional maintenance).
3. **Terms of service:** automating login against the portal may or may not
   be permitted under MagicBooking's terms — this is the user's own
   determination to make for their own account, not something assessed as
   part of this design.

## Out of scope / explicitly deferred

- Multi-family / multi-account support (single parent account only).
- Two-way sync or writing bookings back to MagicBooking.
- A UI/dashboard beyond CloudWatch logs.
- CI-based end-to-end testing against the live site.
