import unittest

from temvera.reanalysis import (
    Proportion,
    abstention,
    category_counts,
    k_sweep,
    matched_cells,
)


def _row(**kw):
    base = {"profile": "p", "entities": 3, "revisions": 2, "seed": 7}
    base.update(kw)
    return base


class ProportionTest(unittest.TestCase):
    def test_wilson_is_bounded_and_nonzero_width_at_zero(self) -> None:
        zero = Proportion(0, 16)
        low, high = zero.wilson()
        self.assertEqual(zero.rate, 0.0)
        self.assertEqual(low, 0.0)
        # A 0/16 observation must not be read as a precise zero.
        self.assertGreater(high, 0.15)
        self.assertLess(high, 0.25)

    def test_empty_denominator_is_nan_not_crash(self) -> None:
        empty = Proportion(0, 0)
        self.assertNotEqual(empty.rate, empty.rate)  # NaN


class AbstentionTest(unittest.TestCase):
    def test_vacuous_cells_are_excluded(self) -> None:
        rows = [
            _row(abstention_cases=0, abstention_accuracy=1.0, seed=1),
            _row(abstention_cases=0, abstention_accuracy=1.0, seed=2),
            _row(abstention_cases=4, abstention_accuracy=0.0, seed=3),
        ]
        result = abstention(rows)
        # Averaging all three would give 0.667; only the real cell counts.
        self.assertEqual(result.total, 4)
        self.assertEqual(result.successes, 0)
        self.assertEqual(result.rate, 0.0)


class MatchingTest(unittest.TestCase):
    def test_matched_cells_is_intersection(self) -> None:
        a = {"rows": [_row(seed=1), _row(seed=2), _row(seed=3)]}
        b = {"rows": [_row(seed=2), _row(seed=3)]}
        self.assertEqual(len(matched_cells(a, b)), 2)


class KSweepTest(unittest.TestCase):
    def _transcript(self):
        return [
            _row(
                category="valid_time",
                answer="Busan | Seoul",
                expected_values=["Busan"],
                stale_values=["Seoul"],
                exact=False,
            )
        ]

    def test_truncation_changes_score(self) -> None:
        sweep = k_sweep(self._transcript(), budgets=(1, 2))
        # At k=1 only the current value is returned, so the case is exact;
        # at k=2 the superseded value appears and it is not.
        self.assertEqual(sweep[1]["overall"]["rate"], 1.0)
        self.assertEqual(sweep[2]["overall"]["rate"], 0.0)

    def test_category_counts_carry_denominators(self) -> None:
        counts = category_counts(self._transcript())
        self.assertEqual(counts["valid_time"].total, 1)


if __name__ == "__main__":
    unittest.main()


class ConsolidatedValuesTest(unittest.TestCase):
    def _oracle(self, *tail):
        from datetime import datetime, timezone

        from temvera.model import MemoryEvent, Operation
        from temvera.oracle import LifecycleOracle

        def day(n):
            return datetime(2025, 1, n, tzinfo=timezone.utc)

        def ingest(belief, value, n):
            return MemoryEvent(event_id=f"i-{belief}", operation=Operation.INGEST,
                               belief_id=belief, subject="s", attribute="a", value=value,
                               valid_from=day(n), recorded_at=day(n))

        events = [ingest("b1", "old", 1)]
        for kind in tail:
            if kind == "supersede":
                events += [MemoryEvent(event_id="s-b2", operation=Operation.SUPERSEDE,
                                       belief_id="b2", target_id="b1", valid_from=day(5),
                                       recorded_at=day(5)),
                           ingest("b2", "new", 5)]
            elif kind == "expire":
                events.append(MemoryEvent(event_id="x-b1", operation=Operation.EXPIRE,
                                          belief_id="b1", recorded_at=day(9),
                                          valid_to=day(8)))
            elif kind == "purge":
                events.append(MemoryEvent(event_id="p-b1", operation=Operation.PURGE,
                                          belief_id="b1", recorded_at=day(9)))
        return LifecycleOracle(events), day(20)

    def test_supersession_replaces_the_value(self) -> None:
        from temvera.reanalysis import consolidated_values

        oracle, at = self._oracle("supersede")
        self.assertEqual(consolidated_values(oracle, "s", "a", at), frozenset({"new"}))

    def test_expiry_keeps_the_value(self) -> None:
        from temvera.reanalysis import consolidated_values

        oracle, at = self._oracle("expire")
        self.assertEqual(consolidated_values(oracle, "s", "a", at), frozenset({"old"}))

    def test_purge_leaves_nothing(self) -> None:
        from temvera.reanalysis import consolidated_values

        oracle, at = self._oracle("purge")
        self.assertEqual(consolidated_values(oracle, "s", "a", at), frozenset())


class ConsolidationSweepTest(unittest.TestCase):
    def test_sweep_matches_the_oracle_on_every_case(self) -> None:
        from temvera.generator import generate_histories
        from temvera.nl_workload import build_nl_cases
        from temvera.oracle import LifecycleOracle
        from temvera.reanalysis import consolidated_values, consolidation_answerable

        for seed in (7, 13, 42):
            events = generate_histories(
                seed=seed, entities=6, revisions=4, attributes=2,
                reconfirm_probability=0.5, expire_probability=0.35, purge_probability=0.25,
            )
            cases = build_nl_cases(events)
            oracle = LifecycleOracle(events)
            swept = consolidation_answerable(events, cases)
            for case in cases:
                kept = consolidated_values(oracle, case.subject, case.attribute,
                                           case.transaction_at)
                expected = set(case.expected_values)
                self.assertEqual(swept[case.case_id], bool(expected) and expected <= kept,
                                 case.case_id)
            self.assertTrue(any(swept.values()) and not all(swept.values()))
