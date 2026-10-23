import threading
import time
import weakref
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import main
from ui import camera_preview as preview


@pytest.fixture
def component(monkeypatch, real_cv2):
    monkeypatch.setattr(preview, "cv2", real_cv2)
    widget = preview.CameraPreview.__new__(preview.CameraPreview)
    widget.video = MagicMock()
    widget.indicators = MagicMock()
    widget.show_landmarks = MagicMock()
    widget.show_landmarks.get.return_value = True
    widget._image_size = (480, 270)
    widget._image = None
    widget._placeholder_image = MagicMock()
    widget._get_widget_scaling = MagicMock(return_value=1.0)
    widget._last_frame_at = None
    return widget


def packet(session=1, landmarks=(), frame=None, captured_at=None):
    return preview.PreviewFrame(
        session,
        np.zeros((90, 160, 3), dtype=np.uint8) if frame is None else frame,
        landmarks,
        24.0,
        time.monotonic() if captured_at is None else captured_at,
    )


def test_real_bgr_to_rgb_and_aspect_ratio(monkeypatch, real_cv2):
    monkeypatch.setattr(preview, "cv2", real_cv2)
    bgr = np.zeros((200, 400, 3), dtype=np.uint8)
    bgr[:] = [10, 80, 230]
    image = preview.frame_to_image(bgr, (100, 100))
    assert image.size == (100, 50)
    assert image.getpixel((50, 25)) == (230, 80, 10)
    assert tuple(bgr[0, 0]) == (10, 80, 230)


@pytest.mark.parametrize(
    "frame",
    [
        None,
        [],
        np.zeros((0, 10, 3), dtype=np.uint8),
        np.zeros((10, 10), dtype=np.uint8),
        np.zeros((10, 10, 4), dtype=np.uint8),
        np.zeros((10, 10, 3), dtype=np.float32),
    ],
)
def test_invalid_frames_reset_image_and_indicators(component, frame):
    component.show_frame(packet(frame=np.ones((1, 1, 3), dtype=np.uint8)))
    data = preview.PreviewFrame(1, frame, (), 1.0, time.monotonic())
    component.show_frame(data)
    assert component._image is None
    assert component._last_frame_at is None
    assert component.video.configure.call_args.kwargs["text"] == "Brak poprawnego obrazu z kamery"
    assert "Nieaktywna" in component.indicators.configure.call_args.kwargs["text"]


def test_landmarks_toggle_face_loss_and_reset(component):
    data = packet(landmarks=((0.5, 0.5),) * 478)
    with patch.object(preview, "frame_to_image", wraps=preview.frame_to_image) as convert:
        component.show_frame(data)
        assert convert.call_args.args[2] == data.landmarks
        assert "Wykryto twarz" in component.indicators.configure.call_args.kwargs["text"]
        assert "24.0" in component.indicators.configure.call_args.kwargs["text"]
        component.show_landmarks.get.return_value = False
        component.show_frame(data)
        assert convert.call_args.args[2] == ()
        component.show_frame(packet())
        assert "Nie wykryto twarzy" in component.indicators.configure.call_args.kwargs["text"]
    component.reset()
    assert component._image is None
    assert component._last_frame_at is None
    assert "Wstrzymane" in component.indicators.configure.call_args.kwargs["text"]
    assert "FPS: 0.0" in component.indicators.configure.call_args.kwargs["text"]


def test_overlay_draws_on_copy_without_modifying_camera_frame(monkeypatch, real_cv2):
    monkeypatch.setattr(preview, "cv2", real_cv2)
    bgr = np.zeros((90, 160, 3), dtype=np.uint8)
    image = preview.frame_to_image(bgr, (160, 90), ((0.5, 0.5),) * 478)
    assert image.getbbox() is not None
    assert not bgr.any()


def test_latest_frame_buffer_discards_old_images():
    buffer = preview.LatestFrameBuffer()
    first = packet()
    reference = weakref.ref(first.bgr)
    buffer.publish(first)
    del first
    for index in range(100):
        buffer.publish(packet(session=index))
    assert reference() is None
    assert buffer.take().session_id == 99
    assert buffer.take() is None
    buffer.publish(packet())
    buffer.clear()
    assert buffer.take() is None


def test_preview_expires_when_driver_stops_producing_frames(component):
    component.show_frame(packet(captured_at=10.0))
    component.expire(now=10.5)
    assert component._image is not None
    component.expire(now=11.1)
    assert component._image is None
    assert component.video.configure.call_args.kwargs["text"] == "Brak nowych klatek z kamery"


def test_preview_adapts_to_small_window(component):
    component._on_resize(SimpleNamespace(width=320))
    assert component._image_size == (296, 166)
    component.show_frame(packet())
    assert component._image is not None
    component._get_widget_scaling.return_value = 1.25
    component._on_resize(SimpleNamespace(width=400))
    assert component._image_size == (296, 166)


