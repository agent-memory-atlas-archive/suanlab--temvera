"""H14: what a store costs and how it answers as it grows (E5 of IDEA_ICDE.md).

One store per system ingests one seeded history (200 people x 3 attributes x 3
revisions = 3,000 turns, natural names and values throughout) and is measured
at checkpoints of 100, 300, 1,000 and 3,000 turns:

* ingest latency (p50/p95/p99) and throughput over each segment;
* tokens and dollars per segment -- Mem0 and Graphiti by patching the OpenAI
  client in this process (``telemetry.measure_openai``), Hindsight from its own
  per-bank LLM-request log;
* store size -- rows, records and characters, read through each store;
* server memory (resident set size of the database and daemon processes);
* query latency and exact accuracy on probe questions built from the oracle
  over the ingested prefix: the current value, and the value at an earlier
  valid time for people whose value has changed;
* at the last checkpoint, for the system served over HTTP (Hindsight), query
  throughput and latency at 1, 4 and 16 concurrent clients.

Hindsight is read two ways on the same store: its retrieval layer (recall) and
its own reader (reflect). Mem0 and Graphiti run in this process; concurrency is
measured only where the system is a server.

    python scripts/scale_cost.py {mem0,graphiti,hindsight} experiments/runs/scale-growth-<system>-v1
"""

from __future__ import annotations

import json
import os
import random
import resource
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from temvera.experiment import seal_run
from temvera.external_experiment import _events_for
from temvera.model import Operation
from temvera.nl_workload import NLQueryCase, render_turns
from temvera.oracle import LifecycleOracle
from temvera.telemetry import PRICES, Meter, measure_openai

ROOT = Path(__file__).resolve().parents[1]
PROFILE = {"name": "revision_only", "purge_probability": 0.0, "expire_probability": 0.0,
           "reconfirm_probability": 0.0}
WORKLOAD = {"seed": 7, "entities": 200, "attributes": 3, "revisions": 3,
            "natural_pools": "large", "distinct_values": True}
CHECKPOINTS = (100, 300, 1000, 3000)
PROBES = 40  # per kind and checkpoint
CONCURRENCY = (1, 4, 16)
if os.environ.get("TEMVERA_SCALE_SMOKE"):
    # Plumbing check on a history the study does not use; never sealed into experiments/.
    WORKLOAD = {**WORKLOAD, "seed": 99, "entities": 8}
    CHECKPOINTS, PROBES, CONCURRENCY = (20, 40), 3, (1, 2)


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)

    def at(q: float) -> float:
        return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]

    return {"n": len(ordered), "mean_s": sum(ordered) / len(ordered), "p50_s": at(0.5),
            "p95_s": at(0.95), "p99_s": at(0.99), "total_s": sum(ordered)}


def history():
    events = _events_for(WORKLOAD["seed"], WORKLOAD["entities"], WORKLOAD["revisions"], PROFILE,
                         True, WORKLOAD["attributes"], WORKLOAD["distinct_values"],
                         WORKLOAD["natural_pools"])
    turns = sorted(render_turns(events), key=lambda t: (t.recorded_at, t.event_id))
    return events, turns


