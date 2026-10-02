"""Render the paper's abstract as plain text for the CMT submission field.

CMT takes plain text, so the abstract has to be transcribed out of LaTeX by
hand or by this script. Transcribing it by hand is how a submission ends up
claiming something the paper no longer says: the abstract went a full day
asserting Graphiti "matches" Mem0 after the body had been corrected to
"indistinguishable". `tests/test_abstract.py` regenerates and compares, so the
file cannot drift from the source again.

    python scripts/make_abstract.py            # write paper/abstract.txt
    python scripts/make_abstract.py --check    # fail if it is out of date
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "paper" / "main.tex"
TARGET = ROOT / "paper" / "abstract.txt"


def render(latex: str) -> str:
    body = latex[
        latex.index(r"\begin{abstract}") + len(r"\begin{abstract}") : latex.index(
            r"\end{abstract}"
        )
    ]
    # Citation markers are meaningless without the bibliography; drop the
    # preceding space too so "Hindsight \citep{x}---under" does not become
    # "Hindsight —under".
    body = re.sub(r"\s*\\citep\{[^}]*\}", "", body)
    for command in ("texttt", "emph", "textbf"):
        body = re.sub(rf"\\{command}\{{([^}}]*)\}}", r"\1", body)
    body = re.sub(r"\$([^$]*)\$", r"\1", body)
    body = body.replace(r"\,", " ").replace(r"\%", "%").replace(r"\&", "&")
    # A tie is a non-breaking space in LaTeX; in plain text it is just a space.
    # Missed once: "4.7~s" would have gone into the CMT field verbatim.
    body = body.replace("~", " ")
    body = re.sub(r"\\[a-zA-Z]+", "", body)
    body = body.replace("---", "\u2014")

    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", body):
        if not paragraph.strip():
            continue
        text = re.sub(r"\s+", " ", paragraph).strip()
        text = re.sub(r"\s*\u2014\s*", " \u2014 ", text)
        paragraphs.append(re.sub(r"\s+([,.;:])", r"\1", text))
    return "\n\n".join(paragraphs) + "\n"


def main() -> int:
    rendered = render(SOURCE.read_text(encoding="utf-8"))
    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != rendered:
            print(f"FAIL: {TARGET.name} is out of date; run this script to regenerate")
            return 1
        print(f"{TARGET.name} matches the paper ({len(rendered.strip())} characters)")
        return 0
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"wrote {TARGET.name}: {len(rendered.strip())} characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
