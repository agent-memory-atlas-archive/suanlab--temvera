"""H17: deletion when one stored unit mixes what must go with what must stay.

In the H10/H13 histories every unit held one person's one statement, so a caller
that checks the name could delete exactly the right units (E-104). The paper
says units that mix people or attributes are untested; this tests them. Each
history (12 people, natural names) is rendered one of three ways:

* ``attributes`` -- one turn per person states both their home city and their
  employer; the home city of every second person is to be deleted, so their
  employer shares its unit;
* ``people`` -- one turn per pair states both people's home cities; the first
  person's is to be deleted, so the second's shares its unit;
* ``shared`` -- one turn per statement, but each pair has the same home city;
  the first person's is to be deleted, so the second's shares its value.

Every person's attributes are asked once ingest is done, the deletion is made
through the system's API by a caller, and the same questions are asked again,
so retention is conditional on what the store answered before (no comparison
across separately ingested stores, unlike E-104). Two callers: ``api-oracle``
deletes every unit whose text holds a value to delete; ``api-verified``
searches for the person's attribute and deletes the returned units that name
the person. Systems: Mem0, which deletes extracted facts, and Hindsight, which
deletes whole documents.

    python scripts/deletion_mixed.py {mem0,hindsight} experiments/runs/h17-deletion-mixed-<system>-v1
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from temvera.deletion_study import DRIVERS
from temvera.experiment import seal_run
from temvera.generator import generate_histories
from temvera.model import Operation
from temvera.nl_workload import WorkloadTurn, naturalize_events

SEEDS = (11, 12, 13, 14, 15)
PEOPLE = 12
UNITS = ("attributes", "people", "shared")
CALLERS = ("api-oracle", "api-verified")
if os.environ.get("TEMVERA_H17_SMOKE"):
    # Plumbing check on a history the study does not use; never written under experiments/.
    SEEDS, PEOPLE = (99,), 4


@dataclasses.dataclass(frozen=True, slots=True)
class Fact:
    subject: str
    attribute: str
    value: str
    role: str  # "purge", "colocated" (shares a unit or value with a purged fact) or "other"


def _day(when) -> str:
    return when.date().isoformat()


def history(seed: int, unit: str) -> tuple[list[WorkloadTurn], list[Fact]]:
    """Turns and the facts they state, with each fact's role."""
    events = naturalize_events(generate_histories(seed=seed, entities=PEOPLE, revisions=1,
                                                  attributes=2, distinct_values=True), pools="large")
    ingests = [e for e in events if e.operation is Operation.INGEST]
    people = sorted({e.subject for e in ingests}, key=lambda s: [e.subject for e in ingests].index(s))
    by = {(e.subject, e.attribute): e for e in ingests}
    attributes = {e.attribute for e in ingests}
    city = "home city"
    (employer,) = attributes - {city}
    turns, facts = [], []
    for i in range(0, len(people), 2):
        first, second = people[i], people[i + 1]
        if unit == "attributes":
            for person, doomed in ((first, True), (second, False)):
                c, w = by[(person, city)], by[(person, employer)]
                turns.append(WorkloadTurn(c.recorded_at, (
                    f"[recorded {_day(c.recorded_at)}] {person}'s {city} is {c.value} and "
                    f"{person}'s {employer} is {w.value}, both valid from {_day(c.valid_from)}."),
                    c.event_id))
                facts += [Fact(person, city, c.value, "purge" if doomed else "other"),
                          Fact(person, employer, w.value, "colocated" if doomed else "other")]
        elif unit == "people":
            a, b = by[(first, city)], by[(second, city)]
            turns.append(WorkloadTurn(a.recorded_at, (
                f"[recorded {_day(a.recorded_at)}] {first}'s {city} is {a.value}, and "
                f"{second}'s {city} is {b.value}, both valid from {_day(a.valid_from)}."),
                a.event_id))
            facts += [Fact(first, city, a.value, "purge"), Fact(second, city, b.value, "colocated")]
        elif unit == "shared":
            a = by[(first, city)]
            for person, role, offset in ((first, "purge", 0), (second, "colocated", 1)):
                at = a.recorded_at + timedelta(hours=offset)
                turns.append(WorkloadTurn(at, (
                    f"[recorded {_day(at)}] {person}'s {city} is {a.value}, valid from "
                    f"{_day(a.valid_from)}."), f"{a.event_id}-{person}"))
                facts.append(Fact(person, city, a.value, role))
        else:
            raise ValueError(unit)
    return sorted(turns, key=lambda t: (t.recorded_at, t.event_id)), facts


