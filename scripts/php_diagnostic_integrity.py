"""Audit diagnostic state/contact rows without inventing missing terminal data."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def aligned_solver_rows(trial: Path) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Return the aligned prefix; permit one unscored qpos/qvel terminal row.

    The terminal exception applies only after an x-target stop and after the
    last scored pelvis sample. Raw files remain unchanged and the omission is
    reported to callers. Any earlier gap or larger discrepancy is an error.
    """
    with (trial / "qpos.csv").open(newline="") as stream:
        states = list(csv.DictReader(stream))
    with (trial / "qvel.csv").open(newline="") as stream:
        velocities = list(csv.DictReader(stream))
    with (trial / "solver_contacts.jsonl").open() as stream:
        contacts = [json.loads(line) for line in stream]
    if not states or len(states) != len(velocities):
        raise ValueError("qpos and qvel are empty or have different sample counts")
    if len(contacts) not in (len(states), len(states) - 1):
        raise ValueError("solver contacts have more than one missing sample")
    for state, velocity, contact in zip(states, velocities, contacts):
        if (abs(float(state["sim_s"]) - float(velocity["sim_s"])) > 1e-5 or
                abs(float(state["sim_s"]) - float(contact["sim_s"])) > 1e-5):
            raise ValueError("solver records do not share an aligned simulation time")
    tail = len(states) - len(contacts)
    if tail:
        result = json.loads((trial / "result.json").read_text())
        with (trial / "pelvis.csv").open(newline="") as stream:
            scored = list(csv.DictReader(stream))
        if (result.get("status") != "x_target_reached" or not scored or
                float(states[-1]["wall_s"]) <= float(scored[-1]["wall_s"]) or
                float(states[-1]["qpos_0"]) < float(result["target_x"])):
            raise ValueError("missing solver contact is not an unscored terminal row")
    report = {"qpos_raw": len(states), "qvel_raw": len(velocities),
              "solver_contacts_raw": len(contacts),
              "aligned_prefix": len(contacts),
              "unscored_terminal_contact_rows_missing": tail}
    return states[:len(contacts)], velocities[:len(contacts)], contacts, report
