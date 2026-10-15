#!/usr/bin/env python3
"""Audit a released-model MuJoCo trial using its own inference/simulator logs."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from datetime import datetime
from pathlib import Path


ANSI = re.compile(r"\x1b\[[0-9;]*m")
TIMESTAMP = re.compile(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?)")
SIM_FPS = re.compile(r"Simulation FPS: ([\d.]+)")
POLICY_FPS = re.compile(r"RL FPS: ([\d.]+)")
DEPTH_STALE = ("depth frame stale", "entering stiff hold")


def log_entries(path: Path, marker: re.Pattern, after: datetime, before: datetime):
    for raw in path.read_text(errors="replace").splitlines():
        line = ANSI.sub("", raw)
        timestamp = TIMESTAMP.search(line)
        match = marker.search(line)
        if timestamp and match:
            at = datetime.fromisoformat(timestamp.group(1))
            if after <= at <= before:
                yield at, float(match.group(1))


def longest_below(values: list[float], threshold: float) -> int:
    longest = current = 0
    for value in values:
        current = current + 1 if value < threshold else 0
        longest = max(longest, current)
    return longest


def audit(folder: Path) -> dict:
    result = json.loads((folder / "result.json").read_text())
    if not (folder / "inference.log").exists() or not (folder / "sim.log").exists():
        return {"trial": str(folder), "quality": "logs_missing"}
    inference_lines = (folder / "inference.log").read_text(errors="replace").splitlines()
    start_line = next((line for line in inference_lines
                       if "Depth distillation policy started" in line), None)
    if start_line is None:
        return {"trial": str(folder), "quality": "policy_not_started"}
    walk_start = datetime.fromisoformat(TIMESTAMP.search(start_line).group(1))
    finish = datetime.fromisoformat(result["finished"][:19])
    sim = list(log_entries(folder / "sim.log", SIM_FPS, walk_start, finish))
    policy = list(log_entries(folder / "inference.log", POLICY_FPS, walk_start, finish))
    stale = [line for line in inference_lines
             if (stamp := TIMESTAMP.search(line))
             and walk_start <= datetime.fromisoformat(stamp.group(1)) <= finish
             and any(marker in line.lower() for marker in DEPTH_STALE)]
    sim_values = [value for _, value in sim]
    policy_values = [value for _, value in policy]
    longest = longest_below(sim_values, 400)
    start_yaw = result.get("yaw_before_release_deg")
    heading_outlier = start_yaw is not None and abs(start_yaw) > 2.0
    # The benchmark's finished timestamp has one-second precision. Its live
    # guard can observe the final slow/stale log line later in that second,
    # even though the offline log window above excludes it.
    live_status = result.get("status")
    quality = ("sustained_sim_slowdown" if live_status == "sim_fps_low" else
               "depth_stale" if live_status == "depth_stale" else
               "no_sim_fps_samples" if not sim_values else
               "depth_stale" if stale else
               "sustained_sim_slowdown" if longest >= 2 else
               "policy_rate_low" if longest_below(policy_values, 45) >= 2 else
               "start_heading_outlier" if heading_outlier else
               "nominal")
    return {"trial": str(folder), "quality": quality,
            "start_yaw_deg": start_yaw,
            "start_heading_within_2_deg": not heading_outlier if start_yaw is not None else None,
            "walk_start": walk_start.isoformat(), "finished": finish.isoformat(),
            "sim_fps_samples": len(sim_values),
            "sim_fps_median": round(statistics.median(sim_values), 1) if sim_values else None,
            "sim_fps_min": min(sim_values, default=None),
            "sim_fps_below_400": sum(value < 400 for value in sim_values),
            "sim_fps_longest_below_400": longest,
            "live_sim_fps_low_reports": result.get("sim_fps_low_reports", []),
            "sim_fps_slow_intervals": [{"at": at.isoformat(), "fps": value}
                                       for at, value in sim if value < 400],
            "policy_fps_samples": len(policy_values),
            "policy_fps_median": round(statistics.median(policy_values), 1)
                                 if policy_values else None,
            "policy_fps_longest_below_45": longest_below(policy_values, 45),
            "depth_stale_events": len(stale)}


class LiveRateGuard:
    """Read new complete simulator log lines; two slow reports stop the walk."""

    def __init__(self, path: Path, threshold: float = 400.0):
        self.path = path
        self.offset = path.stat().st_size
        self.pending = ""
        self.threshold = threshold
        self.consecutive_low = 0
        self.low_reports = []

    def poll(self) -> bool:
        with self.path.open("r", errors="replace") as stream:
            stream.seek(self.offset)
            chunk = stream.read()
            self.offset = stream.tell()
        if not chunk:
            return self.consecutive_low >= 2
        lines = (self.pending + chunk).split("\n")
        self.pending = lines.pop()
        for raw in lines:
            match = SIM_FPS.search(ANSI.sub("", raw))
            if not match:
                continue
            fps = float(match.group(1))
            self.consecutive_low = self.consecutive_low + 1 if fps < self.threshold else 0
            if fps < self.threshold:
                self.low_reports.append(round(fps, 1))
        return self.consecutive_low >= 2


class LiveDepthGuard:
    """Detect a new stale-depth warning after the walking phase starts."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = path.stat().st_size
        self.pending = ""

    def poll(self) -> bool:
        with self.path.open("r", errors="replace") as stream:
            stream.seek(self.offset)
            chunk = stream.read()
            self.offset = stream.tell()
        lines = (self.pending + chunk).split("\n")
        self.pending = lines.pop()
        return any(any(marker in line.lower() for marker in DEPTH_STALE)
                   for line in lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trials", type=Path, nargs="+")
    parser.add_argument("--write", action="store_true", help="write audit.json in each trial")
    args = parser.parse_args()
    for folder in args.trials:
        report = audit(folder)
        if args.write:
            (folder / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
