"""H16: store size and revision load, separated; one question, three read paths, their cost.

H14 grew one store and asked new questions at each checkpoint, so its
checkpoints changed store size, revisions per person and the probe set together
(E-107). Here the questions are fixed and only one factor moves at a time.

* Focal history: 14 people x 3 attributes (42 keys), each revised ``r`` times,
  with natural names and distinct values. Every store holds all of it.
* Distractors: other people, 3 attributes, 3 values each (15 turns a person),
  drawn from one seeded history and nested -- a smaller store's distractors are
  a prefix of a larger one's. They span the same dates as the focal history and
  are interleaved with it in recorded order.
* Size axis (``r`` = 3): about 300, 1,005 and 3,000 turns. The 84 questions and
  their answers are identical at the three sizes.
* Revision axis (about 1,000 turns): ``r`` = 2, 3 (the size-axis store) and 5,
  with distractors padding each store to the same size.
* Questions: for each focal key, the current value and the first value at its
  valid-from date, both "based only on what was known by" the last focal turn.

Each condition is a fresh store. After ingest (and, for Hindsight, once its
background work has gone quiet), three warm-up questions about distractors are
asked and discarded, then the 84 questions in a seeded order, each read up to
three ways: the retrieval layer's top five; one common reader (the H9 reader:
``gpt-4o-mini``, its fixed prompt) over those five; and, for Hindsight, its own
reader (reflect). Per path and question: answer, exact score, latency, API
tokens and dollars. Per store: ingest tokens and dollars, size, and the
proportional set size (PSS) of the processes that serve it.

Systems: Mem0 0.1.118 in-process, one process per store (stores run in
parallel); Hindsight 0.9.1, one daemon with its own PostgreSQL per seed, its
stores run one after another, each bank deleted once measured.

    python scripts/scale_fixed.py run mem0 1 experiments/runs/h16-fixed-mem0-s1-v1
    python scripts/scale_fixed.py run hindsight 1 experiments/runs/h16-fixed-hindsight-s1-v1 \\
        --url http://localhost:8911 --pg-instance <instance.json> --psql <psql>
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import llm_rescore  # noqa: E402

from temvera.experiment import seal_run  # noqa: E402
from temvera.generator import generate_histories  # noqa: E402
from temvera.model import Operation  # noqa: E402
from temvera.nl_workload import NLQueryCase, _large_pools, naturalize_events, render_turns  # noqa: E402
from temvera.oracle import LifecycleOracle  # noqa: E402
from temvera.telemetry import PRICES, Meter, measure_openai  # noqa: E402

FOCAL_ENTITIES = 14
ATTRIBUTES = 3
DISTRACTOR_REVISIONS = 3
SEEDS = {1: (101, 201), 2: (102, 202), 3: (103, 203)}  # seed index -> (focal, distractor)
# condition -> (focal revisions, distractor people)
CONDITIONS = {"size-300": (3, 6), "size-1005": (3, 53), "size-3000": (3, 186),
              "rev-2": (2, 59), "rev-5": (5, 42)}
WARMUP = 3
ROTATION = 211  # pool offset per seed index
READER_MODEL = "gpt-4o-mini"
SMOKE = bool(os.environ.get("TEMVERA_H16_SMOKE"))
if SMOKE:
    # Plumbing check on histories the study does not use; never written under experiments/.
    FOCAL_ENTITIES = 2
    SEEDS = {9: (909, 919)}
    CONDITIONS = {"size-30": (2, 1), "size-60": (2, 3), "rev-3": (3, 2)}


# -------------------------------------------------------------------- history
def _relabel(events, prefix: str):
    return tuple(dataclasses.replace(e, value=f"{prefix}{e.value}") if e.value else e for e in events)


def _rotate(events, offset: int):
    """Shift every relabelled name and value ``offset`` places along its pool.
    Relabelling assigns pool entries by rank, so without this every seed would
    hold the same people and values; a rotation keeps the map injective and
    containment-free, and leaves a seed's questions the same at every size."""
    persons, pools = _large_pools()
    person_at = {name: i for i, name in enumerate(persons)}
    value_at = {value: (pool, i) for pool in pools.values() for i, value in enumerate(pool)}

    def person(name):
        return persons[(person_at[name] + offset) % len(persons)] if name else name

    def value(text):
        if not text:
            return text
        pool, i = value_at[text]
        return pool[(i + offset) % len(pool)]

    return tuple(dataclasses.replace(e, subject=person(e.subject), value=value(e.value)) for e in events)


