#!/usr/bin/env python3
"""Run a separate, resource-gated ONNX depth probe with raw video capture.

This is a diagnostic trial, not a fixed-protocol score sample: the passive
depth sidecar adds work while the simulator is running. Without --run, only
GPU preflight is performed. Use the same php environment as the benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from php_run_controlled_batch import ROOT, preflight, run_trial


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--trial-id", type=int, default=1)
    parser.add_argument("--steer", choices=("none", "guided"), default="none")
    parser.add_argument("--target-x", type=float, default=27.4,
                        help="diagnostic stop point; 8.8 isolates the first block")
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--max-gpu-util", type=int, default=50)
    parser.add_argument("--max-gpu-memory-mib", type=int, default=10000)
    parser.add_argument("--max-cpu-load-1m", type=float,
                        default=(os.cpu_count() or 1) * 0.75)
    args = parser.parse_args()
    if args.trial_id < 1 or args.samples < 1 or args.interval < 0:
        parser.error("trial-id and samples must be positive; interval must be nonnegative")
    if args.target_x <= 0:
        parser.error("target-x must be positive")
    if (not 0 < args.max_gpu_util <= 100 or args.max_gpu_memory_mib <= 0 or
            args.max_cpu_load_1m <= 0):
        parser.error("resource thresholds must be positive")
    if args.run and Path("/tmp/.X11-unix/X99").exists():
        parser.error("isolated display :99 is occupied")

    directory = (ROOT / "outputs/reproduction/official_benchmark" /
                 f"diagnostic_{args.trial_id:03d}_{args.steer}")
    if args.run and directory.exists():
        parser.error(f"refusing to overwrite {directory}")
    check = preflight(args.samples, args.interval, args.max_gpu_util,
                      args.max_gpu_memory_mib, args.max_cpu_load_1m)
    record = {
        "kind": "separate_depth_probe_not_fixed_protocol",
        "trial": str(directory.relative_to(ROOT)),
        "steer": args.steer,
        "target_x": args.target_x,
        "preflight": check,
        "probe_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    print(json.dumps(record), flush=True)
    if not args.run:
        return
    if check["ready"]:
        try:
            record["result"] = run_trial(directory, args.steer, sys.executable,
                                         depth_diagnostic=True,
                                         target_x=args.target_x,
                                         preflight_report={
                                             "runner_sha256": record["probe_script_sha256"],
                                             "preflight": check})
        except Exception as exc:
            record["result"] = {"error": f"{type(exc).__name__}: {exc}"}
    else:
        record["stopped_reason"] = "shared_host_busy"
    output = ROOT / "outputs/reproduction" / f"depth_probe_{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.write_text(json.dumps(record, indent=2) + "\n")
    print(output, flush=True)


if __name__ == "__main__":
    main()
