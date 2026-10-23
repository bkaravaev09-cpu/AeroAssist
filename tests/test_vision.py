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
    tracker.face_mesh.process.return_value.multi_face_landmarks = None
    with patch.object(vision, "win32_move") as move:
        tracker.process_frame(object())
        move.assert_not_called()


def test_calibration_uses_25_frames(tracker):
    tracker.is_calibrated = False
    for _ in range(25):
        tracker.process_frame(object())
    assert tracker.is_calibrated
    assert tracker.blink_threshold == pytest.approx(0.195)
    assert tracker.center_x == 0.5
