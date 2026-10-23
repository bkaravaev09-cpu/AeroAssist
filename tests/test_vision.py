from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core import vision_tracker as vision


@pytest.fixture
def tracker():
    tracker = vision.VisionTracker()
    tracker.face_mesh = MagicMock()
    tracker.face_mesh.process.return_value = SimpleNamespace(
        multi_face_landmarks=[SimpleNamespace(landmark=[SimpleNamespace(x=0.5, y=0.55)] * 468)]
    )
    tracker.is_calibrated = True
    tracker.calculate_ear = MagicMock(return_value=0.3)
    return tracker


def frame(tracker, now, left, right, assistant=None, pause=None):
    tracker.calculate_ear.side_effect = [left, right]
    with patch.object(vision.time, "time", return_value=now):
        tracker.process_frame(object(), assistant, pause)


def test_long_eye_closure_triggers_once_until_reopened(tracker):
    callback = MagicMock()
    for now in (10, 12, 13):
        frame(tracker, now, 0.05, 0.05, assistant=callback)
    callback.assert_called_once()
    frame(tracker, 14, 0.3, 0.3)
    frame(tracker, 15, 0.05, 0.05, assistant=callback)
    frame(tracker, 17, 0.05, 0.05, assistant=callback)
    assert callback.call_count == 2


def test_four_fast_blinks_pause_tracking(tracker):
    callback = MagicMock()
    for now in (10, 10.5, 11, 11.5):
        frame(tracker, now, 0.05, 0.05, pause=callback)
        frame(tracker, now + 0.1, 0.3, 0.3)
    callback.assert_called_once()


def test_four_blinks_stop_camera_session_and_allow_restart(tracker, app):
    app._stop_event.clear()
    app._tracking_state = "running"
    app.camera_thread = MagicMock()
    app.camera_thread.is_alive.return_value = False
    for now in (10, 10.5, 11, 11.5):
        frame(tracker, now, 0.05, 0.05, pause=app.pause_tracking_from_gesture)
        frame(tracker, now + 0.1, 0.3, 0.3)
    assert app._stop_event.is_set()
    app.label_status.configure.assert_not_called()
    app._worker_events.put((app._session_id, "stopped", None))
    app._poll_worker_events()
    assert app._tracking_state == "stopped"
    with patch("main.threading.Thread") as thread:
        app.toggle_system()
    thread.return_value.start.assert_called_once()
    assert not app._stop_event.is_set()


def test_slow_blinks_do_not_pause(tracker):
    callback = MagicMock()
    for now in (10, 14, 18, 22):
        frame(tracker, now, 0.05, 0.05, pause=callback)
        frame(tracker, now + 0.1, 0.3, 0.3)
    callback.assert_not_called()


def test_left_wink_click_is_debounced(tracker):
    with patch.object(vision, "win32_click") as click:
        frame(tracker, 10, 0.05, 0.3)
        frame(tracker, 11, 0.05, 0.3)
        click.assert_called_once()
        frame(tracker, 12, 0.3, 0.3)
        frame(tracker, 13, 0.05, 0.3)
        assert click.call_count == 2


def test_no_face_produces_no_cursor_action(tracker):
    tracker.process_frame(object())
    assert len(tracker.get_preview_landmarks()) == 468
    tracker.face_mesh.process.reset_mock()
    tracker.face_mesh.process.return_value.multi_face_landmarks = None
    with patch.object(vision, "win32_move") as move:
        tracker.process_frame(object())
        move.assert_not_called()
    assert tracker.get_preview_landmarks() == ()
    tracker.face_mesh.process.assert_called_once()


def test_calibration_uses_25_frames(tracker):
    tracker.is_calibrated = False
    for _ in range(25):
        tracker.process_frame(object())
    assert tracker.is_calibrated
    assert tracker.blink_threshold == pytest.approx(0.195)
    assert tracker.center_x == 0.5


def test_vision_routes_head_position_to_cursor_controller(tracker):
    with (
        patch.object(
            tracker.cursor_controller, "update_head", return_value=(120.4, 180.7)
        ) as update,
        patch.object(vision, "win32_move") as move,
    ):
        tracker.process_frame(object())
    update.assert_called_once_with(0.5, 0.55, 0.5, 0.55)
    move.assert_called_once_with(120, 181)


def test_sensitivity_property_controls_actual_movement(tracker):
    nose = SimpleNamespace(x=0.5, y=0.55)
    tracker.face_mesh.process.return_value.multi_face_landmarks[0].landmark = [nose] * 468
    tracker.sensitivity = 1.0
    tracker.process_frame(object())
    nose.x = 0.53
    tracker.process_frame(object())
    low_distance = tracker.cursor_controller.position[0] - 960
    from core.cursor_controller import CursorController

    tracker.cursor_controller = CursorController(1920, 1080)
    tracker.sensitivity = 3.0
    nose.x = 0.5
    tracker.process_frame(object())
    nose.x = 0.53
    tracker.process_frame(object())
    high_distance = tracker.cursor_controller.position[0] - 960
    assert high_distance == pytest.approx(low_distance * 3)


def test_no_face_holds_position_and_reacquisition_does_not_jump(tracker):
    results = tracker.face_mesh.process.return_value
    detected = results.multi_face_landmarks
    tracker.process_frame(object())
    detected[0].landmark = [SimpleNamespace(x=0.55, y=0.55)] * 468
    tracker.process_frame(object())
    position = tracker.cursor_controller.position
    results.multi_face_landmarks = None
    with patch.object(vision, "win32_move") as move:
        tracker.process_frame(object())
        move.assert_not_called()
    assert tracker.cursor_controller.position == position
    detected[0].landmark = [SimpleNamespace(x=0.4, y=0.55)] * 468
    results.multi_face_landmarks = detected
    tracker.process_frame(object())
    assert tracker.cursor_controller.position == position


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -0.1, 1.1, None])
def test_invalid_nose_does_not_move_or_poison_calibration(tracker, invalid):
    tracker.is_calibrated = False
    tracker.face_mesh.process.return_value.multi_face_landmarks[0].landmark = [
        SimpleNamespace(x=invalid, y=0.55)
    ] * 468
    with patch.object(vision, "win32_move") as move:
        tracker.process_frame(object())
        move.assert_not_called()
    assert tracker.calibration_nose_x == []
