from unittest.mock import MagicMock, patch

import pytest

import main


def test_close_handler_registered(app):
    app.protocol.assert_called_once_with("WM_DELETE_WINDOW", app.close)


def test_start_stop_and_no_overlapping_camera_workers(app):
    with patch.object(main.threading, "Thread") as thread:
        app.toggle_system()
        assert app.is_running
        thread.return_value.start.assert_called_once()
        app.toggle_system()
        assert not app.is_running
        thread.return_value.is_alive.return_value = True
        app.toggle_system()
        assert thread.call_count == 1
        thread.return_value.is_alive.return_value = False
        app.toggle_system()
        assert thread.call_count == 2


@pytest.mark.parametrize("failure", [None, "open", "read", "process", "construct"])
def test_camera_lifecycle(app, failure):
    camera = MagicMock()
    camera.isOpened.return_value = failure != "open"
    camera.read.return_value = (failure != "read", object())
    app.is_running = True

    def process(*args, **kwargs):
        app.is_running = False
        if failure == "process":
            raise RuntimeError("tracker failed")

    app.tracker.process_frame.side_effect = process
    with patch.object(main.cv2, "VideoCapture", return_value=camera) as capture:
        if failure == "construct":
            capture.side_effect = RuntimeError("camera unavailable")
        app._worker_loop()
    assert not app.is_running
    assert app.cap is None
    assert camera.release.call_count == (
        0 if failure == "construct" else 2 if failure == "open" else 1
    )
    app.after.assert_called_once_with(0, app._camera_stopped)
    if failure is None:
        kwargs = app.tracker.process_frame.call_args.kwargs
        assert kwargs["on_assistant_trigger"] == app.trigger_assistant
        assert kwargs["on_shutdown_trigger"] == app.pause_tracking_from_gesture


def test_camera_fallback_releases_first_capture(app):
    first, fallback = MagicMock(), MagicMock()
    first.isOpened.return_value = False
    fallback.read.return_value = (False, None)
    app.is_running = True
    with patch.object(main.cv2, "VideoCapture", side_effect=[first, fallback]) as capture:
        app._worker_loop()
    assert capture.call_args_list[0].args == (0, main.cv2.CAP_DSHOW)
    assert capture.call_args_list[1].args == (0,)
    first.release.assert_called_once()
    fallback.release.assert_called_once()


def test_sensitivity_configuration(app):
    app.change_sensitivity("2.5")
    assert app.tracker.sensitivity == 2.5


def test_stale_camera_completion_does_not_stop_new_worker(app):
    app.is_running = True
    app._camera_stopped()
    assert app.is_running
    app.btn_toggle.configure.assert_not_called()
    app.is_running = False
    app._camera_stopped()
    app.btn_toggle.configure.assert_called_once()


def test_camera_read_exception_releases_capture(app):
    camera = MagicMock()
    camera.read.side_effect = OSError("disconnected")
    app.is_running = True
    with patch.object(main.cv2, "VideoCapture", return_value=camera):
        app._worker_loop()
    camera.release.assert_called_once()
    assert app.cap is None and not app.is_running


def test_destroy_runs_even_if_face_mesh_cleanup_fails(app):
    app.tracker.face_mesh.close.side_effect = RuntimeError("cleanup failed")
    with pytest.raises(RuntimeError):
        app.close()
    app.destroy.assert_called_once()


def test_voice_activation_excludes_overlap_and_recovers_after_error(app):
    with patch.object(main.threading, "Thread") as thread:
        app.trigger_assistant()
        app.trigger_assistant()
        assert thread.call_count == 1
        assert thread.call_args.kwargs["target"] == app._run_assistant
        app.assistant.listen_and_execute.side_effect = RuntimeError("microphone error")
        with patch.object(main.winsound, "Beep", side_effect=OSError):
            app._run_assistant()
        app.assistant.listen_and_execute.assert_called_once()
        app.trigger_assistant()
        assert thread.call_count == 2


def test_thread_start_failure_restores_state(app):
    with patch.object(main.threading, "Thread") as thread:
        thread.return_value.start.side_effect = RuntimeError("cannot start")
        with pytest.raises(RuntimeError):
            app.toggle_system()
        assert not app.is_running
        with pytest.raises(RuntimeError):
            app.trigger_assistant()
        assert app._assistant_lock.acquire(blocking=False)
        app._assistant_lock.release()


def test_pause_schedules_gui_update_even_if_audio_fails(app):
    with patch.object(main.winsound, "Beep", side_effect=OSError):
        app.pause_tracking_from_gesture()
    app.after.assert_called_once_with(0, app._set_stopped_state)


def test_shutdown_waits_for_workers_before_disposing_resources(app):
    app.camera_thread, app.assistant_thread = MagicMock(), MagicMock()
    app.camera_thread.is_alive.return_value = True
    app.assistant_thread.is_alive.return_value = True
    app.close()
    assert app._closing and not app.is_running
    app.destroy.assert_not_called()
    app.tracker.face_mesh.close.assert_not_called()
    app.camera_thread.is_alive.return_value = False
    app._finish_close()
    app.destroy.assert_not_called()
    app.assistant_thread.is_alive.return_value = False
    app._finish_close()
    app.tracker.face_mesh.close.assert_called_once()
    app.destroy.assert_called_once()
    with patch.object(main.threading, "Thread") as thread:
        app.toggle_system()
        app.trigger_assistant()
        thread.assert_not_called()
