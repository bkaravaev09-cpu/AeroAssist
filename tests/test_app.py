import threading
from unittest.mock import MagicMock, patch

import pytest

import main


def prepare_session(app):
    app._session_id += 1
    app._stop_event = threading.Event()
    app._tracking_state = "starting"
    app.camera_thread = MagicMock()
    app.camera_thread.is_alive.return_value = False
    return app._session_id, app._stop_event


def test_close_handler_registered(app):
    app.protocol.assert_called_once_with("WM_DELETE_WINDOW", app.close)


def test_start_stop_and_rapid_clicks_wait_for_completion(app):
    with patch.object(main.threading, "Thread") as thread:
        app.toggle_system()
        assert app._tracking_state == "starting"
        assert not app._stop_event.is_set()
        thread.return_value.start.assert_called_once()
        app.toggle_system()
        assert app._stop_event.is_set()
        for _ in range(20):
            app.toggle_system()
        assert thread.call_count == 1
        app._worker_events.put((app._session_id, "stopped", None))
        thread.return_value.is_alive.return_value = True
        app._poll_worker_events()
        app.toggle_system()
        assert thread.call_count == 1
        thread.return_value.is_alive.return_value = False
        app._poll_worker_events()
        assert app._tracking_state == "stopped"
        app.toggle_system()
        assert thread.call_count == 2


@pytest.mark.parametrize("failure", [None, "open", "read", "process", "construct", "exception"])
def test_camera_lifecycle(app, failure, caplog):
    session, stop = prepare_session(app)
    camera = MagicMock()
    camera.isOpened.return_value = failure != "open"
    camera.read.return_value = (failure != "read", object())
    if failure == "exception":
        camera.read.side_effect = OSError("unplugged")

    def process(*args, **kwargs):
        if failure == "process":
            raise RuntimeError("tracker failed")
        stop.set()

    app.tracker.process_frame.side_effect = process
    with patch.object(main.cv2, "VideoCapture", return_value=camera) as capture:
        if failure == "construct":
            capture.side_effect = RuntimeError("camera unavailable")
        app._worker_loop(session, stop)
    assert stop.is_set()
    assert app.tracker.reset_cursor.call_count == 2
    assert camera.release.call_count == (
        0 if failure == "construct" else 2 if failure == "open" else 1
    )
    if failure == "read":
        assert camera.read.call_count == 3
    app.after.assert_not_called()
    app.btn_toggle.configure.assert_not_called()
    app.label_status.configure.assert_not_called()
    app._poll_worker_events()
    assert app.camera_thread is None
    assert app._tracking_state == "stopped"
    if failure:
        assert app._tracking_error
        assert app.label_status.configure.call_args.kwargs["text"] == app._tracking_error
        assert "Camera session" in caplog.text
    else:
        assert app._tracking_error is None
        kwargs = app.tracker.process_frame.call_args.kwargs
        assert kwargs["on_assistant_trigger"] == app.trigger_assistant
        assert kwargs["on_shutdown_trigger"] == app.pause_tracking_from_gesture


@pytest.mark.parametrize("initial_failure", ["closed", "constructor", "probe"])
def test_directshow_fallback_releases_failed_capture(app, initial_failure):
    session, stop = prepare_session(app)
    first, fallback = MagicMock(), MagicMock()
    first.isOpened.return_value = False
    if initial_failure == "probe":
        first.isOpened.side_effect = OSError("probe failed")
    fallback.read.return_value = (False, None)
    values = [
        OSError("backend unavailable") if initial_failure == "constructor" else first,
        fallback,
    ]
    with patch.object(main.cv2, "VideoCapture", side_effect=values) as capture:
        app._worker_loop(session, stop)
    assert capture.call_args_list[0].args == (0, main.cv2.CAP_DSHOW)
    assert capture.call_args_list[1].args == (0,)
    assert first.release.call_count == (0 if initial_failure == "constructor" else 1)
    fallback.release.assert_called_once()


