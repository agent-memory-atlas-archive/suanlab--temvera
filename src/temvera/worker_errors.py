"""Error handling shared by the adapters that talk to a system out of process.

A failed call that comes back as an empty answer looks exactly like a system
that answered nothing, and an empty answer scores as a correct abstention. Two
rules keep that from reaching a sealed run. Authentication failures are fatal:
they never recover mid-run, so continuing would only turn every remaining
answer into an empty one (this happened: a revoked key emptied two whole runs).
Every other error is kept, redacted, so a sealed run records what went wrong
and not only how often.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

_FATAL = (
    "AuthenticationError",
    "invalid_api_key",
    "Incorrect API key",
    "HTTP 401",
    "HTTP 403",
    # An exhausted account: retrying cannot help, and the run would otherwise
    # continue on empty answers until it finished.
    "insufficient_quota",
    "no credits remaining",
)
_SECRET = re.compile(r"sk-[A-Za-z0-9_\-*.…]{4,}")


class FatalWorkerError(RuntimeError):
    """An error no retry or later call can recover from; the run must stop."""


def redact(message: str) -> str:
    return _SECRET.sub("sk-<redacted>", message)


def check_fatal(message: str) -> None:
    if any(marker in message for marker in _FATAL):
        raise FatalWorkerError(redact(message)[:500])


def summarize(
    messages: Iterable[str], *, limit: int = 10, width: int = 240
) -> list[dict[str, object]]:
    """The most frequent errors, redacted and truncated, most frequent first."""
    counts = Counter(redact(message)[:width] for message in messages)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"message": message, "count": count} for message, count in ranked[:limit]]
