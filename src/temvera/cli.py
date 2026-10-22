"""Small reproducible baseline command for the first lifecycle artifact."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .evaluation import (
    AppendOnlyBaseline,
    BM25Baseline,
    FullContextBaseline,
    LastWriteWinsBaseline,
    RecentContextBaseline,
    cases_from_oracle,
    evaluate,
)
from .efficiency import benchmark_efficiency
from .decay import decay_smoke_cases, evaluate_decay, run_decay_sweep
from .dataset import freeze_dataset, verify_dataset
from .generator import generate_histories
from .hybrid import HybridRetriever, channel_ablation
from .hard_cases import hard_retrieval_fixture
from .hybrid import hard_channel_ablation
from .experiment import (
    run_lifecycle_experiment,
    seal_run,
    verify_run,
    verify_run_set,
)
from .oracle import LifecycleOracle
from .store import JsonlEventStore
from .threats import (
    evaluate_governed_threats,
    evaluate_threats,
    generate_threat_scenarios,
)


def _write_external_run(output, config, result, command_name, arguments) -> None:
    """Write results + transcript for an external comparison run and seal it."""
    transcript = result.pop("transcript")
    output.mkdir(parents=True)
    (output / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (output / "transcript.jsonl").open("w", encoding="utf-8") as stream:
        for row in transcript:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    seal_run(
        output,
        config={**config, "backbone": result["backbone"]},
        command=f"temvera {command_name} {arguments.config} {arguments.output}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="temvera")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate")
    generate.add_argument("output")
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--entities", type=int, default=4)
    generate.add_argument("--revisions", type=int, default=3)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("store")
    benchmark = subparsers.add_parser("benchmark")
    benchmark.add_argument("store")
    security = subparsers.add_parser("security-smoke")
    security.add_argument("--seed", type=int, required=True)
    external = subparsers.add_parser("external-smoke")
    external.add_argument("--seed", type=int, required=True)
    external_mem0 = subparsers.add_parser("external-mem0")
    external_mem0.add_argument("config")
    external_mem0.add_argument("output")
    external_graphiti = subparsers.add_parser("external-graphiti")
    external_graphiti.add_argument("config")
    external_graphiti.add_argument("output")
    external_hindsight = subparsers.add_parser("external-hindsight")
    external_hindsight.add_argument("config")
    external_hindsight.add_argument("output")
    external_cognee = subparsers.add_parser("external-cognee")
    external_cognee.add_argument("config")
    external_cognee.add_argument("output")
    external_langmem = subparsers.add_parser("external-langmem")
    external_langmem.add_argument("config")
    external_langmem.add_argument("output")
    longmemeval = subparsers.add_parser("longmemeval-eval")
    longmemeval.add_argument("config")
    longmemeval.add_argument("output")
    purge_residual = subparsers.add_parser("purge-residual")
    purge_residual.add_argument("config")
    purge_residual.add_argument("output")
    deletion = subparsers.add_parser("deletion-study")
    deletion.add_argument("config")
    deletion.add_argument("output")
    decay = subparsers.add_parser("decay-smoke")
    decay.add_argument("--half-life-days", type=float, default=30.0)
    decay.add_argument("--minimum-confidence", type=float, default=0.25)
    experiment = subparsers.add_parser("run-experiment")
    experiment.add_argument("config")
    experiment.add_argument("output_root")
    freeze = subparsers.add_parser("freeze-dataset")
    freeze.add_argument("output")
    freeze.add_argument("--entities", type=int, default=8)
    freeze.add_argument("--revisions", type=int, default=4)
    verify = subparsers.add_parser("verify-dataset")
    verify.add_argument("dataset")
    sweep = subparsers.add_parser("decay-sweep")
    sweep.add_argument("config")
    sweep.add_argument("output")
    ablation = subparsers.add_parser("channel-ablation")
    ablation.add_argument("config")
    ablation.add_argument("output")
    hard_ablation = subparsers.add_parser("hard-channel-ablation")
    hard_ablation.add_argument("output")
    efficiency = subparsers.add_parser("efficiency-benchmark")
    efficiency.add_argument("config")
    efficiency.add_argument("output")
    learned = subparsers.add_parser("learned-vector-eval")
    learned.add_argument("config")
    learned.add_argument("output")
    synonym = subparsers.add_parser("vector-synonym-compare")
    synonym.add_argument("output")
    synonym.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    governance = subparsers.add_parser("governance-smoke")
    governance.add_argument("--seed", type=int, required=True)
    fusion = subparsers.add_parser("fusion-comparison")
    fusion.add_argument("config")
    fusion.add_argument("output")
    forgeteval = subparsers.add_parser("forgeteval-compatibility")
    forgeteval.add_argument("config")
    forgeteval.add_argument("source_root")
    forgeteval.add_argument("output")
    seal = subparsers.add_parser("seal-run")
    seal.add_argument("run_dir")
    seal.add_argument("config")
    seal.add_argument("--command", dest="invocation", required=True)
    verify_run_parser = subparsers.add_parser("verify-run")
    verify_run_parser.add_argument("run_dir")
    lifecycle_grid = subparsers.add_parser("lifecycle-grid")
    lifecycle_grid.add_argument("config")
    lifecycle_grid.add_argument("output")
    operation_suite = subparsers.add_parser("lifecycle-operation-suite")
    operation_suite.add_argument("config")
    operation_suite.add_argument("output")
    artifacts = subparsers.add_parser("verify-artifacts")
    artifacts.add_argument("manifest")
    artifacts.add_argument("runs_root")
    security_experiment = subparsers.add_parser("security-experiment")
    security_experiment.add_argument("config")
    security_experiment.add_argument("output")
    artifact_package = subparsers.add_parser("artifact-package")
    artifact_package.add_argument("root")
    artifact_package.add_argument("output")
    artifact_verify = subparsers.add_parser("verify-artifact-package")
    artifact_verify.add_argument("archive")
    subparsers.add_parser("bypass-report")
    arguments = parser.parse_args()
    if arguments.command == "generate":
        from pathlib import Path

        store = JsonlEventStore(Path(arguments.output))
        store.extend(
            generate_histories(
                seed=arguments.seed,
                entities=arguments.entities,
                revisions=arguments.revisions,
            )
        )
        print(json.dumps({"events": len(store.load()), "seed": arguments.seed}))
    elif arguments.command == "inspect":
        from pathlib import Path

        events = JsonlEventStore(Path(arguments.store)).load()
        print(
            json.dumps(
                {
                    "events": len(events),
                    "systems": [
                        type(system).__name__
                        for system in (
                            LifecycleOracle(events),
                            AppendOnlyBaseline(events),
                            FullContextBaseline(events),
                            RecentContextBaseline(events),
                            BM25Baseline(events),
                            LastWriteWinsBaseline(events),
                        )
                    ],
                    "first_event": asdict(events[0]) if events else None,
                },
                default=str,
                sort_keys=True,
            )
        )
    elif arguments.command == "benchmark":
        from pathlib import Path

        events = JsonlEventStore(Path(arguments.store)).load()
        cases = cases_from_oracle(events)
        if not cases:
            raise SystemExit("store contains no benchmark cases")
        systems = {
            "oracle": LifecycleOracle(events),
            "append_only": AppendOnlyBaseline(events),
            "full_context": FullContextBaseline(events),
            "recent_context": RecentContextBaseline(events),
            "bm25_at_1": BM25Baseline(events, limit=1),
            "last_write_wins": LastWriteWinsBaseline(events),
        }
        report = {
            name: asdict(evaluate(system, cases))
            for name, system in systems.items()
        }
        print(json.dumps({"cases": len(cases), "results": report}, sort_keys=True))
    elif arguments.command == "security-smoke":
        scenarios = generate_threat_scenarios(arguments.seed)
        report = {
            "undefended": asdict(evaluate_threats(scenarios, defended=False)),
            "defended": asdict(evaluate_threats(scenarios, defended=True)),
        }
        print(json.dumps(report, sort_keys=True))
    elif arguments.command == "external-smoke":
        from .external_harness import (
            LatestValueSystem,
            OracleMemorySystem,
            evaluate_external,
        )

        events = generate_histories(
            seed=arguments.seed,
            entities=4,
            revisions=3,
            reconfirm_probability=0.5,
            expire_probability=0.3,
            purge_probability=0.3,
        )
        report = {
            "oracle_reference": asdict(
                evaluate_external(OracleMemorySystem(events), events)
            ),
            "latest_value_baseline": asdict(
                evaluate_external(LatestValueSystem(events), events)
            ),
        }
        print(json.dumps(report, sort_keys=True))
    elif arguments.command == "decay-smoke":
        cases = decay_smoke_cases()
        report = {
            method: asdict(
                evaluate_decay(
                    cases,
                    method,
                    half_life_days=arguments.half_life_days,
                    minimum_confidence=arguments.minimum_confidence,
                )
            )
            for method in ("rank_only", "state_level")
        }
        print(json.dumps(report, sort_keys=True))
    elif arguments.command == "run-experiment":
        from pathlib import Path

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        run_dir = run_lifecycle_experiment(config, Path(arguments.output_root))
        print(json.dumps({"run_dir": str(run_dir)}, sort_keys=True))
    elif arguments.command == "freeze-dataset":
        from pathlib import Path

        manifest = freeze_dataset(
            Path(arguments.output),
            entities=arguments.entities,
            revisions=arguments.revisions,
        )
        print(json.dumps(manifest, sort_keys=True))
    elif arguments.command == "verify-dataset":
        from pathlib import Path

        valid = verify_dataset(Path(arguments.dataset))
        print(json.dumps({"valid": valid}, sort_keys=True))
        if not valid:
            raise SystemExit(1)
    elif arguments.command == "decay-sweep":
        from pathlib import Path

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        rows = run_decay_sweep(
            ages_days=tuple(config["ages_days"]),
            half_lives_days=tuple(config["half_lives_days"]),
            thresholds=tuple(config["thresholds"]),
        )
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        output.write_text(
            json.dumps([asdict(row) for row in rows], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"rows": len(rows), "output": str(output)}, sort_keys=True))
    elif arguments.command == "channel-ablation":
        from pathlib import Path

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        events = generate_histories(
            seed=config["seed"],
            entities=config["entities"],
            revisions=config["revisions"],
        )
        transaction_at = max(event.recorded_at for event in events)
        oracle = LifecycleOracle(events)
        beliefs = tuple(oracle.state_as_of(transaction_at).values())
        cases = []
        for belief in beliefs:
            expected = oracle.query(
                belief.subject,
                belief.attribute,
                valid_at=belief.valid_from,
                transaction_at=transaction_at,
            )
            cases.append(
                (
                    belief.subject,
                    belief.attribute,
                    belief.valid_from,
                    frozenset(item.belief_id for item in expected),
                )
            )
        rows = channel_ablation(
            HybridRetriever(beliefs), tuple(cases), limit=config["limit"]
        )
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        output.write_text(
            json.dumps([asdict(row) for row in rows], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"rows": len(rows), "output": str(output)}, sort_keys=True))
    elif arguments.command == "hard-channel-ablation":
        from pathlib import Path

        beliefs, cases = hard_retrieval_fixture()
        rows = hard_channel_ablation(HybridRetriever(beliefs), cases)
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        output.write_text(
            json.dumps([asdict(row) for row in rows], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"rows": len(rows), "output": str(output)}, sort_keys=True))
    elif arguments.command == "efficiency-benchmark":
        from pathlib import Path

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        beliefs, cases = hard_retrieval_fixture()
        rows = benchmark_efficiency(
            HybridRetriever(beliefs),
            cases,
            budgets=tuple(config["budgets"]),
            repeats=config["repeats"],
            channels=tuple(config["channels"]),
        )
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        output.write_text(
            json.dumps([asdict(row) for row in rows], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"rows": len(rows), "output": str(output)}, sort_keys=True))
    elif arguments.command == "learned-vector-eval":
        from pathlib import Path

        from .learned import FastEmbedVectorIndex, evaluate_learned_vector

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        beliefs, hard_cases = hard_retrieval_fixture()
        cases = tuple(
            (case.query_text, case.expected_ids)
            for case in hard_cases
            if case.category == "vector_synonym"
        )
        result = evaluate_learned_vector(
            FastEmbedVectorIndex(beliefs, model_name=config["model"]), cases
        )
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        payload = {**asdict(result), **config}
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(payload, sort_keys=True))
    elif arguments.command == "external-mem0":
        from pathlib import Path

        from .external_experiment import run_mem0_comparison

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        result = run_mem0_comparison(config)
        _write_external_run(output, config, result, "external-mem0", arguments)
        print(json.dumps(result, sort_keys=True))
    elif arguments.command == "external-graphiti":
        from pathlib import Path

        from .external_experiment import run_graphiti_comparison

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        result = run_graphiti_comparison(config)
        _write_external_run(output, config, result, "external-graphiti", arguments)
        print(json.dumps(result, sort_keys=True))
    elif arguments.command == "external-hindsight":
        from pathlib import Path

        from .external_experiment import run_hindsight_comparison

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        result = run_hindsight_comparison(config)
        _write_external_run(output, config, result, "external-hindsight", arguments)
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}, sort_keys=True))
    elif arguments.command == "external-cognee":
        from pathlib import Path

        from .external_experiment import run_cognee_comparison

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        result = run_cognee_comparison(config)
        _write_external_run(output, config, result, "external-cognee", arguments)
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}, sort_keys=True))
    elif arguments.command == "external-langmem":
        from pathlib import Path

        from .external_experiment import run_langmem_comparison

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        result = run_langmem_comparison(config)
        _write_external_run(output, config, result, "external-langmem", arguments)
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}, sort_keys=True))
    elif arguments.command == "longmemeval-eval":
        from pathlib import Path

        from .longmemeval_eval import run_longmemeval

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        output.mkdir(parents=True)
        result = run_longmemeval(config, output / "progress.jsonl")
        (output / "results.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        seal_run(
            output,
            config={**config, "backbone": result["backbone"]},
            command=f"temvera longmemeval-eval {arguments.config} {arguments.output}",
        )
        print(json.dumps({k: v for k, v in result.items() if k != "per_instance"}, sort_keys=True))
    elif arguments.command == "purge-residual":
        import tempfile
        from pathlib import Path

        from .external_experiment import run_purge_residual

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        with tempfile.TemporaryDirectory() as workdir:
            result = run_purge_residual(config, workdir)
        output.mkdir(parents=True)
        (output / "results.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        seal_run(
            output,
            config={**config, "backbone": result["backbone"]},
            command=f"temvera purge-residual {arguments.config} {arguments.output}",
        )
        print(json.dumps(result, sort_keys=True))
    elif arguments.command == "deletion-study":
        import tempfile
        from pathlib import Path

        from .deletion_study import run_deletion_study

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        with tempfile.TemporaryDirectory() as workdir:
            result = run_deletion_study(config, workdir)
        output.mkdir(parents=True)
        (output / "results.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        seal_run(
            output,
            config=config,
            command=f"temvera deletion-study {arguments.config} {arguments.output}",
        )
        print(json.dumps(result["summary"], sort_keys=True))
    elif arguments.command == "vector-synonym-compare":
        from pathlib import Path

        from .synonym_eval import compare_vector_channels

        result = compare_vector_channels(model_name=arguments.model)
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        payload = asdict(result)
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(payload, sort_keys=True))
    elif arguments.command == "governance-smoke":
        print(json.dumps(asdict(evaluate_governed_threats(arguments.seed)), sort_keys=True))
    elif arguments.command == "fusion-comparison":
        from pathlib import Path

        from .fusion import compare_fusion

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        result = compare_fusion(
            tuple(config["development_variants"]), tuple(config["test_variants"])
        )
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        output.write_text(
            json.dumps(asdict(result), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(asdict(result), sort_keys=True))
    elif arguments.command == "bypass-report":
        from .bypass import run_bypass_probes

        print(json.dumps([asdict(item) for item in run_bypass_probes()], sort_keys=True))
    elif arguments.command == "forgeteval-compatibility":
        from pathlib import Path

        from .forgeteval_external import run_forgeteval

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        metrics = run_forgeteval(
            Path(arguments.source_root),
            Path(arguments.output),
            expected_commit=config["source_commit"],
            scale=config["scale"],
            seed=config["seed"],
            distractors=config["distractors"],
        )
        print(json.dumps(metrics, sort_keys=True))
    elif arguments.command == "seal-run":
        from pathlib import Path

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        seal_run(
            Path(arguments.run_dir), config=config, command=arguments.invocation
        )
        print(json.dumps({"sealed": arguments.run_dir}, sort_keys=True))
    elif arguments.command == "verify-run":
        from pathlib import Path

        valid = verify_run(Path(arguments.run_dir))
        print(json.dumps({"valid": valid}, sort_keys=True))
        if not valid:
            raise SystemExit(1)
    elif arguments.command == "lifecycle-grid":
        from pathlib import Path

        from .lifecycle_grid import run_lifecycle_grid

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        rows, summary = run_lifecycle_grid(config)
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        output.mkdir(parents=True)
        (output / "results.json").write_text(
            json.dumps([asdict(row) for row in rows], indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        seal_run(
            output,
            config=config,
            command=(
                f"temvera lifecycle-grid {arguments.config} {arguments.output}"
            ),
        )
        print(json.dumps({"rows": len(rows), "output": str(output)}, sort_keys=True))
    elif arguments.command == "lifecycle-operation-suite":
        from pathlib import Path

        from .lifecycle_grid import run_operation_suite

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        rows, summary = run_operation_suite(config)
        output = Path(arguments.output)
        if output.exists():
            raise SystemExit(f"refusing to overwrite: {output}")
        output.mkdir(parents=True)
        (output / "results.json").write_text(
            json.dumps([asdict(row) for row in rows], indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        seal_run(
            output,
            config=config,
            command=(
                "temvera lifecycle-operation-suite "
                f"{arguments.config} {arguments.output}"
            ),
        )
        print(json.dumps({"rows": len(rows), "output": str(output)}, sort_keys=True))
    elif arguments.command == "verify-artifacts":
        from pathlib import Path

        valid = verify_run_set(Path(arguments.runs_root), Path(arguments.manifest))
        print(json.dumps({"valid": valid}, sort_keys=True))
        if not valid:
            raise SystemExit(1)
    elif arguments.command == "security-experiment":
        from pathlib import Path

        from .security_experiment import run_security_experiment

        config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
        output = run_security_experiment(config, Path(arguments.output))
        print(json.dumps({"output": str(output)}, sort_keys=True))
    elif arguments.command == "artifact-package":
        from pathlib import Path

        from .artifact import create_artifact_archive

        manifest = create_artifact_archive(
            Path(arguments.root).resolve(), Path(arguments.output).resolve()
        )
        print(json.dumps({"files": len(manifest["files"])}, sort_keys=True))
    elif arguments.command == "verify-artifact-package":
        from pathlib import Path

        from .artifact import verify_artifact_archive

        valid = verify_artifact_archive(Path(arguments.archive))
        print(json.dumps({"valid": valid}, sort_keys=True))
        if not valid:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
