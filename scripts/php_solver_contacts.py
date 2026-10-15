"""Sample solved foot/terrain contacts from a live MuJoCo physics state.

The result represents the instant being sampled. It is neither an integrated
impulse over the whole step nor a continuous contact history between samples.
"""

from __future__ import annotations

import mujoco
import numpy as np


def geom_maps(model: mujoco.MjModel) -> tuple[dict[int, str], dict[int, str]]:
    terrain: dict[int, str] = {}
    feet: dict[int, str] = {}
    for index in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, index) or ""
        if name == "floor" or name.startswith("floor_"):
            terrain[index] = name
        if "left_foot" in name or "right_foot" in name:
            feet[index] = "left" if "left_foot" in name else "right"
    return terrain, feet


def snapshot(model: mujoco.MjModel, data: mujoco.MjData,
             terrain: dict[int, str], feet: dict[int, str]) -> list[dict]:
    contacts = []
    for contact_id, contact in enumerate(data.contact[:data.ncon]):
        for floor_id, foot_id in ((contact.geom1, contact.geom2),
                                  (contact.geom2, contact.geom1)):
            if floor_id not in terrain or foot_id not in feet:
                continue
            force = np.zeros(6, dtype=np.float64)
            if contact.efc_address >= 0:
                mujoco.mj_contactForce(model, data, contact_id, force)
            contacts.append({
                "terrain": terrain[floor_id], "foot": feet[foot_id],
                "dist_m": round(float(contact.dist), 6),
                "normal_force_n": round(float(force[0]), 4),
                "pos_m": [round(float(x), 5) for x in contact.pos],
            })
    return contacts