def history(seed_index: int, condition: str):
    """(events, turns, focal keys, knowledge time) for one store."""
    focal_seed, distractor_seed = SEEDS[seed_index]
    revisions, people = CONDITIONS[condition]
    largest = max(p for _, p in CONDITIONS.values())
    focal = generate_histories(seed=focal_seed, entities=FOCAL_ENTITIES, revisions=revisions,
                               attributes=ATTRIBUTES, distinct_values=True, namespace="a")
    distractors = generate_histories(seed=distractor_seed, entities=largest,
                                     revisions=DISTRACTOR_REVISIONS, attributes=ATTRIBUTES,
                                     distinct_values=True, namespace="z")
    keep = {f"z-entity-{n:03d}" for n in range(people)}
    subject = {e.belief_id: e.subject for e in distractors if e.operation is Operation.INGEST}
    distractors = tuple(e for e in distractors
                        if (e.subject or subject.get(e.belief_id) or subject.get(e.target_id or "")) in keep)
    # "a-" sorts before "z-", so focal names and values keep their relabelled
    # identity whatever the number of distractors.
    events = _rotate(naturalize_events(_relabel(focal, "a-") + _relabel(distractors, "z-"), pools="large"),
                     ROTATION * seed_index)
    turns = sorted(render_turns(events), key=lambda t: (t.recorded_at, t.event_id))
    focal_ids = {e.event_id for e in focal}
    focal_keys = sorted({(e.subject, e.attribute) for e in events
                         if e.event_id in focal_ids and e.operation is Operation.INGEST})
    known_by = max(t.recorded_at for t in turns if t.event_id in focal_ids)
    return events, turns, focal_keys, known_by


def questions(events, keys, known_by) -> list[NLQueryCase]:
    oracle = LifecycleOracle(tuple(e for e in events if e.recorded_at <= known_by))
    values = {e.belief_id: e.value for e in events if e.operation is Operation.INGEST}
    chains: dict[tuple, list] = {}
    for e in events:
        if e.operation is Operation.INGEST and e.recorded_at <= known_by:
            chains.setdefault((e.subject, e.attribute), []).append(e)
    out = []
    for subject, attribute in keys:
        chain = sorted(chains[(subject, attribute)], key=lambda e: e.valid_from)
        for kind, valid_at in (("current", known_by), ("valid_time", chain[0].valid_from)):
            expected = frozenset(values[b.belief_id] for b in oracle.query(
                subject, attribute, valid_at=valid_at, transaction_at=known_by))
            out.append(NLQueryCase(
                case_id=f"{kind}-{subject}-{attribute}", category=kind,
                query_text=(f"What is {subject}'s {attribute} as of {valid_at.date().isoformat()}, "
                            f"based only on what was known by {known_by.date().isoformat()}?"),
                subject=subject, attribute=attribute, valid_at=valid_at, transaction_at=known_by,
                expected_values=expected,
                stale_values=frozenset(e.value for e in chain) - expected))
    return out


def warmups(events, keys, known_by) -> list[NLQueryCase]:
    focal = set(keys)
    others = sorted({(e.subject, e.attribute) for e in events
                     if e.operation is Operation.INGEST and (e.subject, e.attribute) not in focal})
    return questions(events, others[:WARMUP], known_by)[::2][:WARMUP]


def score(answer: str, case: NLQueryCase) -> dict:
    folded = answer.casefold()
    expected = all(v.casefold() in folded for v in case.expected_values)
    stale = any(v.casefold() in folded for v in case.stale_values)
    return {"exact": expected and not stale, "present_expected": expected, "present_stale": stale}