def probes(events, turns, upto: int, rng: random.Random) -> list[NLQueryCase]:
    """Current-value and earlier-valid-time questions over the first ``upto`` turns."""
    seen_ids = {t.event_id for t in turns[:upto]}
    prefix = tuple(e for e in events if e.event_id in seen_ids)
    now = turns[upto - 1].recorded_at
    oracle = LifecycleOracle(prefix)
    values = {e.belief_id: e.value for e in prefix if e.operation is Operation.INGEST}
    chains: dict[tuple, list] = {}
    for e in prefix:
        if e.operation is Operation.INGEST:
            chains.setdefault((e.subject, e.attribute), []).append(e)

    def case(kind: str, subject: str, attribute: str, valid_at) -> NLQueryCase | None:
        expected = frozenset(values[b.belief_id] for b in oracle.query(
            subject, attribute, valid_at=valid_at, transaction_at=now))
        if not expected:
            return None
        known = frozenset(e.value for e in chains[(subject, attribute)])
        return NLQueryCase(
            case_id=f"{kind}-{upto}-{subject}-{attribute}", category=kind,
            query_text=(f"What is {subject}'s {attribute} as of {valid_at.date().isoformat()}, "
                        f"based only on what was known by {now.date().isoformat()}?"),
            subject=subject, attribute=attribute, valid_at=valid_at, transaction_at=now,
            expected_values=expected, stale_values=known - expected)

    keys = sorted(chains)
    current = [c for c in (case("current", s, a, now) for s, a in rng.sample(keys, min(PROBES, len(keys))))
               if c is not None]
    revised = [k for k in keys if len(chains[k]) > 1]
    past = []
    for s, a in rng.sample(revised, min(PROBES, len(revised))):
        c = case("valid_time", s, a, sorted(chains[(s, a)], key=lambda e: e.valid_from)[0].valid_from)
        if c is not None:
            past.append(c)
    return current + past


def exact(answer: str, case: NLQueryCase) -> bool:
    folded = answer.casefold()
    return all(v.casefold() in folded for v in case.expected_values) and not any(
        v.casefold() in folded for v in case.stale_values)


def _rss_kb(pattern: str) -> int:
    """Summed resident set size of processes whose command line contains ``pattern``."""
    total = 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            if pattern in cmd:
                for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        total += int(line.split()[1])
        except OSError:
            continue
    return total


def _dir_bytes(path: str) -> int:
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file()) if path else 0


# -------------------------------------------------------------------- systems
class _Mem0:
    name = "mem0"

    def __init__(self, workdir: Path) -> None:
        import tempfile

        from temvera.mem0_adapter import Mem0System, default_mem0_config

        self.vector = tempfile.mkdtemp(prefix="scale-mem0-qdrant-", dir=workdir)
        self.history = str(workdir / "mem0-history.db")
        self.system = Mem0System(config=default_mem0_config(history_db_path=self.history,
                                                            vector_path=self.vector),
                                 user_id="scale-cost-mem0")
        self.system.reset()

    def ingest(self, turn):
        self.system.ingest(turn)

    def paths(self):
        return {"retrieval": self.system.answer}

    def size(self) -> dict:
        rows = self.system._memory.get_all(user_id="scale-cost-mem0")
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        return {"memories": len(rows), "characters": sum(len(str(r.get("memory", ""))) for r in rows),
                "vector_store_bytes": _dir_bytes(self.vector),
                "history_db_bytes": Path(self.history).stat().st_size if Path(self.history).exists() else 0}

    def server_rss_kb(self) -> dict:
        return {}


class _Graphiti:
    name = "graphiti"

    def __init__(self, workdir: Path) -> None:
        from temvera.graphiti_adapter import GraphitiSystem

        self.uri, self.user = os.environ["NEO4J_URI"], os.environ.get("NEO4J_USER", "neo4j")
        self.password = os.environ["NEO4J_PASSWORD"]
        self.group = "scale-cost-graphiti"
        self.system = GraphitiSystem(group_id=self.group, neo4j_uri=self.uri, neo4j_user=self.user,
                                     neo4j_password=self.password)
        self.system.reset()

    def ingest(self, turn):
        self.system.ingest(turn)

    def paths(self):
        return {"retrieval": self.system.answer}

    def size(self) -> dict:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        try:
            with driver.session() as session:
                edges = session.run("MATCH ()-[e:RELATES_TO]->() WHERE e.group_id=$g "
                                    "RETURN count(e) AS n, sum(size(coalesce(e.fact,''))) AS c",
                                    g=self.group).single()
                nodes = session.run("MATCH (n:Entity) WHERE n.group_id=$g RETURN count(n) AS n, "
                                    "sum(size(coalesce(n.summary,''))) AS c", g=self.group).single()
                episodes = session.run("MATCH (n:Episodic) WHERE n.group_id=$g RETURN count(n) AS n, "
                                       "sum(size(coalesce(n.content,''))) AS c", g=self.group).single()
        finally:
            driver.close()
        return {"edges": edges["n"], "edge_characters": edges["c"] or 0,
                "entities": nodes["n"], "entity_summary_characters": nodes["c"] or 0,
                "episodes": episodes["n"], "episode_characters": episodes["c"] or 0}

    def server_rss_kb(self) -> dict:
        return {"neo4j": _rss_kb("org.neo4j")}


