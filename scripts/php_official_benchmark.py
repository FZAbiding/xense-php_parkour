#!/usr/bin/env python3
"""Run the released PHP student on the bundled MuJoCo course, off-screen.

This script only controls X display :99 or another explicit, non-desktop display.
It records the simulator's UDP pelvis state rather than inferring motion from a
viewer screenshot. Run from the repository root with the ``php`` environment.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import pty
import re
import signal
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

from php_score_course import DEFAULT_TERRAIN, blocks
from php_audit_trial import LiveDepthGuard, LiveRateGuard, audit


ROOT = Path(__file__).resolve().parents[1]
HOLOSOMA = ROOT / "thirdparty/holosoma"
PYTHON = Path("/home/xense/miniforge3/envs/php/bin/python")
Xvfb = Path("/tmp/php-xvfb/usr/bin/Xvfb")
MODEL_DIR = ROOT / "outputs/reproduction/student"
SIM_PORT = 9870


class MocapReceiver:
    """Keep the newest pelvis packet; never judge a pose from a UDP backlog."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.latest: tuple[float, tuple[float, ...]] | None = None
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while not self.done.is_set():
            try:
                packet, _ = self.sock.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                return
            if len(packet) == 40:
                with self.lock:
                    self.latest = (time.monotonic(), struct.unpack("10f", packet))

    def get(self) -> tuple[float, ...] | None:
        with self.lock:
            latest = self.latest
        if latest is None or time.monotonic() - latest[0] > 0.3:
            return None
        return latest[1]

    def close(self) -> None:
        self.done.set()
        self.sock.close()
        self.thread.join(timeout=1)