def test_transient_frame_failures_recover_and_reset_counter(app):
    session, stop = prepare_session(app)
    camera = MagicMock()
    camera.read.side_effect = [
        (False, None),
        (False, None),
        (True, object()),
        (False, None),
        (False, None),
        (True, object()),
    ]
    calls = []

    def process(*args, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            stop.set()

    app.tracker.process_frame.side_effect = process
    with patch.object(main.cv2, "VideoCapture", return_value=camera):
        app._worker_loop(session, stop)
    assert len(calls) == 2
    app._poll_worker_events()
    assert app._tracking_error is None


def test_stop_before_initialization_does_not_open_camera(app):
    session, stop = prepare_session(app)
    stop.set()
    with patch.object(main.cv2, "VideoCapture") as capture:
        app._worker_loop(session, stop)
    capture.assert_not_called()


def test_stop_during_initialization_releases_without_processing(app):
    session, stop = prepare_session(app)
    camera = MagicMock()

    def opened():
        stop.set()
        return True

    camera.isOpened.side_effect = opened
    with patch.object(main.cv2, "VideoCapture", return_value=camera):
        app._worker_loop(session, stop)
    camera.release.assert_called_once()
    camera.read.assert_not_called()
    app.tracker.process_frame.assert_not_called()


def test_release_error_still_signals_completion(app, caplog):
    session, stop = prepare_session(app)
    camera = MagicMock()
    camera.read.side_effect = OSError("unplugged")
    camera.release.side_effect = OSError("driver error")
    with patch.object(main.cv2, "VideoCapture", return_value=camera):
        app._worker_loop(session, stop)
    app._poll_worker_events()
    assert app.camera_thread is None
    assert "Camera release failed" in caplog.text


def test_sensitivity_configuration(app):
    app.change_sensitivity("2.5")
    assert app.tracker.sensitivity == 2.5


def test_cursor_controls_configure_independently_and_restore_defaults(app):
    from core.cursor_controller import DEFAULT_CURSOR_SETTINGS

    app.change_smoothing("0.85")
    app.tracker.configure_cursor.assert_called_with(smoothing=0.85)
    app.change_dead_zone("4")
    app.tracker.configure_cursor.assert_called_with(dead_zone=4.0)
    app.reset_cursor_settings()
    defaults = DEFAULT_CURSOR_SETTINGS
    app.tracker.configure_cursor.assert_called_with(
        sensitivity=defaults.sensitivity,
        smoothing=defaults.smoothing,
        dead_zone=defaults.dead_zone,
    )
    app.slider_sens.set.assert_called_once_with(defaults.sensitivity)
    app.slider_smoothing.set.assert_called_once_with(defaults.smoothing)
    app.slider_dead_zone.set.assert_called_once_with(defaults.dead_zone)


def test_stale_session_events_do_not_change_current_state(app):
    session, _ = prepare_session(app)
    for kind in ("started", "paused", "error", "stopped", "assistant"):
        app._worker_events.put((session - 1, kind, "old error"))
    app._poll_worker_events()
    assert app._tracking_state == "starting"
    assert app.camera_thread is not None
    app.label_status.configure.assert_not_called()


def test_voice_callback_is_queued_and_sessions_do_not_overlap(app):
    prepare_session(app)
    with patch.object(main.threading, "Thread") as thread:
        app.trigger_assistant()
        app.trigger_assistant()
        thread.assert_not_called()
        app._poll_worker_events()
        assert thread.call_count == 1
        assert thread.call_args.kwargs["target"] == app._run_assistant
        app.assistant.listen_and_execute.side_effect = RuntimeError("microphone error")
        with patch.object(main.winsound, "Beep", side_effect=OSError):
            app._run_assistant()
        app.assistant.listen_and_execute.assert_called_once()
        app.trigger_assistant()
        app._poll_worker_events()
        assert thread.call_count == 2


def test_thread_start_failure_restores_state_and_reports_polish_error(app):
    with patch.object(main.threading, "Thread") as thread:
        thread.return_value.start.side_effect = RuntimeError("cannot start")
        app.toggle_system()
        assert app._tracking_state == "stopped"
        assert app._stop_event.is_set()
        assert app.camera_thread is None
        assert "Nie można" in app._tracking_error
        app._start_assistant()
        assert app._assistant_lock.acquire(blocking=False)
        app._assistant_lock.release()


def test_gesture_pause_stops_immediately_and_gui_poll_allows_restart(app):
    session, stop = prepare_session(app)
    with patch.object(main.winsound, "Beep", side_effect=OSError):
        app.pause_tracking_from_gesture()
    assert stop.is_set()
    app.after.assert_not_called()
    app.label_status.configure.assert_not_called()
    app._worker_events.put((session, "stopped", None))
    app._poll_worker_events()
    assert app._tracking_state == "stopped"
    with patch.object(main.threading, "Thread") as thread:
        app.toggle_system()
    thread.return_value.start.assert_called_once()
    assert not app._stop_event.is_set()


def test_shutdown_waits_for_both_workers_and_ignores_queued_voice(app):
    session, stop = prepare_session(app)
    app.camera_thread.is_alive.return_value = True
    app.assistant_thread = MagicMock()
    app.assistant_thread.is_alive.return_value = True
    app._worker_events.put((session, "assistant", None))
    app.close()
    assert app._closing and stop.is_set()
    app.destroy.assert_not_called()
    app.tracker.face_mesh.close.assert_not_called()
    with patch.object(main.threading, "Thread") as thread:
        app.toggle_system()
        app._poll_worker_events()
        thread.assert_not_called()
    app.camera_thread.is_alive.return_value = False
    app._poll_worker_events()
    app.destroy.assert_not_called()
    app.assistant_thread.is_alive.return_value = False
    app._poll_worker_events()
    app.tracker.face_mesh.close.assert_called_once()
    app.destroy.assert_called_once()
    app.close()
    app._poll_worker_events()
    app.destroy.assert_called_once()


def test_destroy_runs_even_if_face_mesh_cleanup_fails(app):
    app.tracker.face_mesh.close.side_effect = RuntimeError("cleanup failed")
    app.close()
    app.destroy.assert_called_once()


@pytest.mark.parametrize("shutdown", [False, True])
def test_real_worker_cannot_restart_while_camera_release_is_blocked(app, shutdown):
    """Reproduce the original stop/restart race with real threads and Events."""
    entered_read, allow_read, entered_release, allow_release = (threading.Event() for _ in range(4))
    gui_thread = threading.get_ident()
    camera = MagicMock()

    def read():
        assert threading.get_ident() != gui_thread
        entered_read.set()
        assert allow_read.wait(3)
        return True, object()

    def release():
        assert threading.get_ident() != gui_thread
        entered_release.set()
        assert allow_release.wait(3)

    def configure(**kwargs):
        assert threading.get_ident() == gui_thread

    def schedule(*args):
        assert threading.get_ident() == gui_thread

    camera.read.side_effect = read
    camera.release.side_effect = release
    app.btn_toggle.configure.side_effect = configure
    app.label_status.configure.side_effect = configure
    app.after.side_effect = schedule
    with patch.object(main.cv2, "VideoCapture", return_value=camera) as capture:
        try:
            app.toggle_system()
            worker = app.camera_thread
            assert entered_read.wait(3)
            app.toggle_system()
            allow_read.set()
            assert entered_release.wait(3)
            if shutdown:
                app.close()
            for _ in range(20):
                app.toggle_system()
                app._poll_worker_events()
            assert capture.call_count == 1
            assert app.camera_thread is worker
            app.destroy.assert_not_called()
            app.tracker.face_mesh.close.assert_not_called()
        finally:
            app._stop_event.set()
            allow_read.set()
            allow_release.set()
            app.camera_thread.join(3)
        assert not worker.is_alive()
        app._poll_worker_events()
        assert app.camera_thread is None
        camera.release.assert_called_once()
        app.tracker.process_frame.assert_not_called()
        if shutdown:
            app.tracker.face_mesh.close.assert_called_once()
            app.destroy.assert_called_once()


def test_started_event_updates_status_only_when_polled(app):
    session, _ = prepare_session(app)
    app.camera_thread.is_alive.return_value = True
    app._worker_events.put((session, "started", None))
    app.label_status.configure.assert_not_called()
    app._poll_worker_events()
    assert app._tracking_state == "running"
    assert app.label_status.configure.call_args.kwargs["text"] == (
        "Status: Aktywny (Śledzenie twarzy)"
    )


def test_stop_cancels_failed_initialization_without_opening_fallback(app):
    session, stop = prepare_session(app)
    camera = MagicMock()

    def opened():
        stop.set()
        return False

    camera.isOpened.side_effect = opened
    with patch.object(main.cv2, "VideoCapture", return_value=camera) as capture:
        app._worker_loop(session, stop)
    capture.assert_called_once()
    camera.release.assert_called_once()
    app._poll_worker_events()
    assert app._tracking_error is None
