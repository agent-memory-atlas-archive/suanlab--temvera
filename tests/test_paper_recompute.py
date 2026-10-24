"""Regression for the released reproduction command's purge contract."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("paper_recompute", ROOT / "scripts/recompute_paper_numbers.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("name,purge,total", [
    ("Mem0", 0, 290), ("LangMem", 9, 282), ("Graphiti", 0, 94),
    ("Cognee-retr", 0, 93), ("Hindsight-retr", 0, 93),
    ("Cognee-read", 0, 422), ("Hindsight-read", 1, 184),
])
def test_published_request_scope_counts(name, purge, total):
    """Fixed sealed counts catch accidental return to the legacy scope."""
    runs = {n: module.load_run(module.RUNS / p) for n, p in module.SYSTEMS.items()}
    cells = module.matched_cells(*runs.values())
    transcript = module.load_transcript(module.RUNS / module.SYSTEMS[name])
    counts = module.counts_for_table(module.SYSTEMS[name], transcript, cells)
    assert counts["purge"].total == 45
    assert counts["purge"].successes == purge
    assert sum(c.successes for c in counts.values()) == total
    assert sum(c.total for c in counts.values()) == 484
