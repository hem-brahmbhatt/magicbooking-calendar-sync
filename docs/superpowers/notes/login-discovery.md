# Login form discovery

Inspected live (no credentials submitted) via `curl` against
`https://hurstprimary.magicbooking.co.uk/Identity/Account/Login` on 2026-09-13.

## Login page (GET)

- URL: `https://hurstprimary.magicbooking.co.uk/Identity/Account/Login`
- Returns `200 OK` directly (no redirect, no query string needed for a plain
  visit). Server: `Microsoft-IIS/10.0`, `X-Powered-By: ASP.NET` — confirms
  ASP.NET Core Identity as expected.
- Sets cookies on the GET response: `.AspNetCore.Antiforgery.<hash>`,
  `.AspNetCore.Mvc.CookieTempDataProvider`, `mbparent`, `ARRAffinity`,
  `ARRAffinitySameSite`. A plain `httpx.Client` (cookie jar persists across
  requests on the same client instance) picks these up automatically — no
  special handling needed as long as the same `Client` is reused for the GET
  and the following POST.
- No CAPTCHA, reCAPTCHA/hCAPTCHA/Turnstile, or JS bot-challenge markers found
  anywhere in the page source (only unrelated `cdnjs.cloudflare.com` static
  asset URLs for jQuery/Bootstrap/Font Awesome — not a bot-detection
  challenge). Plain HTTP client login is viable; no need to escalate to a
  headless-browser approach.

## Form fields (confirmed from real HTML)

The login form (`<form id="account" method="post">`, no `action` attribute
— submits back to the current URL, i.e. `/Identity/Account/Login`):

- Antiforgery hidden field name: `__RequestVerificationToken`
  (standard ASP.NET Core Identity default — confirmed present as a hidden
  `<input>` with a `value` attribute inside the form).
- Username/email field name: `Input.Email` (`<input type="email" ...
  id="Input_Email" name="Input.Email" ...>`).
- Password field name: `Input.Password` (`<input type="password" ...
  id="Input_Password" name="Input.Password" ...>`).
- Also present: a hidden `Input.RememberMe` field with `value="false"`
  (paired with a visible "Remember me" checkbox — standard ASP.NET MVC
  boolean-checkbox pattern). Not strictly required by the server, but our
  POST includes `Input.RememberMe=false` to submit the same shape of data a
  real browser would.
- Form action: no explicit `action` attribute → submits to
  `/Identity/Account/Login` (POST), matching the brief's assumption. No
  `ReturnUrl` query param was present on a plain (non-redirected) visit to
  the login page, so none is submitted.

**All three key field names (antiforgery, username, password) and the login
path matched the brief's starter-constant guesses exactly** — no changes
were needed to `ANTIFORGERY_FIELD_NAME`, `USERNAME_FIELD_NAME`,
`PASSWORD_FIELD_NAME`, or `LOGIN_PATH`.

## Anonymous vs authenticated signal

- Anonymous requests to `/` and `/Dashboard` redirect (302) toward the login
  page / `/Account/CheckPersistentSession` and ultimately land back on
  `/Identity/Account/Login` (page `<title>Log In - Hurst Primary School</title>`,
  nav shows a `Log In` link).
- ASP.NET Core Identity's Razor Pages login handler re-renders the **same**
  `/Identity/Account/Login` page (HTTP 200, no redirect) when credentials are
  invalid, showing validation errors. On successful login it issues a
  redirect (302) away from the login page (to `/` or a `ReturnUrl`).
  This redirect-vs-200-same-page distinction is a reliable, content-free
  success signal, so `login()` uses "did we end up away from the login page
  after following redirects" as its primary check.
- Post-login redirect target / logged-in marker (confirmed against the real
  site using real credentials — structural HTML/text noted below contains no
  account-holder personal data): after a successful POST with valid
  credentials, the response redirects (302) from `/Identity/Account/Login`
  to `/Dashboard` (final page `<title>Dashboard - Hurst Primary School</title>`).
  That page's nav contains:
  `<form class="form-inline" action="/Account/Logoff/"><button type="submit"
  class="nav-link btn logout-form-btn ...">Logout</button></form>`.
  The literal text **"Logout"** (one word) does not appear anywhere on the
  anonymous login page, so it is a safe, reliable logged-in marker.
  Initially guessed `"Log Out"` (per the brief's placeholder) which did
  *not* match the real text and caused a false-negative `PortalLoginError`
  on an otherwise-successful login — corrected to `"Logout"` after
  inspecting the real authenticated response.
  `LOGGED_IN_MARKER` is implemented as a check for this text, used together
  with the "no longer on the login path" check (failed logins re-render
  `/Identity/Account/Login` at 200; successful ones redirect away from it).

## Manual verification result

Login via `src/magicbooking_sync/portal_client.py`'s `login()` was run
against the real site using the real `.env` credentials (loaded as env
vars, never printed):
- **Correct credentials: login succeeded** — no `PortalLoginError` was
  raised, and the returned client held authenticated session cookies
  (`.AspNetCore.Antiforgery.*`, `mbparent`, `ARRAffinity`,
  `ARRAffinitySameSite`).
- **Wrong password (same username, deliberately invalid password): login
  correctly failed** — `PortalLoginError` was raised as expected, confirming
  the failure path is also correctly detected (not just a lucky
  always-succeeds check).
