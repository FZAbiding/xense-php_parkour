"""Regression checks for the strict first-exit course criterion."""

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.php_score_course import DEFAULT_TERRAIN, score


class FirstExitScoringTest(unittest.TestCase):
    def score_trace(self, first_exit_y):
        with tempfile.TemporaryDirectory() as folder:
            trace = Path(folder) / "pelvis.csv"
            with trace.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("wall_s", "x", "y", "z"))
                writer.writerows(((0, 0, 0, 0.78),
                                  (1, 5, 0, 1.0),
                                  (2, 7.21, first_exit_y, 0.78),
                                  (3, 8, 0, 0.78)))
            return score(trace, DEFAULT_TERRAIN)

    def test_later_recovery_does_not_count_as_clearance(self):
        result = self.score_trace(1.2)
        self.assertEqual(result["consecutive_cleared"], 0)
        self.assertEqual(result["blocks"][0]["status"], "off_course_at_exit")
        self.assertEqual(result["blocks"][0]["recovered_later_at_s"], 3)

    def test_first_exit_on_course_counts_as_clearance(self):
        result = self.score_trace(0.5)
        self.assertEqual(result["consecutive_cleared"], 1)
        self.assertEqual(result["blocks"][0]["status"], "cleared")
        self.assertIsNone(result["blocks"][0]["recovered_later_at_s"])


if __name__ == "__main__":
    unittest.main()
