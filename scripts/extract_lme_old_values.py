"""Ask one model for every LongMemEval update pair's supersession.

Run it twice with different models; `adjudicate_lme_labels.py` accepts only
what both agree on and what passes the verbatim check, and hands the rest to a
person. Output quotes the corpus (each answer cites its evidence sentence), so it
is a local working file and is not tracked.

    python scripts/extract_lme_old_values.py --model gpt-4o-mini
    python scripts/extract_lme_old_values.py --model gpt-4o
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from temvera.lme_bitemporal import (
    EXTRACTION_PROMPT,
    check_extraction,
    extraction_messages,
    load,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "raw" / "longmemeval_oracle.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    out = args.out or ROOT / "data" / f"lme-proposals-v2-{args.model}.json"
    if out.exists():
        print(f"FAIL: refusing to overwrite {out}")
        return 1

    from openai import OpenAI

    client = OpenAI()
    pairs = load(SOURCE)
    items = []
    for index, pair in enumerate(pairs, 1):
        response = client.chat.completions.create(
            model=args.model,
            messages=extraction_messages(pair),
            temperature=0,
            seed=7,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        earlier, later = parsed.get("earlier_value"), parsed.get("later_value")
        items.append({
            "question_id": pair.question_id,
            "attribute": parsed.get("attribute"),
            "earlier_value": earlier,
            "later_value": later,
            "question_asks_for": parsed.get("question_asks_for"),
            "rejected_because": check_extraction(pair, earlier, later),
        })
        print(f"[{index}/{len(pairs)}] {pair.question_id} {earlier!r} -> {later!r}"
              f" ({parsed.get('question_asks_for')}) {items[-1]['rejected_because'] or 'ok'}",
              flush=True)

    record = {
        "model": args.model,
        "system_fingerprints": sorted({getattr(response, "system_fingerprint", None) or ""}),
        "prompt_sha256": hashlib.sha256(EXTRACTION_PROMPT.encode()).hexdigest(),
        "temperature": 0,
        "seed": 7,
        "created": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ok = sum(1 for item in items if not item["rejected_because"])
    print(f"wrote {out.relative_to(ROOT)}: {ok}/{len(items)} pass the verbatim check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
