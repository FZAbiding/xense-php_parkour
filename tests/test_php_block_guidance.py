"""Check block-aware navigation choices against the released course geometry."""

from scripts.php_block_guidance import BlockAim, choose_block_direction, course_aims
from scripts.php_score_course import DEFAULT_TERRAIN, blocks


def aims():
    return course_aims(list(blocks(DEFAULT_TERRAIN)))


def test_course_target_uses_actual_second_block_geometry():
    second = aims()[1]
    assert second.number == 2
    assert abs(second.front_x - 9.400235) < 1e-6
    assert abs(second.rear_x - 10.599765) < 1e-6
    assert abs(second.scored_exit_x - 12.099765) < 1e-6
    assert second.center_y == 0


def test_predicts_negative_drift_before_second_block_and_corrects_left():
    choice = choose_block_direction(
        aims(), x=8.5, y=0.6, z=0.8, vx=1.0, vy=-0.35,
        yaw_rate_deg_s=-20.0)
    assert choice.block == 2
    assert choice.key == "a"
    assert choice.predicted_exit_y < -0.35


def test_avoids_fighting_a_self_correcting_turn():
    choice = choose_block_direction(
        aims(), x=8.31, y=0.6, z=0.8, vx=1.0, vy=0.3,
        yaw_rate_deg_s=-20.0)
    assert choice.key is None
    assert choice.reason == "inside_target_or_self_correcting"


def test_corrects_positive_drift_and_stops_on_obstacle():
    course = aims()
    decision = choose_block_direction(
        course, x=8.5, y=0.6, z=0.8, vx=1.0, vy=0.4,
        yaw_rate_deg_s=10.0)
    assert decision.key == "d"
    high = choose_block_direction(
        course, x=9.8, y=0.6, z=1.2, vx=1.0, vy=0.4,
        yaw_rate_deg_s=10.0)
    assert high.key is None
    assert high.reason == "outside_approach"
    low_on_block = choose_block_direction(
        course, x=9.2, y=0.8, z=0.8, vx=1.0, vy=0.4,
        yaw_rate_deg_s=10.0)
    assert low_on_block.key is None
    assert low_on_block.reason == "outside_approach"


def test_aims_change_with_course_geometry():
    shifted = [BlockAim(2, 9.4, 10.6, 0.45, 0.8)]
    decision = choose_block_direction(
        shifted, x=8.5, y=0.6, z=0.8, vx=1.0, vy=0.0,
        yaw_rate_deg_s=0.0)
    assert decision.target_y == 0.45
    assert decision.key is None
