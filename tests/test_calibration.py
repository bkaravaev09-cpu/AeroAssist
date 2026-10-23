import json
import math
import time
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.calibration import (
    MIN_SAMPLES,
    POINTS,
    CalibrationError,
    CalibrationManager,
    CalibrationParameters,
    HeadSample,
)
from core.cursor_controller import CursorController, CursorSettings
from ui.calibration_window import CalibrationWindow

POSITIONS = ((0.5, 0.5), (0.4, 0.5), (0.65, 0.5), (0.5, 0.35), (0.5, 0.7))


@pytest.fixture
def parameters():
    return CalibrationParameters(0.5, 0.5, 0.4, 0.65, 0.35, 0.7)


@pytest.fixture
def manager(tmp_path):
    return CalibrationManager(tmp_path / "calibration.json")


def populate(manager, positions=POSITIONS):
    for point, position in zip(POINTS, positions, strict=True):
        manager.begin_step(point)
        for _ in range(MIN_SAMPLES):
            complete = manager.add_sample(position)
        assert complete


def test_five_point_medians_and_ranges(manager, parameters):
    populate(manager)
    assert manager.calculate() == parameters
    assert parameters.horizontal_range == pytest.approx(0.25)
    assert parameters.vertical_range == pytest.approx(0.35)
    assert manager.active is None


def test_samples_need_stability_and_median_rejects_small_noise(manager):
    manager.begin_step("center")
    for n in range(MIN_SAMPLES):
        assert not manager.add_sample((0.4 if n % 2 else 0.6, 0.5))
    assert "center" not in manager.points
    for n in range(MIN_SAMPLES):
        complete = manager.add_sample((0.5 + (0.001 if n % 2 else -0.001), 0.5))
    assert complete
    assert manager.points["center"] == (0.5, 0.5)
    assert len(manager.samples) == MIN_SAMPLES


@pytest.mark.parametrize(
    "position",
    [None, (math.nan, 0.5), (math.inf, 0.5), (-0.1, 0.5), (1.1, 0.5), (True, 0.5), (0.5,), "bad"],
)
def test_invalid_or_missing_samples_clear_partial_window(manager, position):
    manager.begin_step("center")
    manager.add_sample((0.5, 0.5))
    assert not manager.add_sample(position)
    assert len(manager.samples) == 0


def test_insufficient_data_and_repeat_only_replaces_selected_point(manager):
    with pytest.raises(CalibrationError):
        manager.calculate()
    populate(manager)
    manager.begin_step("left")
    assert "left" not in manager.points and "right" in manager.points
    for _ in range(MIN_SAMPLES - 1):
        assert not manager.add_sample((0.42, 0.5))
    with pytest.raises(CalibrationError):
        manager.calculate()
    assert manager.add_sample((0.42, 0.5))
    assert manager.calculate().left_x == 0.42


@pytest.mark.parametrize(
    "changes",
    [
        {"left_x": 0.499},
        {"right_x": 0.4},
        {"top_y": 0.5},
        {"bottom_y": 0.49},
        {"center_x": math.nan},
        {"left_x": -1},
        {"center_y": True},
    ],
)
def test_invalid_or_insufficient_ranges_are_rejected(parameters, changes):
    values = asdict(parameters) | changes
    with pytest.raises(CalibrationError):
        CalibrationParameters(**values)


@pytest.mark.parametrize(
    "position,expected",
    [
        ((0.5, 0.5), (500, 400)),
        ((0.4, 0.5), (0, 400)),
        ((0.65, 0.5), (1000, 400)),
        ((0.5, 0.35), (500, 0)),
        ((0.5, 0.7), (500, 800)),
        ((0, 0), (0, 0)),
        ((1, 1), (1000, 800)),
        ((0.45, 0.425), (250, 200)),
    ],
)
def test_asymmetric_mapping_and_clamping(parameters, position, expected):
    assert parameters.map_head(*position, 1001, 801) == pytest.approx(expected)


