"""Interactive calibration wizard for AeroAssist."""

import math
import time

import customtkinter as ctk
import cv2
import mediapipe as mp
from PIL import Image


class CalibrationWizard(ctk.CTkToplevel):
    """Three-step calibration wizard using the webcam."""

    def __init__(self, master_app):
        super().__init__(master_app)
        self.master_app = master_app
        self.title("Kreator kalibracji AeroAssist")
        self.geometry("760x620")
        self.attributes("-topmost", True)
        self.resizable(False, False)

        self._running = True
        self._image_ref = None
        self.stage = 0
        self.center_x = getattr(master_app.tracker, "center_x", 0.5)
        self.center_y = getattr(master_app.tracker, "center_y", 0.55)
        self.stage0_good_since = None
        self.stage1_start = None
        self.stage2_start = None
        self.peak_x = 0.0
        self.peak_y = 0.0
        self.stability_samples = []

        self._cap = None
        self._face_mesh = None
        self._open_camera()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(30, self._tick)

    def _open_camera(self):
        try:
            self._cap = cv2.VideoCapture(0)
        except Exception:
            self._cap = None
        try:
            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        except Exception:
            self._face_mesh = None

    def _build_ui(self):
        self.title_label = ctk.CTkLabel(
            self, text="Etap 1/3: Ustaw głowę przed kamerą", font=("Arial", 18, "bold")
        )
        self.title_label.pack(pady=10)
        self.preview_label = ctk.CTkLabel(
            self, text="Uruchamianie kamery...", width=640, height=360
        )
        self.preview_label.pack(padx=10, pady=5)
        self.status_label = ctk.CTkLabel(self, text="", wraplength=700, justify="left")
        self.status_label.pack(pady=5, padx=10, fill="x")
        self.progress_label = ctk.CTkLabel(self, text="")
        self.progress_label.pack(pady=2)

        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.pack(pady=10)
        self.cancel_btn = ctk.CTkButton(
            button_frame, text="Anuluj", command=self._close, fg_color="#7b241c"
        )
        self.cancel_btn.pack(side="left", padx=5)
        self.next_btn = ctk.CTkButton(
            button_frame, text="Dalej", command=self._next_stage, state="disabled"
        )
        self.next_btn.pack(side="left", padx=5)
        self.finish_btn = ctk.CTkButton(
            button_frame, text="Zakończ", command=self._finish, state="disabled"
        )
        self.finish_btn.pack(side="left", padx=5)

    def _next_stage(self):
        if self.stage == 0:
            self.stage = 1
            self.stage1_start = time.monotonic()
            self.peak_x = 0.0
            self.peak_y = 0.0
            self.title_label.configure(text="Etap 2/3: Maksymalna amplituda ruchu")
            self.next_btn.configure(state="disabled")
            self.status_label.configure(
                text="Poruszaj głową do skrajnych pozycji: lewo, prawo, góra, dół. Pomiar potrwa 8 sekund."
            )
        elif self.stage == 1:
            self.stage = 2
            self.stage2_start = time.monotonic()
            self.stability_samples = []
            self.title_label.configure(text="Etap 3/3: Test stabilności")
            self.next_btn.configure(state="disabled")
            self.status_label.configure(
                text="Trzymaj głowę nieruchomo przez 5 sekund. Mierzę drgania."
            )

    def _tick(self):
        if not self._running:
            return
        if self._cap is None:
            self.status_label.configure(text="Nie można otworzyć kamery.")
            self.after(100, self._tick)
            return

        ret, frame = self._cap.read()
        if not ret or frame is None:
            self.status_label.configure(text="Brak klatki z kamery.")
            self.after(100, self._tick)
            return

        frame = cv2.flip(frame, 1)
        height, width = frame.shape[:2]
        landmarks = None
        if self._face_mesh is not None:
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self._face_mesh.process(rgb)
                if results.multi_face_landmarks:
                    landmarks = results.multi_face_landmarks[0].landmark
            except Exception:
                landmarks = None

        color = (0, 0, 255)
        if landmarks is not None:
            nose = landmarks[4]
            try:
                face_width = abs(landmarks[234].x - landmarks[454].x)
            except Exception:
                face_width = 0.3
            centered = 0.35 <= nose.x <= 0.65 and 0.35 <= nose.y <= 0.65
            good_distance = 0.12 <= face_width <= 0.5
            if centered and good_distance:
                color = (0, 255, 0)
            nx, ny = int(nose.x * width), int(nose.y * height)
            cv2.circle(frame, (nx, ny), 6, color, -1)

        x1, y1 = int(0.35 * width), int(0.35 * height)
        x2, y2 = int(0.65 * width), int(0.65 * height)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        now = time.monotonic()
        if landmarks is not None:
            nose = landmarks[4]
            if self.stage == 0:
                try:
                    face_width = abs(landmarks[234].x - landmarks[454].x)
                except Exception:
                    face_width = 0.3
                centered = 0.35 <= nose.x <= 0.65 and 0.35 <= nose.y <= 0.65
                good_distance = 0.12 <= face_width <= 0.5
                if centered and good_distance:
                    if self.stage0_good_since is None:
                        self.stage0_good_since = now
                    elif now - self.stage0_good_since >= 1.0:
                        self.center_x = float(nose.x)
                        self.center_y = float(nose.y)
                        self.next_btn.configure(state="normal")
                        self.status_label.configure(
                            text="Pozycja prawidłowa. Możesz przejść dalej."
                        )
                else:
                    self.stage0_good_since = None
                    self.status_label.configure(
                        text="Ustaw głowę centralnie przed kamerą, w odpowiedniej odległości (zielona ramka)."
                    )
            elif self.stage == 1:
                dx = abs(float(nose.x) - self.center_x)
                dy = abs(float(nose.y) - self.center_y)
                if dx > self.peak_x:
                    self.peak_x = dx
                if dy > self.peak_y:
                    self.peak_y = dy
                elapsed = now - self.stage1_start
                remaining = max(0.0, 8.0 - elapsed)
                self.progress_label.configure(
                    text=f"Szczyt X: {self.peak_x:.3f} | Szczyt Y: {self.peak_y:.3f} | Pozostało: {remaining:.1f}s"
                )
                if remaining <= 0:
                    self.next_btn.configure(state="normal")
                    self.status_label.configure(text="Pomiar amplitudy zakończony. Przejdź dalej.")
            elif self.stage == 2:
                self.stability_samples.append((float(nose.x), float(nose.y)))
                elapsed = now - self.stage2_start
                remaining = max(0.0, 5.0 - elapsed)
                self.progress_label.configure(
                    text=f"Próbki: {len(self.stability_samples)} | Pozostało: {remaining:.1f}s"
                )
                if remaining <= 0 and len(self.stability_samples) > 10:
                    self.finish_btn.configure(state="normal")
                    self.status_label.configure(
                        text="Test stabilności zakończony. Kliknij Zakończ, aby zapisać kalibrację."
                    )
        else:
            self.status_label.configure(text="Nie wykryto twarzy. Ustaw się przed kamerą.")

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(640, 360))
            self.preview_label.configure(image=ctk_img, text="")
            self._image_ref = ctk_img
        except Exception:
            pass

        self.after(30, self._tick)

    def _finish(self):
        max_peak = max(self.peak_x, self.peak_y, 1e-3)
        sensitivity = 0.15 / max_peak
        sensitivity = max(1.0, min(3.0, sensitivity))

        if len(self.stability_samples) > 1:
            xs = [sample[0] for sample in self.stability_samples]
            ys = [sample[1] for sample in self.stability_samples]

            def pstdev(values):
                mean = sum(values) / len(values)
                return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))

            jitter = (pstdev(xs) + pstdev(ys)) / 2.0
        else:
            jitter = 0.0

        smoothing = 0.75 + jitter * 20.0
        smoothing = max(0.5, min(0.95, smoothing))
        dead_zone = 2.0

        tracker = self.master_app.tracker
        try:
            tracker.center_x = self.center_x
            tracker.center_y = self.center_y
            tracker.is_calibrated = True
            tracker.configure_cursor(
                sensitivity=sensitivity, smoothing=smoothing, dead_zone=dead_zone
            )
        except Exception:
            pass

        try:
            from core.calibration_manager import save_profile

            save_profile(
                self.center_x,
                self.center_y,
                getattr(tracker, "blink_threshold", 0.15),
                [],
                sensitivity=sensitivity,
                smoothing=smoothing,
                dead_zone=dead_zone,
            )
        except Exception:
            pass

        try:
            self.master_app.label_status.configure(
                text=f"Kalibracja zakończona. Czułość: {sensitivity:.2f}, wygładzanie: {smoothing:.2f}",
                text_color="green",
            )
        except Exception:
            pass
        self._close()

    def _close(self):
        self._running = False
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        if self._face_mesh is not None:
            try:
                self._face_mesh.close()
            except Exception:
                pass
            self._face_mesh = None
        try:
            self.destroy()
        except Exception:
            pass