def test_worker_reuses_capture_and_tracking_continues_with_unread_preview(app, real_cv2):
    app._session_id = 1
    app._stop_event.clear()
    camera = MagicMock()
    bgr = np.zeros((720, 1280, 3), dtype=np.uint8)
    camera.read.return_value = (True, bgr)
    app.tracker.get_preview_landmarks.return_value = ((0.5, 0.5),) * 478
    times = iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5])

    def process(*args, **kwargs):
        if app.tracker.process_frame.call_count == 5:
            app._stop_event.set()

    app.tracker.process_frame.side_effect = process
    with (
        patch.object(main.cv2, "VideoCapture", return_value=camera) as capture,
        patch.object(main.cv2, "flip", side_effect=real_cv2.flip),
        patch.object(main.cv2, "resize", side_effect=real_cv2.resize),
        patch.object(main.time, "monotonic", side_effect=lambda: next(times)),
    ):
        app._worker_loop(1, app._stop_event)
    capture.assert_called_once_with(0, main.cv2.CAP_DSHOW)
    assert app.tracker.process_frame.call_count == 5
    data = app._preview_frames.take()
    assert data is not None and data.bgr.shape == (360, 640, 3)
    assert data.landmarks == ((0.5, 0.5),) * 478
    assert app._preview_frames.take() is None
    app.preview.show_frame.assert_not_called()
    app.after.assert_not_called()
    camera.release.assert_called_once()


def test_sampling_is_capped_without_throttling_tracking(app):
    app._stop_event.clear()
    camera = MagicMock()
    camera.read.return_value = (True, object())
    ticks = iter([0.0, 1.0, 1.01, 1.02, 1.03])

    def process(*args, **kwargs):
        if app.tracker.process_frame.call_count == 4:
            app._stop_event.set()

    app.tracker.process_frame.side_effect = process
    with (
        patch.object(main.cv2, "VideoCapture", return_value=camera),
        patch.object(main.time, "monotonic", side_effect=lambda: next(ticks)),
        patch.object(app, "_publish_preview") as publish,
    ):
        app._worker_loop(0, app._stop_event)
    assert app.tracker.process_frame.call_count == 4
    publish.assert_called_once()
    assert publish.call_args.args[2] == 1.0


def test_preview_preparation_failure_does_not_stop_gestures(app):
    app._stop_event.clear()
    camera = MagicMock()
    camera.read.return_value = (True, object())

    def process(*args, **kwargs):
        if app.tracker.process_frame.call_count == 3:
            app._stop_event.set()

    app.tracker.process_frame.side_effect = process
    with (
        patch.object(main.cv2, "VideoCapture", return_value=camera),
        patch.object(app, "_publish_preview", side_effect=ValueError("preview failed")),
    ):
        app._worker_loop(0, app._stop_event)
    assert app.tracker.process_frame.call_count == 3
    assert all(event[1] != "error" for event in list(app._worker_events.queue))


@pytest.mark.parametrize("state", ["stop", "error", "stale", "expired", "shutdown"])
def test_poll_discards_stale_frames_and_resets_on_stop_or_error(app, state):
    app._session_id = 2
    app._stop_event.clear()
    app._tracking_state = "running"
    data = packet(
        session=1 if state == "stale" else 2,
        captured_at=time.monotonic() - (2 if state == "expired" else 0),
    )
    app._preview_frames.publish(data)
    if state == "stop":
        app._request_stop()
    elif state == "error":
        app._stop_event.set()
        app._worker_events.put((2, "error", "Nie można otworzyć kamery"))
    elif state == "shutdown":
        app.close()
    app._poll_worker_events()
    app.preview.show_frame.assert_not_called()
    assert app._preview_frames.take() is None
    if state in ("stop", "error", "shutdown"):
        app.preview.reset.assert_called()


def test_gui_poll_renders_newest_frame_on_gui_thread(app):
    gui_thread = threading.get_ident()
    app._session_id = 1
    app._stop_event.clear()
    app._tracking_state = "running"

    def render(data):
        assert threading.get_ident() == gui_thread

    app.preview.show_frame.side_effect = render
    data = packet()
    app._preview_frames.publish(data)
    app._poll_worker_events()
    app.preview.show_frame.assert_called_once_with(data)


def test_gui_preview_failure_preserves_event_loop_and_tracking(app):
    app._session_id = 1
    app._stop_event.clear()
    app._tracking_state = "running"
    app.preview.show_frame.side_effect = RuntimeError("Tk image failure")
    app._preview_frames.publish(packet())
    app._poll_worker_events()
    assert not app._stop_event.is_set()
    app.after.assert_called_once()
    app.preview.reset.assert_called_once()