class _Hindsight:
    name = "hindsight"

    def __init__(self, workdir: Path) -> None:
        from temvera.hindsight_adapter import HindsightSystem

        self.bank = "scale-cost-hindsight"
        self.url = os.environ.get("HINDSIGHT_URL", "http://localhost:8888")
        self.recall = HindsightSystem(base_url=self.url, bank=self.bank, read_mode="recall")
        self.reflect = HindsightSystem(base_url=self.url, bank=self.bank, read_mode="reflect")
        self.recall.reset()
        self.recall._errors.clear()
        instance = json.loads(Path(os.environ["HINDSIGHT_PG_INSTANCE"]).read_text())
        self._pg = (os.environ["HINDSIGHT_PSQL"], instance)

    def _sql(self, query: str) -> list[list[str]]:
        psql, inst = self._pg
        out = subprocess.run([psql, "-h", "127.0.0.1", "-p", str(inst["port"]), "-U", inst["username"],
                              "-d", inst["database"], "-At", "-F", "\t", "-c", query],
                             capture_output=True, text=True,
                             env={**os.environ, "PGPASSWORD": inst["password"]}, check=True)
        return [line.split("\t") for line in out.stdout.splitlines() if line]

    def ingest(self, turn):
        self.recall.ingest(turn)

    def paths(self):
        return {"retrieval": self.recall.answer, "reader": self.reflect.answer}

    def usage(self) -> dict:
        rows = self._sql("SELECT operation, model, count(*), coalesce(sum(input_tokens),0), "
                         f"coalesce(sum(output_tokens),0) FROM llm_requests WHERE bank_id='{self.bank}' "
                         "GROUP BY 1, 2 ORDER BY 1, 2")
        return {f"{op}|{model}": {"calls": int(n), "prompt_tokens": int(i), "completion_tokens": int(o)}
                for op, model, n, i, o in rows}

    def size(self) -> dict:
        out = {}
        for table in ("memory_units", "entities", "documents", "chunks", "memory_links", "llm_requests"):
            n, c = self._sql(f"SELECT count(*), coalesce(sum(length(row_to_json(t)::text)),0) "
                             f"FROM {table} t WHERE bank_id='{self.bank}'")[0]
            out[f"{table}_rows"], out[f"{table}_characters"] = int(n), int(c)
        return out

    def server_rss_kb(self) -> dict:
        return {"hindsight_daemon": _rss_kb("hindsight"), "postgres": _rss_kb("postgres")}


SYSTEMS = {"mem0": _Mem0, "graphiti": _Graphiti, "hindsight": _Hindsight}


def _cost(usage: dict) -> float:
    total = 0.0
    for key, entry in usage.items():
        model = key.split("|")[-1]
        rate_in, rate_out = PRICES.get(model, (0.0, 0.0))
        total += (entry["prompt_tokens"] * rate_in + entry["completion_tokens"] * rate_out) / 1e6
    return total


def _meter_usage(meter: Meter) -> dict:
    return {f"inprocess|{model}": {"calls": u.calls, "prompt_tokens": u.prompt_tokens,
                                   "completion_tokens": u.completion_tokens}
            for model, u in meter.by_model.items()}


def _diff(after: dict, before: dict) -> dict:
    keys = set(after) | set(before)
    return {k: {f: after.get(k, {}).get(f, 0) - before.get(k, {}).get(f, 0)
                for f in ("calls", "prompt_tokens", "completion_tokens")} for k in sorted(keys)}


