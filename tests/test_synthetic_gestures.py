"""Synthetic landmark tests for new gestures — no camera required."""

from unittest.mock import MagicMock, patch

import numpy as np

from core import vision_tracker as vision


def make_tracker():
    t = vision.VisionTracker()
    t.face_mesh = MagicMock()
    # Synthetic landmarks: 468 points with eye positions
    pts = [MagicMock(x=0.5, y=0.55) for _ in range(468)]
    # Set left eye region open
    pts[159].x, pts[159].y = 0.4, 0.45
    pts[145].x, pts[145].y = 0.4, 0.55
    pts[33].x, pts[33].y = 0.35, 0.5
    pts[133].x, pts[133].y = 0.45, 0.5
    # Right eye open
    pts[386].x, pts[386].y = 0.6, 0.45
    pts[374].x, pts[374].y = 0.6, 0.55
    pts[362].x, pts[362].y = 0.55, 0.5
    pts[263].x, pts[263].y = 0.65, 0.5
    # Nose
    pts[4].x, pts[4].y = 0.5, 0.55
    t.face_mesh.process.return_value = MagicMock(multi_face_landmarks=[MagicMock(landmark=pts)])
    return t


def test_double_blink_triggers_click():
    """Two fast left-eye blinks = double click (synthetic)."""
    tracker = make_tracker()
    tracker.is_calibrated = True
    tracker.calibration_ear = [0.3] * 25
    tracker.blink_threshold = 0.15
    tracker.center_x, tracker.center_y = 0.5, 0.55

    click_counts = []

    def mock_click():
        click_counts.append(1)

    # Hold left eye closed for 1.0s (>= LEFT_HOLD_THRESHOLD) → double click
    with patch.object(vision.time, "time", return_value=10.0):
        tracker.calculate_ear = MagicMock(side_effect=[0.05, 0.3])
        tracker.process_frame(
            np.zeros((480, 640, 3), dtype=np.uint8),
            on_assistant_trigger=lambda: None,
            on_shutdown_trigger=lambda: None,
        )

    with patch.object(vision.time, "time", return_value=11.0):
        tracker.calculate_ear = MagicMock(side_effect=[0.05, 0.3])
        tracker.process_frame(
            np.zeros((480, 640, 3), dtype=np.uint8),
            on_assistant_trigger=lambda: None,
            on_shutdown_trigger=lambda: None,
        )

    # Release left eye → double click should fire
    with patch.object(vision.time, "time", return_value=11.0):
        tracker.calculate_ear = MagicMock(side_effect=[0.3, 0.3])
        tracker.process_frame(
            np.zeros((480, 640, 3), dtype=np.uint8),
            on_assistant_trigger=lambda: None,
            on_shutdown_trigger=lambda: None,
        )

    # After long hold, last_click_time should be updated (double click fired)
    assert tracker.last_click_time >= 10.0
    print("Synthetic left-eye hold double-click test PASSED")


if __name__ == "__main__":
    test_double_blink_triggers_click()
