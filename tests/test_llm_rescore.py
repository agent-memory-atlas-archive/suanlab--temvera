"""The rescoring rules of scripts/llm_rescore.py, without calling any model."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "llm_rescore", ROOT / "scripts" / "llm_rescore.py"
)
rescore = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rescore)


def test_reader_output_is_scored_like_any_answer() -> None:
    assert rescore.exact("Accra", ["Accra"], ["Cairo"])
    assert not rescore.exact("Accra, later Cairo", ["Accra"], ["Cairo"])
    assert rescore.exact("UNKNOWN", [], ["Cairo"])  # abstention is correct
    assert not rescore.exact("Cairo", [], ["Cairo"])


def test_judged_value_must_name_the_expected_value_alone() -> None:
    assert rescore.judged("Accra", ["Accra"], ["Cairo"])
    assert not rescore.judged("AMBIGUOUS", ["Accra"], ["Cairo"])
    assert not rescore.judged("NONE", ["Accra"], ["Cairo"])
    assert not rescore.judged("Cairo", ["Accra"], ["Cairo"])
    assert rescore.judged("NONE", [], ["Cairo"])
    assert not rescore.judged("Cairo", [], ["Cairo"])


def test_judge_reply_parsing_tolerates_broken_json() -> None:
    assert rescore._value("judge", '{"value": "Accra"}') == "Accra"
    assert rescore._value("judge", 'sure: "value": "Accra"') == "Accra"
    assert rescore._value("judge", "nothing") == ""
    assert rescore._value("reader", "  Accra \n") == "Accra"


def test_prompts_are_pinned() -> None:
    assert len(rescore.prompt_hash("reader")) == 64
    assert rescore.prompt_hash("reader") != rescore.prompt_hash("judge")
