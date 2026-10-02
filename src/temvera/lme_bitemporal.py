"""Turn LongMemEval's knowledge-update split into a bitemporal workload.

The synthetic grid gives control; it does not give realism, which is the first
thing an experiments-track reviewer will press on. LongMemEval's
``knowledge-update`` instances are the missing half: human-written conversations
in which a fact is stated, then superseded, each session carrying a real
timestamp. That is a supersession with a real valid time and a real transaction
time, and the benchmark already ships the *current* value as gold.

What it does not ship is the *superseded* value, because it never asks for one.
Recovering that is what makes an as-of query possible, and it is the one step
that cannot be done reliably by rule: the gold answer is often a paraphrase
("25 minutes and 50 seconds (or 25:50)") of what the conversation said. So this
module proposes candidates and hands them to a human, rather than guessing.
Labels are only used once confirmed.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

_DATE = "%Y/%m/%d (%a) %H:%M"


def parse_date(text: str) -> datetime:
    return datetime.strptime(text.strip(), _DATE)


@dataclass(frozen=True, slots=True)
class Session:
    session_id: str
    recorded_at: datetime
    user_turns: tuple[str, ...]

    def sentences(self) -> tuple[str, ...]:
        out: list[str] = []
        for turn in self.user_turns:
            out += [s.strip() for s in re.split(r"(?<=[.!?])\s+", turn) if s.strip()]
        return tuple(out)


@dataclass(frozen=True, slots=True)
class UpdatePair:
    """One knowledge-update instance, reduced to its supersession."""

    question_id: str
    question: str
    asked_at: datetime
    new_value: str
    earlier: Session
    later: Session
    old_value_candidates: tuple[str, ...] = field(default_factory=tuple)

    @property
    def interval_is_ordered(self) -> bool:
        return self.earlier.recorded_at < self.later.recorded_at < self.asked_at


def _sessions(instance: dict[str, Any]) -> list[Session]:
    out = []
    for sid, date, turns in zip(
        instance["haystack_session_ids"],
        instance["haystack_dates"],
        instance["haystack_sessions"],
        strict=True,
    ):
        user = tuple(t["content"] for t in turns if t.get("role") == "user")
        out.append(Session(sid, parse_date(date), user))
    return out


def _gold_keys(gold: str) -> list[str]:
    """Tokens distinctive enough to locate the gold value in running text."""
    tokens = re.findall(r"\b[\w:/.,$-]{2,}\b", gold)
    return [t for t in tokens if any(c.isdigit() for c in t) or t[:1].isupper()]


def candidates_for(pair_sessions: tuple[Session, Session], gold: str) -> tuple[str, ...]:
    """Sentences in the earlier session most likely to carry the superseded value.

    Ranked by similarity to whichever later-session sentence states the gold, on
    the observation that a person restating an updated fact tends to reuse the
    phrasing they used the first time.
    """
    earlier, later = pair_sessions
    keys = _gold_keys(gold)
    anchors = [s for s in later.sentences() if any(k in s for k in keys)] or list(
        later.sentences()
    )
    scored: list[tuple[float, str]] = []
    for sentence in earlier.sentences():
        best = max(
            difflib.SequenceMatcher(None, anchor, sentence).ratio() for anchor in anchors
        )
        scored.append((best, sentence))
    scored.sort(reverse=True)
    return tuple(sentence for score, sentence in scored[:3] if score > 0.25)


def update_pairs(instances: Iterable[dict[str, Any]]) -> list[UpdatePair]:
    """Every knowledge-update instance whose two answer sessions are well formed."""
    pairs: list[UpdatePair] = []
    for instance in instances:
        if instance.get("question_type") != "knowledge-update":
            continue
        # LongMemEval's abstention items ("_abs") have "the information provided
        # is not enough" as gold: there is no updated value, so no supersession.
        if str(instance["question_id"]).endswith("_abs"):
            continue
        answer_ids = set(instance["answer_session_ids"])
        sessions = [s for s in _sessions(instance) if s.session_id in answer_ids]
        if len(sessions) != 2:
            continue
        earlier, later = sorted(sessions, key=lambda s: s.recorded_at)
        pair = UpdatePair(
            question_id=instance["question_id"],
            question=instance["question"],
            asked_at=parse_date(instance["question_date"]),
            new_value=str(instance["answer"]),
            earlier=earlier,
            later=later,
            old_value_candidates=candidates_for((earlier, later), str(instance["answer"])),
        )
        if pair.interval_is_ordered:
            pairs.append(pair)
    return pairs


def load(path: Path) -> list[UpdatePair]:
    return update_pairs(json.loads(path.read_text(encoding="utf-8")))


# --- Supersession extraction ------------------------------------------------
#
# Two models extract independently; each value must occur verbatim in the
# session it is attributed to. Agreement between the two, plus those checks, is
# what lets a label be accepted without a person. A single model's answer is
# never ground truth on its own, because the systems this workload scores are
# LLM-backed too.

EXTRACTION_PROMPT = """You are labelling a benchmark. A user told an assistant a fact
in an EARLIER conversation, and stated a different value for the same thing in a
LATER conversation. You are given a question about it, the benchmark's answer to
that question, and the user's turns from both conversations.

Return:
- "attribute": a few words naming what changed (e.g. "5K personal best time").
- "earlier_value": the value as the user stated it in the EARLIER conversation.
- "later_value": the value as the user stated it in the LATER conversation.
- "question_asks_for": "later", "earlier", "both", or "neither" -- which of the
  two values the question is asking about.

Rules:
- Copy each value EXACTLY, character for character, from its own conversation:
  earlier_value from the EARLIER turns, later_value from the LATER turns. Use the
  shortest span that states the value (e.g. "27:12", "under my bed"), not a
  sentence.
- If a conversation does not state its value for this thing, use null for it.

Respond with JSON only: {"attribute": ..., "earlier_value": ..., "later_value": ...,
"question_asks_for": ...}"""

ASKS_FOR = ("later", "earlier", "both", "neither")


def extraction_messages(pair: UpdatePair) -> list[dict[str, str]]:
    earlier = "\n".join(f"- {turn}" for turn in pair.earlier.user_turns)
    later = "\n".join(f"- {turn}" for turn in pair.later.user_turns)
    user = (
        f"QUESTION: {pair.question}\n"
        f"BENCHMARK ANSWER: {pair.new_value}\n\n"
        f"EARLIER CONVERSATION ({pair.earlier.recorded_at:%Y-%m-%d}), user turns:\n"
        f"{earlier}\n\n"
        f"LATER CONVERSATION ({pair.later.recorded_at:%Y-%m-%d}), user turns:\n{later}"
    )
    return [
        {"role": "system", "content": EXTRACTION_PROMPT},
        {"role": "user", "content": user},
    ]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def check_extraction(
    pair: UpdatePair, earlier_value: str | None, later_value: str | None
) -> str:
    """Why an extracted supersession cannot be used, or "" if it can.

    Deterministic, so a hallucinated or misattributed value is rejected rather
    than trusted: each value must occur verbatim in the session it is attributed
    to -- which is also what fixes its transaction time -- and the two must
    differ, or nothing was superseded.
    """
    if earlier_value is None or later_value is None:
        return "a session states no value"
    old, new = _norm(earlier_value), _norm(later_value)
    if not old or not new:
        return "empty value"
    if old not in _norm(" ".join(pair.earlier.user_turns)):
        return "earlier value not verbatim in the earlier session"
    if new not in _norm(" ".join(pair.later.user_turns)):
        return "later value not verbatim in the later session"
    if old == new:
        return "values are identical"
    return ""
