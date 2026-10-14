#!/usr/bin/env python3
"""Open one saved trial as a local browser-controlled MuJoCo replay.

Runs only on a dedicated Xvfb display and loopback VNC/HTTP ports. Press Ctrl-C
to close every process. The browser can drag/scroll the actual MuJoCo viewer.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("/home/xense/miniforge3/envs/php/bin/python")
XVFB = Path("/tmp/php-xvfb/usr/bin/Xvfb")
X11VNC = Path("/tmp/php-interactive/usr/bin/x11vnc")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--display", default=":99")
    parser.add_argument("--autoplay", action="store_true")
    args = parser.parse_args()
    if args.display in (":0", ":1") or not args.display.startswith(":"):
        parser.error("use a dedicated display such as :99")
    if Path(f"/tmp/.X11-unix/X{args.display[1:]}").exists():
        parser.error(f"display {args.display} is already in use")
    has_states = any((args.trial / name).is_file()
                     for name in ("qpos.csv", "qpos.csv.gz"))
    has_model = any((args.trial / name).is_file()
                    for name in ("replay_model.mjb", "replay_model.mjb.gz"))
    if not has_states or not has_model:
        parser.error("trial must have qpos and replay_model files, plain or gzip")
    if not all(path.is_file() for path in (PYTHON, XVFB, X11VNC)):
        parser.error("local replay dependencies are missing; see DEMO_VIDEO_WORKFLOW.md")
    env = os.environ.copy()
    env["DISPLAY"] = args.display
    env["LD_LIBRARY_PATH"] = ("/tmp/php-interactive/usr/lib/x86_64-linux-gnu:"
                              + env.get("LD_LIBRARY_PATH", ""))
    processes = []

    def start(command):
        process = subprocess.Popen(command, cwd=ROOT, env=env,
                                   start_new_session=True)
        processes.append(process)
        return process

    try:
        start([str(XVFB), args.display, "-screen", "0", "1600x1000x24",
               "-nolisten", "tcp", "-noreset"])
        for _ in range(50):
            if Path(f"/tmp/.X11-unix/X{args.display[1:]}").exists():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Xvfb did not start")
        replay = [str(PYTHON), str(ROOT / "scripts/php_replay_demo.py"),
                  "--trial", str(args.trial.resolve()), "--display", args.display]
        if args.autoplay:
            replay.append("--autoplay")
        start(replay)
        start([str(X11VNC), "-display", args.display, "-localhost", "-rfbport",
               "5900", "-nopw", "-forever", "-shared", "-xkb", "-noxdamage",
               "-quiet"])
        gateway = start([str(PYTHON), str(ROOT / "scripts/php_browser_gateway.py")])
        print("Open the local URL printed by the gateway above. Drag to orbit,"
              " scroll to zoom, Space to play/pause, R to restart.", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError("a replay service exited; see output above")
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in reversed(processes):
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    main()
