#!/usr/bin/env python3
"""Run official Holosoma simulation with opt-in clean viewer and state capture.

Physics, terrain collision, sensors, and policy are unchanged. Only visible geom
colors, camera defaults, sidebars, and a sampled qpos log are added for replay.
"""

from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path

import mujoco
import mujoco.viewer

from holosoma.simulator.mujoco.mujoco import MuJoCo
from holosoma.run_sim import main
from php_solver_contacts import geom_maps, snapshot


trial = Path(os.environ["PHP_DEMO_TRIAL_DIR"])
trial.mkdir(parents=True, exist_ok=True)
start_file = trial / "walk_start.txt"
diagnostic_trial = os.environ.get("PHP_DIAGNOSTIC_TRIAL_DIR")
if diagnostic_trial and Path(diagnostic_trial).resolve() != trial.resolve():
    raise ValueError("diagnostic directory must be the same isolated demo trial")
diagnostic_enabled = bool(diagnostic_trial)

original_launch = mujoco.viewer.launch_passive
def launch_clean(*args, **kwargs):
    kwargs.update(show_left_ui=False, show_right_ui=False)
    return original_launch(*args, **kwargs)
mujoco.viewer.launch_passive = launch_clean

original_setup = MuJoCo.setup_viewer
def setup_clean(self):
    original_setup(self)
    model = self.root_model
    terrain_geoms = []
    if diagnostic_enabled:
        self._php_terrain_names, self._php_foot_names = geom_maps(model)
    for index in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, index) or ""
        if not (name == "floor" or name.startswith("floor_")):
            continue
        terrain_geoms.append({"name": name, "rgba_before": model.geom_rgba[index].tolist(),
                              "matid_before": int(model.geom_matid[index]),
                              "aabb": model.geom_aabb[index].tolist()})
        # Bright, opaque presentation colors; the original collider and mesh are untouched.
        half_sizes = model.geom_aabb[index, 3:]
        model.geom_matid[index] = -1
        model.geom_rgba[index] = ([0.30, 0.36, 0.42, 1.0]
                                  if max(half_sizes[:2]) > 10.0 else
                                  [0.78, 0.49, 0.23, 1.0])
    if self.viewer is not None:
        with self.viewer.lock():
            self.viewer.cam.distance = 5.0
            self.viewer.cam.azimuth = 110.0
            self.viewer.cam.elevation = -20.0
    mujoco.mj_saveModel(model, str(trial / "replay_model.mjb"))
    (trial / "visual_diagnostics.json").write_text(json.dumps({
        "terrain_geoms": terrain_geoms, "camera_distance_m": 5.0,
        "camera_azimuth_deg": 110.0, "camera_elevation_deg": -20.0,
        "debug_frusta": False, "ui_sidebars": False,
        "presentation_only": True,
        "diagnostic_qvel_and_solver_contacts": diagnostic_enabled,
    }, indent=2) + "\n")
MuJoCo.setup_viewer = setup_clean

original_render = MuJoCo.render
def render_and_record(self, sync_frame_time=True):
    original_render(self, sync_frame_time=sync_frame_time)
    if not hasattr(self, "_php_demo_start_s"):
        if not start_file.exists():
            return
        self._php_demo_start_s = float(start_file.read_text())
        self._php_demo_last_sample_s = -1.0
        self._php_demo_qpos_handle = (trial / "qpos.csv").open("w", newline="", buffering=1)
        self._php_demo_qpos_writer = csv.writer(self._php_demo_qpos_handle)
        self._php_demo_qpos_writer.writerow(["wall_s", "sim_s", *
                                             (f"qpos_{i}" for i in range(self.root_model.nq))])
        if diagnostic_enabled:
            self._php_demo_qvel_handle = (trial / "qvel.csv").open("w", newline="", buffering=1)
            self._php_demo_qvel_writer = csv.writer(self._php_demo_qvel_handle)
            self._php_demo_qvel_writer.writerow(["wall_s", "sim_s", *
                                                 (f"qvel_{i}" for i in range(self.root_model.nv))])
            self._php_demo_contacts_handle = (trial / "solver_contacts.jsonl").open("w", buffering=1)
    now = time.monotonic() - self._php_demo_start_s
    if now - self._php_demo_last_sample_s >= 1 / 60:
        self._php_demo_qpos_writer.writerow([round(now, 5),
                                             round(float(self.root_data.time), 5),
                                             *self.root_data.qpos])
        if diagnostic_enabled:
            self._php_demo_qvel_writer.writerow([round(now, 5),
                                                 round(float(self.root_data.time), 5),
                                                 *self.root_data.qvel])
            contacts = snapshot(self.root_model, self.root_data,
                                self._php_terrain_names, self._php_foot_names)
            self._php_demo_contacts_handle.write(json.dumps({
                "wall_s": round(now, 5), "sim_s": round(float(self.root_data.time), 5),
                "contacts": contacts,
            }) + "\n")
        self._php_demo_last_sample_s = now
MuJoCo.render = render_and_record


if __name__ == "__main__":
    main()
