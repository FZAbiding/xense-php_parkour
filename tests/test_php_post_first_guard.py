"""Keep the diagnostic correction confined to a clear outward drift after block 1."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from php_official_benchmark import post_first_guard_direction


class PostFirstGuardTest(unittest.TestCase):
    def test_outward_drift_after_first_block(self):
        self.assertEqual(post_first_guard_direction(6.5, 0.34, 0.70, 34, 0.23), "d")
        self.assertEqual(post_first_guard_direction(7.0, -0.45, 0.76, -38, -0.27), "a")
        self.assertEqual(post_first_guard_direction(8.0, 0.40, 0.76, 8.8, 0.35, 8.0), "d")

    def test_no_pulse_on_block_or_late_approach(self):
        self.assertIsNone(post_first_guard_direction(5.7, 0.40, 0.80, 35, 0.4))
        self.assertIsNone(post_first_guard_direction(9.0, 0.60, 0.80, 35, 0.4))
        self.assertIsNone(post_first_guard_direction(6.8, 0.45, 1.10, 35, 0.4))

    def test_no_pulse_for_returning_or_small_yaw(self):
        self.assertIsNone(post_first_guard_direction(7.0, 0.45, 0.75, -35, -0.4))
        self.assertIsNone(post_first_guard_direction(7.0, 0.45, 0.75, 12, 0.4))
        self.assertIsNone(post_first_guard_direction(7.0, 0.45, 0.75, 35, -0.4))


if __name__ == "__main__":
    unittest.main()
