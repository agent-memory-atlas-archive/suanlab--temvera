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


# --- Queries, scoring and replay ---------------------------------------------
#
# Each labelled supersession yields up to three questions, asked under
# forward-checkpoint replay with the sessions' real timestamps:
#
#   transaction_as_of  after the earlier session only   -> earlier value
#   current            after both, at question time     -> later value
#   valid_time         after both, about a day between  -> earlier value
#
# The first is a control: a store holding one session should recall it. The
# last is the one the paper is about -- the store knows both values and must
# answer for a point in time the later one does not cover.

CATEGORIES = ("transaction_as_of", "current", "valid_time")


@dataclass(frozen=True, slots=True)
class BitemporalQuery:
    case_id: str
    category: str
    query_text: str
    after: str  # which session has been ingested when the question is asked
    valid_at: datetime
    transaction_at: datetime
    expected: str
    stale: str


def _utc(moment: datetime) -> datetime:
    """LongMemEval timestamps carry no zone; they are read as UTC throughout."""
    from datetime import timezone

    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def as_of_day(earlier: datetime, later: datetime) -> datetime | None:
    """A calendar day on which the earlier value held and the later did not yet.

    None when both sessions fall on one day: a date-granular question cannot
    then separate the two values, so no valid-time question is asked.
    """
    first, second = earlier.date(), later.date()
    if first >= second:
        return None
    day = first + (second - first) // 2
    return datetime(day.year, day.month, day.day, 12)


def queries_for(pair: UpdatePair, label: dict[str, Any]) -> list[BitemporalQuery]:
    attribute = label["attribute"]
    old, new = label["earlier_value"], label["later_value"]
    t1, t2, asked = (_utc(t) for t in (pair.earlier.recorded_at, pair.later.recorded_at,
                                       pair.asked_at))
    between = t1 + (t2 - t1) / 2
    queries = [
        BitemporalQuery(f"{pair.question_id}:tx", "transaction_as_of",
                        f"What is my {attribute}?", "earlier", between, between, old, new),
        BitemporalQuery(f"{pair.question_id}:cur", "current",
                        f"What is my {attribute} now?", "later", asked, asked, new, old),
    ]
    day = as_of_day(pair.earlier.recorded_at, pair.later.recorded_at)
    if day is not None:
        queries.append(BitemporalQuery(
            f"{pair.question_id}:vt", "valid_time",
            f"What was my {attribute} on {day:%B} {day.day}, {day.year}?",
            "later", _utc(day), asked, old, new,
        ))
    return queries


_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20",
}
_DIGIT_WORDS = {digit: word for word, digit in _NUMBER_WORDS.items()}


