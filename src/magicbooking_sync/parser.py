"""Parser for the MagicBooking parent portal's booked-sessions data.

Parses the combined HTML produced by
`portal_client.fetch_bookings_html()` — one or more real
`#viewDatesBookedTable` tables (each from a single booking's detail page,
see `portal_client.py` for why) — into a flat list of `Booking` objects,
one per real calendar occurrence.

Confirmed against the real, live portal (see
docs/superpowers/notes/login-discovery.md and the task 4 report for the
discovery notes): each table has a `<thead>` with columns `Date`, `Day`,
`Time`, `Session`, `Child(ren)`, `Status`, `Cost`, and a `<tbody>` with one
`<tr>` per dated/timed session occurrence. `Date` is `DD/MM/YYYY`; `Time`
is `"HH:MM - HH:MM"` (start and end separated by " - ").

Only rows whose `Status` cell represents an active/accepted booking (e.g.
"Accepted") are turned into `Booking` objects — a cancelled or pending row
is skipped. This matters because the reconciliation logic (see the design
doc) treats "no longer in the scrape" as its signal that a booking should
be removed from the synced calendar; a cancelled booking that still
appears in the portal's HTML (just with a different status badge, e.g.
`badge-danger` instead of `badge-success`) must not be resurrected as a
`Booking` here, or it would sync as a permanent calendar event that never
gets cleaned up.
"""
from datetime import datetime

from bs4 import BeautifulSoup

from .models import Booking

DATES_BOOKED_TABLE_ID = "viewDatesBookedTable"

# Status text values (case-insensitive, whitespace-stripped) that represent
# a live booking that should sync as a calendar event. Only "Accepted" has
# been observed on the real portal so far; anything else (e.g. "Cancelled",
# "Pending", "Rejected") is treated as inactive and excluded.
_ACTIVE_STATUSES = {"accepted"}


def parse_bookings(html: str) -> list[Booking]:
    """Parse combined booking-detail HTML into a list of Booking objects.

    `html` is expected to be the string returned by
    `portal_client.fetch_bookings_html()`: one or more
    `<table id="viewDatesBookedTable">` elements, each with a `<tbody>` row
    per booked session occurrence.
    """
    soup = BeautifulSoup(html, "lxml")
    bookings: list[Booking] = []

    for table in soup.find_all("table", id=DATES_BOOKED_TABLE_ID):
        tbody = table.find("tbody")
        if tbody is None:
            continue

        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 6:
                continue

            status = cells[5].get_text(strip=True)
            if not _is_active_status(status):
                continue

            date_str = cells[0].get_text(strip=True)
            time_str = cells[2].get_text(strip=True)
            session_name = cells[3].get_text(strip=True)
            child_name = cells[4].get_text(strip=True)

            start_time, end_time = _split_time_range(time_str)

            bookings.append(
                Booking(
                    date=_to_iso_date(date_str),
                    start_time=start_time,
                    end_time=end_time,
                    session_name=session_name,
                    child_name=child_name,
                )
            )

    return bookings


def _to_iso_date(date_str: str) -> str:
    """Convert the portal's "DD/MM/YYYY" date text to ISO "YYYY-MM-DD"."""
    return datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y-%m-%d")


def _split_time_range(time_str: str) -> tuple[str, str]:
    """Split the portal's "HH:MM - HH:MM" time text into (start, end)."""
    start, end = (part.strip() for part in time_str.split("-", 1))
    return start, end


def _is_active_status(status: str) -> bool:
    """Whether a booking's Status cell text represents an active booking."""
    return status.strip().lower() in _ACTIVE_STATUSES
