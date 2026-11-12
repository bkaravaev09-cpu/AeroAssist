import logging
import queue
import threading
import time
import winsound
from dataclasses import replace

import customtkinter as ctk
import cv2

from core.calibration import CalibrationManager, HeadSample
from core.calibration_wizard import CalibrationWizard
from core.cursor_controller import DEFAULT_CURSOR_SETTINGS
from core.cursor_profile import CursorProfileStore
from core.on_screen_keyboard import OnScreenKeyboard
from core.vision_tracker import VisionTracker
from core.voice_assistant import PolishVoiceAssistant
from ui.calibration_window import CalibrationWindow
from ui.camera_preview import CameraPreview, LatestFrameBuffer, PreviewFrame

logger = logging.getLogger(__name__)


class AeroAssistApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AeroAssist - Sterowanie komputerem")
        available_height = int(self.winfo_screenheight() / self._get_window_scaling()) - 80
        self.geometry(f"580x{max(480, min(780, available_height))}")
        self.minsize(360, 480)
        self.resizable(True, True)
        ctk.set_appearance_mode("dark")

        self.keyboard_window = None
        self.tracker = VisionTracker()
        self.assistant = PolishVoiceAssistant()
        self.assistant.set_keyboard_callback(self._keyboard_action_from_voice)
        self.calibration_manager = CalibrationManager()
        self.tracker.apply_calibration(self.calibration_manager.load())
        self.calibration_window = None
        self.stability_window = None
        self.cursor_profile_store = CursorProfileStore()
        self._apply_cursor_profile(self.cursor_profile_store.load())
        self._calibration_open = threading.Event()
        self._calibration_samples = LatestFrameBuffer()

        self._stop_event = threading.Event()
        self._stop_event.set()
        self._worker_events = queue.Queue()
        self._preview_frames = LatestFrameBuffer()
        self._session_id = 0
        self._tracking_state = "stopped"
        self._tracking_error = None
        self._worker_finished = False
        self.camera_thread = None
        self.assistant_thread = None
        self._closing = False
        self._closed = False
        self._assistant_lock = threading.Lock()
        self.protocol("WM_DELETE_WINDOW", self.close)

        self._build_ui()
        self.after(50, self._poll_worker_events)

    def _build_ui(self):
        content = ctk.CTkScrollableFrame(self)
        content.pack(fill="both", expand=True)
        self.label_title = ctk.CTkLabel(
            content, text="AeroAssist System", font=("Arial", 22, "bold")
        )
        self.label_title.pack(pady=12)
        self.preview = CameraPreview(content)
        self.preview.pack(padx=12, pady=(0, 8), fill="x")

        self.btn_toggle = ctk.CTkButton(
            content,
            text="Uruchom sterowanie",
            command=self.toggle_system,
            height=45,
            font=("Arial", 14, "bold"),
        )
        self.btn_toggle.pack(pady=10, padx=40, fill="x")

        self.btn_keyboard = ctk.CTkButton(
            content,
            text="Klawiatura ekranowa",
            command=self.toggle_keyboard_ui,
            height=38,
            fg_color="#2e4053",
            hover_color="#34495e",
            font=("Arial", 13, "bold"),
        )
        self.btn_keyboard.pack(pady=5, padx=40, fill="x")

        self.label_status = ctk.CTkLabel(
            content,
            text="Status: Zatrzymany",
            text_color="gray",
            font=("Arial", 13),
            wraplength=300,
        )
        self.label_status.pack(pady=5)

        self.label_sens = ctk.CTkLabel(content, text="Czułość kursora")
        self.label_sens.pack(pady=(15, 0))

        self.slider_sens = ctk.CTkSlider(
            content, from_=1.0, to=3.0, command=self.change_sensitivity
        )
        settings = self.tracker.cursor_controller.settings
        self.slider_sens.set(settings.sensitivity)
        self.slider_sens.pack(pady=8, padx=40, fill="x")

        ctk.CTkLabel(content, text="Wygładzanie ruchu (więcej = płynniej)").pack(pady=(8, 0))
        self.slider_smoothing = ctk.CTkSlider(
            content, from_=0.0, to=0.95, command=self.change_smoothing
        )
        self.slider_smoothing.set(settings.smoothing)
        self.slider_smoothing.pack(pady=8, padx=40, fill="x")
        ctk.CTkLabel(content, text="Strefa martwa (0–10 pikseli)").pack(pady=(8, 0))
        self.slider_dead_zone = ctk.CTkSlider(
            content, from_=0.0, to=10.0, command=self.change_dead_zone
        )
        self.slider_dead_zone.set(settings.dead_zone)
        self.slider_dead_zone.pack(pady=8, padx=40, fill="x")
        ctk.CTkButton(
            content, text="Przywróć ustawienia domyślne", command=self.reset_cursor_settings
        ).pack(pady=8, padx=40, fill="x")

        self.info_box = ctk.CTkTextbox(content, height=140, wrap="word")
        self.info_box.pack(pady=15, padx=30, fill="x")
        self.info_box.insert(
            "0.0",
            "Instrukcja obsługi:\n"
            "• Ruch głowy — płynne przesuwanie kursora\n"
            "• Pochylenie głowy — autoprzesuwanie do krawędzi\n"
            "• Mrugnięcie lewym okiem — lewy klik\n"
            "• Zamknięcie oczu (> 1.5s) — asystent głosowy\n"
            "• 4 szybkie mrugnięcia — zatrzymanie / pauza śledzenia",
        )
        self.info_box.configure(state="disabled")

        ctk.CTkLabel(content, text="Kalibracja kursora", font=("Arial", 16, "bold")).pack(
            pady=(12, 4)
        )
        self.label_calibration = ctk.CTkLabel(
            content,
            text=("Kalibracja aktywna" if self.calibration_manager.active else "Nie skalibrowano"),
        )
        self.label_calibration.pack(pady=4)
        ctk.CTkButton(content, text="Rozpocznij kalibrację", command=self.open_calibration).pack(
            pady=4
        )
        ctk.CTkButton(content, text="Powtórz kalibrację", command=self.open_calibration).pack(
            pady=4
        )
        ctk.CTkButton(
            content,
            text="Test stabilności (wygładzanie)",
            command=self.open_stability_test,
            fg_color="#27ae60",
            hover_color="#2ecc71",
        ).pack(pady=4)
        ctk.CTkButton(
            content, text="Przywróć domyślne", command=self.restore_default_calibration
        ).pack(pady=(4, 16))

    def toggle_keyboard_ui(self):
        if (
            self.keyboard_window is None
            or not hasattr(self.keyboard_window, "winfo_exists")
            or not self.keyboard_window.winfo_exists()
        ):
            self.keyboard_window = OnScreenKeyboard(self)
        else:
            try:
                self.keyboard_window.destroy()
            except Exception:
                pass
            self.keyboard_window = None

    def _lift_open_calibration_window(self):
        for window in (self.calibration_window, self.stability_window):
            if window is not None:
                window.lift()
                return True
        return False

    def open_calibration(self):
        if self._closing or self._lift_open_calibration_window():
            return
        self._calibration_open.set()
        self.calibration_window = CalibrationWindow(
            self,
            self.calibration_manager,
            on_begin=self._begin_calibration,
            on_preview=self._preview_calibration,
            on_save=self._save_calibration,
            on_cancel=self._cancel_calibration,
            on_reset=self._restore_calibration,
            on_collect=self.tracker.set_calibration_collecting,
        )

    def _begin_calibration(self):
        if self._closing or self._tracking_state == "stopping":
            return False
        self.tracker.apply_calibration(self.calibration_manager.active)
        self.tracker.set_calibration_collecting(False)
        self._calibration_samples.clear()
        if self._tracking_state == "stopped":
            self.toggle_system()
        return self._tracking_state in ("starting", "running")

    def _preview_calibration(self, parameters):
        self.tracker.apply_calibration(parameters)
        self.tracker.set_calibration_collecting(False)
        self.label_calibration.configure(
            text=("Kalibracja aktywna — podgląd" if parameters else "Nie skalibrowano")
        )

    def _end_calibration(self):
        self.calibration_manager.begin()
        self._calibration_open.clear()
        self._calibration_samples.clear()
        self.tracker.set_calibration_collecting(False)
        self.tracker.apply_calibration(self.calibration_manager.active)
        self.calibration_window = None
        self.label_calibration.configure(
            text=("Kalibracja aktywna" if self.calibration_manager.active else "Nie skalibrowano")
        )

    def _cancel_calibration(self):
        self._end_calibration()

    def _save_calibration(self, parameters):
        self.calibration_manager.save(parameters)
        self._drop_profile_sensitivity()
        self._end_calibration()
        self.label_calibration.configure(text="Kalibracja zakończona — aktywna")

    def _restore_calibration(self):
        try:
            self.calibration_manager.restore_defaults()
        except OSError:
            logger.exception("Unable to remove saved calibration")
            self.label_calibration.configure(text="Nie można przywrócić domyślnej kalibracji.")
            return False
        self._end_calibration()
        return True

    def restore_default_calibration(self):
        if self.calibration_window is not None:
            self.calibration_window.cancel()
        if self.stability_window is not None:
            self.stability_window.cancel()
        self.reset_cursor_settings()
        return self._restore_calibration()

    # --- Stability test (cursor smoothing / dead zone) ---
    def _apply_cursor_profile(self, profile):
        if profile is None:
            return
        changes = profile.cursor_changes()
        if self.calibration_manager.active is not None:
            # A five-point mapping already spans the screen; extra gain would overshoot.
            changes.pop("sensitivity", None)
        try:
            self.tracker.configure_cursor(**changes)
        except ValueError:
            logger.warning("Ignoring invalid cursor profile", exc_info=True)

    def _sync_cursor_sliders(self):
        settings = self.tracker.cursor_controller.settings
        self.slider_sens.set(settings.sensitivity)
        self.slider_smoothing.set(settings.smoothing)
        self.slider_dead_zone.set(settings.dead_zone)

    def _drop_profile_sensitivity(self):
        """Sensitivity tuned for uncalibrated mode must not scale a five-point mapping."""
        profile = self.cursor_profile_store.load()
        if profile is None or profile.sensitivity is None:
            return
        try:
            self.cursor_profile_store.save(replace(profile, sensitivity=None))
        except OSError:
            logger.exception("Unable to update cursor profile")
        self.tracker.configure_cursor(sensitivity=DEFAULT_CURSOR_SETTINGS.sensitivity)
        self.slider_sens.set(DEFAULT_CURSOR_SETTINGS.sensitivity)

    def open_stability_test(self):
        if self._closing or self._lift_open_calibration_window():
            return
        self._calibration_open.set()
        self._calibration_samples.clear()
        self.stability_window = CalibrationWizard(
            self,
            calibrated=self.calibration_manager.active is not None,
            on_begin=self._begin_stability_test,
            on_finish=self._finish_stability_test,
            on_close=self._end_stability_test,
        )

    def _begin_stability_test(self):
        if self._closing or self._tracking_state == "stopping":
            return False
        # Freeze cursor movement while measuring; eye gestures stay active.
        self.tracker.set_calibration_collecting(True)
        if self._tracking_state == "stopped":
            self.toggle_system()
        return self._tracking_state in ("starting", "running")

    def _finish_stability_test(self, profile, center):
        self._apply_cursor_profile(profile)
        if center is not None:
            self.tracker.center_x, self.tracker.center_y = center
        saved = ""
        try:
            self.cursor_profile_store.save(profile)
        except OSError:
            logger.exception("Unable to save cursor profile")
            saved = " (nie zapisano na dysku)"
        self._sync_cursor_sliders()
        settings = self.tracker.cursor_controller.settings
        self.label_status.configure(
            text=(
                f"Test zakończony{saved}. Czułość: {settings.sensitivity:.2f}, "
                f"wygładzanie: {settings.smoothing:.2f}, strefa martwa: {settings.dead_zone:.1f}px"
            ),
            text_color="green",
        )

    def _end_stability_test(self):
        self.stability_window = None
        self._calibration_open.clear()
        self._calibration_samples.clear()
        self.tracker.set_calibration_collecting(False)

    def change_sensitivity(self, val):
        self.tracker.sensitivity = float(val)

    def change_smoothing(self, val):
        self.tracker.configure_cursor(smoothing=float(val))

    def change_dead_zone(self, val):
        self.tracker.configure_cursor(dead_zone=float(val))

    def reset_cursor_settings(self):
        defaults = DEFAULT_CURSOR_SETTINGS
        self.tracker.configure_cursor(
            sensitivity=defaults.sensitivity,
            smoothing=defaults.smoothing,
            dead_zone=defaults.dead_zone,
        )
        self.slider_sens.set(defaults.sensitivity)
        self.slider_smoothing.set(defaults.smoothing)
        self.slider_dead_zone.set(defaults.dead_zone)
        try:
            self.cursor_profile_store.clear()
        except OSError:
            logger.exception("Unable to remove cursor profile")

    def trigger_assistant(self):
        """Called by the camera worker; never call Tk from this boundary."""
        self._worker_events.put((self._session_id, "assistant", None))

    def _start_assistant(self):
        if self._closing or not self._assistant_lock.acquire(blocking=False):
            return
        try:
            self.assistant_thread = threading.Thread(target=self._run_assistant, daemon=True)
            self.assistant_thread.start()
        except Exception:
            self._assistant_lock.release()
            logger.exception("Unable to start voice assistant worker")
            self.label_status.configure(
                text="Nie można uruchomić asystenta głosowego.", text_color="orange"
            )

    def _run_assistant(self):
        try:
            try:
                winsound.Beep(1200, 200)
            except Exception:
                logger.debug("Voice notification sound unavailable", exc_info=True)
            self.assistant.listen_and_execute()
        except Exception:
            logger.exception("Voice assistant failed")
            self._worker_events.put((self._session_id, "voice_error", None))
        finally:
            self._assistant_lock.release()

    def pause_tracking_from_gesture(self):
        """Stop immediately; queue the visual update for the GUI thread."""
        self._stop_event.set()
        self._worker_events.put((self._session_id, "paused", None))
        try:
            winsound.Beep(700, 250)
        except Exception:
            logger.debug("Pause notification sound unavailable", exc_info=True)

    def _set_stopped_state(self):
        self._preview_frames.clear()
        self.preview.reset(self._tracking_error or "Kamera nieaktywna")
        self._tracking_state = "stopped"
        self.btn_toggle.configure(
            text="Uruchom sterowanie",
            state="normal",
            fg_color=["#3a7ebf", "#1f538d"],
            hover_color=["#325882", "#14375e"],
        )
        self.label_status.configure(
            text=self._tracking_error or "Status: Zatrzymany (Pauza)",
            text_color="orange",
        )

    def _request_stop(self):
        self._stop_event.set()
        self._preview_frames.clear()
        self.preview.reset()
        self._tracking_state = "stopping"
        self.btn_toggle.configure(text="Zatrzymywanie…", state="disabled")
        self.label_status.configure(text="Status: Zatrzymywanie kamery…", text_color="orange")

    def toggle_system(self):
        # This method and all lifecycle state transitions run on the GUI thread.
        if self._closing:
            return
        if self._tracking_state in ("starting", "running"):
            self._request_stop()
            return
        if self._tracking_state == "stopping" or self.camera_thread is not None:
            return
        self._session_id += 1
        self._preview_frames.clear()
        self.preview.reset("Uruchamianie kamery…")
        self._stop_event = threading.Event()
        self._tracking_error = None
        self._worker_finished = False
        self._tracking_state = "starting"
        self.btn_toggle.configure(text="Zatrzymaj sterowanie", state="normal")
        self.label_status.configure(text="Status: Uruchamianie kamery…", text_color="orange")
        try:
            self.camera_thread = threading.Thread(
                target=self._worker_loop, args=(self._session_id, self._stop_event), daemon=True
            )
            self.camera_thread.start()
        except Exception:
            logger.exception("Unable to start camera worker")
            self.camera_thread = None
            self._stop_event.set()
            self._tracking_error = "Nie można uruchomić wątku kamery. Spróbuj ponownie."
            self._set_stopped_state()

    @staticmethod
    def _release_camera(cap):
        try:
            cap.release()
        except Exception:
            logger.exception("Camera release failed")

    def _open_camera(self, stop_event):
        for backend in (cv2.CAP_DSHOW, None):
            if stop_event.is_set():
                return None
            cap = None
            try:
                cap = cv2.VideoCapture(0, backend) if backend is not None else cv2.VideoCapture(0)
                if cap.isOpened():
                    return cap
                logger.warning("Camera did not open with backend %s", backend)
            except Exception:
                logger.exception("Camera initialization failed with backend %s", backend)
            if cap is not None:
                self._release_camera(cap)
        if not stop_event.is_set():
            raise RuntimeError("Camera unavailable with DirectShow and default backend")
        return None

    def _worker_loop(self, session_id, stop_event):
        # Only this worker opens, reads, processes, and releases its capture.
        cap = None
        error_message = "Nie można otworzyć kamery. Sprawdź połączenie i uprawnienia."
        try:
            self.tracker.reset_cursor()
            cap = self._open_camera(stop_event)
            if cap is None or stop_event.is_set():
                return
            self._worker_events.put((session_id, "started", None))
            failures = 0
            last_preview = 0.0
            fps_started = time.monotonic()
            frame_count = 0
            fps = 0.0
            while not stop_event.is_set():
                error_message = "Utracono połączenie z kamerą. Sprawdź kamerę i uruchom ponownie."
                ret, frame = cap.read()
                if stop_event.is_set():
                    break
                if not ret or frame is None:
                    failures += 1
                    if failures >= 3:
                        raise RuntimeError("Three consecutive camera frame read failures")
                    stop_event.wait(0.05)
                    continue
                failures = 0
                error_message = "Błąd przetwarzania obrazu. Uruchom sterowanie ponownie."
                frame = cv2.flip(frame, 1)
                self.tracker.process_frame(
                    frame,
                    on_assistant_trigger=self.trigger_assistant,
                    on_shutdown_trigger=self.pause_tracking_from_gesture,
                )
                frame_count += 1
                now = time.monotonic()
                if self._calibration_open.is_set():
                    self._calibration_samples.publish(
                        HeadSample(session_id, self.tracker.get_head_position(), now)
                    )
                elapsed = now - fps_started
                if elapsed >= 0.5:
                    fps = frame_count / elapsed
                    fps_started, frame_count = now, 0
                if not stop_event.is_set() and now - last_preview >= 1 / 15:
                    last_preview = now
                    try:
                        self._publish_preview(session_id, frame, fps, now)
                    except Exception:
                        # Preview failures must not disable gesture recognition.
                        logger.exception("Unable to prepare preview frame")
        except Exception:
            logger.exception("Camera session %s failed", session_id)
            if not stop_event.is_set():
                self._worker_events.put((session_id, "error", error_message))
        finally:
            if cap is not None:
                self._release_camera(cap)
            try:
                self.tracker.reset_cursor()
            except Exception:
                logger.exception("Unable to reset cursor after tracking")
            stop_event.set()
            self._worker_events.put((session_id, "stopped", None))

    def _publish_preview(self, session_id, frame, fps, captured_at):
        height, width = frame.shape[:2]
        scale = min(1.0, 640 / width, 360 / height)
        small = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))))
        self._preview_frames.publish(
            PreviewFrame(session_id, small, self.tracker.get_preview_landmarks(), fps, captured_at)
        )

    def _keyboard_action_from_voice(self, action, *args):
        """Safe callback from voice thread to execute keyboard actions on GUI thread."""

        def run_action():
            if action == "toggle":
                self.toggle_keyboard_ui()
            elif action == "close":
                if hasattr(self, "keyboard_window") and self.keyboard_window is not None:
                    try:
                        if self.keyboard_window.winfo_exists():
                            self.keyboard_window.destroy()
                    except Exception:
                        pass
                    self.keyboard_window = None
            elif action == "language":
                if hasattr(self, "keyboard_window") and self.keyboard_window is not None:
                    try:
                        self.keyboard_window.toggle_language()
                    except Exception:
                        pass

        self.after(0, run_action)

    def _poll_worker_events(self):
        """Tk schedules this poll; workers use Queue.put and never Tk.after."""
        if self._closed:
            return
        for _ in range(100):
            try:
                session_id, kind, message = self._worker_events.get_nowait()
            except queue.Empty:
                break
            if session_id != self._session_id:
                continue
            if kind == "stopped":
                self._worker_finished = True
            if self._closing:
                continue
            if kind == "started" and not self._stop_event.is_set():
                self._tracking_state = "running"
                self.btn_toggle.configure(fg_color="#C0392B", hover_color="#962D22")
                self.label_status.configure(
                    text="Status: Aktywny (Śledzenie twarzy)", text_color="#2ECC71"
                )
            elif kind == "paused":
                self._request_stop()
            elif kind == "error":
                self._tracking_error = message
                self._preview_frames.clear()
                self.preview.reset(message)
                self.label_status.configure(text=message, text_color="orange")
            elif kind == "assistant" and not self._stop_event.is_set():
                self._start_assistant()
            elif kind == "voice_error":
                self.label_status.configure(text="Błąd asystenta głosowego.", text_color="orange")
        # The completion event can arrive just before Thread.run returns.
        # Retain the worker reference until both conditions are true.
        if (
            self._worker_finished
            and self.camera_thread is not None
            and not self.camera_thread.is_alive()
        ):
            self.camera_thread = None
            self._worker_finished = False
            if not self._closing:
                self._set_stopped_state()
        if self._closing:
            self._finish_close()
        active_window = self.calibration_window or self.stability_window
        if active_window is not None and not self._closing:
            sample = self._calibration_samples.take()
            if self._stop_event.is_set():
                active_window.tracking_unavailable(
                    self._tracking_error or "Śledzenie wstrzymane. Powtórz punkt, aby wznowić."
                )
            elif (
                sample is not None
                and sample.session_id == self._session_id
                and time.monotonic() - sample.captured_at <= 1
            ):
                active_window.receive_sample(sample)
        if not self._closing:
            packet = self._preview_frames.take()
            if (
                packet is not None
                and packet.session_id == self._session_id
                and not self._stop_event.is_set()
                and time.monotonic() - packet.captured_at <= 1.0
            ):
                try:
                    self.preview.show_frame(packet)
                except Exception:
                    logger.exception("Unable to display preview frame")
                    self.preview.reset("Nie można wyświetlić podglądu kamery")
            self.preview.expire()
        if not self._closed:
            self.after(50, self._poll_worker_events)

    def close(self):
        if self._closing:
            return
        if self.calibration_window is not None:
            self.calibration_window.cancel()
        if self.stability_window is not None:
            self.stability_window.cancel()
        self._closing = True
        if (
            hasattr(self, "keyboard_window")
            and self.keyboard_window
            and self.keyboard_window.winfo_exists()
        ):
            try:
                self.keyboard_window.destroy()
            except Exception:
                pass
        self._request_stop()
        self._finish_close()

    def _finish_close(self):
        # Safe keyboard cleanup before destroying main window
        if hasattr(self, "keyboard_window") and self.keyboard_window is not None:
            try:
                if (
                    hasattr(self.keyboard_window, "winfo_exists")
                    and self.keyboard_window.winfo_exists()
                ):
                    self.keyboard_window.destroy()
            except Exception:
                pass
            self.keyboard_window = None
        if self._closed:
            return
        workers = (self.camera_thread, self.assistant_thread)
        if any(worker is not None and worker.is_alive() for worker in workers):
            return
        self._closed = True
        self._preview_frames.clear()
        self.preview.reset()
        try:
            self.tracker.face_mesh.close()
        except Exception:
            logger.exception("FaceMesh cleanup failed")
        finally:
            self.destroy()


if __name__ == "__main__":
    app = AeroAssistApp()
    app.mainloop()
