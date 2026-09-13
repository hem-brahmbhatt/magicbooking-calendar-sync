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
