import logging
import queue
import threading
import winsound

import customtkinter as ctk
import cv2

from core.vision_tracker import VisionTracker
from core.voice_assistant import PolishVoiceAssistant

logger = logging.getLogger(__name__)


class AeroAssistApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AeroAssist - Sterowanie komputerem")
        self.geometry("440x540")
        self.resizable(False, False)
        ctk.set_appearance_mode("dark")

        self.tracker = VisionTracker()
        self.assistant = PolishVoiceAssistant()

        self._stop_event = threading.Event()
        self._stop_event.set()
        self._worker_events = queue.Queue()
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
        self.label_title = ctk.CTkLabel(self, text="AeroAssist System", font=("Arial", 22, "bold"))
        self.label_title.pack(pady=20)

        self.btn_toggle = ctk.CTkButton(
            self,
            text="Uruchom sterowanie",
            command=self.toggle_system,
            height=45,
            font=("Arial", 14, "bold"),
        )
        self.btn_toggle.pack(pady=10, padx=40, fill="x")

        self.label_status = ctk.CTkLabel(
            self, text="Status: Zatrzymany", text_color="gray", font=("Arial", 13)
        )
        self.label_status.pack(pady=5)

        self.label_sens = ctk.CTkLabel(self, text="Czułość ruchów (Sensitivity):")
        self.label_sens.pack(pady=(15, 0))

        self.slider_sens = ctk.CTkSlider(self, from_=1.0, to=3.0, command=self.change_sensitivity)
        self.slider_sens.set(1.9)
        self.slider_sens.pack(pady=8, padx=40, fill="x")

        self.info_box = ctk.CTkTextbox(self, height=140)
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

    def change_sensitivity(self, val):
        self.tracker.sensitivity = float(val)

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
            cap = self._open_camera(stop_event)
            if cap is None or stop_event.is_set():
                return
            self._worker_events.put((session_id, "started", None))
            failures = 0
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
        except Exception:
            logger.exception("Camera session %s failed", session_id)
            if not stop_event.is_set():
                self._worker_events.put((session_id, "error", error_message))
        finally:
            if cap is not None:
                self._release_camera(cap)
            stop_event.set()
            self._worker_events.put((session_id, "stopped", None))

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
        if not self._closed:
            self.after(50, self._poll_worker_events)

    def close(self):
        if self._closing:
            return
        self._closing = True
        self._request_stop()
        self._finish_close()

    def _finish_close(self):
        if self._closed:
            return
        workers = (self.camera_thread, self.assistant_thread)
        if any(worker is not None and worker.is_alive() for worker in workers):
            return
        self._closed = True
        try:
            self.tracker.face_mesh.close()
        except Exception:
            logger.exception("FaceMesh cleanup failed")
        finally:
            self.destroy()


if __name__ == "__main__":
    app = AeroAssistApp()
    app.mainloop()
