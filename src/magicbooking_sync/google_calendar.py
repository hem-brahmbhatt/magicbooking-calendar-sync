from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials

from .models import Booking
from .reconcile import SyncedEvent

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


@dataclass(frozen=True)
class GoogleCalendarConfig:
    client_id: str
    client_secret: str = field(repr=False)
    refresh_token: str = field(repr=False)
    calendar_id: str


def _time_to_hhmm(iso_datetime: str) -> str:
    # "2026-09-15T08:00:00+01:00" -> "08:00"
    return iso_datetime.split("T")[1][:5]


class GoogleCalendarClient:
    def __init__(
        self,
        config: GoogleCalendarConfig,
        transport: Optional[httpx.BaseTransport] = None,
        access_token_provider: Optional[Callable[[], str]] = None,
    ):
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

    def list_synced_events(self) -> list[SyncedEvent]:
        events = []
        page_token = None
        while True:
            params = {
                "privateExtendedProperty": "source=magicbooking",
                "singleEvents": "true",
            }
            if page_token:
                params["pageToken"] = page_token

            response = self._http.get(
                f"{CALENDAR_API_BASE}/calendars/{self._config.calendar_id}/events",
                headers=self._headers(),
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items", [])

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

            page_token = payload.get("nextPageToken")
            if not page_token:
                break

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
