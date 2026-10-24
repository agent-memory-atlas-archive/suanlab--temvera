"""Identical-budget comparison harness for external memory systems (E1).

This is the scaffolding for the systems-paper's largest gap: reproducing
external systems (Mem0, Zep/Graphiti, ...) under the *same* generated history,
retrieved-token budget, and bitemporal ground truth as Temvera's oracle. See
``docs/paper-plan-systems.md``.

An external system only ingests and answers text, so the harness:

1. renders the typed history to natural-language turns (:mod:`temvera.nl_workload`);
2. replays, for each query's transaction time, only the turns known by then
   (``per_query_replay=True``) so the input cutoff is enforced; this does not test retrospective
   transaction-time access from a fully ingested store;
3. scores free-text answers by deterministic value-substring match, mirroring
   ForgetEval (E-013).

Two *event-aware reference adapters* are included to validate the renderer,
case builder, and scorer without any network or API: :class:`OracleMemorySystem`
(the ideal, scores 1/1/0) and :class:`LatestValueSystem` (a time-blind baseline
that must degrade, proving the harness discriminates). Text-only adapters for
real third-party systems are added once D-010 authorizes API use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .model import MemoryEvent
from .nl_workload import NLQueryCase, WorkloadTurn, build_nl_cases, render_turns
from .oracle import LifecycleOracle


@runtime_checkable
class MemorySystem(Protocol):
    """Minimal contract every compared system implements."""

    def reset(self) -> None: ...

    def ingest(self, turn: WorkloadTurn) -> None: ...

    def answer(self, case: NLQueryCase) -> str: ...


@dataclass(frozen=True, slots=True)
class ExternalEvaluationResult:
    cases: int
    exact_state_accuracy: float
    evidence_recall: float
    stale_use_rate: float
    abstention_cases: int
    abstention_accuracy: float


@dataclass(frozen=True, slots=True)
class AnswerScore:
    present_expected: frozenset[str]
    present_stale: frozenset[str]
    exact: bool
    recall: float


def score_answer(answer: str, case: NLQueryCase) -> AnswerScore:
    """Deterministically score a free-text answer against value-level truth."""
    folded = answer.casefold()
    present_expected = frozenset(
        value for value in case.expected_values if value.casefold() in folded
    )
    present_stale = frozenset(
        value for value in case.stale_values if value.casefold() in folded
    )
    if case.expected_values:
        exact = present_expected == case.expected_values and not present_stale
        recall = len(present_expected) / len(case.expected_values)
    else:
        # Empty expected set = correct answer is abstention (deleted/expired).
        exact = not present_stale
        recall = float(not present_stale)
    return AnswerScore(
        present_expected=present_expected,
        present_stale=present_stale,
        exact=exact,
        recall=recall,
    )


def evaluate_external(
    system: MemorySystem,
    events: tuple[MemoryEvent, ...],
    *,
    per_query_replay: bool = True,
) -> ExternalEvaluationResult:
    """Feed rendered turns to ``system`` and score its answers against truth.

    With ``per_query_replay`` the store is reset and re-fed only the turns
    recorded on or before each query's transaction time. This prevents exposure
    to later inputs but does not guarantee correct retrieval or answers, nor
    test a native retrospective ``as-of`` predicate.
    """
    cases = build_nl_cases(events)
    if not cases:
        raise ValueError("at least one query case is required")
    turns = sorted(render_turns(events), key=lambda turn: (turn.recorded_at, turn.event_id))

    exact = 0
    recall_total = 0.0
    stale_selected = 0
    selected_total = 0
    abstention_cases = 0
    abstention_correct = 0

    if not per_query_replay:
        system.reset()
        for turn in turns:
            system.ingest(turn)

    for case in cases:
        if per_query_replay:
            system.reset()
            for turn in turns:
                if turn.recorded_at <= case.transaction_at:
                    system.ingest(turn)
        score = score_answer(system.answer(case), case)
        exact += score.exact
        recall_total += score.recall
        stale_selected += len(score.present_stale)
        selected_total += len(score.present_expected) + len(score.present_stale)
        if not case.expected_values:
            abstention_cases += 1
            abstention_correct += score.exact

    return ExternalEvaluationResult(
        cases=len(cases),
        exact_state_accuracy=exact / len(cases),
        evidence_recall=recall_total / len(cases),
        stale_use_rate=stale_selected / selected_total if selected_total else 0.0,
        abstention_cases=abstention_cases,
        abstention_accuracy=(
            abstention_correct / abstention_cases if abstention_cases else 1.0
        ),
    )


class _EventAwareSystem:
    """Base for in-repo reference adapters that resolve turns to typed events."""

    def __init__(self, events: tuple[MemoryEvent, ...]) -> None:
        self._by_event = {event.event_id: event for event in events}
        self._seen: list[MemoryEvent] = []

    def reset(self) -> None:
        self._seen = []

    def ingest(self, turn: WorkloadTurn) -> None:
        event = self._by_event.get(turn.event_id)
        if event is not None:
            self._seen.append(event)


class OracleMemorySystem(_EventAwareSystem):
    """Ideal reference: answers exactly from the bitemporal oracle."""

    def answer(self, case: NLQueryCase) -> str:
        oracle = LifecycleOracle(self._seen)
        beliefs = oracle.query(
            case.subject,
            case.attribute,
            valid_at=case.valid_at,
            transaction_at=case.transaction_at,
        )
        if not beliefs:
            return "No current record."
        return "; ".join(belief.value for belief in beliefs)


class LatestValueSystem(_EventAwareSystem):
    """Time-blind baseline: returns the most recently recorded value.

    It ignores valid time, transaction-time ``as-of``, expiry, and purge, so it
    must fail those categories — demonstrating the harness discriminates.
    """

    def answer(self, case: NLQueryCase) -> str:
        matching = [
            event
            for event in self._seen
            if event.subject == case.subject and event.attribute == case.attribute
        ]
        if not matching:
            return "No current record."
        latest = max(matching, key=lambda event: event.recorded_at)
        return latest.value or "No current record."
