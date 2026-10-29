import unittest

from agv.data.wepa.windows import partition


class WindowSelectionTests(unittest.TestCase):
    def test_partitions_are_deterministic_and_date_disjoint(self):
        cases = [
            dict(
                case=f"{day}-{index}",
                source_day=day,
                tasks=[dict(kind="delivery" if j % 2 else "retrieval") for j in range(40)],
            )
            for day in range(30)
            for index in range(2)
        ]
        first = partition(cases)
        self.assertEqual(first, partition(cases))
        self.assertEqual([len(split) for split in first], [8, 16, 8])
        days = [{case["source_day"] for case in split} for split in first]
        self.assertFalse(days[0] & days[1] or days[0] & days[2] or days[1] & days[2])

    def test_insufficient_dates_fail_without_reusing_a_window(self):
        cases = [
            dict(case=str(i), source_day=0, tasks=[dict(kind="delivery")] * 40) for i in range(50)
        ]
        with self.assertRaisesRegex(ValueError, "date-disjoint"):
            partition(cases)


if __name__ == "__main__":
    unittest.main()
