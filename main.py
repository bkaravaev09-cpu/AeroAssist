import customtkinter as ctk
import cv2
import threading
import winsound

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

        self._build_ui()

    def _build_ui(self):
        self.label_title = ctk.CTkLabel(
            self, text="AeroAssist System", font=("Arial", 22, "bold")
        )
        self.label_title.pack(pady=20)

        self.btn_toggle = ctk.CTkButton(
            self, text="Uruchom sterowanie", command=self.toggle_system, height=45, font=("Arial", 14, "bold")
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
            "• 4 szybkie mrugnięcia — zatrzymanie / pauza śledzenia"
        )
        self.info_box.configure(state="disabled")

    def change_sensitivity(self, val):
        self.tracker.sensitivity = float(val)

    def trigger_assistant(self):
        try:
            winsound.Beep(1200, 200)
        except Exception:
            pass
        threading.Thread(target=self.assistant.listen_and_execute, daemon=True).start()

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
            hover_color=["#325882", "#14375e"]
        )
        self.label_status.configure(text="Status: Zatrzymany (Pauza)", text_color="orange")

    def toggle_system(self):
        if not self.is_running:
            self.is_running = True
            self.btn_toggle.configure(text="Zatrzymaj sterowanie", fg_color="#C0392B", hover_color="#962D22")
            self.label_status.configure(text="Status: Aktywny (Śledzenie twarzy)", text_color="#2ECC71")
            threading.Thread(target=self._worker_loop, daemon=True).start()
        else:
            self._set_stopped_state()

    def _worker_loop(self):
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(0)

        while self.is_running:
            ret, frame = self.cap.read()
            if not ret or frame is None:
                continue

            frame = cv2.flip(frame, 1)

            try:
                self.tracker.process_frame(
                    frame,
                    on_assistant_trigger=self.trigger_assistant,
                    on_shutdown_trigger=self.pause_tracking_from_gesture
                )
            except Exception as e:
                print(f"[ОШИБКА ОБРАБОТКИ]: {e}")
                break

        if self.cap:
            self.cap.release()
            print("[ИНФО] Камера отключена (пауза слежения).")

if __name__ == "__main__":
    app = AeroAssistApp()
    app.mainloop()