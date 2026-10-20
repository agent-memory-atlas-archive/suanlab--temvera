"""E7: external-validity check on LongMemEval natural conversations.

The synthetic E1 grids characterise Mem0 as strong on transaction-scoped
*current* queries and weak on *historical* valid-time reasoning (E-053). This
module tests whether that asymmetry reproduces on LongMemEval's conversations
(simulated by an LLM in self-chat, then edited by annotators) rather than on
histories we generate, using the LongMemEval oracle split (evidence
sessions only, so ingestion stays small).

Two question types are contrasted:

* ``knowledge-update`` — the fact changed and the current value is wanted, which
  the synthetic result predicts the system handles relatively well;
* ``temporal-reasoning`` — requires reasoning over when things held, which the
  synthetic result predicts it handles poorly.

Scoring is deterministic gold-answer substring presence in the *retrieved*
memories. This is a retrieval-level signal, **not** LongMemEval's official
GPT-4o-judged QA metric, and the two must never be reported as comparable
(E-036). The dataset is downloaded locally and never redistributed; only
aggregate numbers are written to the run.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class InstanceScore:
    question_id: str
    question_type: str
    sessions: int
    gold_present: bool
    token_recall: float


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def gold_signal(answer: str, retrieved: str) -> tuple[bool, float]:
    """Exact substring presence plus content-token recall of the gold answer."""
    folded = retrieved.casefold()
    if answer.casefold() in folded:
        return True, 1.0
    gold = [t for t in _tokens(answer) if len(t) > 2]
    if not gold:
        return False, 0.0
    have = set(_tokens(retrieved))
    return False, sum(t in have for t in gold) / len(gold)


def load_instances(
    path: Path, *, question_types: tuple[str, ...], limit: int
) -> list[dict[str, Any]]:
    """Deterministically take the first `limit` instances per question type."""
    data = json.loads(path.read_text(encoding="utf-8"))
    chosen: list[dict[str, Any]] = []
    for question_type in question_types:
        matching = sorted(
            (row for row in data if row["question_type"] == question_type),
            key=lambda row: str(row["question_id"]),
        )
        chosen.extend(matching[:limit])
    return chosen


def session_turns(instance: dict[str, Any]) -> list[str]:
    """Flatten an instance's evidence sessions into dated conversation lines."""
    lines: list[str] = []
    dates = instance.get("haystack_dates") or []
    for index, session in enumerate(instance["haystack_sessions"]):
        stamp = dates[index] if index < len(dates) else ""
        for turn in session:
            role = turn.get("role", "user")
            content = (turn.get("content") or "").strip()
            if content:
                lines.append(f"[{stamp}] {role}: {content}")
    return lines


def run_longmemeval(
    config: dict[str, Any], progress_path: Path | None = None
) -> dict[str, Any]:
    from .mem0_adapter import Mem0System, default_mem0_config
    from .nl_workload import NLQueryCase, WorkloadTurn

    dataset = Path(config["dataset_path"])
    types = tuple(config.get("question_types", ("knowledge-update", "temporal-reasoning")))
    limit = int(config.get("limit_per_type", 10))
    model = config.get("model", "gpt-4o-mini")
    embed_model = config.get("embed_model", "text-embedding-3-small")
    search_limit = int(config.get("search_limit", 10))

    instances = load_instances(dataset, question_types=types, limit=limit)
    scores: list[InstanceScore] = []
    from datetime import datetime, timedelta, timezone

    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    # Mem0 defaults to a single global ~/.mem0/history.db. Any other Mem0
    # process running at the same time contends for it and can raise
    # "attempt to write a readonly database", silently dropping memories and
    # corrupting the measurement, so each run gets its own database file.
    # Keep the database out of the run directory: it embeds the ingested
    # third-party conversation text, which must not be sealed into a
    # distributable artifact.
    import tempfile

    history_db = str(Path(tempfile.mkdtemp(prefix="mem0-lme-")) / "history.db")
    for position, instance in enumerate(instances):
        system = Mem0System(
            config=default_mem0_config(
                model=model, embed_model=embed_model, history_db_path=history_db
            ),
            user_id=f"{config.get('user_id', 'temvera-e7')}-{position:03d}",
            search_limit=search_limit,
        )
        system.reset()
        for offset, line in enumerate(session_turns(instance)):
            system.ingest(
                WorkloadTurn(
                    recorded_at=base + timedelta(minutes=offset),
                    text=line,
                    event_id=f"lme-{position:03d}-{offset:04d}",
                )
            )
        retrieved = system.answer(
            NLQueryCase(
                case_id=str(instance["question_id"]),
                query_text=str(instance["question"]),
                subject="",
                attribute="",
                valid_at=base,
                transaction_at=base,
                expected_values=frozenset(),
                stale_values=frozenset(),
                category=str(instance["question_type"]),
            )
        )
        present, recall = gold_signal(str(instance["answer"]), retrieved)
        score = InstanceScore(
            question_id=str(instance["question_id"]),
            question_type=str(instance["question_type"]),
            sessions=len(instance["haystack_sessions"]),
            gold_present=present,
            token_recall=recall,
        )
        scores.append(score)
        if progress_path is not None:
            # Stream each instance so an interrupted run still leaves data.
            with progress_path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "question_id": score.question_id,
                            "question_type": score.question_type,
                            "sessions": score.sessions,
                            "gold_present": score.gold_present,
                            "token_recall": round(score.token_recall, 3),
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )

    by_type: dict[str, dict[str, float]] = {}
    for question_type in types:
        selected = [s for s in scores if s.question_type == question_type]
        if not selected:
            continue
        by_type[question_type] = {
            "instances": len(selected),
            "gold_present_rate": sum(s.gold_present for s in selected) / len(selected),
            "mean_token_recall": sum(s.token_recall for s in selected) / len(selected),
        }
    return {
        "dataset": dataset.name,
        "scorer": "deterministic gold substring + token recall over retrieved memories; NOT LongMemEval official GPT-4o QA judge (E-036)",
        "backbone": {"llm_model": model, "embed_model": embed_model, "system": "mem0"},
        "instances": len(scores),
        "by_question_type": by_type,
        "per_instance": [
            {
                "question_id": s.question_id,
                "question_type": s.question_type,
                "sessions": s.sessions,
                "gold_present": s.gold_present,
                "token_recall": round(s.token_recall, 3),
            }
            for s in scores
        ],
    }
