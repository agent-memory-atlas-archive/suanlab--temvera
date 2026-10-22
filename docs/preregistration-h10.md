# Preregistration: deletion across five systems, many histories and three callers (H10)

Committed and pushed before the study's harness has run on any system. Results
are reported whatever they are.

Why: the paper's deletion result (§VI-C) rests on one seeded history (three
purged subjects), one prose wording, two systems (Mem0, Graphiti), and native
API calls whose handles the harness chose by matching the known payload. Both
simulated EAB reviews ranked this among the top threats, and one asked whether
Mem0's silently dropped actions, not its design, explain the ignored prose
request.

Before writing this, each library's deletion surface was probed on a throwaway
sentence ("Zed's favorite color is Teal", not in any study history): Cognee
1.4.2's `forget(data_id=...)` cleared that sentence from its vector store, graph
and raw input file but not from its relational database; Hindsight 0.9.1 deletes
whole documents (one ingested input) or a bank, and its recall results name
their document; LangMem 0.0.30's memory manager ships with `enable_deletes=False`.
Nothing else was run.

## Design

- **Histories:** the purge profile (purge probability 0.5, no expiry or
  reconfirmation), 6 people, 2 revisions, 10 seeds (7, 13, 17, 23, 42, 1, 2, 3, 4,
  5): 24 purged subjects and 36 that are never purged.
- **Systems:** the measured versions -- Mem0 0.1.118, Graphiti 0.29.2, Cognee
  1.4.2, Hindsight 0.9.1 (own daemon), LangMem 0.0.30 -- on `gpt-4o-mini`, plus
  the reference implementation.
- **Conditions,** each on a fresh store with the full history ingested:
  - `prose-1`, `prose-2`, `prose-3`: the purge request in one of three wordings
    (none restates the value): "Permanently delete everything you recorded about
    X's A." / "Please forget X's A; I do not want it kept." / "X has asked for
    their A to be erased from your memory."
  - `api-oracle`: `prose-1`, then the native deletion API on every unit whose
    stored text contains a value of the purged subject (the harness knows the
    value; this is the most a caller could achieve, and is labelled as such).
  - `api-caller`: `prose-1`, then what a caller without the value can do: ask
    the store about "X's A" and delete every unit the answer returns.
- **Measures** for each purged subject (all values it ever had):
  - *answer leak* -- does any of its values appear in the store's answer to
    "What is X's A?" after deletion;
  - *store residue* -- occurrences in each store, read through the store's own
    library, split into stores a query path reads and stores it does not;
  - for each never-purged subject, *collateral* -- its current value is missing
    from the answer after deletion while present under `prose-1`.
  - For Mem0, the DELETE actions its extractor emitted and the actions it
    dropped with a logged error.

## Predictions

- **H10a -- prose is ignored:** under each prose wording, in each of the five
  systems, at least 80% of purged subjects still leak into the answer.
- **H10b -- the API clears the serving path when given the right handles:**
  under `api-oracle`, Mem0, Graphiti, Cognee and LangMem leak for at most 10% of
  purged subjects. No prediction for Hindsight, whose consolidated observations
  may outlive the documents they came from.
- **H10c -- something survives off the serving path:** under `api-oracle`, at
  least one store no query reads still holds a purged value in at least half of
  the histories with a purge, for Mem0 (history table), Cognee (relational
  database) and Hindsight (audit or LLM-request tables). LangMem, whose only store
  is the one it serves from, holds none.
- **H10d -- Mem0's ignored prose is not just its dropped actions:** under the
  prose conditions, the share of purged subjects that leak exceeds the share for
  which Mem0 logged a dropped action.
- **H10e -- a realistic caller does worse than the oracle:** under `api-caller`,
  summed over systems, more purged subjects leak, or more never-purged subjects
  are lost, than under `api-oracle`.

Analysis: counts per system and condition with Wilson intervals over purged
subjects; no test beyond the thresholds above.

## Addendum (2026-10-23, before the study runs; predictions unchanged)

- **Smoke run, disclosed.** The harness was run once per system on seed 97,
  which is not one of the study's ten seeds, with `prose-2`, `api-oracle` and
  `api-caller`, to check the plumbing (outputs kept outside the repository).
  Purged subjects leaking under `prose-2`: Mem0 0/3 (its extractor emitted 4
  DELETE actions), LangMem 1/3, Graphiti 3/3, Cognee 3/3, Hindsight 3/3. Under
  `api-oracle` none leaked in any system; under `api-caller` none leaked, but the
  caller's deletions removed every never-purged subject in Mem0, Graphiti and
  LangMem (Cognee 1 of 3, Hindsight 0). This is one history and changes no
  prediction above; H10a may well fail for Mem0.
- **Values never coincide.** The histories are generated with distinct values
  (`distinct_values`), so a value of a purged subject is never also a kept
  subject's value; the counts stay 24 purged and 36 kept.
- **Two readings of a leak.** While building the study we found that the
  generator's typed purge removes only the latest belief, whereas the request
  asks for everything about the attribute (evidence ledger E-096). The primary
  measure stays as stated above -- any value the subject ever had -- and each
  record also reports whether the latest value alone leaks.

## Outcomes (recorded 2026-10-23, after all runs; `deletion-study-*-v1`)

| | Prediction | Observed | Verdict |
|---|---|---|---|
| H10a | >= 80% of purged subjects leak under each prose wording, in each system | Graphiti, Cognee, Hindsight 24/24 under all three; Mem0 24, 2, 24; LangMem 15, 3, 6 | **falsified** for Mem0 (wording 2) and LangMem (all wordings) |
| H10b | `api-oracle` leaks <= 10% for Mem0, Graphiti, Cognee, LangMem | 0/24 in all five systems | holds |
| H10c | off-path residue in >= half the histories for Mem0, Cognee, Hindsight; none for LangMem | 9/9, 9/9, 9/9; LangMem 0 | holds |
| H10d | Mem0's prose leaks exceed its dropped actions | 50/72 leaked, 0 dropped actions logged | holds |
| H10e | `api-caller` leaks more or loses more kept subjects than `api-oracle` | leaks 0 vs 0; kept 114/180 vs 174/180 | holds (by collateral loss) |

Not predicted, reported: Mem0's extractor emitted 23 DELETE actions under
"Please forget ..." and 1-3 under the other wordings; LangMem, whose manager
cannot delete, rewrote memories and lost never-purged subjects under prose (30,
32, 27 of 36 kept); the realistic caller kept 8 (Mem0), 18 (Graphiti), 19
(LangMem), 33 (Cognee), 36 (Hindsight) of 36; Graphiti's entity summaries and,
in up to 3 histories, Cognee's graph or vector store still hold a purged value
after `api-oracle`; Hindsight's LLM-request log holds it in every history.
