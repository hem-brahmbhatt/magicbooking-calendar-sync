"""Login client for the MagicBooking parent portal.

Field names and success-detection logic here are based on live inspection
of https://hurstprimary.magicbooking.co.uk/Identity/Account/Login (an
ASP.NET Core Identity Razor Pages login form). See
docs/superpowers/notes/login-discovery.md for the full discovery notes.
"""
import httpx
from bs4 import BeautifulSoup


class PortalLoginError(Exception):
    """Raised when authentication against the MagicBooking portal fails."""


# Confirmed against the real, live login page (see login-discovery.md) —
# these matched the brief's ASP.NET Core Identity scaffolding defaults
# exactly, no changes were required.
ANTIFORGERY_FIELD_NAME = "__RequestVerificationToken"
USERNAME_FIELD_NAME = "Input.Email"
PASSWORD_FIELD_NAME = "Input.Password"
REMEMBER_ME_FIELD_NAME = "Input.RememberMe"
LOGIN_PATH = "/Identity/Account/Login"

# A string that only appears on pages rendered for a logged-in user.
# Confirmed against the real site: the anonymous login page only ever shows
# a "Log In" link, while an authenticated page (e.g. /Dashboard) renders a
# nav "Logout" button (a <button> inside a <form action="/Account/Logoff/">).
LOGGED_IN_MARKER = "Logout"


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
            REMEMBER_ME_FIELD_NAME: "false",
        },
    )
    response.raise_for_status()

    # ASP.NET Core Identity re-renders the same login page (200, same path)
    # when credentials are invalid, and redirects away from it on success.
    # Check both the redirect and a content marker as belt-and-braces.
    still_on_login_page = response.url.path.rstrip("/") == LOGIN_PATH.rstrip("/")
    if still_on_login_page or LOGGED_IN_MARKER not in response.text:
        client.close()
        raise PortalLoginError(
            "Login request completed but logged-in marker was not found in "
            "the response — credentials may be wrong, or LOGGED_IN_MARKER "
            "needs updating to match the real portal."
        )

    return client
