#!/usr/bin/env python3
"""Render one recorded trial's actual qpos as a smooth, full-frame MuJoCo video.

This is a visualization of the saved simulation state, not a new policy run.
The same replay_model.mjb and qpos.csv power php_replay_demo.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import mujoco
import numpy as np

from php_replay_demo import load_model, load_states, sample_state


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--ffmpeg", type=Path, default=Path("/tmp/php-ffmpeg/usr/bin/ffmpeg"))
    parser.add_argument("--max-seconds", type=float, default=0.0,
                        help="render only the first N seconds for a visual check")
    parser.add_argument("--disable-shadows", action="store_true",
                        help="hide shadow-map artifacts on software OpenGL; visuals only")
    args = parser.parse_args()
    if args.fps <= 0 or args.width <= 0 or args.height <= 0:
        parser.error("fps and dimensions must be positive")
    model_path = args.trial / "replay_model.mjb"
    qpos_path = args.trial / "qpos.csv"
    model = load_model(args.trial)
    if args.disable_shadows:
        model.light_castshadow[:] = False
    model.vis.global_.offwidth = max(model.vis.global_.offwidth, args.width)
    model.vis.global_.offheight = max(model.vis.global_.offheight, args.height)
    walls, sims, positions = load_states(qpos_path, model.nq)
    duration = min(walls[-1], args.max_seconds) if args.max_seconds > 0 else walls[-1]
    frames = int(duration * args.fps) + 1
    data = mujoco.MjData(model)
    velocity = np.empty(model.nv, dtype=np.float64)
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_TRACKING
    camera.trackbodyid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "robot_pelvis")
    camera.distance = 5.0
    camera.azimuth = 110.0
    camera.elevation = -20.0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["MUJOCO_GL"] = "egl"
    command = [str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s:v",
               f"{args.width}x{args.height}", "-r", str(args.fps), "-i", "-",
               "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(args.output)]
    with mujoco.Renderer(model, width=args.width, height=args.height) as renderer:
        with subprocess.Popen(command, stdin=subprocess.PIPE, env=env) as encoder:
            assert encoder.stdin is not None
            try:
                for frame in range(frames):
                    elapsed = frame / args.fps
                    data.time = sample_state(model, walls, sims, positions,
                                             elapsed, data.qpos, velocity)
                    mujoco.mj_forward(model, data)
                    renderer.update_scene(data, camera=camera)
                    encoder.stdin.write(renderer.render().tobytes())
            finally:
                encoder.stdin.close()
            if encoder.wait() != 0:
                raise RuntimeError(f"FFmpeg failed with exit {encoder.returncode}")
    report = {"trial": str(args.trial), "video": str(args.output),
              "source": "recorded_qpos_same_trial_quaternion_safe_interpolation",
              "fps": args.fps,
              "size": [args.width, args.height], "frames": frames,
              "duration_s": round(frames / args.fps, 3),
              "sample_count": len(walls), "sample_duration_s": round(walls[-1], 3),
              "shadows_disabled": args.disable_shadows,
              "sha256": {"video": sha256(args.output), "qpos": sha256(qpos_path),
                         "model": sha256(model_path)}}
    report_path = args.output.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
