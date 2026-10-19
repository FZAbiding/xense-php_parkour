"""Geometry-aware heading pulses for a released ONNX policy.

This is external navigation using known course geometry and simulator pelvis
telemetry. It is not an onboard-perception policy or a modification of ONNX.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BlockAim:
    number: int
    front_x: float
    rear_x: float
    center_y: float
    half_width_y: float

    @property
    def scored_exit_x(self) -> float:
        return self.rear_x + 1.5


@dataclass(frozen=True)
class Guidance:
    key: str | None
    block: int | None
    target_x: float | None
    target_y: float | None
    predicted_exit_y: float | None
    horizon_s: float | None
    error_m: float | None
    reason: str


def course_aims(course_blocks) -> list[BlockAim]:
    aims = []
    for number, corners, _height in course_blocks:
        xs = [corner[0] for corner in corners]
        ys = [corner[1] for corner in corners]
        aims.append(BlockAim(number, min(xs), max(xs),
                             (min(ys) + max(ys)) / 2,
                             (max(ys) - min(ys)) / 2))
    return aims


def choose_block_direction(aims: list[BlockAim], *, x: float, y: float,
                           z: float, vx: float, vy: float,
                           yaw_rate_deg_s: float) -> Guidance:
    """Predict lateral position at the next scored exit and choose a short turn.

    The second block is the first active target. Start 1.1 m before its front
    edge to avoid disturbing the first-block skill and allow correction before
    takeoff. No pulses are requested while the pelvis is high on an obstacle.
    """
    # Do not issue new turns on a block: trial 012 alternated directions
    # there and fell before it could complete the second-block exit.
    active = next((aim for aim in aims if aim.number >= 2 and
                   aim.front_x - 1.1 <= x < aim.front_x - 0.25), None)
    if active is None:
        return Guidance(None, None, None, None, None, None, None, "outside_approach")
    if z >= 0.98:
        return Guidance(None, active.number, active.scored_exit_x, active.center_y,
                        None, None, None, "on_obstacle_or_airborne")
    horizon = min(1.8, max(0.5, (active.scored_exit_x - x) / max(vx, 0.6)))
    yaw_rate = math.radians(max(-40.0, min(40.0, yaw_rate_deg_s)))
    predicted = y + vy * horizon + 0.5 * max(vx, 0.0) * yaw_rate * horizon ** 2
    error = predicted - active.center_y
    threshold = min(0.35, 0.4 * active.half_width_y)
    # A negative yaw rate is already steering from positive y toward center;
    # a positive one is already steering back from negative y. Avoid fighting it.
    if error < -threshold and yaw_rate_deg_s < 5.0:
        key, reason = "a", "predicted_left_of_block"
    elif error > threshold and yaw_rate_deg_s > -5.0:
        key, reason = "d", "predicted_right_of_block"
    else:
        key, reason = None, "inside_target_or_self_correcting"
    return Guidance(key, active.number, active.scored_exit_x, active.center_y,
                    predicted, horizon, error, reason)
