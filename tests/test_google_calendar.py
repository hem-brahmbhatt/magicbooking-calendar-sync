import json

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
    return GoogleCalendarClient(
        CONFIG, transport=transport, access_token_provider=lambda: "test-token"
    )


def test_list_synced_events_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == (
            "/calendar/v3/calendars/test-calendar@group.calendar.google.com/events"
        )
        assert "privateExtendedProperty" in str(request.url)
        assert "source%3Dmagicbooking" in str(request.url)
        assert request.headers["Authorization"] == "Bearer test-token"
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
        captured["path"] = request.url.path
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.read())
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
    assert captured["path"] == (
        "/calendar/v3/calendars/test-calendar@group.calendar.google.com/events"
    )
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    body = captured["body"]
    assert body["summary"] == "Breakfast Club (Alex)"
    assert body["start"] == {
        "dateTime": "2026-09-15T08:00:00",
        "timeZone": "Europe/London",
    }
    assert body["end"] == {
        "dateTime": "2026-09-15T08:30:00",
        "timeZone": "Europe/London",
    }
    assert body["extendedProperties"]["private"] == {
        "source": "magicbooking",
        "bookingId": booking.booking_id,
        "date": "2026-09-15",
        "sessionName": "Breakfast Club",
        "childName": "Alex",
    }


def test_update_event_puts_to_event_id_with_expected_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={"id": "evt-1"})

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
    booking = Booking(
        date="2026-09-15",
        start_time="09:00",
        end_time="09:30",
        session_name="Breakfast Club",
        child_name="Alex",
    )
    client.update_event(event, booking)

    assert captured["method"] == "PUT"
    assert captured["path"] == (
        "/calendar/v3/calendars/test-calendar@group.calendar.google.com/events/evt-1"
    )
    assert captured["body"]["start"]["dateTime"] == "2026-09-15T09:00:00"
    assert captured["body"]["end"]["dateTime"] == "2026-09-15T09:30:00"
    assert captured["body"]["extendedProperties"]["private"]["bookingId"] == booking.booking_id


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


def test_raises_on_http_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    client = _client_with(handler)
    event = SyncedEvent(
        google_event_id="missing",
        booking_id="abc123",
        date="2026-09-15",
        start_time="08:00",
        end_time="08:30",
        session_name="Breakfast Club",
        child_name="Alex",
    )
    with pytest.raises(httpx.HTTPStatusError):
        client.delete_event(event)