# -------------------------------------------------------------------- measuring
def _percentiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)

    def at(q: float) -> float:
        return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]

    return {"n": len(ordered), "mean_s": sum(ordered) / len(ordered), "p50_s": at(0.5),
            "p95_s": at(0.95), "max_s": ordered[-1], "total_s": sum(ordered)}


def _cost(usage: dict) -> float:
    total = 0.0
    for key, entry in usage.items():
        rate_in, rate_out = PRICES.get(key.split("|")[-1], (0.0, 0.0))
        total += (entry["prompt_tokens"] * rate_in + entry["completion_tokens"] * rate_out) / 1e6
    return total


def _diff(after: dict, before: dict) -> dict:
    keys = set(after) | set(before)
    out = {k: {f: after.get(k, {}).get(f, 0) - before.get(k, {}).get(f, 0)
               for f in ("calls", "prompt_tokens", "completion_tokens")} for k in sorted(keys)}
    return {k: v for k, v in out.items() if any(v.values())}


def _children(pids: set[int]) -> set[int]:
    found = set(pids)
    grew = True
    while grew:
        grew = False
        for entry in os.listdir("/proc"):
            if not entry.isdigit() or int(entry) in found:
                continue
            try:
                ppid = int(Path(f"/proc/{entry}/stat").read_text().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
            if ppid in found:
                found.add(int(entry))
                grew = True
    return found


def memory_kb(pids: set[int]) -> dict:
    """Summed PSS (shared pages divided among sharers) and RSS of ``pids`` and
    their descendants."""
    pss = rss = 0
    for pid in _children(pids):
        try:
            for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
                if line.startswith("Pss:"):
                    pss += int(line.split()[1])
                elif line.startswith("Rss:"):
                    rss += int(line.split()[1])
        except OSError:
            continue
    return {"pss_kb": pss, "rss_kb": rss, "processes": len(_children(pids))}


class CommonReader:
    """The H9 common reader, with its tokens and latency recorded."""

    def __init__(self) -> None:
        self.client = llm_rescore._client("openai")

    def read(self, records: str, case: NLQueryCase) -> tuple[str, dict]:
        row = {"answer": records, "query": case.query_text}
        messages = [{"role": "system", "content": llm_rescore.READER_SYSTEM},
                    {"role": "user", "content": llm_rescore.READER_USER.format(
                        records=row["answer"] or "(no records)", query=row["query"])}]
        for attempt in range(6):
            try:
                response = self.client.chat.completions.create(
                    model=READER_MODEL, messages=messages, temperature=0, seed=7, max_tokens=64)
                usage = response.usage
                return (response.choices[0].message.content or "").strip(), {
                    f"reader|{READER_MODEL}": {"calls": 1, "prompt_tokens": usage.prompt_tokens,
                                               "completion_tokens": usage.completion_tokens}}
            except Exception as error:  # noqa: BLE001 - classified below
                llm_rescore.check_fatal(str(error))
                if attempt == 5:
                    raise
                time.sleep(2 ** attempt)
        raise AssertionError("unreachable")


# -------------------------------------------------------------------- systems
class Mem0Store:
    name = "mem0"

    def __init__(self, workdir: Path, label: str) -> None:
        from temvera.mem0_adapter import Mem0System, default_mem0_config

        self.meter = Meter()
        self._ctx = measure_openai(self.meter)
        self._ctx.__enter__()
        self.vector = tempfile.mkdtemp(prefix="h16-mem0-qdrant-", dir=workdir)
        self.history = str(workdir / f"{label}-history.db")
        self.user = f"h16-{label}"
        self.system = Mem0System(config=default_mem0_config(history_db_path=self.history,
                                                            vector_path=self.vector),
                                 user_id=self.user)
        self.system.reset()

    def usage(self) -> dict:
        return {f"inprocess|{m}": {"calls": u.calls, "prompt_tokens": u.prompt_tokens,
                                   "completion_tokens": u.completion_tokens}
                for m, u in self.meter.by_model.items()}

    def ingest(self, turn) -> None:
        self.system.ingest(turn)

    def settle(self) -> dict:
        return {"waited_s": 0.0, "timed_out": False}

    def retrieve(self, case) -> str:
        return self.system.answer(case)

    def own_reader(self):
        return None

    def size(self) -> dict:
        rows = self.system._memory.get_all(user_id=self.user)
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        disk = sum(p.stat().st_size for p in Path(self.vector).rglob("*") if p.is_file())
        return {"memories": len(rows), "characters": sum(len(str(r.get("memory", ""))) for r in rows),
                "vector_store_bytes": disk,
                "history_db_bytes": Path(self.history).stat().st_size if Path(self.history).exists() else 0}

    def memory(self) -> dict:
        return memory_kb({os.getpid()})

    def close(self) -> None:
        self._ctx.__exit__(None, None, None)


class HindsightStore:
    name = "hindsight"

    def __init__(self, url: str, bank: str, pg_instance: str, psql: str) -> None:
        from temvera.hindsight_adapter import HindsightSystem

        self.url, self.bank = url, bank
        self.recall = HindsightSystem(base_url=url, bank=bank, read_mode="recall")
        self.reflect = HindsightSystem(base_url=url, bank=bank, read_mode="reflect")
        self.recall.reset()
        self.recall._errors.clear()
        self.instance = json.loads(Path(pg_instance).read_text())
        self.psql = psql

    def _sql(self, query: str) -> list[list[str]]:
        inst = self.instance
        out = subprocess.run([self.psql, "-h", "127.0.0.1", "-p", str(inst["port"]), "-U", inst["username"],
                              "-d", inst["database"], "-At", "-F", "\t", "-c", query],
                             capture_output=True, text=True,
                             env={**os.environ, "PGPASSWORD": inst["password"]}, check=True)
        return [line.split("\t") for line in out.stdout.splitlines() if line]

    def usage(self) -> dict:
        rows = self._sql("SELECT operation, model, count(*), coalesce(sum(input_tokens),0), "
                         f"coalesce(sum(output_tokens),0) FROM llm_requests WHERE bank_id='{self.bank}' "
                         "GROUP BY 1, 2 ORDER BY 1, 2")
        return {f"{op}|{model}": {"calls": int(n), "prompt_tokens": int(i), "completion_tokens": int(o)}
                for op, model, n, i, o in rows}

    def ingest(self, turn) -> None:
        self.recall.ingest(turn)

    def settle(self, quiet_s: int = 60, poll_s: int = 15, cap_s: int = 2400) -> dict:
        """Wait until the bank logs no new LLM request for ``quiet_s``: its
        background consolidation would otherwise land among the questions."""
        start = last_change = time.monotonic()
        last = None
        while True:
            count = sum(v["calls"] for v in self.usage().values())
            now = time.monotonic()
            if count != last:
                last, last_change = count, now
            if now - last_change >= quiet_s:
                return {"waited_s": now - start, "timed_out": False}
            if now - start >= cap_s:
                return {"waited_s": now - start, "timed_out": True}
            time.sleep(poll_s)

    def retrieve(self, case) -> str:
        return self.recall.answer(case)

    def own_reader(self):
        return self.reflect.answer

    def size(self) -> dict:
        out = {}
        for table in ("memory_units", "entities", "documents", "chunks", "memory_links"):
            n, c = self._sql(f"SELECT count(*), coalesce(sum(length(row_to_json(t)::text)),0) "
                             f"FROM {table} t WHERE bank_id='{self.bank}'")[0]
            out[f"{table}_rows"], out[f"{table}_characters"] = int(n), int(c)
        return out

    def memory(self) -> dict:
        port = self.url.rsplit(":", 1)[1]
        daemon = set()
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                try:
                    cmd = Path(f"/proc/{entry}/cmdline").read_bytes().replace(b"\0", b" ").decode()
                except OSError:
                    continue
                if "hindsight_api.main" in cmd and f"--port {port}" in cmd:
                    daemon.add(int(entry))
        return {"daemon": memory_kb(daemon), "postgres": memory_kb({int(self.instance["pid"])})}

    def close(self) -> None:
        self.recall.reset()


# -------------------------------------------------------------------- one store
def measure(store, seed_index: int, condition: str) -> dict:
    events, turns, keys, known_by = history(seed_index, condition)
    cases = questions(events, keys, known_by)
    before = store.usage()
    ingest_lat, start = [], time.perf_counter()
    for turn in turns:
        t0 = time.perf_counter()
        store.ingest(turn)
        ingest_lat.append(time.perf_counter() - t0)
    ingest_wall = time.perf_counter() - start
    settled = store.settle()
    ingest_usage = _diff(store.usage(), before)
    size, memory = store.size(), store.memory()
    reader = CommonReader()
    own = store.own_reader()
    for case in warmups(events, keys, known_by):
        store.retrieve(case)
        if own is not None:
            own(case)
    order = list(cases)
    random.Random(f"{seed_index}-{condition}").shuffle(order)
    rows = []
    for case in order:
        paths = {}
        u0, t0 = store.usage(), time.perf_counter()
        error = ""
        try:
            records = store.retrieve(case)
        except Exception as exc:  # noqa: BLE001 - recorded per question, scored wrong
            records, error = "", f"{type(exc).__name__}: {exc}"[:300]
        paths["retrieval"] = {"answer": records, "latency_s": time.perf_counter() - t0,
                              "usage": _diff(store.usage(), u0), "error": error}
        t0, error = time.perf_counter(), ""
        try:
            text, usage = reader.read(records, case)
        except Exception as exc:  # noqa: BLE001
            text, usage, error = "", {}, f"{type(exc).__name__}: {exc}"[:300]
        paths["common_reader"] = {"answer": text, "latency_s": time.perf_counter() - t0,
                                  "usage": usage, "error": error}
        if own is not None:
            u0, t0, error = store.usage(), time.perf_counter(), ""
            try:
                text = own(case)
            except Exception as exc:  # noqa: BLE001
                text, error = "", f"{type(exc).__name__}: {exc}"[:300]
            paths["own_reader"] = {"answer": text, "latency_s": time.perf_counter() - t0,
                                   "usage": _diff(store.usage(), u0), "error": error}
        for path, entry in paths.items():
            rows.append({"seed_index": seed_index, "condition": condition, "path": path,
                         "case_id": case.case_id, "category": case.category, "query": case.query_text,
                         "expected_values": sorted(case.expected_values),
                         "stale_values": sorted(case.stale_values), **entry,
                         "cost_usd": _cost(entry["usage"]), **score(entry["answer"], case)})
    focal = sum(1 for t in turns if t.event_id.startswith("a-"))
    summary = {"condition": condition, "turns": len(turns), "focal_turns": focal,
               "focal_revisions": CONDITIONS[condition][0], "distractor_people": CONDITIONS[condition][1],
               "known_by": known_by.isoformat(), "questions": len(cases),
               "ingest_latency": _percentiles(ingest_lat), "ingest_wall_s": ingest_wall,
               "ingest_usage": ingest_usage, "ingest_cost_usd": _cost(ingest_usage),
               "settle": settled, "store": size, "memory": memory, "paths": {}}
    for path in sorted({r["path"] for r in rows}):
        mine = [r for r in rows if r["path"] == path]
        entry = summary["paths"][path] = {"cost_usd": sum(r["cost_usd"] for r in mine),
                                          "errors": sum(bool(r["error"]) for r in mine)}
        for category in ("current", "valid_time"):
            part = [r for r in mine if r["category"] == category]
            entry[category] = {"n": len(part), "exact": sum(r["exact"] for r in part),
                               "stale_present": sum(r["present_stale"] for r in part),
                               "latency": _percentiles([r["latency_s"] for r in part]),
                               "prompt_tokens": sum(e["prompt_tokens"] for r in part for e in r["usage"].values()),
                               "completion_tokens": sum(e["completion_tokens"] for r in part
                                                        for e in r["usage"].values())}
    return {"summary": summary, "rows": rows}


# -------------------------------------------------------------------- driver
def _worker(args) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        store = Mem0Store(Path(tmp), f"s{args.seed}-{args.condition}")
        try:
            result = measure(store, args.seed, args.condition)
        finally:
            store.close()
    Path(args.partial).write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    return 0


def _version(system: str, url: str | None) -> str:
    if system == "mem0":
        import mem0

        return getattr(mem0, "__version__", "unknown")
    from temvera.hindsight_adapter import HindsightSystem

    return HindsightSystem(base_url=url, bank="h16-version-probe").version


def _run(args) -> int:
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    if SMOKE and "experiments" in out.resolve().parts:
        raise SystemExit("smoke runs are never written under experiments/")
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        if args.system == "mem0":
            procs = []
            for condition in CONDITIONS:
                partial = Path(tmp) / f"{condition}.json"
                log = open(Path(tmp) / f"{condition}.log", "w")  # noqa: SIM115
                # Mem0 0.1.118 builds a telemetry vector store under MEM0_DIR
                # (default ~/.mem0) and rmtree's it on every construction and
                # reset, so parallel processes delete each other's: give each its own.
                private = Path(tmp) / f"{condition}-mem0-dir"
                private.mkdir()
                procs.append((condition, partial, log, subprocess.Popen(
                    [sys.executable, __file__, "worker", "mem0", str(args.seed), condition, str(partial)],
                    stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "MEM0_DIR": str(private)})))
            for condition, partial, log, proc in procs:
                code = proc.wait()
                log.close()
                if code != 0:
                    tail = (Path(tmp) / f"{condition}.log").read_text()[-2000:]
                    raise SystemExit(f"{condition} failed ({code}):\n{tail}")
                results.append(json.loads(partial.read_text()))
        else:
            for condition in CONDITIONS:
                store = HindsightStore(args.url, f"h16-s{args.seed}-{condition}", args.pg_instance, args.psql)
                try:
                    results.append(measure(store, args.seed, condition))
                finally:
                    store.close()
                print(json.dumps({"condition": condition, "done": True}), flush=True)
    out.mkdir(parents=True)
    with (out / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for result in results:
            for row in result["rows"]:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    (out / "results.json").write_text(json.dumps({
        "system": args.system, "seed_index": args.seed, "seeds": SEEDS[args.seed],
        "conditions": [r["summary"] for r in results], "prices_usd_per_million": PRICES},
        indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal_run(out, config={
        "benchmark": f"temvera-h16-fixed-{args.system}-v1", "system": args.system,
        "system_version": _version(args.system, args.url), "seed_index": args.seed,
        "seeds": list(SEEDS[args.seed]), "focal_entities": FOCAL_ENTITIES, "attributes": ATTRIBUTES,
        "distractor_revisions": DISTRACTOR_REVISIONS, "conditions": CONDITIONS, "warmup": WARMUP,
        "model": "gpt-4o-mini", "embed_model": "text-embedding-3-small" if args.system == "mem0"
        else "BAAI/bge-small-en-v1.5 (Hindsight default)", "search_limit": 5,
        "common_reader": {"model": READER_MODEL, "prompt_sha256": llm_rescore.prompt_hash("reader"),
                          "temperature": 0, "seed": 7, "max_tokens": 64}},
        command=f"python scripts/scale_fixed.py run {args.system} {args.seed} {args.output}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    run = sub.add_parser("run")
    run.add_argument("system", choices=("mem0", "hindsight"))
    run.add_argument("seed", type=int)
    run.add_argument("output")
    run.add_argument("--url")
    run.add_argument("--pg-instance")
    run.add_argument("--psql")
    worker = sub.add_parser("worker")
    worker.add_argument("system", choices=("mem0",))
    worker.add_argument("seed", type=int)
    worker.add_argument("condition")
    worker.add_argument("partial")
    args = parser.parse_args(argv)
    return _run(args) if args.mode == "run" else _worker(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
