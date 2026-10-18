#!/usr/bin/env python3
"""Align saved first-block foot geometry contacts with pelvis yaw.

This is an offline mj_forward reconstruction. Recorded qpos cannot recover the
original solver impulses, joint velocities, or policy observations.
"""

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
import mujoco


ROOT = Path(__file__).resolve().parents[1]
TRIALS = ROOT / "outputs/reproduction/official_benchmark"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def yaw_degrees(qpos) -> float:
    qw, qx, qy, qz = qpos[3:7]
    return math.degrees(math.atan2(2 * (qw * qz + qx * qy),
                                   1 - 2 * (qy * qy + qz * qz)))


def trace_trial(directory: Path) -> dict:
    model_path = directory / "replay_model.mjb"
    state_path = directory / "qpos.csv"
    result = json.loads((directory / "result.json").read_text())
    model = mujoco.MjModel.from_binary_path(str(model_path))
    data = mujoco.MjData(model)
    geom_names = [mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, index) or ""
                  for index in range(model.ngeom)]
    floors = {index: name for index, name in enumerate(geom_names)
              if name in ("floor", "floor_1")}
    feet = {index: "left" if "left_foot" in name else "right"
            for index, name in enumerate(geom_names)
            if "left_foot" in name or "right_foot" in name}
    if set(floors.values()) != {"floor", "floor_1"} or not feet:
        raise ValueError("saved model lacks the first-block or foot geometry")
    rows = []
    with state_path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            data.qpos[:] = [float(row[f"qpos_{index}"]) for index in range(model.nq)]
            data.qvel[:] = 0
            data.time = float(row["sim_s"])
            x = float(data.qpos[0])
            if not 3.8 <= x <= 6.2:
                continue
            mujoco.mj_forward(model, data)
            touched = set()
            for contact in data.contact[:data.ncon]:
                if contact.dist > 0:
                    continue
                for terrain_id, foot_id in ((contact.geom1, contact.geom2),
                                            (contact.geom2, contact.geom1)):
                    if terrain_id in floors and foot_id in feet:
                        touched.add((floors[terrain_id], feet[foot_id]))
            rows.append({
                "wall_s": round(float(row["wall_s"]), 5),
                "x_m": round(x, 4), "y_m": round(float(data.qpos[1]), 4),
                "yaw_deg": round(yaw_degrees(data.qpos), 2),
                "block_left": ("floor_1", "left") in touched,
                "block_right": ("floor_1", "right") in touched,
                "ground_left": ("floor", "left") in touched,
                "ground_right": ("floor", "right") in touched,
            })
    if not rows:
        raise ValueError(f"no saved first-block states in {directory}")
    t0 = next((row["wall_s"] for row in rows if row["x_m"] >= 4.3), rows[0]["wall_s"])
    for row in rows:
        row["since_x4_3_s"] = round(row["wall_s"] - t0, 5)
    first_yaw_45 = next((row for row in rows if row["x_m"] >= 4.3
                         and abs(row["yaw_deg"]) >= 45), None)
    first_x5_7 = next((row for row in rows if row["x_m"] >= 5.7), None)
    first_direction = next((event for event in result.get("steer_events", [])
                            if event.get("key") in ("a", "d")), None)
    return {
        "trial": directory.name,
        "model_sha256": digest(model_path), "qpos_sha256": digest(state_path),
        "first_yaw_abs45": first_yaw_45,
        "first_x5_7": first_x5_7,
        "first_direction_event": first_direction,
        "block_contact_frames": {
            "left": sum(row["block_left"] for row in rows),
            "right": sum(row["block_right"] for row in rows),
            "both": sum(row["block_left"] and row["block_right"] for row in rows),
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", action="append", required=True,
                        help="saved trial folder name; repeat for comparisons")
    parser.add_argument("--trial-root", type=Path, default=TRIALS)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "reports/phase1_first_block_support.png")
    args = parser.parse_args()
    trials = [trace_trial(args.trial_root / name) for name in args.trial]
    figure, axes = plt.subplots(len(trials), 2, figsize=(13, 3.1 * len(trials)),
                                squeeze=False)
    colors = {"block_left": "#277da1", "block_right": "#f9844a",
              "ground_left": "#6c91a7", "ground_right": "#bd8f72"}
    labels = {"block_left": "block: left", "block_right": "block: right",
              "ground_left": "ground: left", "ground_right": "ground: right"}
    for index, trial in enumerate(trials):
        rows = trial["rows"]
        times = [row["since_x4_3_s"] for row in rows]
        yaw_axis, foot_axis = axes[index]
        yaw_axis.plot(times, [row["yaw_deg"] for row in rows], color="#684fa3")
        yaw_axis.axhline(45, color="#a44", linestyle="--", linewidth=0.8)
        yaw_axis.axhline(-45, color="#a44", linestyle="--", linewidth=0.8)
        yaw_axis.axvline(0, color="#555", linewidth=0.8)
        if trial["first_x5_7"]:
            for axis in (yaw_axis, foot_axis):
                axis.axvline(trial["first_x5_7"]["since_x4_3_s"],
                             color="#777", linestyle=":", linewidth=0.9)
        for side_index, key in enumerate(labels):
            foot_axis.scatter([row["since_x4_3_s"] for row in rows if row[key]],
                              [side_index] * sum(row[key] for row in rows),
                              color=colors[key], s=9, label=labels[key])
        yaw_axis.set_ylabel(f"{trial['trial']}\nyaw (deg)")
        foot_axis.set_yticks(range(4), list(labels.values()))
        foot_axis.set_ylim(-0.6, 3.6)
        for axis in (yaw_axis, foot_axis):
            axis.grid(alpha=0.2)
            axis.set_xlabel("Seconds since pelvis first crossed x=4.3 m")
    figure.suptitle("First-block support and yaw from saved states\n"
                     "Dotted = pelvis first crossed x=5.7 m; dots = sampled geometry contacts")
    figure.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=160)
    report = {"method": "offline mj_forward with saved qpos and zero placeholder qvel",
              "limits": "geometry proximity at sampled states, not solver force or causal proof",
              "trials": trials}
    json_path = args.output.with_suffix(".json")
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    print(args.output)
    print(json_path)


if __name__ == "__main__":
    main()
