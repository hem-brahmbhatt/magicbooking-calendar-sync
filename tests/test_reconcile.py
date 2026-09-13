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


def test_duplicate_synced_events_for_same_booking_id_keep_one_delete_rest():
    booking = _booking()
    first_event = _synced_event_for(booking, google_event_id="evt-first")
    duplicate_event = _synced_event_for(booking, google_event_id="evt-duplicate")

    actions = reconcile(
        scraped_bookings=[booking], synced_events=[first_event, duplicate_event]
    )

    assert actions.to_create == []
    assert actions.to_update == []
    assert actions.to_delete == [duplicate_event]


def test_duplicate_scraped_bookings_with_same_booking_id_create_only_one():
    booking = _booking()
    duplicate_booking = _booking()  # identical fields -> identical booking_id

    actions = reconcile(
        scraped_bookings=[booking, duplicate_booking], synced_events=[]
    )

    assert actions.to_create == [booking]
    assert actions.to_update == []
    assert actions.to_delete == []
