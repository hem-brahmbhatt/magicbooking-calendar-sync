from pathlib import Path

from magicbooking_sync.models import Booking
from magicbooking_sync.parser import parse_bookings

FIXTURE = Path(__file__).parent / "fixtures" / "bookings_page_sample.html"


def test_parse_bookings_returns_expected_count_and_fields():
    html = FIXTURE.read_text()
    bookings = parse_bookings(html)

    # The scrubbed fixture combines 7 real booking detail pages, totalling
    # 33 individual dated/timed session occurrences.
    assert len(bookings) == 33

    first = bookings[0]
    assert first.date  # non-empty ISO date string, e.g. "2026-09-15"
    assert first.start_time
    assert first.end_time
    assert first.session_name
    assert first.child_name


def test_parse_bookings_first_row_matches_known_real_values():
    html = FIXTURE.read_text()
    bookings = parse_bookings(html)

    assert bookings[0] == Booking(
        date="2026-10-01",
        start_time="15:10",
        end_time="18:00",
        session_name="Autumn after school provision",
        child_name="Test Child",
    )


def test_parse_bookings_last_row_matches_known_real_values():
    html = FIXTURE.read_text()
    bookings = parse_bookings(html)

    # The final table in the fixture is a single-row "Wraparound Annual
    # Membership" administrative booking with an unusual short time window
    # — a genuine real-data edge case, not a fabricated one.
    assert bookings[-1] == Booking(
        date="2026-08-26",
        start_time="23:50",
        end_time="23:55",
        session_name="Wraparound Annual Membership",
        child_name="Test Child",
    )


def test_parse_bookings_all_have_the_expected_child_name():
    html = FIXTURE.read_text()
    bookings = parse_bookings(html)

    assert all(b.child_name == "Test Child" for b in bookings)


def test_parse_bookings_dates_are_iso_formatted():
    html = FIXTURE.read_text()
    bookings = parse_bookings(html)

    for booking in bookings:
        year, month, day = booking.date.split("-")
        assert len(year) == 4
        assert len(month) == 2
        assert len(day) == 2
