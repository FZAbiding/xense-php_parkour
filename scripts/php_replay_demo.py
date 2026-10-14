#!/usr/bin/env python3
"""Replay recorded MuJoCo states in an orbitable viewer on an isolated X display.

Mouse drag rotates/pans the camera; wheel zooms. Space pauses, R restarts,
Left/Right seek five seconds, and Home resets the camera. This reads one trial's
actual qpos samples; it never reruns the policy or changes the trial's score.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import os
import shutil
import tempfile
import time
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np


def load_model(folder: Path) -> mujoco.MjModel:
    plain = folder / "replay_model.mjb"
    if plain.is_file():
        return mujoco.MjModel.from_binary_path(str(plain))
    compressed = folder / "replay_model.mjb.gz"
    if not compressed.is_file():
        raise FileNotFoundError(f"missing replay model in {folder}")
    with tempfile.NamedTemporaryFile(suffix=".mjb") as stream:
        with gzip.open(compressed, "rb") as source:
            shutil.copyfileobj(source, stream)
        stream.flush()
        return mujoco.MjModel.from_binary_path(stream.name)


def load_states(path: Path, nq: int) -> tuple[list[float], list[float], np.ndarray]:
    if not path.is_file() and path.suffix == ".csv":
        path = path.with_suffix(".csv.gz")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    if not rows:
        raise ValueError(f"no recorded states in {path}")
    walls = [float(row["wall_s"]) for row in rows]
    sims = [float(row["sim_s"]) for row in rows]
    positions = np.array([[float(row[f"qpos_{i}"]) for i in range(nq)]
                          for row in rows], dtype=np.float64)
    if any(right <= left for left, right in zip(walls, walls[1:])):
        raise ValueError("wall_s must increase strictly")
    return walls, sims, positions


def sample_state(model: mujoco.MjModel, walls: list[float], sims: list[float],
                 positions: np.ndarray, elapsed: float,
                 qpos: np.ndarray, qvel: np.ndarray) -> float:
    """Interpolate one measured interval, including free-joint rotation safely."""
    right = bisect.bisect_right(walls, elapsed)
    if right == 0:
        qpos[:] = positions[0]
        return sims[0]
    if right >= len(walls):
        qpos[:] = positions[-1]
        return sims[-1]
    left = right - 1
    interval = walls[right] - walls[left]
    qpos[:] = positions[left]
    mujoco.mj_differentiatePos(model, qvel, interval, positions[left], positions[right])
    mujoco.mj_integratePos(model, qpos, qvel, elapsed - walls[left])
    return sims[left] + (sims[right] - sims[left]) * (elapsed - walls[left]) / interval


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--display", default=":99")
    parser.add_argument("--autoplay", action="store_true")
    parser.add_argument("--start-seconds", type=float, default=5.0,
                        help="initial preview time; R restarts from the beginning")
    args = parser.parse_args()
    if args.display in (":0", ":1") or not args.display.startswith(":"):
        parser.error("replay requires an isolated display, such as :99")
    os.environ["DISPLAY"] = args.display
    model = load_model(args.trial)
    walls, sims, positions = load_states(args.trial / "qpos.csv", model.nq)
    data = mujoco.MjData(model)
    velocity = np.empty(model.nv, dtype=np.float64)
    controls = {"paused": not args.autoplay, "seek": 0.0, "restart": False,
                "camera_reset": False}

    def on_key(key: int) -> None:
        # GLFW key codes are stable across X11 and Wayland.
        if key == 32:  # Space
            controls["paused"] = not controls["paused"]
        elif key == 82:  # R
            controls["restart"] = True
        elif key == 263:  # Left
            controls["seek"] -= 5.0
        elif key == 262:  # Right
            controls["seek"] += 5.0
        elif key == 268:  # Home
            controls["camera_reset"] = True

    with mujoco.viewer.launch_passive(model, data, key_callback=on_key,
                                      show_left_ui=False, show_right_ui=False) as viewer:
        with viewer.lock():
            viewer.cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
            viewer.cam.trackbodyid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY,
                                                        "robot_pelvis")
            viewer.cam.distance = 5.0
            viewer.cam.azimuth = 110.0
            viewer.cam.elevation = -20.0
        start = time.monotonic()
        offset = min(max(0.0, args.start_seconds), walls[-1])
        last_paused = controls["paused"]
        last_position = None
        while viewer.is_running():
            now = time.monotonic()
            if controls["restart"]:
                start, offset = now, 0.0
                controls["restart"] = False
            if controls["seek"]:
                offset = min(max(0.0, offset + controls["seek"]), walls[-1])
                start = now
                controls["seek"] = 0.0
            if controls["paused"] != last_paused:
                if controls["paused"]:
                    offset = min(walls[-1], offset + now - start)
                start = now
                last_paused = controls["paused"]
            position = offset if controls["paused"] else offset + now - start
            if position >= walls[-1]:
                position = walls[-1]
                controls["paused"] = True
            if position != last_position or controls["camera_reset"]:
                data.time = sample_state(model, walls, sims, positions, position,
                                         data.qpos, velocity)
                mujoco.mj_forward(model, data)
                if controls["camera_reset"]:
                    with viewer.lock():
                        viewer.cam.distance = 5.0
                        viewer.cam.azimuth = 110.0
                        viewer.cam.elevation = -20.0
                    controls["camera_reset"] = False
                viewer.sync()
                last_position = position
            time.sleep(1 / 30)


if __name__ == "__main__":
    main()
