#!/usr/bin/env python3
"""Reconstruct sampled foot/terrain geometry contacts from saved MuJoCo qpos.

This offline diagnostic uses mj_forward with recorded positions. It does not
recover the simulator's historical contact impulses or policy observations.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import mujoco


CHECKPOINTS = (5.0, 8.0, 9.4, 10.0, 10.8, 12.1, 13.5)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", required=True, type=Path)
    parser.add_argument("--output", type=Path,
                        help="JSON destination; default is <trial>/contact_replay.json")
    args = parser.parse_args()
    trial = args.trial.resolve()
    model_path = trial / "replay_model.mjb"
    trace_path = trial / "qpos.csv"
    if not model_path.is_file() or not trace_path.is_file():
        parser.error("trial requires replay_model.mjb and qpos.csv")
    model = mujoco.MjModel.from_binary_path(str(model_path))
    data = mujoco.MjData(model)
    names = [mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i) or ""
             for i in range(model.ngeom)]
    terrain = {i: name for i, name in enumerate(names)
               if name == "floor" or name.startswith("floor_")}
    feet = {i: ("left" if "left_foot" in name else "right")
            for i, name in enumerate(names)
            if "left_foot" in name or "right_foot" in name}
    if not terrain or not feet:
        raise ValueError("model has no named foot or terrain geoms")
    by_floor: dict[str, dict] = defaultdict(
        lambda: {"frames_with_touch": 0, "left_frames": 0,
                 "right_frames": 0, "first": None, "last": None})
    checkpoint_rows = {}
    total = 0
    with trace_path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"wall_s", "sim_s", *(f"qpos_{i}" for i in range(model.nq))}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("qpos.csv columns do not match the saved model")
        for row in reader:
            total += 1
            data.qpos[:] = [float(row[f"qpos_{i}"]) for i in range(model.nq)]
            data.qvel[:] = 0
            data.time = float(row["sim_s"])
            mujoco.mj_forward(model, data)
            x, y = float(data.qpos[0]), float(data.qpos[1])
            at = {"wall_s": round(float(row["wall_s"]), 5),
                  "sim_s": round(float(row["sim_s"]), 5),
                  "x_m": round(x, 4), "y_m": round(y, 4)}
            touches = {}
            for contact in data.contact[:data.ncon]:
                pair = ((contact.geom1, contact.geom2),
                        (contact.geom2, contact.geom1))
                for floor_id, foot_id in pair:
                    if floor_id not in terrain or foot_id not in feet:
                        continue
                    if contact.dist > 0:
                        continue
                    key = (terrain[floor_id], feet[foot_id])
                    touches[key] = min(touches.get(key, float("inf")),
                                       float(contact.dist))
            for floor in {floor for floor, _ in touches}:
                summary = by_floor[floor]
                summary["frames_with_touch"] += 1
                for side in ("left", "right"):
                    summary[f"{side}_frames"] += int((floor, side) in touches)
                if summary["first"] is None:
                    summary["first"] = at
                summary["last"] = at
            for checkpoint in CHECKPOINTS:
                label = f"{checkpoint:g}"
                if label not in checkpoint_rows and x >= checkpoint:
                    checkpoint_rows[label] = {
                        **at,
                        "foot_terrain_touches": [
                            {"terrain": floor, "foot": side,
                             "min_contact_dist_m": round(distance, 5)}
                            for (floor, side), distance in sorted(touches.items())],
                    }
    report = {
        "method": "offline mj_forward on recorded qpos; nonpositive geometry contact distance",
        "limits": "sampled positions only; no historical qvel, contact forces, depth, or impulses",
        "trial": str(trial), "model_sha256": sha256(model_path),
        "qpos_sha256": sha256(trace_path), "sampled_frames": total,
        "foot_terrain_touch_frames": dict(sorted(by_floor.items())),
        "first_x_crossings": checkpoint_rows,
    }
    output = args.output or trial / "contact_replay.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
