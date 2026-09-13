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


def test_run_sync_handles_mixed_create_update_delete_and_reports_summary():
    unchanged_booking = Booking(
        date="2026-09-15", start_time="08:00", end_time="08:30",
        session_name="Breakfast Club", child_name="Alex",
    )
    updated_booking = Booking(
        date="2026-09-16", start_time="15:00", end_time="16:00",
        session_name="After School Club", child_name="Alex",
    )
    new_booking = Booking(
        date="2026-09-17", start_time="08:00", end_time="08:30",
        session_name="Breakfast Club", child_name="Sam",
    )

    unchanged_event = SyncedEvent(
        google_event_id="evt-unchanged", booking_id=unchanged_booking.booking_id,
        date=unchanged_booking.date, start_time=unchanged_booking.start_time,
        end_time=unchanged_booking.end_time, session_name=unchanged_booking.session_name,
        child_name=unchanged_booking.child_name,
    )
    stale_event_for_update = SyncedEvent(
        google_event_id="evt-updated", booking_id=updated_booking.booking_id,
        date=updated_booking.date, start_time="14:00", end_time="15:00",
        session_name=updated_booking.session_name, child_name=updated_booking.child_name,
    )
    event_to_delete = SyncedEvent(
        google_event_id="evt-deleted", booking_id="stale-booking-id",
        date="2026-09-10", start_time="08:00", end_time="08:30",
        session_name="Breakfast Club", child_name="Jo",
    )

    fake_client_holder = {}

    def fake_calendar_client_factory(config):
        client = FakeCalendarClient(config)
        client._existing_events = [
            unchanged_event, stale_event_for_update, event_to_delete
        ]
        fake_client_holder["client"] = client
        return client

    summary = run_sync(
        CONFIG,
        portal_login=lambda base_url, username, password: object(),
        portal_fetch=lambda client: "<html></html>",
        parse=lambda html: [unchanged_booking, updated_booking, new_booking],
        calendar_client_factory=fake_calendar_client_factory,
    )

    assert summary.created == 1
    assert summary.updated == 1
    assert summary.deleted == 1
    assert summary.unchanged == 1

    client = fake_client_holder["client"]
    assert client.created == [new_booking]
    assert client.updated == [(stale_event_for_update, updated_booking)]
    assert client.deleted == [event_to_delete]
