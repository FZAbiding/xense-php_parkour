#!/usr/bin/env python3
"""Compare saved PHP trials near block 2 without running the simulator."""

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


ROOT = Path(__file__).resolve().parents[1]
TRIALS = ROOT / "outputs/reproduction/official_benchmark"
DEFAULT_NAMES = (
    "trial_025",
    "trial_030_interactive",
    "trial_031_interactive",
    "trial_032_w_only",
)
CHECKPOINTS = (8.0, 10.0, 10.8, 12.1, 13.0)


def read_trace(path: Path) -> list[dict[str, float]]:
    with path.open(newline="") as stream:
        rows = [{key: float(value) for key, value in row.items()}
                for row in csv.DictReader(stream)]
    if not rows or any(rows[i]["wall_s"] > rows[i + 1]["wall_s"]
                       for i in range(len(rows) - 1)):
        raise ValueError(f"empty or non-monotonic time in {path}")
    return rows


def yaw_deg(row: dict[str, float]) -> float:
    w, x, y, z = (row[name] for name in ("qw", "qx", "qy", "qz"))
    return math.degrees(math.atan2(2 * (w * z + x * y),
                                   1 - 2 * (y * y + z * z)))


def first_at_x(rows: list[dict[str, float]], x: float) -> dict[str, float] | None:
    return next((row for row in rows if row["x"] >= x), None)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def first_saved_pose(path: Path) -> dict[str, float] | None:
    """Read the first walking state; this is after release, not the release packet."""
    if not path.is_file():
        return None
    with path.open(newline="") as stream:
        row = next(csv.DictReader(stream), None)
    if row is None:
        return None
    w, x, y, z = (float(row[f"qpos_{i}"]) for i in (3, 4, 5, 6))
    pitch_sin = max(-1.0, min(1.0, 2 * (w * y - z * x)))
    return {
        "wall_s": round(float(row["wall_s"]), 5),
        "x_m": round(float(row["qpos_0"]), 4),
        "y_m": round(float(row["qpos_1"]), 4),
        "z_m": round(float(row["qpos_2"]), 4),
        "pitch_deg": round(math.degrees(math.asin(pitch_sin)), 2),
        "yaw_deg": round(math.degrees(math.atan2(
            2 * (w * z + x * y), 1 - 2 * (y * y + z * z))), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", action="append", dest="names")
    parser.add_argument("--trial-root", type=Path, default=TRIALS)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "reports/phase1_early_drift.png")
    args = parser.parse_args()
    names = args.names or DEFAULT_NAMES
    figure, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    colors = ("#2b7a78", "#d9822b", "#7a52a3", "#be4343", "#2363a6",
              "#8a5685", "#696969", "#a2a038")
    observed_y = []
    summary = {"scope": "descriptive historical comparison, not a controlled effect estimate",
               "first_crossing_x_m": list(CHECKPOINTS), "trials": []}
    for index, name in enumerate(names):
        directory = args.trial_root / name
        trace_path = directory / "pelvis.csv"
        rows = read_trace(trace_path)
        result = json.loads((directory / "result.json").read_text())
        score = json.loads((directory / "course_score.json").read_text())
        audit = json.loads((directory / "audit.json").read_text())
        color = colors[index % len(colors)]
        stop = next((i + 1 for i, row in enumerate(rows) if row["x"] >= 13.5),
                    len(rows))
        segment = [row for row in rows[:stop] if 7.5 <= row["x"] <= 13.5]
        observed_y.extend(row["y"] for row in segment)
        label = f"{name} ({result['steer']}, {score['consecutive_cleared']}/12)"
        axes[0].plot([row["x"] for row in segment], [row["y"] for row in segment],
                     color=color, linewidth=1.6, label=label)
        axes[1].plot([row["x"] for row in segment], [yaw_deg(row) for row in segment],
                     color=color, linewidth=1.4)
        axes[2].plot([row["x"] for row in segment], [row["vy"] for row in segment],
                     color=color, linewidth=1.4)
        events = [event for event in result.get("steer_events", [])
                  if event.get("key") in ("a", "d") and 7.5 <= event["x"] <= 13.5]
        axes[0].scatter([event["x"] for event in events],
                        [event["y"] for event in events], marker="v", s=38,
                        color=color, edgecolors="black", linewidths=0.35, zorder=5)
        points = {}
        for x in CHECKPOINTS:
            row = first_at_x(rows, x)
            if row is not None:
                points[f"{x:g}"] = {"wall_s": round(row["wall_s"], 3),
                                     "y_m": round(row["y"], 3),
                                     "vy_m_s": round(row["vy"], 3),
                                     "yaw_deg": round(yaw_deg(row), 1)}
        summary["trials"].append({
            "name": name,
            "trajectory_sha256": digest(trace_path),
            "benchmark_script_sha256": result["benchmark_script_sha256"],
            "steer": result["steer"],
            "target_x_m": result["target_x"],
            "quality": audit["quality"],
            "consecutive_cleared": score["consecutive_cleared"],
            "first_saved_pose": first_saved_pose(directory / "qpos.csv"),
            "block_2_first_exit_y_m": score["blocks"][1]["first_exit_y_m"],
            "early_steer_events": events,
            "first_crossings": points,
        })
    for axis in axes:
        axis.axvspan(9.4, 10.6, color="#d4c6a5", alpha=0.28)
        axis.axvline(12.1, color="#555555", linestyle=":", linewidth=1)
        axis.grid(alpha=0.2)
    axes[0].axhline(1, color="#888888", linestyle="--", linewidth=0.8)
    axes[0].axhline(-1, color="#888888", linestyle="--", linewidth=0.8)
    axes[0].set_ylabel("Lateral pelvis y (m)")
    axes[0].set_ylim(min(-2.1, min(observed_y) - 0.2),
                     max(1.1, max(observed_y) + 0.2))
    axes[0].legend(loc="lower left", fontsize=8)
    axes[1].set_ylabel("World yaw (deg)")
    axes[2].set_ylabel("World lateral velocity (m/s)")
    axes[2].set_xlabel("Forward pelvis x (m)")
    axes[2].set_xlim(7.5, 13.5)
    figure.suptitle("PHP released ONNX: early lateral drift near block 2\n"
                     "Shaded = block footprint; dotted = first-exit scoring x; triangles = a/d commands")
    figure.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=170)
    json_path = args.output.with_suffix(".json")
    json_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(args.output)
    print(json_path)


if __name__ == "__main__":
    main()