def test_save_load_schema_contains_only_calculated_parameters(manager, parameters):
    manager.save(parameters)
    data = json.loads(manager.path.read_text())
    assert data == {"version": 1, "parameters": asdict(parameters)}
    assert not manager.path.with_suffix(".json.tmp").exists()
    assert CalibrationManager(manager.path).load() == parameters


@pytest.mark.parametrize(
    "content",
    [
        "{",
        "[]",
        "null",
        "{}",
        '{"version":2,"parameters":{}}',
        '{"version":true,"parameters":{}}',
        "x" * 5000,
    ],
)
def test_corrupt_or_unsupported_files_fall_back_without_crashing(manager, content):
    manager.path.write_text(content)
    assert manager.load() is None


def test_invalid_saved_parameters_are_rejected(manager, parameters):
    manager.path.write_text(
        json.dumps({"version": 1, "parameters": asdict(parameters) | {"left_x": 0.5}})
    )
    assert manager.load() is None


def test_missing_file_and_restore_defaults(manager, parameters):
    assert manager.load() is None
    manager.save(parameters)
    manager.restore_defaults()
    assert manager.active is None and not manager.path.exists()
    assert CalibrationManager(manager.path).load() is None


def test_failed_save_preserves_previous_file_and_active_parameters(manager, parameters):
    manager.save(parameters)
    previous = manager.path.read_bytes()
    replacement = CalibrationParameters(0.55, 0.55, 0.4, 0.7, 0.4, 0.75)
    with patch.object(type(manager.path), "replace", side_effect=OSError("disk error")):
        with pytest.raises(OSError):
            manager.save(replacement)
    assert manager.active == parameters
    assert manager.path.read_bytes() == previous
    assert not manager.path.with_suffix(".json.tmp").exists()


def test_failed_default_removal_preserves_active(manager, parameters):
    manager.save(parameters)
    with patch.object(type(manager.path), "unlink", side_effect=OSError("permission denied")):
        with pytest.raises(OSError):
            manager.restore_defaults()
    assert manager.active == parameters


def test_calibrated_controller_keeps_smoothing_sensitivity_and_resets(parameters):
    cursor = CursorController(1001, 801, CursorSettings(smoothing=0.5, dead_zone=0))
    cursor.set_calibration(parameters)
    assert cursor.update_head(0.5, 0.5, 0.5, 0.5) == (500, 400)
    assert cursor.update_head(0.55, 0.5, 0.5, 0.5)[0] == pytest.approx(580)
    position = cursor.position
    cursor.reset()
    assert cursor.calibration == parameters
    assert cursor.update_head(0.4, 0.5, 0.5, 0.5) == position
    assert cursor.update_head(math.nan, 0.5, 0.5, 0.5) is None
    assert cursor.calibration == parameters
    cursor.set_calibration(None)
    assert cursor.calibration is None
    assert cursor.update_head(0.5, 0.5, 0.5, 0.5) == position


def test_calibrated_sensitivity_remains_independent(parameters):
    positions = []
    for sensitivity in (1.0, 3.0):
        cursor = CursorController(
            1001, 801, CursorSettings(sensitivity=sensitivity, smoothing=0, dead_zone=0)
        )
        cursor.set_calibration(parameters)
        cursor.update_head(0.5, 0.5, 0.5, 0.5)
        positions.append(cursor.update_head(0.51, 0.5, 0.5, 0.5)[0] - 500)
    assert positions[1] == pytest.approx(positions[0] * 3)


