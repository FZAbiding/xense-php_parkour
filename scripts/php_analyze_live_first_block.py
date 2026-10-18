#!/usr/bin/env python3
"""Audit time-aligned live solver force, full velocity, and depth near block 1."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def yaw_degrees(row: dict) -> float:
    w, x, y, z = [float(row[f"qpos_{index}"]) for index in range(3, 7)]
    return math.degrees(math.atan2(2 * (w * z + x * y),
                                   1 - 2 * (y * y + z * z)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "reports/phase1_live_first_block.png")
    args = parser.parse_args()
    trial = args.trial.resolve()
    state_path = trial / "qpos.csv"
    velocity_path = trial / "qvel.csv"
    contacts_path = trial / "solver_contacts.jsonl"
    depth_path = trial / "depth_diagnostic.npz"
    with state_path.open(newline="") as stream:
        states = list(csv.DictReader(stream))
    with velocity_path.open(newline="") as stream:
        velocities = list(csv.DictReader(stream))
    with contacts_path.open() as stream:
        contacts = [json.loads(line) for line in stream]
    if not states or len(states) != len(velocities) or len(states) != len(contacts):
        raise ValueError("qpos, qvel, and solver contact sample counts differ")
    for state, velocity, contact in zip(states, velocities, contacts):
        if (abs(float(state["sim_s"]) - float(velocity["sim_s"])) > 1e-5 or
                abs(float(state["sim_s"]) - float(contact["sim_s"])) > 1e-5):
            raise ValueError("solver records do not share a simulation time")
    selected = []
    for state, velocity, contact in zip(states, velocities, contacts):
        x = float(state["qpos_0"])
        if not 3.8 <= x <= 6.2:
            continue
        force = {side: sum(item["normal_force_n"] for item in contact["contacts"]
                           if item["terrain"] == "floor_1" and item["foot"] == side)
                 for side in ("left", "right")}
        angular_speed = math.degrees(math.sqrt(sum(
            float(velocity[f"qvel_{index}"]) ** 2 for index in (3, 4, 5))))
        selected.append({"wall_s": float(state["wall_s"]), "x_m": x,
                         "yaw_deg": yaw_degrees(state),
                         "root_angular_speed_deg_s": angular_speed,
                         "block_left_normal_force_n": force["left"],
                         "block_right_normal_force_n": force["right"]})
    if not selected:
        raise ValueError("no first-block samples")
    footprint = [row for row in selected if 4.3 <= row["x_m"] <= 5.7]
    if not footprint:
        raise ValueError("no states within the first block footprint")
    t0 = next((row["wall_s"] for row in selected if row["x_m"] >= 4.3),
              selected[0]["wall_s"])
    for row in selected:
        row["since_x4_3_s"] = row["wall_s"] - t0
    depth_summary = json.loads((trial / "depth_diagnostic.json").read_text())
    with np.load(depth_path) as depth:
        seq = depth["producer_seq"]
        receiver = depth["receiver_monotonic_s"]
        walk_start = depth_summary["walk_start_monotonic_s"]
        relative = receiver - walk_start
        on_block = (relative >= selected[0]["wall_s"]) & (
            relative <= selected[-1]["wall_s"])
        on_footprint = (relative >= footprint[0]["wall_s"]) & (
            relative <= footprint[-1]["wall_s"])
        depth_report = {
            "frame_count": int(len(seq)),
            "sequence_gaps": int(np.sum(np.diff(seq) != 1)),
            "median_receiver_gap_s": round(float(np.median(np.diff(relative))), 4),
            "approx_frames_in_plot_window": int(np.sum(on_block)),
            "approx_frames_in_block_footprint": int(np.sum(on_footprint)),
            "alignment_limit": "receiver time minus walk start is approximate; "
                               "not camera exposure or exact policy input time",
        }
    times = [row["since_x4_3_s"] for row in selected]
    figure, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    axes[0].plot(times, [row["yaw_deg"] for row in selected], color="#684fa3")
    axes[0].set_ylabel("Pelvis yaw (deg)")
    axes[1].plot(times, [row["root_angular_speed_deg_s"] for row in selected],
                 color="#2b7a78")
    axes[1].set_ylabel("Root angular speed (deg/s)")
    for side, color in (("left", "#277da1"), ("right", "#f9844a")):
        axes[2].plot(times, [row[f"block_{side}_normal_force_n"] for row in selected],
                     color=color, label=side)
    axes[2].set_ylabel("Instantaneous normal force (N)")
    axes[2].set_xlabel("Seconds since pelvis first crossed x=4.3 m")
    axes[2].legend()
    for axis in axes:
        axis.axvline(0, color="#777", linewidth=0.8)
        axis.grid(alpha=0.2)
    figure.suptitle("Block 1: live solver samples aligned to saved qpos/qvel\n"
                     "Force is an instant sample, not integrated impulse")
    figure.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=160)
    report = {
        "trial": str(trial),
        "method": "original live solver contact force and qvel sampled with qpos",
        "limits": "discrete samples; no force between samples or original policy action tensor",
        "hashes": {name: digest(path) for name, path in (
            ("qpos", state_path), ("qvel", velocity_path),
            ("solver_contacts", contacts_path), ("depth_npz", depth_path))},
        "matched_sample_count": len(states),
        "plot_window_x_m": [3.8, 6.2],
        "block_footprint_x_m": [4.3, 5.7],
        "block_footprint_sample_count": len(footprint),
        "block_footprint_yaw_range_deg": [round(min(row["yaw_deg"] for row in footprint), 2),
                                         round(max(row["yaw_deg"] for row in footprint), 2)],
        "block_footprint_peak_normal_force_n": {
            side: round(max(row[f"block_{side}_normal_force_n"] for row in footprint), 2)
            for side in ("left", "right")},
        "block_footprint_peak_root_angular_speed_deg_s": round(max(
            row["root_angular_speed_deg_s"] for row in footprint), 2),
        "depth": depth_report,
        "rows": selected,
    }
    json_path = args.output.with_suffix(".json")
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    print(args.output)
    print(json_path)


if __name__ == "__main__":
    main()
