#!/usr/bin/env python3
"""Run interleaved official-ONNX trials only when the shared GPU is idle.

Without --run, this prints a read-only preflight report. Trial outputs live in
ignored outputs/; choose a representative recorded trial for each video version
after the batch rather than choosing the best outcome.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "outputs/reproduction/official_benchmark"


def gpu_sample() -> dict[str, int]:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
         "--format=csv,noheader,nounits"], text=True, timeout=10,
    ).strip().splitlines()
    if len(output) != 1:
        raise RuntimeError(f"expected one shared GPU, got {len(output)}")
    match = re.fullmatch(r"\s*(\d+)\s*,\s*(\d+)\s*", output[0])
    if not match:
        raise RuntimeError(f"unexpected nvidia-smi output: {output[0]!r}")
    return {"util_percent": int(match.group(1)),
            "memory_used_mib": int(match.group(2))}


def preflight(samples: int, interval_s: float, max_util: int,
              max_memory_mib: int) -> dict:
    readings = []
    for index in range(samples):
        readings.append(gpu_sample())
        if index + 1 < samples:
            time.sleep(interval_s)
    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "readings": readings,
        "max_util_percent_exclusive": max_util,
        "max_memory_used_mib_exclusive": max_memory_mib,
        "ready": all(row["util_percent"] < max_util and
                     row["memory_used_mib"] < max_memory_mib for row in readings),
    }


def run_trial(directory: Path, steer: str, python: str) -> dict:
    if directory.exists():
        raise FileExistsError(f"refusing to overwrite {directory}")
    if Path("/tmp/.X11-unix/X99").exists():
        raise RuntimeError("isolated display :99 is occupied")
    directory.mkdir(parents=True)
    recorder_command = ["nice", "-n", "15", python,
                        "scripts/php_record_demo.py", "--trial", str(directory),
                        "--display", ":99", "--fps", "8", "--width", "960"]
    benchmark_command = ["nice", "-n", "15", python,
                         "scripts/php_official_benchmark.py", "--steer", steer,
                         "--guided-max-pulse", "0.16", "--target-x", "27.4",
                         "--max-seconds", "60", "--interactive-demo",
                         "--display", ":99", "--output", str(directory)]
    benchmark_exit = None
    recorder_exit = None
    launch_error = None
    with (directory / "record.log").open("w") as record_log, \
            (directory / "benchmark.log").open("w") as benchmark_log:
        recorder = subprocess.Popen(recorder_command, cwd=ROOT, stdout=record_log,
                                    stderr=subprocess.STDOUT)
        try:
            try:
                benchmark = subprocess.run(benchmark_command, cwd=ROOT,
                                           stdout=benchmark_log,
                                           stderr=subprocess.STDOUT, timeout=180)
                benchmark_exit = benchmark.returncode
            except subprocess.TimeoutExpired:
                launch_error = "benchmark exceeded 180 s wall-time limit"
            try:
                recorder_exit = recorder.wait(timeout=25)
            except subprocess.TimeoutExpired:
                recorder.terminate()
                recorder_exit = recorder.wait(timeout=5)
        finally:
            if recorder.poll() is None:
                recorder.terminate()
                try:
                    recorder.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    recorder.kill()
                    recorder.wait(timeout=5)
    record = {"trial": str(directory.relative_to(ROOT)), "steer": steer,
              "benchmark_exit": benchmark_exit,
              "recorder_exit": recorder_exit}
    if launch_error:
        record["error"] = launch_error
        return record
    capture = directory / "demo_capture.json"
    if recorder_exit != 0 or not capture.exists() or json.loads(
            capture.read_text()).get("status") != "complete":
        record["error"] = "raw video capture incomplete"
        return record
    if not (directory / "result.json").exists():
        record["error"] = "benchmark did not write result.json"
        return record
    result = json.loads((directory / "result.json").read_text())
    record["status"] = result["status"]
    if benchmark_exit != 0 or not (directory / "pelvis.csv").exists():
        record["error"] = "benchmark failed or trajectory missing"
        return record
    with (directory / "score.log").open("w") as log:
        score = subprocess.run([python, "scripts/php_score_course.py",
                                str(directory / "pelvis.csv"), "--output",
                                str(directory / "course_score.json")],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                               timeout=30)
    with (directory / "audit.log").open("w") as log:
        audit = subprocess.run([python, "scripts/php_audit_trial.py", "--write",
                                str(directory)], cwd=ROOT, stdout=log,
                               stderr=subprocess.STDOUT, timeout=30)
    if score.returncode or audit.returncode:
        record["error"] = "score or audit failed"
        return record
    record["consecutive_cleared"] = json.loads(
        (directory / "course_score.json").read_text())["consecutive_cleared"]
    record["quality"] = json.loads(
        (directory / "audit.json").read_text())["quality"]
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true",
                        help="actually run the protected batch; default only checks resources")
    parser.add_argument("--sequence", default="none,guided,none,guided")
    parser.add_argument("--start-id", type=int, default=36)
    parser.add_argument("--trial-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--max-gpu-util", type=int, default=50)
    parser.add_argument("--max-gpu-memory-mib", type=int, default=10000)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    sequence = args.sequence.split(",")
    if not sequence or any(mode not in ("none", "guided") for mode in sequence):
        parser.error("--sequence must contain only comma-separated none/guided")
    if args.start_id < 1 or args.samples < 1 or args.interval < 0:
        parser.error("start-id and samples must be positive; interval must be nonnegative")
    if not 0 < args.max_gpu_util <= 100 or args.max_gpu_memory_mib <= 0:
        parser.error("GPU thresholds must be positive")
    if args.run and Path("/tmp/.X11-unix/X99").exists():
        parser.error("isolated display :99 is occupied")
    args.trial_root = args.trial_root.resolve()
    if not args.trial_root.is_relative_to(ROOT):
        parser.error("--trial-root must be inside the PHP checkout")
    batch = {"protocol": "released ONNX; bundled 12-block terrain; low speed; "
                         "interactive state capture; target x=27.4 m; max 60 s",
             "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             "sequence": sequence, "start_id": args.start_id,
             "trials": [], "preflights": []}
    for offset, mode in enumerate(sequence if args.run else sequence[:1]):
        check = preflight(args.samples, args.interval, args.max_gpu_util,
                          args.max_gpu_memory_mib)
        batch["preflights"].append(check)
        print(json.dumps({"preflight": check, "next_mode": mode}), flush=True)
        if not args.run:
            return
        if not check["ready"]:
            batch["stopped_reason"] = "shared_gpu_busy"
            break
        directory = args.trial_root / f"trial_{args.start_id + offset:03d}_{mode}"
        try:
            record = run_trial(directory, mode, sys.executable)
        except Exception as exc:
            record = {"trial": str(directory.relative_to(ROOT)), "steer": mode,
                      "error": f"{type(exc).__name__}: {exc}"}
        batch["trials"].append(record)
        print(json.dumps(record), flush=True)
        if (record.get("error") or record.get("quality") != "nominal" or
                record.get("status") in ("sim_fps_low", "depth_stale",
                                          "telemetry_stale", "process_exited")):
            batch["stopped_reason"] = "trial_failed_quality_gate"
            break
    output = ROOT / "outputs/reproduction/controlled_batch.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output = output.with_name(f"controlled_batch_{int(time.time())}.json")
    output.write_text(json.dumps(batch, indent=2) + "\n")
    print(output, flush=True)


if __name__ == "__main__":
    main()
