import logging
from dataclasses import dataclass

from .config import AppConfig, load_config
from .google_calendar import GoogleCalendarClient
from .parser import parse_bookings
from .portal_client import fetch_bookings_html, login
from .reconcile import reconcile

logger = logging.getLogger("magicbooking_sync")
logger.setLevel(logging.INFO)


@dataclass(frozen=True)
class SyncSummary:
    created: int
    updated: int
    deleted: int
    unchanged: int


def run_sync(
    config: AppConfig,
    *,
    portal_login=login,
    portal_fetch=fetch_bookings_html,
    parse=parse_bookings,
    calendar_client_factory=GoogleCalendarClient,
) -> SyncSummary:
    """Run one full sync: scrape MagicBooking, reconcile against the
    dedicated Google Calendar, and apply create/update/delete actions.

    Dependencies are injectable (portal_login, portal_fetch, parse,
    calendar_client_factory) so this can be unit-tested without any real
    network access; production callers (lambda_handler) use the defaults.
    """
    client = portal_login(
        config.magicbooking_base_url,
        config.magicbooking_username,
        config.magicbooking_password,
    )
    html = portal_fetch(client)
    bookings = parse(html)
    logger.info("scraped %d bookings", len(bookings))

    calendar_client = calendar_client_factory(config.google)
    existing_events = calendar_client.list_synced_events()

    if not bookings and existing_events:
        raise RuntimeError(
            f"Scrape returned 0 bookings but {len(existing_events)} events are "
            "synced — refusing to wipe the calendar; portal markup likely changed"
        )

    actions = reconcile(scraped_bookings=bookings, synced_events=existing_events)

    for booking in actions.to_create:
        calendar_client.create_event(booking)
    for event, booking in actions.to_update:
        calendar_client.update_event(event, booking)
    for event in actions.to_delete:
        calendar_client.delete_event(event)

    unchanged = len(bookings) - len(actions.to_create) - len(actions.to_update)
    summary = SyncSummary(
        created=len(actions.to_create),
        updated=len(actions.to_update),
        deleted=len(actions.to_delete),
        unchanged=unchanged,
    )
    logger.info(
        "sync complete: created=%d updated=%d deleted=%d unchanged=%d",
        summary.created, summary.updated, summary.deleted, summary.unchanged,
    )
    return summary


def lambda_handler(event, context):
    """AWS Lambda entrypoint. Any exception here propagates and fails the
    invocation on purpose (see Global Constraints: fail loudly)."""
    config = load_config()
    summary = run_sync(config)
    return {
        "created": summary.created,
        "updated": summary.updated,
        "deleted": summary.deleted,
        "unchanged": summary.unchanged,
    }