def main(system_name: str, output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    import tempfile

    events, turns = history()
    assert len(turns) >= CHECKPOINTS[-1], len(turns)
    rng = random.Random(29)
    checkpoints, transcript = [], []
    meter = Meter()
    with tempfile.TemporaryDirectory() as tmp, measure_openai(meter):
        system = SYSTEMS[system_name](Path(tmp))
        usage_of = (lambda: system.usage()) if system_name == "hindsight" else (lambda: _meter_usage(meter))
        done = 0
        for upto in CHECKPOINTS:
            before = usage_of()
            latencies, start = [], time.perf_counter()
            for turn in turns[done:upto]:
                t0 = time.perf_counter()
                system.ingest(turn)
                latencies.append(time.perf_counter() - t0)
            wall = time.perf_counter() - start
            ingest_usage = _diff(usage_of(), before)
            size = system.size()
            cases = probes(events, turns, upto, rng)
            before_q = usage_of()
            query_lat: dict[str, list[float]] = {}
            hits: dict[str, dict[str, list[int]]] = {}
            for case in cases:
                for path, ask in system.paths().items():
                    t0 = time.perf_counter()
                    answer = ask(case)
                    query_lat.setdefault(path, []).append(time.perf_counter() - t0)
                    entry = hits.setdefault(path, {}).setdefault(case.category, [0, 0])
                    entry[0] += exact(answer, case)
                    entry[1] += 1
                    transcript.append({"checkpoint": upto, "path": path, "case_id": case.case_id,
                                       "category": case.category, "query": case.query_text,
                                       "expected_values": sorted(case.expected_values),
                                       "stale_values": sorted(case.stale_values),
                                       "answer": answer, "exact": exact(answer, case)})
            query_usage = _diff(usage_of(), before_q)
            checkpoints.append({
                "turns": upto, "segment_turns": upto - done, "ingest_latency": _percentiles(latencies),
                "ingest_throughput_turns_per_s": (upto - done) / wall if wall else 0.0,
                "ingest_usage": ingest_usage, "ingest_cost_usd": _cost(ingest_usage),
                "query_usage": query_usage, "query_cost_usd": _cost(query_usage),
                "query_latency": {p: _percentiles(v) for p, v in query_lat.items()},
                "exact": {p: {c: {"hits": h, "n": n} for c, (h, n) in by.items()} for p, by in hits.items()},
                "store": size, "server_rss_kb": system.server_rss_kb(),
                "client_peak_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            })
            print(json.dumps({"turns": upto, "ingest_p50": checkpoints[-1]["ingest_latency"].get("p50_s"),
                              "cost": checkpoints[-1]["ingest_cost_usd"]}), flush=True)
            done = upto
        concurrency = {}
        if system_name == "hindsight":
            cases = probes(events, turns, CHECKPOINTS[-1], random.Random(31))
            for workers in CONCURRENCY:
                batch = cases * 3
                lat: list[float] = []

                def ask(case):
                    t0 = time.perf_counter()
                    system.recall.answer(case)
                    return time.perf_counter() - t0

                start = time.perf_counter()
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    lat = list(pool.map(ask, batch))
                wall = time.perf_counter() - start
                concurrency[str(workers)] = {"queries": len(batch), "throughput_qps": len(batch) / wall,
                                             "latency": _percentiles(lat)}
        errors = getattr(getattr(system, "recall", system), "worker_errors", 0) \
            if system_name == "hindsight" else getattr(system.system, "worker_errors", 0)
    out.mkdir(parents=True)
    with (out / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for row in transcript:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (out / "results.json").write_text(json.dumps({
        "system": system_name, "checkpoints": checkpoints, "concurrency": concurrency,
        "prices_usd_per_million": PRICES, "worker_errors": errors}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    seal_run(out, config={"benchmark": f"temvera-scale-growth-{system_name}-v1", "system": system_name,
                          "workload": WORKLOAD, "profile": PROFILE, "checkpoints": list(CHECKPOINTS),
                          "probes_per_kind": PROBES, "concurrency": list(CONCURRENCY),
                          "model": "gpt-4o-mini", "embed_model": "text-embedding-3-small",
                          "search_limit": 5},
             command=f"python scripts/scale_cost.py {system_name} {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