def wait_log(path: Path, text: str, process: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{process.args[0]} exited ({process.returncode}); see {path}")
        if path.exists() and text in path.read_text(errors="replace"):
            return
        time.sleep(0.2)
    raise TimeoutError(f"waiting for {text!r}; see {path}")


def start_process(command: list[str], *, env: dict[str, str], log: Path, tty: bool = False):
    output = log.open("w", buffering=1)
    if tty:
        master, slave = pty.openpty()
        process = subprocess.Popen(command, cwd=HOLOSOMA, env=env, stdin=slave,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        os.close(slave)
        return process, master, output
    process = subprocess.Popen(command, cwd=HOLOSOMA, env=env, stdout=output,
                               stderr=subprocess.STDOUT, start_new_session=True)
    return process, None, output


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=6)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def tap(conn, viewer, key: str) -> None:
    from Xlib import X, XK
    from Xlib.ext import xtest

    code = conn.keysym_to_keycode(XK.string_to_keysym(key))
    if not code:
        raise ValueError(f"unknown X11 key {key}")
    viewer.set_input_focus(X.RevertToParent, X.CurrentTime)
    conn.sync()
    xtest.fake_input(conn, X.KeyPress, code)
    conn.sync()
    time.sleep(0.12)
    xtest.fake_input(conn, X.KeyRelease, code)
    conn.sync()


def get_viewer(display_name: str):
    from Xlib import display

    conn = display.Display(display_name)
    root = conn.screen().root
    for _ in range(100):
        viewers = [w for w in root.query_tree().children
                   if "MuJoCo" in (w.get_wm_name() or "")]
        if len(viewers) == 1:
            return conn, viewers[0]
        time.sleep(0.2)
    raise RuntimeError(f"expected one MuJoCo window on {display_name}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_view(conn, viewer, display_name: str, path: Path) -> None:
    from PIL import ImageGrab

    root = conn.screen().root
    geometry = viewer.get_geometry()
    position = root.translate_coords(viewer, 0, 0)
    ImageGrab.grab(bbox=(position.x, position.y, position.x + geometry.width,
                         position.y + geometry.height), xdisplay=display_name).save(path)


def post_first_guard_direction(x: float, y: float, z: float,
                               yaw_deg: float, vy: float,
                               min_yaw_deg: float = 15.0) -> str | None:
    """Select a conservative direction during the first flat transfer."""
    if not (6.3 < x < 8.4 and z < 0.95):
        return None
    if y < -0.30 and yaw_deg < -min_yaw_deg and vy < -0.2:
        return "a"
    if y > 0.30 and yaw_deg > min_yaw_deg and vy > 0.2:
        return "d"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default=":99")
    parser.add_argument("--terrain-obj", type=Path,
                        help="optional diagnostic OBJ mesh; omit for the official bundled course")
    parser.add_argument("--target-x", type=float, default=12.0)
    parser.add_argument("--max-seconds", type=float, default=30.0)
    parser.add_argument("--speed-mode", choices=("low", "high"), default="low",
                        help="official policy speed class selected with '=' (default: low)")
    parser.add_argument("--pause-after-block", type=float, default=0.0,
                        help="diagnostic stand duration after clearing each block (0 disables)")
    parser.add_argument("--steer", choices=("none", "centerline", "late_yaw", "inter_obstacle", "post_climb", "predictive", "guided"), default="none",
                        help="operator-style left/right corrections from measured lateral offset")
    parser.add_argument("--guided-max-pulse", type=float, default=0.30,
                        help="maximum a/d pulse in guided mode; try 0.16 for conservative correction")
    parser.add_argument("--guided-reversal-guard", action="store_true",
                        help="after block 4, skip a guided pulse when lateral motion is already returning and yaw is small")
    parser.add_argument("--approach-guard", action="store_true",
                        help="in guided mode, counter strong yaw/lateral drift before block 2")
    parser.add_argument("--post-first-guard", action="store_true",
                        help="diagnostic: counter outward yaw after block 1, before block 2")
    parser.add_argument("--post-first-min-yaw", type=float, default=15.0,
                        help="diagnostic outward yaw threshold in degrees (default: 15)")
    parser.add_argument("--demo-view", action="store_true",
                        help="hide MuJoCo menus for recording on the dedicated X display")
    parser.add_argument("--interactive-demo", action="store_true",
                        help="clean, orbitable MuJoCo view plus full qpos/model capture for replay")
    parser.add_argument("--demo-start-delay", type=float, default=0.0,
                        help="seconds to connect to interactive viewer before walking starts")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "outputs/reproduction/official_benchmark")
    args = parser.parse_args()
    if args.display in (":0", ":1") or not re.fullmatch(r":\d+", args.display):
        parser.error("use a dedicated X display such as :99, never the office desktop")
    if args.target_x <= 0 or args.max_seconds <= 0 or args.pause_after_block < 0:
        parser.error("target-x and max-seconds must be positive; pause must be nonnegative")
    if args.demo_start_delay < 0:
        parser.error("demo-start-delay must be nonnegative")
    if not 0 < args.guided_max_pulse <= 0.30:
        parser.error("guided-max-pulse must be in (0, 0.30]")
    if not 0 < args.post_first_min_yaw < 90:
        parser.error("post-first-min-yaw must be in (0, 90)")
    if args.post_first_guard and args.steer != "guided":
        parser.error("post-first-guard requires --steer guided")
    if not Xvfb.exists() or not PYTHON.exists():
        parser.error("php Python or unpacked Xvfb is missing; see PHP_REPRODUCTION_GUIDE.md")
    if Path(f"/tmp/.X11-unix/X{args.display[1:]}").exists():
        parser.error(f"X display {args.display} is already in use")
    models = [MODEL_DIR / "depth_backbone.onnx", MODEL_DIR / "student.onnx"]
    if not all(path.exists() for path in models):
        parser.error("official ONNX pair missing; run scripts/download_assets.py student")
    if args.terrain_obj is not None:
        args.terrain_obj = args.terrain_obj.resolve()
        if not args.terrain_obj.is_file():
            parser.error(f"terrain OBJ does not exist: {args.terrain_obj}")

    args.output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["DISPLAY"] = args.display
    env["MUJOCO_GL"] = "egl"
    env["SIM_MOCAP_UDP_PORT"] = str(SIM_PORT)
    if args.interactive_demo:
        env["PHP_DEMO_TRIAL_DIR"] = str(args.output.resolve())
    sim = inference = xvfb = None
    master = None
    outputs = []
    conn = None
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    result = {"started": started, "status": "setup_failed", "target_x": args.target_x,
              "max_seconds": args.max_seconds, "display": args.display, "steer": args.steer,
              "speed_mode": args.speed_mode, "pause_after_block": args.pause_after_block,
              "guided_max_pulse": args.guided_max_pulse,
              "guided_reversal_guard": args.guided_reversal_guard,
              "approach_guard": args.approach_guard,
              "post_first_guard": args.post_first_guard,
              "post_first_min_yaw_deg": args.post_first_min_yaw,
              "demo_view": args.demo_view,
              "interactive_demo": args.interactive_demo,
              "demo_start_delay": args.demo_start_delay,
              "model_sha256": {p.name: sha256(p) for p in models},
              "benchmark_script_sha256": sha256(Path(__file__)),
              "terrain_obj": str(args.terrain_obj) if args.terrain_obj else "bundled terrain.obj"}
    if args.terrain_obj is not None:
        result["terrain_sha256"] = sha256(args.terrain_obj)
    course_blocks = list(blocks(args.terrain_obj or DEFAULT_TERRAIN))
    guided_windows = []
    for position, (number, corners, height) in enumerate(course_blocks):
        if number < 3:
            continue
        xs = [corner[0] for corner in corners]
        next_x = (min(corner[0] for corner in course_blocks[position + 1][1])
                  if position + 1 < len(course_blocks) else max(xs) + 4.0)
        guided_windows.append((number, (min(xs) + max(xs)) / 2 + 0.2,
                               next_x - 0.2, 1.15 if height > 0.5 else 0.95))
    if args.steer == "guided":
        result["guided_windows"] = guided_windows
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", SIM_PORT))
    sock.settimeout(0.2)
    mocap = MocapReceiver(sock)
    try:
        xvfb, _, handle = start_process(
            [str(Xvfb), args.display, "-screen", "0", "1600x1000x24",
             "-nolisten", "tcp", "-noreset"], env=env, log=args.output / "xvfb.log")
        outputs.append(handle)
        for _ in range(40):
            if Path(f"/tmp/.X11-unix/X{args.display[1:]}").exists():
                break
            if xvfb.poll() is not None:
                raise RuntimeError("Xvfb exited; display may already be in use")
            time.sleep(0.2)
        sim_entry = (str(ROOT / "scripts/php_sim_demo.py") if args.interactive_demo
                     else "src/holosoma/holosoma/run_sim.py")
        sim_cmd = [str(PYTHON), sim_entry,
                   "robot:g1-29dof", "sensor.d435i_front_depth:g1-d435i-front-depth",
                   "plugin.depth:depth-shm-d435i", "terrain:terrain-load-step",
                   "--robot.asset.xml-file", "g1/g1_29dof_halfspherehand.xml",
                   "--simulator.config.bridge.enabled=True",
                   "--simulator.config.sim.fps=500",
                   "--simulator.config.virtual-gantry.length=0.3"]
        if args.interactive_demo:
            sim_cmd += ["--simulator.config.debug-viz=False"]
        if args.terrain_obj is not None:
            sim_cmd += ["--terrain.terrain-term.obj-file-path", str(args.terrain_obj)]
        sim, _, handle = start_process(sim_cmd, env=env, log=args.output / "sim.log")
        outputs.append(handle)
        wait_log(args.output / "sim.log", "[DepthShmPlugin] created", sim, 60)
        inf_cmd = [str(PYTHON), "src/holosoma_inference/holosoma_inference/run_policy.py",
                   "inference:g1-wbt-distillation-d435i", "--task.interface", "lo",
                   "--task.model-path", repr([str(path) for path in models])]
        inference, master, handle = start_process(inf_cmd, env=env,
                                                  log=args.output / "inference.log", tty=True)
        outputs.append(handle)
        wait_log(args.output / "inference.log", "[DepthShmSensor] attached", inference, 60)
        conn, viewer = get_viewer(args.display)
        tap(conn, viewer, "y")  # Follow the robot as it leaves the initial camera frame.
        if args.demo_view or args.interactive_demo:
            tap(conn, viewer, "g")
        time.sleep(1.0)
        for _ in range(9):
            tap(conn, viewer, "8")
            time.sleep(0.25)
        time.sleep(1.0)
        # Wait for a stable, upright heading before releasing the gantry.
        # Trial 021 started 5.7 degrees off-axis despite a normal pelvis height.
        pose_samples = []
        stable_since = None
        pre = latest_pose = None
        pose_deadline = time.monotonic() + 4.0
        while time.monotonic() < pose_deadline:
            candidate = mocap.get()
            if candidate is not None:
                latest_pose = candidate
                qw, qx, qy, qz = candidate[3:7]
                candidate_yaw = math.degrees(math.atan2(
                    2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz)))
                pose_samples.append([round(candidate[2], 3), round(candidate_yaw, 2)])
                if 0.65 <= candidate[2] <= 0.95 and abs(candidate_yaw) <= 2.0:
                    stable_since = stable_since or time.monotonic()
                    if time.monotonic() - stable_since >= 0.5:
                        pre = candidate
                        break
                else:
                    stable_since = None
            time.sleep(0.1)
        result["startup_pose_samples"] = pose_samples
        if latest_pose is None:
            raise RuntimeError("no fresh pelvis packet before gantry release")
        # A bad gantry release can invalidate a run before policy inference starts.
        pose_ready = pre is not None
        if pre is None:
            pre = latest_pose
        z_before_release = pre[2]
        result["z_before_release"] = z_before_release
        qw, qx, qy, qz = pre[3:7]
        result["yaw_before_release_deg"] = round(math.degrees(math.atan2(
            2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))), 2)
        if not pose_ready:
            result["status"] = "bad_start_pose"
            return
        tap(conn, viewer, "9")
        time.sleep(0.5)
        os.write(master, b"]")
        wait_log(args.output / "inference.log", "Depth distillation policy started",
                 inference, 15)
        if args.speed_mode == "high":
            os.write(master, b"=")
            wait_log(args.output / "inference.log", "Speed mode -> HIGH", inference, 10)
        if args.demo_start_delay:
            time.sleep(args.demo_start_delay)
        if args.interactive_demo:
            capture_view(conn, viewer, args.display, args.output / "pre_walk.png")
        from Xlib import X, XK
        from Xlib.ext import xtest

        code = conn.keysym_to_keycode(XK.string_to_keysym("w"))
        viewer.set_input_focus(X.RevertToParent, X.CurrentTime)
        conn.sync()
        xtest.fake_input(conn, X.KeyPress, code)
        conn.sync()
        forward_held = True
        pause_until = 0.0
        paused_blocks = set()
        pause_events = []
        held_steer = None
        steer_events = []
        guard_suppressed_events = []
        last_guard_suppressed_at = 0.0
        steer_release_at = 0.0
        steer_cooldown_until = 0.0
        screenshots = set()
        result["status"] = "timeout"
        begin = time.monotonic()
        if args.interactive_demo:
            (args.output / "walk_start.txt").write_text(f"{begin:.9f}\n")
        result["walk_started"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        rate_guard = LiveRateGuard(args.output / "sim.log")
        depth_guard = LiveDepthGuard(args.output / "inference.log")
        next_rate_check = begin + 0.5
        last_progress = begin
        max_x = -1e9
        progress_x = -1e9
        low_since = None
        values = pre
        with (args.output / "pelvis.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["wall_s", "x", "y", "z", "qw", "qx", "qy", "qz",
                             "vx", "vy", "vz"])
            while time.monotonic() - begin < args.max_seconds:
                if sim.poll() is not None or inference.poll() is not None:
                    result["status"] = "process_exited"
                    break
                if time.monotonic() >= next_rate_check:
                    next_rate_check = time.monotonic() + 0.5
                    if rate_guard.poll():
                        result["status"] = "sim_fps_low"
                        result["sim_fps_low_reports"] = rate_guard.low_reports
                        break
                    if depth_guard.poll():
                        result["status"] = "depth_stale"
                        break
                newest = mocap.get()
                if newest is None:
                    if time.monotonic() - last_progress > 3.0:
                        result["status"] = "telemetry_stale"
                        break
                    time.sleep(0.03)
                    continue
                values = newest
                elapsed = time.monotonic() - begin
                writer.writerow([round(elapsed, 3), *values])
                x, y, z = values[:3]
                max_x = max(max_x, x)
                now = time.monotonic()
                if pause_until and now >= pause_until:
                    xtest.fake_input(conn, X.KeyPress, code)
                    conn.sync()
                    forward_held = True
                    pause_until = 0.0
                    pause_events.append({"t": round(elapsed, 2), "x": round(x, 2),
                                         "y": round(y, 2), "event": "resume"})
                if args.pause_after_block and not pause_until and forward_held:
                    for number, corners, _ in course_blocks[:-1]:
                        if number in paused_blocks:
                            continue
                        if (x >= max(corner[0] for corner in corners) + 1.5
                                and abs(y) <= 1.0 and 0.55 <= z <= 0.95):
                            if held_steer is not None:
                                xtest.fake_input(conn, X.KeyRelease,
                                                 conn.keysym_to_keycode(XK.string_to_keysym(held_steer)))
                                held_steer = None
                            xtest.fake_input(conn, X.KeyRelease, code)
                            conn.sync()
                            forward_held = False
                            pause_until = now + args.pause_after_block
                            paused_blocks.add(number)
                            pause_events.append({"t": round(elapsed, 2), "x": round(x, 2),
                                                 "y": round(y, 2), "event": f"pause_after_{number}"})
                            break
                if args.steer == "centerline" and not pause_until:
                    wanted = held_steer
                    if held_steer is None:
                        if y > 0.40:
                            wanted = "d"
                        elif y < -0.40:
                            wanted = "a"
                    elif held_steer == "d" and y < 0.10:
                        wanted = None
                    elif held_steer == "a" and y > -0.10:
                        wanted = None
                    if wanted != held_steer:
                        if held_steer is not None:
                            xtest.fake_input(conn, X.KeyRelease,
                                             conn.keysym_to_keycode(XK.string_to_keysym(held_steer)))
                        if wanted is not None:
                            xtest.fake_input(conn, X.KeyPress,
                                             conn.keysym_to_keycode(XK.string_to_keysym(wanted)))
                        conn.sync()
                        steer_events.append({"t": round(elapsed, 2), "x": round(x, 2),
                                             "y": round(y, 2), "key": wanted})
                        held_steer = wanted
                elif not pause_until and args.steer in ("late_yaw", "inter_obstacle", "post_climb", "predictive", "guided"):
                    now = time.monotonic()
                    if held_steer is not None and now >= steer_release_at:
                        xtest.fake_input(conn, X.KeyRelease,
                                         conn.keysym_to_keycode(XK.string_to_keysym(held_steer)))
                        conn.sync()
                        steer_events.append({"t": round(elapsed, 2), "x": round(x, 2),
                                             "y": round(y, 2), "key": None})
                        held_steer = None
                        steer_cooldown_until = now + (1.5 if args.steer == "inter_obstacle" else 1.0)
                    on_flat = (11.5 < x < 13.5 or 16.0 < x < 18.5 or
                               21.5 < x < 23.5 or 26.0 < x < 28.5 or
                               31.5 < x < 33.5 or 36.0 < x < 38.5 or
                               41.5 < x < 43.5 or 46.0 < x < 48.5 or
                               51.5 < x < 53.5 or 56.0 < x < 58.5)
                    eligible = (x > 15.5 if args.steer == "late_yaw" else
                                15.2 < x < 19.3 if args.steer in ("post_climb", "predictive")
                                else on_flat)
                    max_ground_z = 1.15 if args.steer in ("post_climb", "predictive", "guided") else 0.95
                    phase = "later"
                    if args.steer == "guided":
                        post_first_guard = (args.post_first_guard and 6.3 < x < 8.4
                                            and z < 0.95)
                        approach_guard = (args.approach_guard and 8.7 < x < 10.8
                                          and z < 0.95)
                        early_guard = 10.8 < x < 13.8 and z < 0.95
                        active_window = next((window for window in guided_windows
                                              if window[1] < x < window[2]
                                              and z < window[3]), None)
                        eligible = post_first_guard or approach_guard or early_guard or active_window is not None
                        phase = "post_first_guard" if post_first_guard else "before_block_2" if approach_guard else "early_guard" if early_guard else (
                            f"after_block_{active_window[0]}" if active_window else "none")
                    if held_steer is None and now >= steer_cooldown_until and eligible and z < max_ground_z:
                        qw, qx, qy, qz = values[3:7]
                        yaw = math.degrees(math.atan2(2 * (qw * qz + qx * qy),
                                                       1 - 2 * (qy * qy + qz * qz)))
                        if args.steer == "guided" and phase == "post_first_guard":
                            wanted = post_first_guard_direction(
                                x, y, z, yaw, values[8], args.post_first_min_yaw)
                            predicted_y = y + values[8]
                        elif args.steer == "guided" and phase == "before_block_2":
                            wanted = ("a" if yaw < -20 and values[8] < -0.4 else
                                      "d" if yaw > 20 and values[8] > 0.4 else None)
                            predicted_y = y + values[8]
                        elif args.steer == "guided" and phase == "early_guard":
                            wanted = ("a" if y < -0.4 and yaw < -20 and values[8] < -0.2 else
                                      "d" if y > 0.4 and yaw > 20 and values[8] > 0.2 else None)
                            predicted_y = y + values[8]
                        elif args.steer in ("predictive", "guided"):
                            predicted_y = y + values[8] + 0.2 * math.sin(math.radians(yaw))
                            wanted = "d" if predicted_y > 0.55 else "a" if predicted_y < -0.55 else None
                        elif args.steer == "post_climb":
                            predicted_y = y + math.sin(math.radians(yaw))
                            wanted = "d" if predicted_y > 0.65 else "a" if predicted_y < -0.65 else None
                        elif args.steer == "inter_obstacle":
                            wanted = "d" if (yaw > 20 or y > 0.5) else "a" if (yaw < -20 or y < -0.5) else None
                        else:
                            wanted = "d" if (yaw > 20 or y > 0.65) else "a" if (yaw < -20 or y < -0.65) else None
                        if (args.steer == "guided" and args.guided_reversal_guard
                                and phase == "after_block_4" and abs(yaw) < 12
                                and abs(y) < 1.4
                                and ((wanted == "a" and y < 0 and values[8] > 0)
                                     or (wanted == "d" and y > 0 and values[8] < 0))):
                            if now - last_guard_suppressed_at >= 0.5:
                                guard_suppressed_events.append({
                                    "t": round(elapsed, 2), "x": round(x, 2),
                                    "y": round(y, 2), "yaw_deg": round(yaw, 1),
                                    "vy": round(values[8], 2), "skipped_key": wanted})
                                last_guard_suppressed_at = now
                            wanted = None
                        if wanted is not None:
                            pulse_s = (min(args.guided_max_pulse,
                                           0.30 if phase != "early_guard"
                                           and abs(predicted_y) > 1.35 else 0.16)
                                       if args.steer == "guided" else
                                       0.20 if args.steer == "inter_obstacle" else
                                       0.16 if args.steer == "predictive" else
                                       0.22 if args.steer == "post_climb" else 0.35)
                            xtest.fake_input(conn, X.KeyPress,
                                             conn.keysym_to_keycode(XK.string_to_keysym(wanted)))
                            conn.sync()
                            held_steer = wanted
                            steer_release_at = now + pulse_s
                            steer_events.append({"t": round(elapsed, 2), "x": round(x, 2),
                                                 "y": round(y, 2), "yaw_deg": round(yaw, 1),
                                                 "vy": round(values[8], 2),
                                                 "predicted_y": round(predicted_y, 2) if args.steer in ("predictive", "guided") else None,
                                                 "phase": phase,
                                                 "pulse_s": pulse_s,
                                                 "key": wanted})
                if x > progress_x + 0.1:
                    progress_x, last_progress = x, time.monotonic()
                for milestone in (5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60):
                    if milestone not in screenshots and x >= milestone:
                        capture_view(conn, viewer, args.display,
                                     args.output / f"at_{milestone:02d}m.png")
                        screenshots.add(milestone)
                if z < 0.4:
                    low_since = low_since or time.monotonic()
                else:
                    low_since = None
                if x >= args.target_x:
                    result["status"] = "x_target_reached"
                    break
                if low_since and time.monotonic() - low_since > 1.0:
                    result["status"] = "fell"
                    break
                if abs(y) > 3.0:
                    result["status"] = "left_course"
                    break
                if time.monotonic() - last_progress > 8.0:
                    result["status"] = "stalled"
                    break
                time.sleep(0.03)
        if forward_held:
            xtest.fake_input(conn, X.KeyRelease, code)
        if held_steer is not None:
            xtest.fake_input(conn, X.KeyRelease,
                             conn.keysym_to_keycode(XK.string_to_keysym(held_steer)))
        conn.sync()
        result.update({"elapsed_s": round(time.monotonic() - begin, 2),
                       "final_xyz": [round(v, 3) for v in values[:3]],
                       "max_x": round(max_x, 3), "steer_events": steer_events,
                       "guard_suppressed_events": guard_suppressed_events,
                       "pause_events": pause_events})
        time.sleep(0.3)
        capture_view(conn, viewer, args.display, args.output / "final.png")
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        result["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        if conn is not None:
            conn.close()
        stop_process(inference)
        stop_process(sim)
        stop_process(xvfb)
        if master is not None:
            os.close(master)
        for handle in outputs:
            handle.close()
        mocap.close()
        report = audit(args.output)
        (args.output / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