def _clean(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return " ".join(text.split())


def value_forms(value: str) -> set[str]:
    """Surface forms that count as stating ``value``.

    Real answers paraphrase where synthetic ones do not: "four bikes" for "4",
    "every 2 weeks" for "every two weeks", "Fridays" for "Friday". Forms are
    generated conservatively -- articles, number words up to twenty, a trailing
    plural, a leading currency sign -- so a match still means the value.
    """
    base = _clean(value).strip(" .,;:!?\"'")
    forms = {base}
    for article in ("the ", "a ", "an ", "my "):
        if base.startswith(article):
            forms.add(base[len(article):])
    if base.startswith("$"):
        forms.add(base[1:])
    for form in list(forms):
        tokens = form.split()
        forms.add(" ".join(_NUMBER_WORDS.get(t, t) for t in tokens))
        forms.add(" ".join(_DIGIT_WORDS.get(t, t) for t in tokens))
    for form in list(forms):
        if form.endswith("s") and len(form) > 3:
            forms.add(form[:-1])
    return {form for form in forms if form}


def mentions(text: str, value: str) -> bool:
    """Whether ``text`` states ``value``, on token boundaries.

    Boundaries matter because the values are often bare numbers. A digit run
    joined to another by a date, time or decimal separator is part of a larger
    token, so "17" does not match "2023-05-17", "20" does not match "20:21",
    and "4" does not match "4.5". Missing that once would have been fatal here:
    every ingested line starts "[2023/05/25 (Thu) 20:21]", so a bare value of
    25, 20 or 21 would have read as present in any answer that echoes a line.
    """
    haystack = _clean(text)
    return any(
        re.search(
            rf"(?<![a-z0-9])(?<![0-9][-/:.]){re.escape(form)}(?![a-z0-9])(?![-/:.][0-9])",
            haystack,
        )
        for form in value_forms(value)
    )


def score(answer: str, expected: str, stale: str) -> dict[str, bool]:
    present_expected = mentions(answer, expected)
    present_stale = mentions(answer, stale)
    return {
        "present_expected": present_expected,
        "present_stale": present_stale,
        "exact": present_expected and not present_stale,
    }


def _turns(instance: dict[str, Any], session_id: str) -> list[tuple[datetime, str]]:
    """A session's turns, both roles, as dated lines one minute apart.

    Both roles are ingested because that is what a deployed memory sees; the
    session's own timestamp is kept, which is what lets a time-aware store place
    the fact.
    """
    from datetime import timedelta

    index = instance["haystack_session_ids"].index(session_id)
    start = _utc(parse_date(instance["haystack_dates"][index]))
    stamp = instance["haystack_dates"][index]
    lines = []
    for offset, turn in enumerate(instance["haystack_sessions"][index]):
        content = (turn.get("content") or "").strip()
        if content:
            lines.append((start + timedelta(minutes=offset),
                          f"[{stamp}] {turn.get('role', 'user')}: {content}"))
    return lines


def run_lme_bitemporal(
    config: dict[str, Any], system_factory: Any, *, system_name: str
) -> dict[str, Any]:
    """Replay each labelled LongMemEval supersession into a fresh store and score it.

    Alongside the system, a full-context baseline answers every question with
    everything ingested so far: it shows whether the information was available
    at all, so a system's miss can be told apart from an absent fact.
    """
    from .nl_workload import NLQueryCase, WorkloadTurn
    from .telemetry import Meter, measure_openai

    raw = {inst["question_id"]: inst
           for inst in json.loads(Path(config["dataset_path"]).read_text(encoding="utf-8"))}
    labels = json.loads(Path(config["labels_path"]).read_text(encoding="utf-8"))["labels"]
    pairs = {pair.question_id: pair for pair in update_pairs(raw.values())}
    question_ids = sorted(qid for qid in labels if qid in pairs)
    if config.get("limit"):
        question_ids = question_ids[: int(config["limit"])]

    transcript: list[dict[str, Any]] = []
    meter = Meter()
    for qid in question_ids:
        pair, label, instance = pairs[qid], labels[qid], raw[qid]
        queries = queries_for(pair, label)
        # The later value cannot legitimately appear before the update, so any
        # occurrence in the earlier session is incidental -- usually a small
        # number word in the assistant's advice ("here are five tips"). Such a
        # label can score a correct answer as stale, so results are also
        # reported without them.
        incidental = any(
            mentions(text, label["later_value"])
            for _, text in _turns(instance, pair.earlier.session_id)
        )
        system = system_factory(qid)
        seen: list[str] = []
        with measure_openai(meter):
            system.reset()
            for phase, session in (("earlier", pair.earlier), ("later", pair.later)):
                for moment, line in _turns(instance, session.session_id):
                    with meter.time_ingest():
                        system.ingest(WorkloadTurn(recorded_at=moment, text=line,
                                                   event_id=f"{qid}:{len(seen):04d}"))
                    seen.append(line)
                for query in (q for q in queries if q.after == phase):
                    with meter.time_query():
                        answer = system.answer(NLQueryCase(
                            case_id=query.case_id, query_text=query.query_text,
                            subject="", attribute=label["attribute"],
                            valid_at=query.valid_at, transaction_at=query.transaction_at,
                            expected_values=frozenset({query.expected}),
                            stale_values=frozenset({query.stale}),
                            category=query.category,
                        ))
                    full = "\n".join(seen)
                    transcript.append({
                        "case_id": query.case_id, "question_id": qid,
                        "category": query.category, "system": system_name,
                        "query": query.query_text, "answer": answer,
                        "expected_values": [query.expected], "stale_values": [query.stale],
                        "label_method": label.get("method", ""),
                        "incidental_value": incidental,
                        **score(answer, query.expected, query.stale),
                        "full_context": score(full, query.expected, query.stale),
                    })
        if hasattr(system, "close"):
            system.close()

    summary: dict[str, Any] = {}
    for category in CATEGORIES:
        rows = [row for row in transcript if row["category"] == category]
        clean = [row for row in rows if not row["incidental_value"]]
        summary[category] = {
            "cases_without_incidental_values": len(clean),
            "exact_without_incidental_values": sum(row["exact"] for row in clean),
            "cases": len(rows),
            "exact": sum(row["exact"] for row in rows),
            "present_expected": sum(row["present_expected"] for row in rows),
            "present_stale": sum(row["present_stale"] for row in rows),
            "full_context_exact": sum(row["full_context"]["exact"] for row in rows),
            "full_context_expected": sum(row["full_context"]["present_expected"]
                                         for row in rows),
        }
    return {
        "workload": "lme_bitemporal",
        "replay": "transaction_checkpoint",
        "naturalized": False,
        "instances": len(question_ids),
        "rows": [{"system": system_name, "category": c, **summary[c]} for c in CATEGORIES],
        "summary": summary,
        "telemetry": meter.as_dict(),
        "transcript": transcript,
    }
