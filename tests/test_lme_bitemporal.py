"""The real-data workload is derived, so the derivation is tested."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from temvera.lme_bitemporal import (
    Session,
    candidates_for,
    check_extraction,
    parse_date,
    update_pairs,
)


def _session(sid: str, when: str, *turns: str) -> Session:
    return Session(sid, parse_date(when), turns)


def _instance(**over):
    base = {
        "question_id": "q1",
        "question_type": "knowledge-update",
        "question": "What is my best time?",
        "question_date": "2023/06/01 (Thu) 00:58",
        "answer": "25:50",
        "answer_session_ids": ["s1", "s2"],
        "haystack_session_ids": ["s0", "s1", "s2"],
        "haystack_dates": [
            "2023/05/20 (Sat) 09:00",
            "2023/05/25 (Thu) 20:21",
            "2023/05/27 (Sat) 10:20",
        ],
        "haystack_sessions": [
            [{"role": "user", "content": "Unrelated chatter about tennis."}],
            [{"role": "user", "content": "I set a personal best time of 27:12."}],
            [{"role": "user", "content": "I hope to beat my personal best of 25:50."}],
        ],
    }
    base.update(over)
    return base


def test_pair_orders_sessions_by_time_not_by_listed_order() -> None:
    reversed_dates = _instance(
        haystack_dates=[
            "2023/05/20 (Sat) 09:00",
            "2023/05/27 (Sat) 10:20",
            "2023/05/25 (Thu) 20:21",
        ]
    )
    pair = update_pairs([reversed_dates])[0]
    assert pair.earlier.recorded_at < pair.later.recorded_at


def test_only_answer_sessions_are_used() -> None:
    pair = update_pairs([_instance()])[0]
    assert {pair.earlier.session_id, pair.later.session_id} == {"s1", "s2"}


def test_instances_whose_update_postdates_the_question_are_dropped() -> None:
    """An as-of query needs the supersession to precede the question."""
    late_update = _instance(question_date="2023/05/26 (Fri) 08:00")
    assert update_pairs([late_update]) == []


def test_other_question_types_are_ignored() -> None:
    assert update_pairs([_instance(question_type="multi-session")]) == []


def test_candidate_ranks_the_sentence_that_carries_the_superseded_value() -> None:
    earlier = _session(
        "s1",
        "2023/05/25 (Thu) 20:21",
        "I set a personal best time of 27:12.",
        "The weather was cold.",
    )
    later = _session("s2", "2023/05/27 (Sat) 10:20", "I hope to beat my personal best of 25:50.")
    top = candidates_for((earlier, later), "25 minutes and 50 seconds (or 25:50)")[0]
    assert "27:12" in top


@pytest.mark.parametrize("text", ["2023/05/25 (Thu) 20:21", "2023/12/31 (Sun) 23:59"])
def test_dates_round_trip(text: str) -> None:
    assert isinstance(parse_date(text), datetime)


def _pair():
    return update_pairs([_instance()])[0]


def test_supersession_stated_verbatim_in_each_session_is_accepted() -> None:
    assert check_extraction(_pair(), "27:12", "25:50") == ""


def test_earlier_value_must_come_from_the_earlier_session() -> None:
    """Attribution fixes transaction time, so the wrong session is a wrong label."""
    reason = check_extraction(_pair(), "25:50", "25:50")
    assert reason == "earlier value not verbatim in the earlier session"


def test_hallucinated_later_value_is_rejected() -> None:
    reason = check_extraction(_pair(), "27:12", "24:59")
    assert reason == "later value not verbatim in the later session"


def test_identical_values_are_not_a_supersession() -> None:
    same = _instance(
        haystack_sessions=[
            [{"role": "user", "content": "Unrelated chatter about tennis."}],
            [{"role": "user", "content": "My best is 25:50 already."}],
            [{"role": "user", "content": "I hope to beat my personal best of 25:50."}],
        ]
    )
    assert check_extraction(update_pairs([same])[0], "25:50", "25:50") == (
        "values are identical"
    )


def test_missing_value_is_reported_not_accepted() -> None:
    assert check_extraction(_pair(), None, "25:50") == "a session states no value"


def test_abstention_items_are_not_update_pairs() -> None:
    """Their gold is "not enough information", so there is no superseded value."""
    assert update_pairs([_instance(question_id="q1_abs")]) == []


# --- queries, scoring, replay ---------------------------------------------

from datetime import datetime as _dt  # noqa: E402

from temvera.lme_bitemporal import (  # noqa: E402
    as_of_day,
    mentions,
    queries_for,
    run_lme_bitemporal,
    score,
)

_LABEL = {"attribute": "5K personal best time", "earlier_value": "27:12",
          "later_value": "25:50", "question_asks_for": "later"}


def test_as_of_day_lies_strictly_before_the_update() -> None:
    assert as_of_day(_dt(2023, 5, 25, 20), _dt(2023, 5, 27, 10)).date().day == 26
    assert as_of_day(_dt(2023, 5, 25, 20), _dt(2023, 5, 26, 10)).date().day == 25


def test_same_day_supersession_gets_no_valid_time_question() -> None:
    assert as_of_day(_dt(2023, 5, 25, 9), _dt(2023, 5, 25, 18)) is None


def test_each_query_expects_the_value_true_at_its_point_in_time() -> None:
    by_category = {q.category: q for q in queries_for(_pair(), _LABEL)}
    assert by_category["transaction_as_of"].expected == "27:12"
    assert by_category["transaction_as_of"].after == "earlier"
    assert (by_category["current"].expected, by_category["current"].stale) == ("25:50", "27:12")
    assert (by_category["valid_time"].expected, by_category["valid_time"].stale) == (
        "27:12", "25:50")
    assert "May 26, 2023" in by_category["valid_time"].query_text


@pytest.mark.parametrize("text, value, expected", [
    ("Session on 2023-05-17 went well", "17", False),
    ("I caught 14 bass", "4", False),
    ("I own 4 bikes", "four", True),
    ("I have four bikes now", "4", True),
    ("class moved to Friday", "Fridays", True),
    ("bought a house for 325,000", "$325,000", True),
    ("therapy every 2 weeks", "every two weeks", True),
    ("Personal best: 25:50", "25:50", True),
    ("[2023/05/25 (Thu) 20:21] user: hello", "25", False),
    ("[2023/05/25 (Thu) 20:21] user: hello", "20", False),
    ("[2023/05/25 (Thu) 20:21] user: hello", "21", False),
    ("I ran 4.5 miles", "4", False),
    ("I ran 4 miles.", "4", True),
    ("Now I have 25 postcards.", "25", True),
])
def test_mentions_matches_paraphrase_but_not_digits_inside_other_tokens(
    text: str, value: str, expected: bool
) -> None:
    assert mentions(text, value) is expected


def test_exact_requires_the_value_and_forbids_the_superseded_one() -> None:
    assert score("best is 25:50", "25:50", "27:12")["exact"]
    assert not score("was 27:12, now 25:50", "25:50", "27:12")["exact"]


class _EchoSystem:
    """Returns everything it has ingested: a stand-in for a store that keeps all."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def reset(self) -> None:
        self.lines = []

    def ingest(self, turn) -> None:
        self.lines.append(turn.text)

    def answer(self, case) -> str:
        return "\n".join(self.lines)


