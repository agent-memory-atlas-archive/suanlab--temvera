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
