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


def test_list_synced_events_follows_next_page_token():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if "pageToken" not in str(request.url):
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
                    ],
                    "nextPageToken": "page-2-token",
                },
            )
        assert "page-2-token" in str(request.url)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "evt-2",
                        "extendedProperties": {
                            "private": {
                                "source": "magicbooking",
                                "bookingId": "def456",
                                "date": "2026-09-16",
                                "sessionName": "After School Club",
                                "childName": "Sam",
                            }
                        },
                        "start": {"dateTime": "2026-09-16T15:00:00+01:00"},
                        "end": {"dateTime": "2026-09-16T16:00:00+01:00"},
                    }
                ]
            },
        )

    client = _client_with(handler)
    events = client.list_synced_events()

    assert call_count["n"] == 2
    assert events == [
        SyncedEvent(
            google_event_id="evt-1",
            booking_id="abc123",
            date="2026-09-15",
            start_time="08:00",
            end_time="08:30",
            session_name="Breakfast Club",
            child_name="Alex",
        ),
        SyncedEvent(
            google_event_id="evt-2",
            booking_id="def456",
            date="2026-09-16",
            start_time="15:00",
            end_time="16:00",
            session_name="After School Club",
            child_name="Sam",
        ),
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


def test_access_token_provider_is_called_only_once_per_client_instance():
    token_calls = {"n": 0}

    def access_token_provider():
        token_calls["n"] += 1
        return f"test-token-{token_calls['n']}"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token-1"
        if request.method == "GET":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(200, json={"id": "evt-1"})

    transport = httpx.MockTransport(handler)
    client = GoogleCalendarClient(
        CONFIG, transport=transport, access_token_provider=access_token_provider
    )
    booking = Booking(
        date="2026-09-15",
        start_time="08:00",
        end_time="08:30",
        session_name="Breakfast Club",
        child_name="Alex",
    )
    event = SyncedEvent(
        google_event_id="evt-1",
        booking_id="abc123",
        date="2026-09-15",
        start_time="08:00",
        end_time="08:30",
        session_name="Breakfast Club",
        child_name="Alex",
    )

    client.list_synced_events()
    client.create_event(booking)
    client.update_event(event, booking)
    client.delete_event(event)

    assert token_calls["n"] == 1


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
