"""Exercise the passive depth sidecar against a local fake producer."""

import json
import tempfile
import threading
import time
import unittest
import uuid
from multiprocessing import shared_memory
from pathlib import Path

import numpy as np
import zmq

from scripts.php_record_depth_diagnostic import SHAPE, capture


class DepthSidecarTest(unittest.TestCase):
    def test_captures_heartbeat_frames_until_trial_result(self):
        token = uuid.uuid4().hex
        name = f"php_depth_test_{token}"
        endpoint = f"ipc:///tmp/php_depth_test_{token}.sock"
        shm = shared_memory.SharedMemory(
            name=name, create=True, size=int(np.prod(SHAPE)) * 4)
        array = np.ndarray(SHAPE, dtype=np.float32, buffer=shm.buf)
        with tempfile.TemporaryDirectory() as folder:
            trial = Path(folder)

            def produce():
                socket = zmq.Context.instance().socket(zmq.PUB)
                socket.setsockopt(zmq.LINGER, 0)
                socket.bind(endpoint)
                try:
                    time.sleep(0.25)  # allow the SUB handshake to complete
                    for seq in range(1, 9):
                        array.fill(seq / 100)
                        socket.send_json({"v": 1, "seq": seq,
                                          "t_capture": time.time(), "state": "OK"})
                        time.sleep(0.06)
                    (trial / "result.json").write_text(json.dumps({"status": "done"}))
                finally:
                    socket.close()

            producer = threading.Thread(target=produce)
            try:
                producer.start()
                report = capture(trial, name, endpoint, setup_timeout=2,
                                 max_duration=3)
                producer.join(timeout=2)
                self.assertFalse(producer.is_alive())
                self.assertEqual(report["status"], "complete")
                self.assertGreaterEqual(report["frame_count"], 1)
                with np.load(trial / "depth_diagnostic.npz") as recorded:
                    self.assertEqual(recorded["frames"].shape[1:], SHAPE)
                    self.assertTrue(np.isfinite(recorded["frames"]).all())
                    self.assertEqual(len(recorded["receiver_monotonic_s"]),
                                     report["frame_count"])
            finally:
                producer.join(timeout=2)
                shm.close()
                shm.unlink()


if __name__ == "__main__":
    unittest.main()
