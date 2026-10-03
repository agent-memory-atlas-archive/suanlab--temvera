"""Seeded lifecycle histories for deterministic experiments."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from .model import Authority, MemoryEvent, Operation


# Attribute names the generator can emit. The default of one attribute keeps
# every previously sealed run byte-identical; asking for more is opt-in. A
# single attribute per entity makes semantic retrieval degenerate — every stored
# fact about a subject is near-identical text — so multi-attribute histories are
# needed before any retrieval claim generalises.
ATTRIBUTES = ("location", "employer", "device", "diet", "role")


def generate_histories(
    *,
    seed: int,
    entities: int = 4,
    revisions: int = 3,
    namespace: str = "",
    reconfirm_probability: float = 0.0,
    expire_probability: float = 0.0,
    purge_probability: float = 0.0,
    attributes: int = 1,
    distinct_values: bool = False,
) -> tuple[MemoryEvent, ...]:
    """Seeded bitemporal histories.

    By default values are drawn with replacement from 100 per attribute, so at
    scale many subjects share a value and a revision can redraw the value it
    replaces. ``distinct_values`` gives every ingest a value of its own instead.
    It still consumes the same random draw, so a seed yields a history of the
    same shape -- same dates, reconfirms, expiries and purges -- in which only
    value identity differs. That makes the two modes a controlled comparison.
    """
    if entities < 1 or revisions < 1:
        raise ValueError("entities and revisions must be positive")
    if not 1 <= attributes <= len(ATTRIBUTES):
        raise ValueError(f"attributes must be between 1 and {len(ATTRIBUTES)}")
    if namespace and not all(
        character.isalnum() or character == "-" for character in namespace
    ):
        raise ValueError("namespace must contain only letters, numbers, and hyphens")
    probabilities = (
        reconfirm_probability,
        expire_probability,
        purge_probability,
    )
    if any(value < 0 or value > 1 for value in probabilities):
        raise ValueError("operation probabilities must be between zero and one")
    if expire_probability + purge_probability > 1:
        raise ValueError("expire and purge probabilities must sum to at most one")
    prefix = f"{namespace}-" if namespace else ""
    rng = random.Random(seed)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    events: list[MemoryEvent] = []
    sequence = 0
    issued: dict[str, int] = {}
    for entity_number in range(entities):
      for attribute_index in range(attributes):
        attribute = ATTRIBUTES[attribute_index]
        # Single-attribute histories keep their original identifiers so earlier
        # sealed runs remain byte-reproducible.
        suffix = "" if attributes == 1 else f"-{attribute_index:02d}"
        previous: str | None = None
        for revision in range(revisions):
            sequence += 1
            belief_id = f"{prefix}b-{entity_number:03d}-{revision:03d}{suffix}"
            valid_from = start + timedelta(days=revision * 30 + rng.randint(0, 5))
            recorded_at = valid_from + timedelta(days=rng.randint(0, 3))
            if previous is not None:
                events.append(
                    MemoryEvent(
                        event_id=f"{prefix}e-{sequence:05d}-s",
                        operation=Operation.SUPERSEDE,
                        belief_id=belief_id,
                        target_id=previous,
                        valid_from=valid_from,
                        recorded_at=recorded_at,
                    )
                )
            events.append(
                MemoryEvent(
                    event_id=f"{prefix}e-{sequence:05d}-i",
                    operation=Operation.INGEST,
                    belief_id=belief_id,
                    subject=f"{prefix}entity-{entity_number:03d}",
                    attribute=attribute,
                    value=_value(rng, attribute, attributes, distinct_values, issued),
                    valid_from=valid_from,
                    recorded_at=recorded_at,
                    sources=(f"{prefix}source-{sequence:05d}",),
                    authority=Authority.USER,
                )
            )
            if reconfirm_probability and rng.random() < reconfirm_probability:
                events.append(
                    MemoryEvent(
                        event_id=f"{prefix}e-{sequence:05d}-r",
                        operation=Operation.RECONFIRM,
                        belief_id=belief_id,
                        recorded_at=recorded_at + timedelta(days=7),
                    )
                )
            previous = belief_id
        assert previous is not None
        final_ingest = next(
            event
            for event in reversed(events)
            if event.operation is Operation.INGEST and event.belief_id == previous
        )
        if expire_probability or purge_probability:
            draw = rng.random()
            if draw < purge_probability:
                events.append(
                    MemoryEvent(
                        event_id=f"{prefix}e-{sequence:05d}-p",
                        operation=Operation.PURGE,
                        belief_id=previous,
                        recorded_at=final_ingest.recorded_at + timedelta(days=15),
                    )
                )
            elif draw < purge_probability + expire_probability:
                events.append(
                    MemoryEvent(
                        event_id=f"{prefix}e-{sequence:05d}-x",
                        operation=Operation.EXPIRE,
                        belief_id=previous,
                        recorded_at=final_ingest.recorded_at + timedelta(days=15),
                        valid_to=final_ingest.valid_from + timedelta(days=10),
                    )
                )
    return tuple(sorted(events, key=lambda event: (event.recorded_at, event.event_id)))


def generate_lifecycle_suite(*, seed: int) -> tuple[MemoryEvent, ...]:
    """Cover every v1 operation with a small, seeded, inspectable history."""
    rng = random.Random(seed)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    suffix = rng.randrange(10_000)
    return (
        MemoryEvent(
            f"e-{suffix}-1",
            Operation.INGEST,
            "stable",
            start,
            "agent",
            "owner",
            "alice",
            start,
            sources=("verified:profile",),
            authority=Authority.VERIFIED_TOOL,
        ),
        MemoryEvent(
            f"e-{suffix}-2",
            Operation.RECONFIRM,
            "stable",
            start + timedelta(days=5),
        ),
        MemoryEvent(
            f"e-{suffix}-3",
            Operation.INGEST,
            "temporary",
            start,
            "agent",
            "task",
            "draft",
            start,
            sources=("user:session",),
            authority=Authority.USER,
        ),
        MemoryEvent(
            f"e-{suffix}-4",
            Operation.EXPIRE,
            "temporary",
            start + timedelta(days=10),
            valid_to=start + timedelta(days=7),
        ),
        MemoryEvent(
            f"e-{suffix}-4a",
            Operation.INGEST,
            "stable-v2",
            start + timedelta(days=8),
            "agent",
            "owner",
            "bob",
            start + timedelta(days=8),
            sources=("verified:profile-update",),
            authority=Authority.VERIFIED_TOOL,
        ),
        MemoryEvent(
            f"e-{suffix}-4b",
            Operation.SUPERSEDE,
            "stable-v2",
            start + timedelta(days=8),
            valid_from=start + timedelta(days=8),
            target_id="stable",
        ),
        MemoryEvent(
            f"e-{suffix}-5",
            Operation.INGEST,
            "sensitive",
            start,
            "agent",
            "secret",
            "redact-me",
            start,
            sources=("user:private",),
            authority=Authority.USER,
        ),
        MemoryEvent(
            f"e-{suffix}-6",
            Operation.INGEST,
            "derived",
            start + timedelta(days=1),
            "agent",
            "summary",
            "derived-secret",
            start,
            sources=("derived:sensitive",),
            derived_from=("sensitive",),
            authority=Authority.INFERRED,
        ),
        MemoryEvent(
            f"e-{suffix}-7",
            Operation.PURGE,
            "derived",
            start + timedelta(days=20),
        ),
        MemoryEvent(
            f"e-{suffix}-8",
            Operation.PURGE,
            "sensitive",
            start + timedelta(days=20),
        ),
    )


def _value(
    rng: random.Random,
    attribute: str,
    attributes: int,
    distinct: bool,
    issued: dict[str, int],
) -> str:
    """One value token; the random draw is consumed in both modes."""
    draw = rng.randrange(100)
    stem = attribute[:5] if attributes > 1 else "place"
    if not distinct:
        return f"{stem}-{draw:02d}"
    issued[stem] = issued.get(stem, 0) + 1
    return f"{stem}-u{issued[stem]:05d}"
