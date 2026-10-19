#!/usr/bin/env python3
"""Opt-in, read-only per-tick trace around the released depth policy.

The official policy and ONNX sessions still produce the commands. This wrapper
records their returned values and fingerprints the depth array actually read by
the policy; a heartbeat sequence is only a timing hint, not a frame identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

from holosoma_inference.policies.depth_distillation import DepthDistillationPolicy
from holosoma_inference.sensors.depth_shm import DepthShmSensor
from holosoma_inference.run_policy import main


trial = Path(os.environ["PHP_POLICY_TRACE_DIR"]).resolve()
if not trial.is_dir():
    raise FileNotFoundError(f"diagnostic trial directory missing: {trial}")
trace_path = trial / "policy_ticks.jsonl"
if trace_path.exists():
    raise FileExistsError(f"refusing to overwrite {trace_path}")
trace = trace_path.open("x", buffering=1)
walk_start = trial / "walk_start.txt"
original_get_latest = DepthShmSensor.get_latest
original_rl_inference = DepthDistillationPolicy.rl_inference
tick = 0


def traced_get_latest(self):
    frames = original_get_latest(self)
    # Hash the exact copied array returned to the policy. The policy may also
    # use earlier buffered frames, so this hash identifies only the newest read.
    self._php_depth_sha256 = hashlib.sha256(np.ascontiguousarray(frames).tobytes()).hexdigest()
    heartbeat = getattr(self, "_heartbeat", None)
    self._php_depth_seq_hint = getattr(heartbeat, "_seq", None)
    return frames


def traced_rl_inference(self, robot_state_data):
    global tick
    action = original_rl_inference(self, robot_state_data)
    now = time.monotonic()
    start = float(walk_start.read_text()) if walk_start.exists() else None
    sensor = self._depth_sensor
    trace.write(json.dumps({
        "tick": tick,
        "monotonic_s": round(now, 9),
        "walk_wall_s": round(now - start, 9) if start is not None else None,
        "velocity_command_idx": int(self.active_velocity_command_idx),
        "speed_mode": int(self.speed_mode),
        "depth_newest_read_sha256": getattr(sensor, "_php_depth_sha256", None),
        "depth_last_seen_heartbeat_seq_hint": getattr(sensor, "_php_depth_seq_hint", None),
        "depth_buffer_len": int(self.depth_buffer_len),
        "action_model_order": np.asarray(self.last_policy_action).reshape(-1).tolist(),
        "action_scaled_robot_order": np.asarray(action).reshape(-1).tolist(),
    }, separators=(",", ":")) + "\n")
    tick += 1
    return action


DepthShmSensor.get_latest = traced_get_latest
DepthDistillationPolicy.rl_inference = traced_rl_inference


if __name__ == "__main__":
    try:
        main()
    finally:
        trace.close()
