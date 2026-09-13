import os
from dataclasses import dataclass, field

from .google_calendar import GoogleCalendarConfig

SSM_PATH_PREFIX = "/magicbooking-calendar-sync/"


@dataclass(frozen=True)
class AppConfig:
    magicbooking_base_url: str
    magicbooking_username: str
    magicbooking_password: str = field(repr=False)
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
