import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Booking:
    """A single booked session for a child, scraped from MagicBooking."""

    date: str  # ISO format: YYYY-MM-DD
    start_time: str  # HH:MM, 24h
    end_time: str  # HH:MM, 24h
    session_name: str  # e.g. "Breakfast Club"
    child_name: str

    @property
    def booking_id(self) -> str:
        """Stable identifier for this booking, independent of time.

        Used as the Google Calendar extendedProperties.private.bookingId
        marker so re-runs are idempotent and a time change is treated as
        an update to the same event rather than a new one.
        """
        raw = f"{self.date}|{self.session_name}|{self.child_name}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
