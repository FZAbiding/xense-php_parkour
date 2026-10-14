#!/usr/bin/env python3
"""Record the real MuJoCo window on an isolated X display during one trial.

Start this process before php_official_benchmark.py. Recording begins when that
trial creates pelvis.csv and ends when it writes result.json. Nothing is read
from, or sent to, the user's desktop display.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import ImageGrab
from Xlib import display


def viewer_box(display_name: str) -> tuple[int, int, int, int] | None:
    conn = display.Display(display_name)
    try:
        root = conn.screen().root
        for window in root.query_tree().children:
            if "MuJoCo" in (window.get_wm_name() or ""):
                geometry = window.get_geometry()
                position = root.translate_coords(window, 0, 0)
                return (position.x, position.y,
                        position.x + geometry.width, position.y + geometry.height)
        return None
    finally:
        conn.close()


def record(trial: Path, display_name: str, fps: int, width: int,
           setup_timeout: float, max_duration: float) -> dict:
    capture_path = trial / "demo_capture.mp4"
    result_path = trial / "result.json"
    trace_path = trial / "pelvis.csv"
    if result_path.exists() or capture_path.exists():
        raise FileExistsError("demo recording requires a fresh trial directory")
    deadline = time.monotonic() + setup_timeout
    box = None
    while time.monotonic() < deadline:
        if result_path.exists():
            raise RuntimeError("benchmark ended before its walking trace began")
        if trace_path.exists():
            try:
                box = viewer_box(display_name)
            except Exception:
                box = None
            if box is not None:
                break
        time.sleep(0.1)
    if box is None:
        raise TimeoutError("no walking trace and MuJoCo viewer before setup timeout")

    source_w, source_h = box[2] - box[0], box[3] - box[1]
    height = int(round(source_h * width / source_w / 2) * 2)
    writer = cv2.VideoWriter(str(capture_path), cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not open MP4 video writer")
    started = time.monotonic()
    frames = 0
    grabs = 0
    duplicates = 0
    last_frame = None
    error = None
    try:
        while not result_path.exists() and time.monotonic() - started < max_duration:
            target = started + frames / fps
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(min(delay, 0.1))
                continue
            now = time.monotonic()
            expected = math.floor((now - started) * fps)
            while last_frame is not None and frames < expected:
                writer.write(last_frame)
                frames += 1
                duplicates += 1
            image = ImageGrab.grab(bbox=box, xdisplay=display_name)
            frame = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            writer.write(frame)
            last_frame = frame
            frames += 1
            grabs += 1
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        writer.release()
    wall_s = time.monotonic() - started
    report = {"display": display_name, "capture_box": box,
              "source_size": [source_w, source_h], "video_size": [width, height],
              "fps": fps, "frames": frames, "frames_captured": grabs,
              "frames_duplicated": duplicates, "wall_s": round(wall_s, 2),
              "encoded_s": round(frames / fps, 2), "capture_file": capture_path.name,
              "error": error,
              "status": "complete" if result_path.exists() and not error and frames else "incomplete"}
    (trial / "demo_capture.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--display", default=":99")
    parser.add_argument("--fps", type=int, default=8)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--setup-timeout", type=float, default=120)
    parser.add_argument("--max-duration", type=float, default=80)
    args = parser.parse_args()
    if args.display in (":0", ":1") or not args.display.startswith(":"):
        parser.error("record only a dedicated X display")
    if args.fps <= 0 or args.width <= 0 or args.width % 2:
        parser.error("fps and even width must be positive")
    args.trial.mkdir(parents=True, exist_ok=True)
    report = record(args.trial, args.display, args.fps, args.width,
                    args.setup_timeout, args.max_duration)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