@pytest.fixture
def wizard(manager):
    window = CalibrationWindow.__new__(CalibrationWindow)
    window.manager = manager
    window.on_begin = MagicMock(return_value=True)
    window.on_collect = MagicMock()
    window.on_preview = MagicMock()
    window.on_save = MagicMock(side_effect=manager.save)
    window.on_cancel = MagicMock()
    window.on_reset = MagicMock(return_value=True)
    window.stage, window.step, window.capturing = "intro", 0, False
    window._closed = False
    window._tick_id = None
    window._last_sample = window._capture_started = None
    window._focus_index = 0
    for name in (
        "heading",
        "instructions",
        "status",
        "progress",
        "primary",
        "next_button",
        "previous",
        "repeat",
        "save_button",
        "defaults",
        "cancel_button",
        "target",
    ):
        setattr(window, name, MagicMock())
    window.buttons = [
        window.primary,
        window.next_button,
        window.previous,
        window.repeat,
        window.save_button,
        window.defaults,
        window.cancel_button,
    ]
    window.target.winfo_width.return_value = 800
    window.target.winfo_height.return_value = 400
    window.destroy = MagicMock()
    window.after = MagicMock()
    window.after_cancel = MagicMock()
    return window


def finish_wizard_points(wizard):
    wizard.start()
    now = time.monotonic()
    for position in POSITIONS:
        wizard.capture()
        for _ in range(MIN_SAMPLES):
            now += 0.05
            wizard.receive_sample(HeadSample(1, position, now))
        assert not wizard.capturing
        wizard.advance()


def test_wizard_five_points_preview_then_explicit_save(wizard, parameters):
    finish_wizard_points(wizard)
    assert wizard.stage == "preview"
    assert wizard.on_collect.call_count == 10
    wizard.on_collect.assert_called_with(False)
    wizard.on_preview.assert_called_once_with(parameters)
    assert wizard.manager.active is None
    assert not wizard.manager.path.exists()
    wizard.save()
    assert wizard.manager.active == parameters
    wizard.destroy.assert_called_once()


def test_wizard_cancel_preview_does_not_save(wizard):
    finish_wizard_points(wizard)
    wizard.cancel()
    wizard.cancel()
    wizard.on_cancel.assert_called_once()
    wizard.on_save.assert_not_called()
    assert not wizard.manager.path.exists()


def test_loss_duplicate_samples_timeout_and_repeat(wizard):
    wizard.start()
    wizard.capture()
    wizard.receive_sample(HeadSample(1, (0.5, 0.5), 1.0))
    wizard.receive_sample(HeadSample(1, (0.5, 0.5), 1.0))
    assert len(wizard.manager.samples) == 1
    wizard.receive_sample(HeadSample(1, None, 1.1))
    assert len(wizard.manager.samples) == 0
    wizard.receive_sample(HeadSample(1, (0.5, 0.5), 3.0))
    assert len(wizard.manager.samples) == 1
    with patch("ui.calibration_window.time.monotonic", return_value=wizard._capture_started + 11):
        wizard._tick()
    assert not wizard.capturing
    wizard.capture()
    assert wizard.capturing and len(wizard.manager.samples) == 0


def test_failed_save_allows_retry_or_cancel(wizard):
    finish_wizard_points(wizard)
    wizard.on_save.side_effect = OSError("disk full")
    wizard.save()
    wizard.destroy.assert_not_called()
    assert wizard.stage == "preview"
    assert wizard.manager.active is None
    wizard.on_preview.assert_called_with(None)
    wizard.cancel()
    wizard.destroy.assert_called_once()


def test_failed_range_keeps_previous_calibration_and_allows_step_repeat(wizard, parameters):
    wizard.manager.active = parameters
    wizard.start()
    populate(wizard.manager, (POSITIONS[0], (0.499, 0.5), *POSITIONS[2:]))
    wizard.step = 4
    wizard.advance()
    assert wizard.stage == "collecting"
    assert wizard.manager.active == parameters
    wizard.on_preview.assert_not_called()
    wizard.go_back()
    assert wizard.step == 3
    wizard.capture()
    assert wizard.manager.current_point == "top"


