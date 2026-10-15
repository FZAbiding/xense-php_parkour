"""Regression for a live slowdown hidden by second-precision finish times."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.php_audit_trial import audit


class LiveStopAuditTest(unittest.TestCase):
    def test_live_slowdown_overrides_truncated_offline_window(self):
        with tempfile.TemporaryDirectory() as folder:
            trial = Path(folder)
            (trial / "result.json").write_text(json.dumps({
                "status": "sim_fps_low",
                "finished": "2026-10-15T10:45:16+0800",
                "yaw_before_release_deg": 0.15,
                "sim_fps_low_reports": [210.7, 198.2],
            }))
            (trial / "inference.log").write_text(
                "2026-10-15 10:45:03.981 Depth distillation policy started\n"
                "2026-10-15 10:45:12.000 RL FPS: 50.5\n")
            (trial / "sim.log").write_text(
                "2026-10-15 10:45:11.367 Simulation FPS: 210.7\n"
                "2026-10-15 10:45:16.411 Simulation FPS: 198.2\n")
            report = audit(trial)
        self.assertEqual(report["sim_fps_samples"], 1)
        self.assertEqual(report["quality"], "sustained_sim_slowdown")
        self.assertEqual(report["live_sim_fps_low_reports"], [210.7, 198.2])


if __name__ == "__main__":
    unittest.main()
