"""Deterministic bitemporal reference semantics."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Iterable

from .model import Belief, MemoryEvent, Operation


class LifecycleOracle:
    """Materialize beliefs as known at transaction time and valid at event time."""

    def __init__(self, events: Iterable[MemoryEvent] = ()) -> None:
        self._events = list(events)
        self._validate_unique_ids()
        # Folding the log is O(events) per call and queries repeat transaction
        # times, so states are memoised; ``append`` invalidates. Callers get a
        # copy, so mutating a returned state cannot corrupt the cache.
        self._states: dict[datetime, dict[str, Belief]] = {}

    @property
    def events(self) -> tuple[MemoryEvent, ...]:
        return tuple(self._events)

    def append(self, event: MemoryEvent) -> None:
        if any(existing.event_id == event.event_id for existing in self._events):
            raise ValueError(f"duplicate event_id: {event.event_id}")
        self._events.append(event)
        self._states.clear()

    def state_as_of(self, transaction_at: datetime) -> dict[str, Belief]:
        cached = self._states.get(transaction_at)
        if cached is None:
            cached = self._states[transaction_at] = self._fold(transaction_at)
        return dict(cached)

    def _fold(self, transaction_at: datetime) -> dict[str, Belief]:
        state: dict[str, Belief] = {}
        ordered = sorted(
            (e for e in self._events if e.recorded_at <= transaction_at),
            key=lambda e: (e.recorded_at, e.event_id),
        )
        for event in ordered:
            if event.operation is Operation.INGEST:
                if event.belief_id in state:
                    raise ValueError(f"belief already exists: {event.belief_id}")
                assert event.subject is not None
                assert event.attribute is not None
                assert event.value is not None
                assert event.valid_from is not None
                state[event.belief_id] = Belief(
                    belief_id=event.belief_id,
                    subject=event.subject,
                    attribute=event.attribute,
                    value=event.value,
                    valid_from=event.valid_from,
                    valid_to=event.valid_to,
                    recorded_at=event.recorded_at,
                    last_confirmed_at=event.recorded_at,
                    authority=event.authority,
                    sources=event.sources,
                    derived_from=event.derived_from,
                )
            elif event.operation is Operation.RECONFIRM:
                belief = self._require(state, event.belief_id)
                state[event.belief_id] = replace(
                    belief, last_confirmed_at=event.recorded_at
                )
            elif event.operation is Operation.SUPERSEDE:
                old = self._require(state, event.target_id or "")
                valid_to = event.valid_from or event.recorded_at
                state[old.belief_id] = replace(
                    old,
                    valid_to=min(old.valid_to, valid_to) if old.valid_to else valid_to,
                    status="superseded",
                    superseded_by=event.belief_id,
                )
            elif event.operation is Operation.EXPIRE:
                belief = self._require(state, event.belief_id)
                expires = event.valid_to or event.valid_from or event.recorded_at
                state[event.belief_id] = replace(
                    belief,
                    valid_to=min(belief.valid_to, expires) if belief.valid_to else expires,
                    status="expired",
                )
            elif event.operation is Operation.PURGE:
                self._require(state, event.belief_id)
                del state[event.belief_id]
        return state

    def query(
        self,
        subject: str,
        attribute: str,
        *,
        valid_at: datetime,
        transaction_at: datetime,
    ) -> tuple[Belief, ...]:
        beliefs = self.state_as_of(transaction_at).values()
        return tuple(
            sorted(
                (
                    belief
                    for belief in beliefs
                    if belief.subject == subject
                    and belief.attribute == attribute
                    and belief.valid_at(valid_at)
                ),
                key=lambda belief: (belief.valid_from, belief.recorded_at, belief.belief_id),
                reverse=True,
            )
        )

    def purge_lineage(self, belief_id: str, transaction_at: datetime) -> set[str]:
        """Return the belief and every derived descendant requiring deletion."""
        state = self.state_as_of(transaction_at)
        if belief_id not in state:
            return set()
        result = {belief_id}
        changed = True
        while changed:
            changed = False
            for belief in state.values():
                if belief.belief_id not in result and result.intersection(
                    belief.derived_from
                ):
                    result.add(belief.belief_id)
                    changed = True
        return result

    def _validate_unique_ids(self) -> None:
        ids = [event.event_id for event in self._events]
        if len(ids) != len(set(ids)):
            raise ValueError("event_id values must be unique")

    @staticmethod
    def _require(state: dict[str, Belief], belief_id: str) -> Belief:
        try:
            return state[belief_id]
        except KeyError as error:
            raise ValueError(f"unknown belief_id: {belief_id}") from error
