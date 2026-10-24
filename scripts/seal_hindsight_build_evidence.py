"""Which Hindsight build served the August runs, which did not record it.

The sealed ``external-hindsight-{recall,reflect}-v1`` runs carry no server
version. The daemon's own log does carry its schema: at its first start an
embedded PostgreSQL is migrated, by alembic, through every revision the
installed release ships, and the log names each. Releases differ in that list,
so the last revision applied identifies the release. This keeps, from the
daemon log, the server start, every migration line and the first and last line
naming each run's bank prefix; and, from the published ``hindsight-api-slim``
wheels around the date of the runs, each one's sha256, its migration files and
the revision it ends at, with its upload time on PyPI.

    python scripts/seal_hindsight_build_evidence.py ~/.hindsight/daemon.log.2 <wheel-dir> \\
        experiments/runs/hindsight-build-evidence-v1

``<wheel-dir>`` holds ``slim-<version>/*.whl`` and ``pypi-release-times.json``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

from temvera.experiment import seal_run

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"
BANKS = {"external-hindsight-recall-v1": "hsrecall", "external-hindsight-reflect-v1": "hsreflect"}
STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
UPGRADE = re.compile(r"Running upgrade (.*?) -> ([0-9a-z]+)")


def wheel_heads(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        files = {name: archive.read(name).decode("utf-8") for name in archive.namelist()
                 if name.startswith("hindsight_api/alembic/versions/") and name.endswith(".py")}
    revisions, parents = set(), set()
    for text in files.values():
        rev = re.search(r'^revision(?:: str)?\s*=\s*["\']([0-9a-z]+)["\']', text, re.M)
        down = re.findall(r'["\']([0-9a-z]{12})["\']', text.split("down_revision", 1)[1].split("\n")[0]) \
            if "down_revision" in text else []
        if rev:
            revisions.add(rev.group(1))
        parents.update(down)
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "migrations": len(files),
            "heads": sorted(revisions - parents)}


def main(log: str, wheels: str, output: str) -> int:
    out = Path(output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite: {out}")
    lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()
    keep, upgrades, starts, banks = [], [], 0, {}
    for line in lines:
        if "Started server process" in line or "Starting embedded PostgreSQL" in line:
            keep.append(line)
            starts += "Started server process" in line
        elif UPGRADE.search(line):
            keep.append(line)
            upgrades.append((STAMP.match(line).group(1), *UPGRADE.search(line).groups()))
        for run, prefix in BANKS.items():
            if prefix in line and STAMP.match(line):
                first_last = banks.setdefault(run, [line, line])
                first_last[1] = line
    for run in BANKS:
        keep += banks[run]
    times = json.loads((Path(wheels) / "pypi-release-times.json").read_text(encoding="utf-8"))
    releases = {}
    for folder in sorted(Path(wheels).glob("slim-*")):
        version = folder.name.removeprefix("slim-")
        releases[version] = {**wheel_heads(next(folder.glob("*.whl"))), "uploaded": times[version]}
    sealed = {run: json.loads((RUNS / run / "environment.json").read_text())["created_at"] for run in BANKS}
    head = upgrades[-1][2] if upgrades else None
    results = {
        "server_starts": starts, "migrations_applied": len(upgrades),
        "migration_window": [upgrades[0][0], upgrades[-1][0]] if upgrades else None,
        "head_applied": head,
        "bank_activity": {run: [STAMP.match(a).group(1), STAMP.match(b).group(1)] for run, (a, b) in banks.items()},
        "runs_sealed_utc": sealed, "releases": releases,
        "matching_releases": sorted(v for v, r in releases.items()
                                    if r["heads"] == [head] and r["migrations"] == len(upgrades)),
    }
    out.mkdir(parents=True)
    (out / "daemon-excerpt.log").write_text("\n".join(keep) + "\n", encoding="utf-8")
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal_run(out, config={"benchmark": "temvera-hindsight-build-evidence-v1", "log": Path(log).name,
                          "banks": BANKS, "package": "hindsight-api-slim", "versions": sorted(releases),
                          "note": "daemon log timestamps are local time (KST, UTC+9)"},
             command=f"python scripts/seal_hindsight_build_evidence.py {Path(log).name} <wheels> {output}")
    print(json.dumps({k: v for k, v in results.items() if k != "releases"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
