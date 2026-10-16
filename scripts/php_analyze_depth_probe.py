#!/usr/bin/env python3
"""Summarize one separate depth probe and plot passive frames near course landmarks."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


LANDMARK_X = (8.0, 10.0, 15.0, 20.0)


def analyze(trial: Path, output: Path) -> dict:
    sidecar = json.loads((trial / "depth_diagnostic.json").read_text())
    score = json.loads((trial / "course_score.json").read_text())
    audit = json.loads((trial / "audit.json").read_text())
    if sidecar["status"] != "complete" or sidecar["walk_start_monotonic_s"] is None:
        raise ValueError("probe requires complete depth data and a walking start time")
    with (trial / "qpos.csv").open(newline="") as stream:
        positions = [(float(row["wall_s"]), float(row["qpos_0"]))
                     for row in csv.DictReader(stream)]
    if not positions:
        raise ValueError("qpos trace is empty")
    state_t, state_x = (np.asarray(values) for values in zip(*positions))
    by_floor = defaultdict(lambda: {"sampled_contacts": 0,
                                    "positive_force_samples": 0,
                                    "max_normal_force_n": 0.0,
                                    "first_x_m": None, "last_x_m": None})
    contact_rows = 0
    with (trial / "solver_contacts.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            contact_rows += 1
            x = float(np.interp(row["wall_s"], state_t, state_x))
            for contact in row["contacts"]:
                floor = by_floor[contact["terrain"]]
                floor["sampled_contacts"] += 1
                force = float(contact["normal_force_n"])
                if force > 0:
                    floor["positive_force_samples"] += 1
                floor["max_normal_force_n"] = max(floor["max_normal_force_n"], force)
                floor["first_x_m"] = x if floor["first_x_m"] is None else floor["first_x_m"]
                floor["last_x_m"] = x
    if contact_rows != len(positions):
        raise ValueError("qpos and solver-contact sample counts differ")

    with np.load(trial / "depth_diagnostic.npz") as recorded:
        frames = recorded["frames"][:, 0, 0]
        seq = recorded["producer_seq"]
        receiver_t = recorded["receiver_monotonic_s"]
        publish_t = recorded["producer_heartbeat_unix_s"]
        receive_unix_t = recorded["receiver_unix_s"]
    depth_walk_t = receiver_t - sidecar["walk_start_monotonic_s"]
    in_walk = (depth_walk_t >= 0) & (depth_walk_t <= state_t[-1])
    gaps = np.diff(receiver_t)
    report = {
        "trial": str(trial), "kind": "passive diagnostic, excluded from fixed-protocol cohort",
        "score_consecutive_cleared": score["consecutive_cleared"],
        "quality": audit["quality"],
        "state_samples": len(positions), "contact_rows": contact_rows,
        "walk_duration_s": round(float(state_t[-1]), 3),
        "depth": {
            "frames_total": len(frames), "frames_during_walk": int(in_walk.sum()),
            "first_seq": int(seq[0]), "last_seq": int(seq[-1]),
            "sequence_gaps": sidecar["sequence_gaps"],
            "receiver_interval_median_ms": round(float(np.median(gaps) * 1000), 2),
            "receiver_interval_p95_ms": round(float(np.percentile(gaps, 95) * 1000), 2),
            "finite_fraction": round(float(np.isfinite(frames).mean()), 8),
            "pixel_min": round(float(frames.min()), 5),
            "pixel_max": round(float(frames.max()), 5),
            "pixel_below_minus_half_fraction": round(float((frames < -0.5).mean()), 8),
            "publish_to_receive_median_ms": round(float(np.median(
                (receive_unix_t - publish_t) * 1000)), 2),
        },
        "contacts_by_terrain": {key: {
            **value,
            "max_normal_force_n": round(value["max_normal_force_n"], 2),
            "first_x_m": round(value["first_x_m"], 3),
            "last_x_m": round(value["last_x_m"], 3),
        } for key, value in sorted(by_floor.items())},
        "limits": "Frames are passive post-publish shared-memory copies, not exact policy-tick inputs; "
                  "contacts and states are sampled near 60 Hz, not every 500 Hz physics step.",
    }
    # Publish and receiver Unix clocks live on the same host; this is transport
    # observation, not camera exposure or precise policy-consumption latency.

    landmarks = []
    figure, axes = plt.subplots(1, len(LANDMARK_X), figsize=(13, 3.5),
                               constrained_layout=True)
    for axis, target_x in zip(axes, LANDMARK_X):
        candidates = np.flatnonzero(state_x >= target_x)
        if len(candidates) == 0:
            axis.set_axis_off()
            landmarks.append({"target_x_m": target_x, "reached": False})
            continue
        state_idx = int(candidates[0])
        frame_idx = int(np.argmin(np.abs(depth_walk_t - state_t[state_idx])))
        axis.imshow(frames[frame_idx], cmap="viridis", vmin=-0.5, vmax=0.5)
        axis.set_title(f"x≈{target_x:g} m\nΔt={1000 * (depth_walk_t[frame_idx] - state_t[state_idx]):+.0f} ms")
        axis.set_axis_off()
        landmarks.append({
            "target_x_m": target_x, "reached": True,
            "state_wall_s": round(float(state_t[state_idx]), 3),
            "depth_seq": int(seq[frame_idx]),
            "depth_receiver_minus_state_ms": round(float(
                (depth_walk_t[frame_idx] - state_t[state_idx]) * 1000), 2),
        })
    figure.suptitle("Passive normalized depth nearest saved robot states (not exact policy inputs)")
    figure.savefig(output.with_suffix(".png"), dpi=160)
    plt.close(figure)
    report["depth_landmarks"] = landmarks
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = analyze(args.trial.resolve(), args.output)
    print(json.dumps({"output": str(args.output), "score": report["score_consecutive_cleared"],
                      "depth_frames": report["depth"]["frames_total"]}))


if __name__ == "__main__":
    main()
