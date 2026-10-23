"""The paper's numbers are part of the test suite, not a manual review step.

An audit found seven figures in one subsection had drifted onto runs the paper
does not use, including one it explicitly disowns. Nothing failed, because
nothing checked. This runs the claim verifier as a test so that editing a number
by hand, or re-sealing a run without updating the prose, breaks the build.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_every_paper_claim_matches_its_sealed_run() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_paper_claims.py")],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "every claim matches" in result.stdout


def test_one_metric_cannot_be_printed_as_two_values() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import verify_paper_claims as v

    same = [v.Claim("t", "a", "0.583", lambda: 0.583, metric="m"),
            v.Claim("p", "b", "0.583", lambda: 0.583, metric="m")]
    split = same[:1] + [v.Claim("p", "b", "0.576", lambda: 0.576, metric="m")]
    assert v.inconsistent(same) == []
    assert v.inconsistent(split) and "m" in v.inconsistent(split)[0]