def test_wizard_keyboard_navigation_activates_focused_control(wizard):
    for button in wizard.buttons:
        button.winfo_ismapped.return_value = True
        button.cget.return_value = "normal"
    assert wizard._cycle_focus() == "break"
    wizard.next_button.focus_set.assert_called_once()
    wizard.focus_get = MagicMock(return_value=wizard.cancel_button)
    assert wizard._activate_focused(SimpleNamespace()) == "break"
    wizard.cancel_button.invoke.assert_called_once()


def test_application_preview_cancel_save_and_default_restore(app, parameters):
    app.calibration_manager.save(parameters)
    candidate = CalibrationParameters(0.55, 0.55, 0.4, 0.7, 0.4, 0.75)
    app._preview_calibration(candidate)
    app.tracker.apply_calibration.assert_called_with(candidate)
    app._cancel_calibration()
    app.tracker.apply_calibration.assert_called_with(parameters)
    assert app.calibration_manager.active == parameters
    app._save_calibration(candidate)
    assert CalibrationManager(app.calibration_manager.path).load() == candidate
    assert app._restore_calibration()
    app.tracker.apply_calibration.assert_called_with(None)
    assert not app.calibration_manager.path.exists()


def test_app_poll_forwards_head_sample_from_existing_worker_and_reports_pause(app):
    app.calibration_window = MagicMock()
    app._stop_event.clear()
    sample = HeadSample(app._session_id, (0.5, 0.5), time.monotonic())
    app._calibration_samples.publish(sample)
    app._poll_worker_events()
    app.calibration_window.receive_sample.assert_called_once_with(sample)
    app._stop_event.set()
    app._poll_worker_events()
    app.calibration_window.tracking_unavailable.assert_called_once()


def test_calibrated_mapping_reaches_corners_with_smoothing_and_dead_zone(parameters):
    cursor = CursorController(1001, 801)
    cursor.set_calibration(parameters)
    cursor.update_head(0.5, 0.5, 0.5, 0.5)
    for nose, corner in (
        ((0.4, 0.35), (0, 0)),
        ((0.65, 0.35), (1000, 0)),
        ((0.65, 0.7), (1000, 800)),
        ((0.4, 0.7), (0, 800)),
    ):
        for _ in range(100):
            position = cursor.update_head(*nose, 0.5, 0.5)
            assert 0 <= position[0] <= 1000 and 0 <= position[1] <= 800
        assert tuple(round(v) for v in position) == corner


def test_dead_zone_cannot_block_last_pixel_at_boundary():
    cursor = CursorController(1000, 800, CursorSettings(smoothing=0, dead_zone=2))
    for _ in range(20):
        cursor.update_target(998, 400)
    assert cursor.position == (998, 400)
    assert cursor.update_target(999, 400) == (999, 400)


def test_application_starts_only_existing_tracking_and_cancels_on_shutdown(app):
    with patch("main.CalibrationWindow") as window, patch.object(app, "toggle_system") as start:
        app.open_calibration()
        app.open_calibration()
        assert window.call_count == 1
        app._tracking_state = "running"
        assert app._begin_calibration()
        start.assert_not_called()
        app._tracking_state = "stopping"
        assert not app._begin_calibration()
        app.close()
        window.return_value.cancel.assert_called_once()


def test_application_loads_valid_profile_at_startup(app, parameters):
    app.calibration_manager.save(parameters)
    with patch("main.VisionTracker") as tracker:
        app.__init__()
    tracker.return_value.apply_calibration.assert_called_once_with(parameters)


def test_no_camera_during_wizard_stops_capture_without_overwriting_profile(wizard, parameters):
    wizard.manager.save(parameters)
    wizard.start()
    wizard.capture()
    wizard.tracking_unavailable("Nie można otworzyć kamery.")
    assert not wizard.capturing
    assert wizard.manager.active == parameters
    assert CalibrationManager(wizard.manager.path).load() == parameters
    wizard.capture()
    assert wizard.capturing
