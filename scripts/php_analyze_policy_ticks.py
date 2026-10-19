#!/usr/bin/env python3
"""Match actual per-tick depth reads to sidecar frames by bytes, then plot block 1.

A matching SHA-256 identifies the bytes the policy read. Sequence identity is
claimed only when that hash occurs for exactly one recorded producer sequence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_frame_sequences(frames: np.ndarray, seq: np.ndarray) -> dict[str, set[int]]:
    matches: dict[str, set[int]] = defaultdict(set)
    for frame, number in zip(frames, seq):
        matches[hashlib.sha256(np.ascontiguousarray(frame).tobytes()).hexdigest()].add(int(number))
    return matches


def yaw_degrees(row: dict[str, str]) -> float:
    qw, qx, qy, qz = (float(row[f"qpos_{i}"]) for i in range(3, 7))
    return math.degrees(math.atan2(2 * (qw * qz + qx * qy),
                                   1 - 2 * (qy * qy + qz * qz)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "reports/phase1_policy_ticks.png")
    args = parser.parse_args()
    trial = args.trial.resolve()
    output = args.output.resolve()
    trace_path = trial / "policy_ticks.jsonl"
    depth_path = trial / "depth_diagnostic.npz"
    state_path = trial / "qpos.csv"
    ticks = [json.loads(line) for line in trace_path.read_text().splitlines()]
    if not ticks or any(row["tick"] != i for i, row in enumerate(ticks)):
        raise ValueError("policy tick indices are incomplete")
    if any(len(row["action_model_order"]) != 29 or
           len(row["action_scaled_robot_order"]) != 29 for row in ticks):
        raise ValueError("expected 29-dimensional policy actions")
    tick_time = np.asarray([row["walk_wall_s"] if row["walk_wall_s"] is not None
                            else float("nan") for row in ticks])
    if np.any(np.diff(np.asarray([row["monotonic_s"] for row in ticks])) <= 0):
        raise ValueError("policy tick timestamps are not monotonic")
    with np.load(depth_path) as data:
        matches = unique_frame_sequences(data["frames"], data["producer_seq"])
    unmatched = ambiguous = 0
    for row in ticks:
        options = matches.get(row["depth_newest_read_sha256"], set())
        row["depth_matched_seq"] = next(iter(options)) if len(options) == 1 else None
        unmatched += not options
        ambiguous += len(options) > 1
    with state_path.open(newline="") as stream:
        states = list(csv.DictReader(stream))
    state_time = np.asarray([float(row["wall_s"]) for row in states])
    state_x = np.asarray([float(row["qpos_0"]) for row in states])
    state_yaw = np.asarray([yaw_degrees(row) for row in states])
    on_block = (state_x >= 4.3) & (state_x <= 5.7)
    if not np.any(on_block):
        raise ValueError("no first-block state samples")
    first = float(state_time[on_block][0])
    last = float(state_time[on_block][-1])
    tick_window = [row for row in ticks if row["walk_wall_s"] is not None and
                   first <= row["walk_wall_s"] <= last]
    if not tick_window:
        raise ValueError("no policy ticks on first block")
    actions = np.asarray([row["action_model_order"] for row in tick_window])
    action_norm = np.linalg.norm(actions, axis=1)
    action_change = np.r_[np.nan, np.linalg.norm(np.diff(actions, axis=0), axis=1)]
    plot_time = np.asarray([row["walk_wall_s"] for row in tick_window]) - first
    sequence = [row["depth_matched_seq"] for row in tick_window]
    heartbeat = [row["depth_last_seen_heartbeat_seq_hint"] for row in tick_window]
    figure, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    state_window = (state_time >= first) & (state_time <= last)
    axes[0].plot(state_time[state_window] - first, state_yaw[state_window], color="#684fa3")
    axes[0].set_ylabel("Pelvis yaw (deg)")
    axes[1].plot(plot_time, action_norm, label="action L2", color="#2b7a78")
    axes[1].plot(plot_time, action_change, label="tick-to-tick change L2", color="#f9844a")
    axes[1].set_ylabel("Raw model-order action")
    axes[1].legend()
    axes[2].step(plot_time, sequence, where="post", label="frame seq: exact bytes", color="#277da1")
    axes[2].step(plot_time, heartbeat, where="post", label="heartbeat seq hint", color="#b56576",
                 alpha=0.65)
    axes[2].set_ylabel("Depth producer seq")
    axes[2].set_xlabel("Seconds since first saved state on block 1")
    axes[2].legend()
    for axis in axes:
        axis.grid(alpha=0.2)
    figure.suptitle("Block 1: official ONNX actions and exact depth-array fingerprint\n"
                     "Sequence mapping is unique only when no two frames share the same bytes")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=150)
    plt.close(figure)
    report = {
        "trial": str(trial), "ticks_total": len(ticks),
        "ticks_after_walk_start": int(np.sum(np.isfinite(tick_time))),
        "ticks_on_first_block": len(tick_window),
        "depth_hash_matched_ticks": len(ticks) - unmatched,
        "depth_hash_unmatched_ticks": unmatched,
        "depth_sequence_ambiguous_ticks": ambiguous,
        "first_block_yaw_range_deg": [round(float(np.min(state_yaw[on_block])), 2),
                                      round(float(np.max(state_yaw[on_block])), 2)],
        "first_block_action_l2_range": [round(float(np.min(action_norm)), 4),
                                        round(float(np.max(action_norm)), 4)],
        "first_block_action_change_l2_peak": round(float(np.nanmax(action_change)), 4),
        "first_block_command_indices": sorted({row["velocity_command_idx"]
                                               for row in tick_window}),
        "limits": ("Hash matches exact newest depth-array bytes but not camera exposure time. "
                   "The sequence is unknown if identical bytes occur at multiple sequence numbers. "
                   "Action magnitude alone does not establish a cause of yaw."),
        "source_sha256": {name: digest(path) for name, path in (
            ("policy_ticks", trace_path), ("depth_npz", depth_path), ("qpos", state_path))},
        "first_block_ticks": [{key: row[key] for key in (
            "tick", "walk_wall_s", "velocity_command_idx", "depth_matched_seq",
            "depth_last_seen_heartbeat_seq_hint", "depth_newest_read_sha256")}
            for row in tick_window],
    }
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(output)
    print(output.with_suffix(".json"))


if __name__ == "__main__":
    main()