def query(fact: Fact) -> str:
    return f"What is {fact.subject}'s {fact.attribute}?"


def present(answer: str, fact: Fact) -> bool:
    """The fact's value in the answer to its own question. In ``shared`` the
    value is also the other person's, so for the purged person a unit must also
    name them (``named``); both readings are kept."""
    return fact.value.casefold() in answer.casefold()


def named(answer: str, fact: Fact) -> bool:
    return any(fact.value.casefold() in part.casefold() and fact.subject.casefold() in part.casefold()
               for part in answer.split(" | "))


def measure(driver, unit: str, caller: str, turns: list[WorkloadTurn], facts: list[Fact]) -> dict:
    for turn in turns:
        driver.ingest(turn)
    before = {query(f): driver.answer(query(f)) for f in facts}
    doomed = [f for f in facts if f.role == "purge"]
    if caller == "api-oracle":
        deleted = driver.delete_oracle(tuple(f.value for f in doomed))
    elif caller == "api-verified":
        deleted = sum(driver.delete_verified(query(f), f.subject) for f in doomed)
    else:
        raise ValueError(caller)
    after = {query(f): driver.answer(query(f)) for f in facts}
    rows = [{"subject": f.subject, "attribute": f.attribute, "value": f.value, "role": f.role,
             "before": present(before[query(f)], f), "after": present(after[query(f)], f),
             "before_named": named(before[query(f)], f), "after_named": named(after[query(f)], f),
             "answer_before": before[query(f)], "answer_after": after[query(f)]} for f in facts]
    return {"unit": unit, "caller": caller, "units_deleted": deleted, "facts": rows,
            "worker_errors": driver.errors(), **driver.extra()}


def tally(records: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for record in records:
        key = f"{record['unit']}|{record['caller']}"
        entry = out.setdefault(key, {"purge": 0, "purge_answered_before": 0, "purge_left_after": 0,
                                     "purge_left_after_named": 0, "colocated_before": 0,
                                     "colocated_kept": 0, "other_before": 0, "other_kept": 0})
        for f in record["facts"]:
            if f["role"] == "purge":
                entry["purge"] += 1
                entry["purge_answered_before"] += f["before"]
                entry["purge_left_after"] += f["after"]
                entry["purge_left_after_named"] += f["after_named"]
            else:
                entry[f"{f['role']}_before"] += f["before"]
                entry[f"{f['role']}_kept"] += f["before"] and f["after"]
    return out


def main(system: str, output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    if os.environ.get("TEMVERA_H17_SMOKE") and "experiments" in out.resolve().parts:
        raise SystemExit("smoke runs are never written under experiments/")
    config = {"model": "gpt-4o-mini", "embed_model": "text-embedding-3-small",
              "hindsight_url": os.environ.get("HINDSIGHT_URL", "http://localhost:8888")}
    records = []
    with tempfile.TemporaryDirectory() as tmp:
        for seed in SEEDS:
            for unit in UNITS:
                turns, facts = history(seed, unit)
                for caller in CALLERS:
                    driver = DRIVERS[system](config, f"h17-{seed}-{unit}-{caller}", Path(tmp))
                    try:
                        records.append({"seed": seed, **measure(driver, unit, caller, turns, facts)})
                    finally:
                        driver.close()
    out.mkdir(parents=True)
    with (out / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    (out / "results.json").write_text(json.dumps({"system": system, "summary": tally(records)},
                                                 indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal_run(out, config={"benchmark": f"temvera-h17-deletion-mixed-{system}-v1", "system": system,
                          "seeds": list(SEEDS), "people": PEOPLE, "units": list(UNITS),
                          "callers": list(CALLERS), "model": config["model"],
                          "embed_model": config["embed_model"]},
             command=f"python scripts/deletion_mixed.py {system} {output}")
    print(json.dumps(tally(records), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
