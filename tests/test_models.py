from magicbooking_sync.models import Booking


def test_booking_id_is_stable_for_same_inputs():
    a = Booking(
        date="2026-09-15",
        start_time="15:15",
        end_time="17:45",
        session_name="After School Club",
        child_name="Alex",
    )
    b = Booking(
        date="2026-09-15",
        start_time="15:15",
        end_time="17:45",
        session_name="After School Club",
        child_name="Alex",
    )
    assert a.booking_id == b.booking_id
    assert len(a.booking_id) == 16


def test_booking_id_differs_when_date_changes():
    base = dict(
        start_time="15:15",
        end_time="17:45",
        session_name="After School Club",
        child_name="Alex",
    )
    a = Booking(date="2026-09-15", **base)
    b = Booking(date="2026-09-16", **base)
    assert a.booking_id != b.booking_id


def test_booking_id_ignores_time_changes():
    """Time is not part of the identity: a booking whose time changed is
    the same booking (update), not a different one."""
    a = Booking(
        date="2026-09-15",
        start_time="15:15",
        end_time="17:45",
        session_name="After School Club",
        child_name="Alex",
    )
    b = Booking(
        date="2026-09-15",
        start_time="16:00",
        end_time="18:00",
        session_name="After School Club",
        child_name="Alex",
    )
    assert a.booking_id == b.booking_id
