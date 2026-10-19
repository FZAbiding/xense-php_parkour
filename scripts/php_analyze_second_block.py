#!/usr/bin/env python3
"""Align live second-block drift, official actions, contacts, and depth reads."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from php_analyze_policy_ticks import unique_frame_sequences
from php_diagnostic_integrity import aligned_solver_rows


def yaw_degrees(row: dict) -> float:
    qw, qx, qy, qz = (float(row[f"qpos_{i}"]) for i in range(3, 7))
    return math.degrees(math.atan2(2 * (qw * qz + qx * qy),
                                   1 - 2 * (qy * qy + qz * qz)))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    trial = args.trial.resolve()
    output = args.output.resolve()
    states, velocities, contacts, integrity = aligned_solver_rows(trial)
    ticks = [json.loads(line) for line in (trial / "policy_ticks.jsonl").read_text().splitlines()]
    with np.load(trial / "depth_diagnostic.npz") as depth:
        sequences = unique_frame_sequences(depth["frames"], depth["producer_seq"])
        depth_count = len(depth["producer_seq"])
    unmatched = ambiguous = 0
    for row in ticks:
        options = sequences.get(row["depth_newest_read_sha256"], set())
        row["matched_depth_seq"] = next(iter(options)) if len(options) == 1 else None
        unmatched += not options
        ambiguous += len(options) > 1
    trace = []
    for state, velocity, contact in zip(states, velocities, contacts):
        x = float(state["qpos_0"])
        if not 8.6 <= x <= 12.2:
            continue
        force = {side: sum(item["normal_force_n"] for item in contact["contacts"]
                           if item["terrain"] == "floor_2" and item["foot"] == side)
                 for side in ("left", "right")}
        trace.append({
            "wall_s": float(state["wall_s"]), "x_m": x,
            "y_m": float(state["qpos_1"]), "yaw_deg": yaw_degrees(state),
            "root_lateral_velocity_m_s": float(velocity["qvel_1"]),
            "block_left_normal_force_n": force["left"],
            "block_right_normal_force_n": force["right"],
        })
    if not trace:
        raise ValueError("no saved second-block approach states")
    t0 = trace[0]["wall_s"]
    t1 = trace[-1]["wall_s"]
    selected_ticks = [row for row in ticks if row["walk_wall_s"] is not None and
                      t0 <= row["walk_wall_s"] <= t1]
    if not selected_ticks:
        raise ValueError("no policy ticks in second-block window")
    action = np.asarray([row["action_model_order"] for row in selected_ticks])
    action_norm = np.linalg.norm(action, axis=1)
    action_change = np.r_[np.nan, np.linalg.norm(np.diff(action, axis=0), axis=1)]
    on_block = [row for row in trace if 9.4 <= row["x_m"] <= 10.6]
    pre_block = [row for row in trace if 8.6 <= row["x_m"] < 9.4]
    if not on_block or not pre_block:
        raise ValueError("second-block approach or footprint samples missing")
    wall = np.asarray([row["wall_s"] - t0 for row in trace])
    tick_wall = np.asarray([row["walk_wall_s"] - t0 for row in selected_ticks])
    figure, axes = plt.subplots(4, 1, figsize=(11, 10), sharex=True)
    axes[0].plot(wall, [row["y_m"] for row in trace], label="pelvis y (m)", color="#2b7a78")
    axes[0].axhline(-1, linestyle="--", color="#a44", alpha=0.6)
    axes[0].set_ylabel("Lateral y (m)")
    axes[1].plot(wall, [row["yaw_deg"] for row in trace], color="#684fa3")
    axes[1].set_ylabel("Pelvis yaw (deg)")
    for side, color in (("left", "#277da1"), ("right", "#f9844a")):
        axes[2].plot(wall, [row[f"block_{side}_normal_force_n"] for row in trace],
                     label=side, color=color)
    axes[2].set_ylabel("Block 2 force (N)")
    axes[2].legend()
    axes[3].plot(tick_wall, action_norm, label="action L2", color="#2b7a78")
    axes[3].plot(tick_wall, action_change, label="change L2", color="#f9844a")
    axes[3].set_ylabel("Raw action")
    axes[3].set_xlabel("Seconds since pelvis reached x=8.6 m")
    axes[3].legend()
    for axis in axes:
        axis.axvspan(on_block[0]["wall_s"] - t0, on_block[-1]["wall_s"] - t0,
                     alpha=0.08, color="#d77c2a")
        axis.grid(alpha=0.2)
    figure.suptitle("Block 2: live drift, contact forces, and official ONNX actions\n"
                     "Shaded interval is pelvis x=9.4–10.6 m; force is instantaneous")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=150)
    plt.close(figure)
    report = {
        "trial": str(trial), "integrity": integrity,
        "window_x_m": [8.6, 12.2], "block_footprint_x_m": [9.4, 10.6],
        "state_count": len(trace), "pre_block_state_count": len(pre_block),
        "block_state_count": len(on_block), "policy_ticks_in_window": len(selected_ticks),
        "policy_command_indices_in_window": sorted({row["velocity_command_idx"]
                                                     for row in selected_ticks}),
        "depth_sidecar_frames": depth_count, "depth_hash_matched_ticks_total": len(ticks) - unmatched,
        "depth_unmatched_ticks_total": unmatched, "depth_ambiguous_ticks_total": ambiguous,
        "pre_block_yaw_start_end_deg": [round(pre_block[0]["yaw_deg"], 2),
                                        round(pre_block[-1]["yaw_deg"], 2)],
        "pre_block_lateral_y_start_end_m": [round(pre_block[0]["y_m"], 3),
                                            round(pre_block[-1]["y_m"], 3)],
        "block_footprint_yaw_range_deg": [round(min(row["yaw_deg"] for row in on_block), 2),
                                          round(max(row["yaw_deg"] for row in on_block), 2)],
        "block_footprint_peak_force_n": {side: round(max(row[f"block_{side}_normal_force_n"]
                                                         for row in on_block), 2)
                                         for side in ("left", "right")},
        "block_footprint_contact_state_count": sum(
            row["block_left_normal_force_n"] > 0 or row["block_right_normal_force_n"] > 0
            for row in on_block),
        "action_l2_range_window": [round(float(np.min(action_norm)), 4),
                                   round(float(np.max(action_norm)), 4)],
        "action_change_l2_peak_window": round(float(np.nanmax(action_change)), 4),
        "limits": (("One solver-contact row is missing only after the scored x target; "
                    "all raw files remain intact. "
                    if integrity["unscored_terminal_contact_rows_missing"] else "") +
                   "Wall-clock alignment is approximate, force is sampled rather than "
                   "integrated, and a single trajectory cannot identify why yaw changed."),
        "source_sha256": {name: digest(trial / name) for name in (
            "qpos.csv", "qvel.csv", "solver_contacts.jsonl", "policy_ticks.jsonl",
            "depth_diagnostic.npz", "course_score.json")},
        "rows": trace,
    }
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(output)
    print(output.with_suffix(".json"))


if __name__ == "__main__":
    main()
