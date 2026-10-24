# Preregistration: deletion when one unit mixes what must go with what must stay (H17)

Committed and pushed before `scripts/deletion_mixed.py` has run on any system.
The harness was tested only offline, on two fake stores
(`tests/test_deletion_mixed.py`). Results are reported whatever they are.
Responds to M07 of the 2026-10-23 re-review (`MODIFY.md`) and to the paper's
statement that units mixing people or attributes are untested.

## Why

In the H10/H13 deletion histories every stored unit held one person's one
statement, so a caller that checks the name could delete exactly the right
units and kept every unrelated person in four of five systems (E-104). That
result says nothing about units that mix a fact to delete with facts to keep,
and E-104 compared callers across separately ingested stores.

## Design

Five seeded histories (seeds 11-15) of 12 people with natural names, each
rendered three ways:

- `attributes`: one turn per person states their home city and their employer;
  every second person's home city is to be deleted, so their employer shares
  its unit (12 other facts are unrelated);
- `people`: one turn per pair states both people's home cities; the first's is
  to be deleted, so the second's shares its unit;
- `shared`: one turn per statement, but each pair has the same home city; the
  first's is to be deleted, so the second's shares its value.

Each condition is a fresh store. All questions ("What is X's A?") are asked once
ingest is done, the deletion is made, and the same questions are asked again:
retention is counted only over facts the store answered before, so it never
compares separately ingested stores. Callers: `api-oracle` deletes every unit
whose text holds a value to delete; `api-verified` searches for the person's
attribute and deletes the returned units that name the person (the H13 checked
caller). Systems: Mem0 0.1.118 (deletes extracted facts) and Hindsight 0.9.1
(deletes whole documents), `gpt-4o-mini`. A value is "left" if it appears in the
answer to its own question; in `shared`, where the value is also the other
person's, a purged value counts as left only in a returned unit that also names
the person (both readings are reported).

Analysis: `scripts/analyze_h17.py`, committed with this file.

## Predictions

- **H17a -- the checked caller removes what it is asked to:** for both systems,
  over the three renderings, a deleted value is left in at most 10% of the
  answers to its question afterwards.
- **H17b -- a document store loses what shares a unit:** under the checked
  caller, Hindsight keeps at most 20% of the co-located facts it answered
  before, in both `attributes` and `people`.
- **H17c -- a fact store keeps it:** under the checked caller, Mem0 keeps at
  least 80% of them, in both `attributes` and `people`.
- **H17d -- matching by value cannot tell owners apart:** under the oracle
  caller, in `shared`, both systems keep at most 20% of the other person's
  facts they answered before.
- **H17e -- checking the name can:** under the checked caller, in `shared`,
  both systems keep at least 80% of them.
- **H17f -- unrelated facts survive the checked caller:** in `attributes`,
  both systems keep at least 90% of the unrelated facts they answered before.
