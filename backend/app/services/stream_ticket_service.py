"""Single-use, short-lived tickets that authorise one SSE stream.

Why this exists (GAP_ANALYSIS.md §2.2): the browser `EventSource` API cannot
set an `Authorization` header, so the progress stream took the access token as
`?token=`. A URL query string is the worst place to put a credential — it lands
in the server's access log, every intermediate proxy's log, browser history,
and the `Referer` header of anything the page subsequently loads. The token
there was a full-privilege, 15-minute credential for the whole API.

A ticket is the opposite of that:

* **Single-use.** Redeemed with an atomic `GETDEL`, so a replay from a log finds
  nothing. Two concurrent uses cannot both win.
* **Scoped.** Bound to one user *and* one proposal. Even before it expires it
  authorises exactly one stream and grants nothing else.
* **Short-lived.** Seconds (`settings.stream_ticket_ttl_seconds`), long enough
  to hand to `new EventSource(...)` and no longer.

**This fails closed**, unlike `core/cache.py` and `core/rate_limit.py` which
deliberately fail open. Those degrade to "slower" and "unthrottled"; this one
would degrade to "unauthenticated", so a Redis outage here must deny the stream,
not grant it. The stream is a progress indicator — losing it while Redis is down
is an acceptable outcome in a way that serving another tenant's data is not.
"""

import logging
import secrets

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None


class TicketError(Exception):
    """Ticket missing, expired, already used, or not issuable."""


def _redis():
    global _client
    if _client is None:
        import redis

        _client = redis.from_url(settings.cache_url, socket_timeout=0.5)
    return _client


def _key(ticket: str) -> str:
    return f"sse_ticket:{ticket}"


def issue(user_id, proposal_id) -> str:
    """Mints a ticket authorising `user_id` to stream `proposal_id`.

    Raises TicketError if the store is unreachable — the caller must surface
    that rather than fall back to an unauthenticated stream.
    """
    ticket = secrets.token_urlsafe(32)
    try:
        _redis().set(
            _key(ticket),
            f"{user_id}:{proposal_id}",
            ex=settings.stream_ticket_ttl_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — fails closed, see module docstring
        logger.error("stream ticket issue failed (redis unavailable): %s", exc)
        raise TicketError("Ticket store unavailable.") from exc
    return ticket


def redeem(ticket: str, proposal_id) -> str:
    """Consumes `ticket` and returns the user id it was issued to.

    Raises TicketError unless the ticket exists, has not been used, and was
    issued for this exact proposal. The proposal check matters because the
    ticket travels in a URL: without it, a ticket captured from one stream's
    URL would open any other proposal the same user owns.
    """
    try:
        # GETDEL is atomic, so a replayed ticket cannot be redeemed twice even
        # if both requests arrive at once. (Redis 6.2+; the pinned image is 7.)
        raw = _redis().getdel(_key(ticket))
    except Exception as exc:  # noqa: BLE001 — fails closed
        logger.error("stream ticket redeem failed (redis unavailable): %s", exc)
        raise TicketError("Ticket store unavailable.") from exc

    if raw is None:
        raise TicketError("Unknown, expired, or already-used ticket.")

    value = raw.decode() if isinstance(raw, bytes) else str(raw)
    user_id, _, ticket_proposal = value.partition(":")
    if ticket_proposal != str(proposal_id):
        # Already consumed above, so a mismatch burns the ticket. That is the
        # right way round: a ticket used against the wrong resource is either a
        # bug or an attack, and neither deserves a retry.
        raise TicketError("Ticket was not issued for this proposal.")
    return user_id
