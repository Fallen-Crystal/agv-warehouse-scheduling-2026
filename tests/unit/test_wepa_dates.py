import math
import unittest
from collections import Counter
from unittest.mock import patch

from agv.data.wepa.windows import make_dates_pool, partition_dates
from agv.experiments.wepa_dates import summarize_dates


def case(name, day, count=40):
    return dict(
        case=name,
        source_day=day,
        tasks=[dict(kind="delivery" if i % 2 else "retrieval", sku=i % 2) for i in range(count)],
    )


class DateSelectionTests(unittest.TestCase):
    def test_dates_have_fixed_quotas_and_at_most_two_windows(self):
        cases = [case(f"{day}-{i}", day) for day in range(27) for i in range(5)]
        splits = partition_dates(cases, max_windows_per_day=2)
        self.assertEqual(splits, partition_dates(list(reversed(cases)), max_windows_per_day=2))
        self.assertEqual([len(split) for split in splits], [12, 20, 12])
        dates = [{c["source_day"] for c in split} for split in splits]
        self.assertEqual([len(days) for days in dates], [6, 10, 6])
        self.assertEqual(len(set.union(*dates)), 22)
        for split in splits:
            self.assertLessEqual(max(Counter(c["source_day"] for c in split).values()), 2)

    def test_previously_researched_dates_only_enter_development(self):
        cases = [case(str(day), day) for day in range(27)]
        known = set(range(8))
        splits = partition_dates(cases, known_days=known)
        self.assertFalse(known & {c["source_day"] for split in splits[1:] for c in split})
        with self.assertRaisesRegex(ValueError, "unresearched"):
            partition_dates(cases, known_days=set(range(12)))

    def test_many_windows_cannot_substitute_for_independent_dates(self):
        with self.assertRaisesRegex(ValueError, "date-disjoint"):
            partition_dates([case(str(i), 0) for i in range(100)])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            partition_dates([case("a", 0), case("a", 1)])
        for options in ({"max_windows_per_day": 3}, {"date_quotas": (0, 10, 6)}):
            with self.assertRaises(ValueError):
                partition_dates([], **options)

    def test_excluded_sealed_date_still_updates_prefix_inventory(self):
        rows = [
            ["delivery" if i < 15 else "retrieval", 1, day * 86400, 0, 0, 0]
            for day in range(4)
            for i in range(20)
        ]
        with (
            patch("agv.data.wepa.windows.read_source", return_value=(rows, Counter({1: 5}), {})),
            patch("agv.data.wepa.windows.build"),
        ):
            value = make_dates_pool("unused", excluded_days={0}, date_quotas=(1, 1, 1))
        self.assertEqual({c["source_day"] for c in value["cases"]}, {1, 2, 3})
        first = next(c for c in value["cases"] if c["source_day"] == 1)
        self.assertEqual(first["initial"], {"1": 15})
        self.assertEqual(value["input_audit"]["counters"]["sealed_date_excluded"], 1)
        self.assertEqual(value["input_audit"]["selection_unit"], "source_day")
        self.assertFalse(value["input_audit"]["algorithm_results_read"])


class DateSummaryTests(unittest.TestCase):
    def setUp(self):
        self.cases = [case("a", 1), case("b", 1), case("c", 2, 90)]
        self.pairs = [
            dict(case=name, gain_percent=gain, deltas={"F": -gain, "T": -gain})
            for name, gain in (("a", 10.0), ("b", 10.0), ("c", -10.0))
        ]

    def test_dates_not_windows_are_resampling_units(self):
        report = summarize_dates(self.pairs, self.cases)
        self.assertEqual(report["all"]["mean_gain_percent"], 0.0)
        self.assertEqual(report["all"]["mean_deltas"], {"F": 0.0, "T": 0.0})
        self.assertEqual(report["all"]["bootstrap95"], [-10.0, 10.0])
        self.assertEqual(report["all"]["sign_test_two_sided_p"], 1.0)
        subset = report["original_filter_subset"]
        self.assertEqual((subset["comparable_dates"], subset["comparable_windows"]), (1, 2))
        self.assertEqual(subset["mean_gain_percent"], 10.0)
        self.assertIsNone(subset["bootstrap95"])
        self.assertEqual(report, summarize_dates(self.pairs, self.cases))

    def test_exact_sign_test_excludes_ties(self):
        cases = [case(str(i), i) for i in range(8)]
        pairs = [dict(case=str(i), gain_percent=1.0 if i < 7 else 0.0, deltas={}) for i in range(8)]
        report = summarize_dates(pairs, cases)["all"]
        self.assertEqual(report["sign_test_two_sided_p"], 2 / 128)
        self.assertEqual(report["tied"], 1)
        self.assertEqual((report["improved"], report["worsened"]), (7, 0))

    def test_incomplete_duplicate_and_nonfinite_pairs_are_rejected(self):
        for pairs in (self.pairs[:-1], self.pairs[:2] + self.pairs[:1]):
            with self.assertRaisesRegex(ValueError, "complete paired"):
                summarize_dates(pairs, self.cases)
        for bad in (math.nan, math.inf):
            pairs = [dict(row) for row in self.pairs]
            pairs[0]["gain_percent"] = bad
            with self.assertRaisesRegex(ValueError, "finite"):
                summarize_dates(pairs, self.cases)
        with self.assertRaisesRegex(ValueError, "bootstrap"):
            summarize_dates(self.pairs, self.cases, resamples=1)


if __name__ == "__main__":
    unittest.main()
