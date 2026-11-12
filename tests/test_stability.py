"""Stability test + five-point calibration working together."""

from unittest.mock import MagicMock, patch

import pytest

from core.calibration import CalibrationParameters, HeadSample
from core.calibration_wizard import (
    AMPLITUDE_SECONDS,
    CENTER_HOLD,
    STABILITY_SECONDS,
    CalibrationWizard,
)
from core.cursor_controller import DEFAULT_CURSOR_SETTINGS
from core.cursor_profile import CursorProfile, CursorProfileStore, compute_profile

STEADY = [(0.5, 0.5)] * 20
SHAKY = [(0.5 + i * 0.001, 0.5 - i * 0.001) for i in range(20)]
FIVE_POINT = CalibrationParameters(0.5, 0.5, 0.4, 0.65, 0.35, 0.7)


def test_jitter_raises_smoothing_and_dead_zone_and_peak_is_optional():
    steady, shaky = compute_profile(STEADY), compute_profile(SHAKY)
    assert shaky.smoothing > steady.smoothing
    assert shaky.dead_zone > steady.dead_zone
    assert steady.sensitivity is None
    assert compute_profile(STEADY, peak=0.1).sensitivity == pytest.approx(1.5)
    assert compute_profile(STEADY, peak=0.1, fine_mode=True).sensitivity == pytest.approx(1.0)
    with pytest.raises(ValueError):
        compute_profile(STEADY[:3])


def test_profile_store_round_trip_corrupt_and_clear(tmp_path):
    store = CursorProfileStore(tmp_path / "p.json")
    assert store.load() is None
    profile = CursorProfile(smoothing=0.8, dead_zone=3.0, sensitivity=None)
    store.save(profile)
    assert store.load() == profile
    store.path.write_text('{"version": 1, "profile": {"smoothing": 5}}', encoding="utf-8")
    assert store.load() is None
    store.clear()
    assert not store.path.exists()


def configure_real_cursor(app):
    """Let configure_cursor update real settings so sliders can be synced."""
    from core.cursor_controller import CursorController

    controller = CursorController(1920, 1080)
    app.tracker.cursor_controller = controller
    app.tracker.configure_cursor.side_effect = controller.configure
    return controller


def test_startup_profile_skips_sensitivity_when_five_point_is_active(app):
    app.cursor_profile_store.save(CursorProfile(smoothing=0.9, dead_zone=4.0, sensitivity=2.5))
    app._apply_cursor_profile(app.cursor_profile_store.load())
    app.tracker.configure_cursor.assert_called_with(smoothing=0.9, dead_zone=4.0, sensitivity=2.5)
    app.calibration_manager.save(FIVE_POINT)
    app._apply_cursor_profile(app.cursor_profile_store.load())
    app.tracker.configure_cursor.assert_called_with(smoothing=0.9, dead_zone=4.0)


def test_saving_five_point_drops_stale_profile_sensitivity(app):
    controller = configure_real_cursor(app)
    app.cursor_profile_store.save(CursorProfile(smoothing=0.9, dead_zone=4.0, sensitivity=2.8))
    controller.configure(sensitivity=2.8)
    app._save_calibration(FIVE_POINT)
    assert app.cursor_profile_store.load() == CursorProfile(0.9, 4.0, None)
    assert controller.settings.sensitivity == DEFAULT_CURSOR_SETTINGS.sensitivity


def test_finish_applies_saves_syncs_sliders_and_freezes_only_while_open(app):
    controller = configure_real_cursor(app)
    with patch("main.CalibrationWizard") as wizard:
        app.open_stability_test()
        app.open_calibration()  # must not open a second calibration window
    wizard.return_value.lift.assert_called_once()
    assert app.calibration_window is None
    assert app._calibration_open.is_set()
    app._tracking_state = "running"
    assert app._begin_stability_test()
    app.tracker.set_calibration_collecting.assert_called_with(True)
    profile = CursorProfile(smoothing=0.85, dead_zone=5.0, sensitivity=2.0)
    app._finish_stability_test(profile, (0.48, 0.52))
    assert controller.settings.smoothing == 0.85
    assert (app.tracker.center_x, app.tracker.center_y) == (0.48, 0.52)
    assert app.cursor_profile_store.load() == profile
    app.slider_dead_zone.set.assert_called_with(5.0)
    app._end_stability_test()
    app.tracker.set_calibration_collecting.assert_called_with(False)
    assert app.stability_window is None and not app._calibration_open.is_set()


def test_poll_forwards_samples_to_stability_window(app):
    import time

    app.stability_window = MagicMock()
    app._stop_event.clear()
    sample = HeadSample(app._session_id, (0.5, 0.5), time.monotonic())
    app._calibration_samples.publish(sample)
    app._poll_worker_events()
    app.stability_window.receive_sample.assert_called_once_with(sample)


def test_restore_defaults_resets_cursor_profile_too(app):
    app.cursor_profile_store.save(CursorProfile(smoothing=0.9, dead_zone=4.0))
    app.calibration_manager.save(FIVE_POINT)
    assert app.restore_default_calibration()
    assert app.cursor_profile_store.load() is None
    assert app.calibration_manager.active is None


def make_wizard(calibrated):
    window = CalibrationWizard.__new__(CalibrationWizard)
    window.calibrated = calibrated
    window.on_begin = MagicMock(return_value=True)
    window.on_finish = MagicMock()
    window.on_close = MagicMock()
    window._reset_state()
    for name in ("title_label", "canvas", "status_label", "progress_label", "next_btn"):
        setattr(window, name, MagicMock())
    window.finish_btn = MagicMock()
    window.destroy = MagicMock()
    return window


def feed(window, position, start, seconds, step=0.05):
    now = start
    while now <= start + seconds + step:
        window.receive_sample(HeadSample(1, position, now))
        now += step
    return now


@pytest.mark.parametrize("calibrated", [True, False])
def test_wizard_stages_and_sensitivity_only_without_five_point(calibrated):
    window = make_wizard(calibrated)
    now = feed(window, (0.5, 0.5), 0.0, CENTER_HOLD)
    assert window.center == (0.5, 0.5)
    window.next_stage()
    if not calibrated:
        assert window.stage == "amplitude"
        now = feed(window, (0.6, 0.5), now, AMPLITUDE_SECONDS)
        assert window.peak == pytest.approx(0.1)
        window.next_stage()
    assert window.stage == "stability"
    feed(window, (0.5, 0.5), now, STABILITY_SECONDS)
    window.finish()
    profile, center = window.on_finish.call_args.args
    assert (profile.sensitivity is None) == calibrated
    assert (center is None) == calibrated
    window.on_close.assert_called_once()


def test_wizard_tracking_loss_restarts_stage_and_blocks_finish():
    window = make_wizard(True)
    window.stage = "stability"
    feed(window, (0.5, 0.5), 0.0, 2.0)
    window.tracking_unavailable("Śledzenie wstrzymane.")
    assert window.stability_samples == []
    window.finish()
    window.on_finish.assert_not_called()
