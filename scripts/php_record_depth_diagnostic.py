#!/usr/bin/env python3
"""Passively record D435i shared-memory frames for a separate diagnostic trial.

Start before the simulator; stop when its result.json appears. This sidecar is
for diagnosis only and must not be mixed into the fixed-protocol score sample.
"""

from __future__ import annotations

import argparse
import json
import time
from multiprocessing import shared_memory
from pathlib import Path

import numpy as np
import zmq

from holosoma_inference.sensors.depth_heartbeat import decode_heartbeat


SHAPE = (1, 1, 58, 87)


def capture(trial: Path, shm_name: str, endpoint: str,
            setup_timeout: float, max_duration: float) -> dict:
    trial.mkdir(parents=True, exist_ok=True)
    npz_path = trial / "depth_diagnostic.npz"
    json_path = trial / "depth_diagnostic.json"
    if npz_path.exists() or json_path.exists() or (trial / "result.json").exists():
        raise FileExistsError("diagnostic needs a fresh trial and cannot overwrite data")
    socket = zmq.Context.instance().socket(zmq.SUB)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.SUBSCRIBE, b"")
    socket.connect(endpoint)
    poller = zmq.Poller()
    poller.register(socket, zmq.POLLIN)
    shm = None
    frames: list[np.ndarray] = []
    seqs: list[int] = []
    producer_times: list[float] = []
    receiver_times: list[float] = []
    receiver_monotonic_times: list[float] = []
    started = time.monotonic()
    last_seq = None
    error = None
    try:
        while time.monotonic() - started < max_duration:
            if (trial / "result.json").exists():
                break
            if not frames and time.monotonic() - started > setup_timeout:
                error = "no depth frame before setup timeout"
                break
            if socket not in dict(poller.poll(100)):
                continue
            try:
                beat = decode_heartbeat(socket.recv(zmq.NOBLOCK))
            except (ValueError, zmq.Again):
                continue
            if beat["state"] != "OK" or beat["seq"] == last_seq:
                continue
            if shm is None:
                try:
                    shm = shared_memory.SharedMemory(name=shm_name)
                except FileNotFoundError:
                    continue
                if shm.size != int(np.prod(SHAPE)) * np.dtype(np.float32).itemsize:
                    raise ValueError(f"depth shared-memory size mismatch: {shm.size}")
            frame = np.ndarray(SHAPE, dtype=np.float32, buffer=shm.buf).copy()
            frames.append(frame)
            seqs.append(beat["seq"])
            producer_times.append(beat["t_capture"])
            receiver_times.append(time.time())
            receiver_monotonic_times.append(time.monotonic())
            last_seq = beat["seq"]
    finally:
        if shm is not None:
            shm.close()
        socket.close()
    if frames:
        np.savez_compressed(npz_path, frames=np.stack(frames),
                            producer_seq=np.asarray(seqs, dtype=np.int64),
                            producer_heartbeat_unix_s=np.asarray(producer_times),
                            receiver_unix_s=np.asarray(receiver_times),
                            receiver_monotonic_s=np.asarray(receiver_monotonic_times))
    else:
        error = error or "no depth frames captured"
    result_present = (trial / "result.json").exists()
    walk_start = trial / "walk_start.txt"
    walk_start_monotonic = (float(walk_start.read_text())
                            if walk_start.is_file() else None)
    report = {
        "status": "complete" if frames and result_present and not error else "incomplete",
        "error": error, "frame_count": len(frames), "shape": list(SHAPE),
        "shm_name": shm_name, "heartbeat_endpoint": endpoint,
        "first_seq": seqs[0] if seqs else None,
        "last_seq": seqs[-1] if seqs else None,
        "sequence_gaps": sum(max(0, right - left - 1)
                             for left, right in zip(seqs, seqs[1:])),
        "frame_min": float(np.min(frames)) if frames else None,
        "frame_max": float(np.max(frames)) if frames else None,
        "frame_mean": float(np.mean(frames)) if frames else None,
        "result_present": result_present,
        "walk_start_monotonic_s": walk_start_monotonic,
        "meaning": "Heartbeat t_capture is publish time, not exact camera exposure time; "
                   "receiver_monotonic_s minus walk_start_monotonic_s aligns "
                   "samples approximately to qpos wall_s; sidecar frames are not "
                   "proven to be the exact pixels used by each policy tick.",
    }
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--shm-name", default="depth_img_shm")
    parser.add_argument("--heartbeat-endpoint",
                        default="ipc:///tmp/depth_img_shm.heartbeat")
    parser.add_argument("--setup-timeout", type=float, default=120)
    parser.add_argument("--max-duration", type=float, default=200)
    args = parser.parse_args()
    if args.setup_timeout <= 0 or args.max_duration <= 0:
        parser.error("timeouts must be positive")
    report = capture(args.trial, args.shm_name, args.heartbeat_endpoint,
                     args.setup_timeout, args.max_duration)
    print(json.dumps(report, indent=2))
    if report["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
