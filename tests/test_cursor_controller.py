import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from core.cursor_controller import DEFAULT_CURSOR_SETTINGS, CursorController, CursorSettings


def controller(**changes):
    return CursorController(1000, 800, replace(DEFAULT_CURSOR_SETTINGS, **changes))


def test_known_ema_coordinates():
    cursor = controller(smoothing=0.5, dead_zone=0.0)
    assert cursor.update_target(600, 440) == (550, 420)
    assert cursor.update_target(600, 440) == (575, 430)


def test_stronger_smoothing_reduces_step():
    weak, strong = controller(smoothing=0.0), controller(smoothing=0.9)
    assert weak.update_target(560, 400)[0] == 560
    assert strong.update_target(560, 400)[0] == 506


def test_jitter_reduction_compared_to_previous_ema():
    samples = [501.0, 499.0] * 100
    previous = 500.0
    old, new = [], []
    cursor = controller()
    for value in samples:
        previous += (value - previous) * 0.26
        old.append(previous)
        new.append(cursor.update_target(value, 400)[0])
    assert max(old) - min(old) > 0.25
    assert max(new) - min(new) == 0.0


@pytest.mark.parametrize("dead_zone", [0.0, 1.0, 2.0, 5.0, 10.0])
def test_dead_zone_threshold_is_inclusive(dead_zone):
    cursor = controller(smoothing=0.0, dead_zone=dead_zone)
    if dead_zone:
        assert cursor.update_target(500 + dead_zone - 0.01, 400) == (500, 400)
    assert cursor.update_target(500 + dead_zone, 400) == (500 + dead_zone, 400)


def test_slow_motion_accumulates_and_does_not_oscillate_at_threshold():
    cursor = controller(smoothing=0.0)
    for x in (500.5, 501, 501.5):
        assert cursor.update_target(x, 400)[0] == 500
    assert cursor.update_target(502, 400)[0] == 502
    for x in (501.9, 502.1, 501.8, 502.2):
        assert cursor.update_target(x, 400)[0] == 502
    for x in (502.5, 503, 503.5):
        cursor.update_target(x, 400)
    assert cursor.update_target(504, 400)[0] == 504


def test_diagonal_dead_zone_uses_distance():
    cursor = controller(smoothing=0.0)
    assert cursor.update_target(501, 401) == (500, 400)
    assert cursor.update_target(501.5, 401.5) == (501.5, 401.5)


@pytest.mark.parametrize("x,y", [(math.nan, 1), (1, math.inf), (-math.inf, 1), (None, 1), ("x", 1)])
def test_invalid_targets_hold_position_and_allow_recovery(x, y):
    cursor = controller()
    cursor.update_target(530, 420)
    position = cursor.position
    assert cursor.update_target(x, y) is None
    assert cursor.position == position
    assert cursor.update_head(0.6, 0.5, 0.5, 0.5) == position


@pytest.mark.parametrize("nose", [(math.nan, 0.5), (0.5, math.inf), (-0.1, 0.5), (1.1, 0.5)])
def test_invalid_head_coordinates_are_rejected(nose):
    cursor = controller()
    assert cursor.update_head(*nose, 0.5, 0.5) is None
    assert cursor.position == (500, 400)


@pytest.mark.parametrize("smoothing", [0.0, 0.5, 0.95])
@pytest.mark.parametrize("target", [(-100, -100), (9999, 9999), (-100, 9999), (9999, -100)])
def test_boundaries_and_step_limit(smoothing, target):
    cursor = controller(smoothing=smoothing, dead_zone=0.0)
    previous = cursor.position
    for _ in range(400):
        x, y = cursor.update_target(*target)
        assert 0 <= x <= 999 and 0 <= y <= 799
        assert math.dist((x, y), previous) <= 80.000001
        previous = (x, y)
    assert round(x) == (0 if target[0] < 0 else 999)
    assert round(y) == (0 if target[1] < 0 else 799)


def test_reset_removes_tail_and_drift_and_holds_reacquired_position():
    cursor = controller()
    cursor.update_head(0.5, 0.5, 0.5, 0.5)
    for _ in range(10):
        cursor.update_head(0.6, 0.5, 0.5, 0.5)
    position = cursor.position
    cursor.reset()
    assert cursor.update_head(0.4, 0.5, 0.5, 0.5) == position
    # Holding a neutral reference after reset cannot replay the old EMA tail.
    cursor.reset()
    for _ in range(5):
        assert cursor.update_head(0.5, 0.5, 0.5, 0.5) == position


def test_abrupt_landmark_spike_does_not_jump_cursor():
    cursor = controller()
    origin = cursor.update_head(0.5, 0.5, 0.5, 0.5)
    assert cursor.update_head(0.95, 0.95, 0.5, 0.5) == origin
    assert cursor.update_head(0.5, 0.5, 0.5, 0.5) == origin


def test_sensitivity_affects_small_movements_independently_of_smoothing():
    low, high = controller(sensitivity=1.0), controller(sensitivity=3.0)
    for cursor in (low, high):
        cursor.update_head(0.5, 0.5, 0.5, 0.5)
        cursor.update_head(0.53, 0.5, 0.5, 0.5)
    assert high.position[0] - 500 == pytest.approx((low.position[0] - 500) * 3)


@pytest.mark.parametrize(
    "nose,edge",
    [
        ((0.6, 0.5), (999, 400)),
        ((0.4, 0.5), (0, 400)),
        ((0.5, 0.6), (500, 799)),
        ((0.5, 0.4), (500, 0)),
    ],
)
def test_head_tilt_reaches_all_edges_and_can_return(nose, edge):
    cursor = controller()
    cursor.update_head(0.5, 0.5, 0.5, 0.5)
    for _ in range(200):
        cursor.update_head(*nose, 0.5, 0.5)
    assert tuple(round(value) for value in cursor.position) == edge
    for _ in range(200):
        cursor.update_head(0.5, 0.5, 0.5, 0.5)
    assert cursor.position == pytest.approx((500, 400), abs=3)


def test_settings_are_independent_atomic_and_resettable():
    cursor = controller()
    cursor.configure(sensitivity=2.5, smoothing=0.5, dead_zone=4)
    assert cursor.settings == CursorSettings(sensitivity=2.5, smoothing=0.5, dead_zone=4)
    cursor.configure(**vars(DEFAULT_CURSOR_SETTINGS))
    assert cursor.settings == DEFAULT_CURSOR_SETTINGS


@pytest.mark.parametrize(
    "changes",
    [
        {"sensitivity": 0},
        {"sensitivity": math.nan},
        {"smoothing": 1.0},
        {"smoothing": -0.1},
        {"dead_zone": -1},
        {"max_step": math.inf},
        {"max_head_step": 0},
        {"sensitivity": "high"},
    ],
)
def test_invalid_configuration_cannot_corrupt_current_settings(changes):
    cursor = controller()
    with pytest.raises(ValueError):
        cursor.configure(**changes)
    assert cursor.settings == DEFAULT_CURSOR_SETTINGS


@pytest.mark.parametrize("dimensions", [(0, 100), (100, -1), (100.5, 100)])
def test_invalid_screen_dimensions(dimensions):
    with pytest.raises(ValueError):
        CursorController(*dimensions)


def test_configuration_is_safe_during_worker_updates():
    cursor = controller()

    def configure():
        for n in range(100):
            cursor.configure(sensitivity=1.0 if n % 2 else 3.0)

    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(configure)
        for _ in range(100):
            x, y = cursor.update_head(0.51, 0.52, 0.5, 0.5)
            assert math.isfinite(x) and math.isfinite(y)
        task.result(timeout=3)
