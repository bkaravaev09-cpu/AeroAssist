import threading
import winsound

import customtkinter as ctk
import cv2

from core.vision_tracker import VisionTracker
from core.voice_assistant import PolishVoiceAssistant


class AeroAssistApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AeroAssist - Sterowanie komputerem")
        self.geometry("440x540")
        self.resizable(False, False)
        ctk.set_appearance_mode("dark")

        self.tracker = VisionTracker()
        self.assistant = PolishVoiceAssistant()

        self.is_running = False
        self.cap = None
        self.camera_thread = None
        self.assistant_thread = None
        self._closing = False
        self._assistant_lock = threading.Lock()
        self.protocol("WM_DELETE_WINDOW", self.close)

        self._build_ui()

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
        if self._closing or not self._assistant_lock.acquire(blocking=False):
            return
        try:
            self.assistant_thread = threading.Thread(target=self._run_assistant, daemon=True)
            self.assistant_thread.start()
        except Exception:
            self._assistant_lock.release()
            raise

    def _run_assistant(self):
        try:
            try:
                winsound.Beep(1200, 200)
            except Exception:
                pass
            self.assistant.listen_and_execute()
        except Exception as exc:
            print(f"Voice assistant error: {exc}")
        finally:
            self._assistant_lock.release()

    def pause_tracking_from_gesture(self):
        """Мягкая остановка слежения без закрытия приложения"""
        try:
            winsound.Beep(700, 250)
        except Exception:
            pass
        # Безопасно обновляем UI из фонового потока
        self.after(0, self._set_stopped_state)

    def _set_stopped_state(self):
        self.is_running = False
        self.btn_toggle.configure(
            text="Uruchom sterowanie",
            fg_color=["#3a7ebf", "#1f538d"],
            hover_color=["#325882", "#14375e"],
        )
        self.label_status.configure(text="Status: Zatrzymany (Pauza)", text_color="orange")

    def toggle_system(self):
        if self._closing:
            return
        if not self.is_running:
            if self.camera_thread is not None and self.camera_thread.is_alive():
                return
            self.is_running = True
            self.btn_toggle.configure(
                text="Zatrzymaj sterowanie", fg_color="#C0392B", hover_color="#962D22"
            )
            self.label_status.configure(
                text="Status: Aktywny (Śledzenie twarzy)", text_color="#2ECC71"
            )
            try:
                self.camera_thread = threading.Thread(target=self._worker_loop, daemon=True)
                self.camera_thread.start()
            except Exception:
                self._set_stopped_state()
                raise
        else:
            self._set_stopped_state()

    def _worker_loop(self):
        cap = None
        try:
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            self.cap = cap
            if not cap.isOpened():
                cap.release()
                cap = None
                self.cap = None
                cap = cv2.VideoCapture(0)
                self.cap = cap
            if not cap.isOpened():
                raise RuntimeError("Cannot open camera")
            while self.is_running and not self._closing:
                ret, frame = cap.read()
                if not ret or frame is None:
                    raise RuntimeError("Cannot read camera frame")
                frame = cv2.flip(frame, 1)
                self.tracker.process_frame(
                    frame,
                    on_assistant_trigger=self.trigger_assistant,
                    on_shutdown_trigger=self.pause_tracking_from_gesture,
                )
        except Exception as exc:
            print(f"Camera error: {exc}")
        finally:
            if cap is not None:
                cap.release()
            self.cap = None
            self.is_running = False
            self.after(0, self._camera_stopped)

    def _camera_stopped(self):
        # A new worker may have started before this queued GUI callback runs.
        if not self.is_running:
            self._set_stopped_state()

    def close(self):
        self._closing = True
        self.is_running = False
        self._finish_close()

    def _finish_close(self):
        workers = (self.camera_thread, self.assistant_thread)
        if any(worker is not None and worker.is_alive() for worker in workers):
            self.after(50, self._finish_close)
            return
        try:
            self.tracker.face_mesh.close()
        finally:
            self.destroy()


if __name__ == "__main__":
    app = AeroAssistApp()
    app.mainloop()
