"""Protect diagnostic conclusions from dropped contact rows inside a course."""

import csv
import json

import pytest

from scripts.php_diagnostic_integrity import aligned_solver_rows


def make_trial(path, *, contact_times=(1.0, 2.0), last_state_wall=3.0,
               last_scored_wall=2.5):
    with (path / "qpos.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("wall_s", "sim_s", "qpos_0"))
        writer.writerows(((1.0, 1.0, 5.0), (2.0, 2.0, 10.0),
                          (last_state_wall, 3.0, 14.0)))
    with (path / "qvel.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("wall_s", "sim_s", "qvel_0"))
        writer.writerows(((1.0, 1.0, 0), (2.0, 2.0, 0),
                          (last_state_wall, 3.0, 0)))
    (path / "solver_contacts.jsonl").write_text("".join(
        json.dumps({"wall_s": time, "sim_s": time, "contacts": []}) + "\n"
        for time in contact_times))
    (path / "result.json").write_text(json.dumps({"status": "x_target_reached",
                                                  "target_x": 13.8}))
    with (path / "pelvis.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("wall_s", "x"))
        writer.writerow((last_scored_wall, 13.8))


def test_single_unscored_terminal_contact_gap_is_reported(tmp_path):
    make_trial(tmp_path)
    states, velocities, contacts, report = aligned_solver_rows(tmp_path)
    assert len(states) == len(velocities) == len(contacts) == 2
    assert report["unscored_terminal_contact_rows_missing"] == 1
    assert report["qpos_raw"] == 3


def test_missing_contact_inside_aligned_course_is_rejected(tmp_path):
    make_trial(tmp_path, contact_times=(1.0, 3.0))
    with pytest.raises(ValueError, match="aligned simulation time"):
        aligned_solver_rows(tmp_path)


def test_contact_gap_before_last_scored_sample_is_rejected(tmp_path):
    make_trial(tmp_path, last_state_wall=2.4, last_scored_wall=2.5)
    with pytest.raises(ValueError, match="unscored terminal row"):
        aligned_solver_rows(tmp_path)
