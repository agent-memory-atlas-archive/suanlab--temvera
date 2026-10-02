"""The CMT abstract is generated, not transcribed, and the test proves it."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_abstract_file_matches_the_paper() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_abstract.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_abstract_carries_no_latex_or_citation_residue() -> None:
    text = (ROOT / "paper" / "abstract.txt").read_text(encoding="utf-8")
    for residue in ("\\", "{", "}", "$", "~", "citep", "  ", "\t", "\r"):
        assert residue not in text, f"abstract still contains {residue!r}"
