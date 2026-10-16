"""Check that a busy shared CPU prevents a nominally idle-GPU trial."""

import unittest
from unittest.mock import patch

from scripts.php_run_controlled_batch import preflight


class PreflightTest(unittest.TestCase):
    def test_cpu_overload_blocks_trial_even_when_gpu_is_idle(self):
        with patch("scripts.php_run_controlled_batch.gpu_sample",
                   side_effect=lambda: {"util_percent": 10, "memory_used_mib": 2000}), \
             patch("scripts.php_run_controlled_batch.os.getloadavg",
                   side_effect=[(10, 0, 0), (42, 0, 0), (10, 0, 0)]), \
             patch("scripts.php_run_controlled_batch.time.sleep"):
            report = preflight(3, 5, max_util=50, max_memory_mib=10000,
                               max_cpu_load_1m=24)
        self.assertFalse(report["ready"])
        self.assertEqual([row["cpu_load_1m"] for row in report["readings"]],
                         [10, 42, 10])


if __name__ == "__main__":
    unittest.main()
