"""Stability test: tunes cursor smoothing and dead zone from measured head jitter.

It reads head samples from the running tracking session (the same feed as the
five-point calibration window), so it never opens the camera on its own.
Sensitivity is tuned only when no five-point calibration is active.
"""

import customtkinter as ctk

from core.cursor_profile import MIN_STABILITY_SAMPLES, compute_profile

CENTER_BOX = (0.35, 0.65)
CENTER_HOLD = 1.0
AMPLITUDE_SECONDS = 8.0
STABILITY_SECONDS = 5.0
SAMPLE_MAX_AGE = 1.0
CANVAS_W, CANVAS_H = 480, 300


class CalibrationWizard(ctk.CTkToplevel):
    def __init__(self, master, calibrated, on_begin, on_finish, on_close):
        super().__init__(master)
        self.calibrated = calibrated
        self.on_begin, self.on_finish, self.on_close = on_begin, on_finish, on_close
        self.title("Test stabilności kursora")
        self.geometry("560x560")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self._reset_state()
        self._build_ui()
        self._show_stage()
        if not self.on_begin():
            self.tracking_unavailable("Nie można uruchomić śledzenia. Spróbuj ponownie.")

    def _reset_state(self):
        self._closed = False
        self.stage = "position"
        self.fine_mode = False
        self.center = None
        self._good_since = None
        self._stage_started = None
        self.peak = 0.0
        self.stability_samples = []
        self._last_sample_at = None

    @property
    def stages(self):
        if self.calibrated:
            return ("position", "stability")
        return ("position", "amplitude", "stability")

    def _build_ui(self):
        self.title_label = ctk.CTkLabel(self, text="", font=("Arial", 18, "bold"))
        self.title_label.pack(pady=10)
        self.canvas = ctk.CTkCanvas(
            self, width=CANVAS_W, height=CANVAS_H, bg="#1e1e1e", highlightthickness=0
        )
        self.canvas.pack(padx=10, pady=5)
        self.status_label = ctk.CTkLabel(self, text="", wraplength=520, justify="left")
        self.status_label.pack(pady=5, padx=10, fill="x")
        self.progress_label = ctk.CTkLabel(self, text="")
        self.progress_label.pack(pady=2)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(pady=10)
        self.cancel_btn = ctk.CTkButton(
            buttons, text="Anuluj", command=self.cancel, fg_color="#7b241c"
        )
        self.cancel_btn.pack(side="left", padx=5)
        self.next_btn = ctk.CTkButton(
            buttons, text="Dalej", command=self.next_stage, state="disabled"
        )
        self.next_btn.pack(side="left", padx=5)
        self.finish_btn = ctk.CTkButton(
            buttons, text="Zakończ", command=self.finish, state="disabled"
        )
        self.finish_btn.pack(side="left", padx=5)
        self.fine_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self,
            text="Tryb precyzyjny (dla małych przycisków)",
            variable=self.fine_var,
            command=lambda: setattr(self, "fine_mode", bool(self.fine_var.get())),
        ).pack(pady=5)

    def _show_stage(self):
        number = self.stages.index(self.stage) + 1
        total = len(self.stages)
        texts = {
            "position": (
                "Ustaw głowę przed kamerą",
                "Ustaw głowę tak, aby punkt był w zielonej ramce, i przytrzymaj 1 sekundę.",
            ),
            "amplitude": (
                "Maksymalna amplituda ruchu",
                "Poruszaj głową do skrajnych pozycji: lewo, prawo, góra, dół. "
                f"Pomiar potrwa {AMPLITUDE_SECONDS:.0f} sekund.",
            ),
            "stability": (
                "Test stabilności",
                f"Trzymaj głowę nieruchomo przez {STABILITY_SECONDS:.0f} sekund. Mierzę drgania.",
            ),
        }
        title, status = texts[self.stage]
        self.title_label.configure(text=f"Etap {number}/{total}: {title}")
        self.status_label.configure(text=status)
        self.progress_label.configure(text="")
        self.next_btn.configure(state="disabled")
        self.finish_btn.configure(state="disabled")

    def next_stage(self):
        index = self.stages.index(self.stage)
        if index + 1 >= len(self.stages):
            return
        self.stage = self.stages[index + 1]
        self._stage_started = None
        self.peak = 0.0
        self.stability_samples = []
        self._show_stage()

    def _draw(self, position):
        canvas = self.canvas
        canvas.delete("all")
        inside = position is not None and all(
            CENTER_BOX[0] <= value <= CENTER_BOX[1] for value in position
        )
        color = "#2ecc71" if inside else "#e74c3c"
        low, high = CENTER_BOX
        canvas.create_rectangle(
            low * CANVAS_W, low * CANVAS_H, high * CANVAS_W, high * CANVAS_H, outline=color, width=2
        )
        if position is not None:
            x, y = position[0] * CANVAS_W, position[1] * CANVAS_H
            canvas.create_oval(x - 7, y - 7, x + 7, y + 7, fill=color, outline="")

    def receive_sample(self, sample):
        """Called on the GUI thread with a fresh HeadSample from the tracking session."""
        if self._closed or sample.captured_at == self._last_sample_at:
            return
        self._last_sample_at = sample.captured_at
        position = sample.position
        self._draw(position)
        if position is None:
            self.status_label.configure(text="Nie wykryto twarzy. Ustaw się przed kamerą.")
            self._good_since = None
            return
        now = sample.captured_at
        if self.stage == "position":
            self._handle_position(position, now)
            return
        if self._stage_started is None:
            self._stage_started = now
        elapsed = now - self._stage_started
        if self.stage == "amplitude":
            self.peak = max(
                self.peak, abs(position[0] - self.center[0]), abs(position[1] - self.center[1])
            )
            remaining = max(0.0, AMPLITUDE_SECONDS - elapsed)
            self.progress_label.configure(
                text=f"Amplituda: {self.peak:.3f} | Pozostało: {remaining:.1f}s"
            )
            if remaining <= 0:
                self.next_btn.configure(state="normal")
                self.status_label.configure(text="Pomiar amplitudy zakończony. Przejdź dalej.")
        else:
            self.stability_samples.append(tuple(position))
            remaining = max(0.0, STABILITY_SECONDS - elapsed)
            self.progress_label.configure(
                text=f"Próbki: {len(self.stability_samples)} | Pozostało: {remaining:.1f}s"
            )
            if remaining <= 0 and len(self.stability_samples) >= MIN_STABILITY_SAMPLES:
                self.finish_btn.configure(state="normal")
                self.status_label.configure(
                    text="Test stabilności zakończony. Kliknij Zakończ, aby zapisać ustawienia."
                )

    def _handle_position(self, position, now):
        if not all(CENTER_BOX[0] <= value <= CENTER_BOX[1] for value in position):
            self._good_since = None
            self.next_btn.configure(state="disabled")
            self.status_label.configure(text="Ustaw głowę centralnie (punkt w zielonej ramce).")
            return
        if self._good_since is None:
            self._good_since = now
        elif now - self._good_since >= CENTER_HOLD:
            self.center = tuple(position)
            self.next_btn.configure(state="normal")
            self.status_label.configure(text="Pozycja prawidłowa. Możesz przejść dalej.")

    def tracking_unavailable(self, message):
        """Tracking stopped; restart the current stage once it is back."""
        if self._closed:
            return
        self._good_since = None
        self._stage_started = None
        self.peak = 0.0
        self.stability_samples = []
        self._draw(None)
        self.status_label.configure(text=message)
        self.progress_label.configure(text="")
        self.finish_btn.configure(state="disabled")
        if self.stage != "position":
            self.next_btn.configure(state="disabled")

    def finish(self):
        if self._closed:
            return
        peak = None if self.calibrated else self.peak
        try:
            profile = compute_profile(self.stability_samples, peak=peak, fine_mode=self.fine_mode)
        except ValueError:
            self.status_label.configure(text="Za mało próbek. Powtórz test stabilności.")
            return
        center = None if self.calibrated else self.center
        self.on_finish(profile, center)
        self._close()

    def cancel(self):
        self._close()

    def _close(self):
        if self._closed:
            return
        self._closed = True
        self.on_close()
        try:
            self.destroy()
        except Exception:
            pass