def test_replay_hides_the_later_session_from_the_earlier_checkpoint(tmp_path) -> None:
    dataset = tmp_path / "lme.json"
    dataset.write_text(json.dumps([_instance()]))
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"labels": {"q1": _LABEL}}))
    result = run_lme_bitemporal(
        {"dataset_path": str(dataset), "labels_path": str(labels)},
        lambda label: _EchoSystem(), system_name="echo",
    )
    rows = {row["category"]: row for row in result["transcript"]}
    # before the update is ingested the store can only know the old value
    assert rows["transaction_as_of"]["exact"]
    assert not rows["transaction_as_of"]["present_stale"]
    # a store that keeps everything and filters nothing fails both later questions
    assert not rows["current"]["exact"] and not rows["valid_time"]["exact"]
    assert rows["current"]["present_expected"] and rows["current"]["present_stale"]
    assert result["summary"]["valid_time"]["cases"] == 1
    # latency is part of what the paper reports, so the runner must record it
    assert result["telemetry"]["ingest_latency"]["n"] == 2  # one turn per answer session
    assert result["telemetry"]["query_latency"]["n"] == 3


def test_later_value_appearing_before_the_update_is_flagged_incidental(tmp_path) -> None:
    leaky = _instance(haystack_sessions=[
        [{"role": "user", "content": "Unrelated chatter about tennis."}],
        [{"role": "user", "content": "I set a personal best time of 27:12."},
         {"role": "assistant", "content": "Try intervals; some runners hit 25:50."}],
        [{"role": "user", "content": "I hope to beat my personal best of 25:50."}],
    ])
    dataset = tmp_path / "lme.json"
    dataset.write_text(json.dumps([leaky]))
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"labels": {"q1": _LABEL}}))
    result = run_lme_bitemporal(
        {"dataset_path": str(dataset), "labels_path": str(labels)},
        lambda label: _EchoSystem(), system_name="echo",
    )
    assert all(row["incidental_value"] for row in result["transcript"])
    assert result["summary"]["current"]["cases_without_incidental_values"] == 0
