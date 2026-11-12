"""Five-point wizard: all widget access and sample aggregation run on the GUI thread."""

import logging
import time
import tkinter as tk

import customtkinter as ctk

from core.calibration import MIN_SAMPLES, POINTS, CalibrationError

logger = logging.getLogger(__name__)
INSTRUCTIONS = (
    "Ustaw głowę w wygodnej, neutralnej pozycji.",
    "Obróć lub pochyl głowę wygodnie w lewo.",
    "Obróć lub pochyl głowę wygodnie w prawo.",
    "Skieruj głowę wygodnie w górę.",
    "Skieruj głowę wygodnie w dół.",
)
NAMES = ("Środek", "Lewo", "Prawo", "Góra", "Dół")
LOCATIONS = ((0.5, 0.5), (0.1, 0.5), (0.9, 0.5), (0.5, 0.15), (0.5, 0.85))


class CalibrationWindow(ctk.CTkToplevel):
    def __init__(
        self, master, manager, *, on_begin, on_preview, on_save, on_cancel, on_reset, on_collect
    ):
        super().__init__(master)
        self.manager = manager
        self.on_begin, self.on_preview, self.on_save = on_begin, on_preview, on_save
        self.on_cancel, self.on_reset = on_cancel, on_reset
        self.on_collect = on_collect
        self.stage = "intro"
        self.step = 0
        self.capturing = False
        self._closed = False
        self._last_sample = None
        self._capture_started = None
        self._focus_index = 0
        self.title("Kalibracja kursora — ruchy głowy")
        scale = self._get_window_scaling()
        self.geometry(
            f"{min(1000, int(self.winfo_screenwidth() / scale) - 80)}x"
            f"{max(480, min(720, int(self.winfo_screenheight() / scale) - 100))}"
        )
        self.minsize(460, 480)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.heading = ctk.CTkLabel(self, text="Kalibracja kursora", font=("Arial", 22, "bold"))
        self.heading.grid(row=0, column=0, padx=16, pady=(16, 8))
        self.instructions = ctk.CTkLabel(
            self,
            text="Kalibracja pomoże dopasować ruch kursora do Twoich ruchów głowy.",
            wraplength=420,
        )
        self.instructions.grid(row=1, column=0, padx=16, pady=8)
        self.target = tk.Canvas(self, background="#202a36", highlightthickness=0, height=180)
        self.target.grid(row=2, column=0, padx=16, pady=8, sticky="nsew")
        self.target.bind("<Configure>", self._draw_target)
        self.status = ctk.CTkLabel(
            self,
            text="Kalibracja jest opcjonalna. Poruszaj głową w wygodnym zakresie.",
            wraplength=420,
        )
        self.status.grid(row=3, column=0, padx=16, pady=4)
        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.progress.grid(row=4, column=0, padx=16, pady=8, sticky="ew")
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=5, column=0, padx=16, pady=(0, 16), sticky="ew")
        controls.grid_columnconfigure((0, 1), weight=1)
        self.primary = ctk.CTkButton(controls, text="Rozpocznij kalibrację", command=self.start)
        self.next_button = ctk.CTkButton(controls, text="Dalej", command=self.advance)
        self.previous = ctk.CTkButton(controls, text="Poprzedni punkt", command=self.go_back)
        self.repeat = ctk.CTkButton(controls, text="Powtórz punkt", command=self.capture)
        self.save_button = ctk.CTkButton(controls, text="Zapisz kalibrację", command=self.save)
        self.defaults = ctk.CTkButton(controls, text="Przywróć domyślne", command=self.restore)
        self.cancel_button = ctk.CTkButton(controls, text="Anuluj", command=self.cancel)
        self.buttons = [
            self.primary,
            self.next_button,
            self.previous,
            self.repeat,
            self.save_button,
            self.defaults,
            self.cancel_button,
        ]
        for index, button in enumerate(self.buttons):
            button.grid(row=index // 2, column=index % 2, padx=4, pady=4, sticky="ew")
        self._update_buttons()
        self.bind("<Escape>", lambda event: self.cancel())
        self.bind("<Tab>", self._cycle_focus)
        self.bind("<Shift-Tab>", lambda event: self._cycle_focus(event, -1))
        self.bind("<Return>", self._activate_focused)
        self.bind("<space>", self._activate_focused)
        self._tick_id = self.after(100, self._tick)
        self.primary.focus_set()

    def _update_buttons(self):
        collecting = self.stage == "collecting"
        self.primary.configure(
            text="Zbierz próbki"
            if collecting
            else ("Powtórz kalibrację" if self.stage == "preview" else "Rozpocznij kalibrację"),
            command=self.capture if collecting else self.start,
            state="disabled" if self.capturing else "normal",
        )
        self.next_button.configure(
            state="normal"
            if collecting and POINTS[self.step] in self.manager.points and not self.capturing
            else "disabled"
        )
        self.previous.configure(state="normal" if collecting and self.step > 0 else "disabled")
        self.repeat.configure(state="normal" if collecting else "disabled")
        self.save_button.configure(state="normal" if self.stage == "preview" else "disabled")
        for button in (self.next_button, self.previous, self.repeat):
            (button.grid if collecting else button.grid_remove)()
        for button in (self.save_button, self.defaults):
            (button.grid if self.stage == "preview" else button.grid_remove)()

    def _cycle_focus(self, event=None, direction=1):
        enabled = [
            button
            for button in self.buttons
            if button.winfo_ismapped() and button.cget("state") != "disabled"
        ]
        if enabled:
            self._focus_index = (self._focus_index + direction) % len(enabled)
            enabled[self._focus_index].focus_set()
        return "break"

    def _activate_focused(self, event=None):
        focused = self.focus_get()
        for button in self.buttons:
            if focused == button or str(focused).startswith(str(button) + "."):
                button.invoke()
                break
        return "break"

    def _draw_target(self, event=None):
        self.target.delete("all")
        width, height = self.target.winfo_width(), self.target.winfo_height()
        for index, (nx, ny) in enumerate(LOCATIONS):
            x, y = nx * width, ny * height
            active = self.stage == "collecting" and index == self.step
            radius = 22 if active else 7
            self.target.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill="#ffd166" if active else "#526174",
                outline="white" if active else "",
            )
            if active:
                self.target.create_text(
                    x, y + 34, text=NAMES[index], fill="white", font=("Arial", 14)
                )

    def start(self):
        if not self.on_begin():
            self.status.configure(text="Poczekaj na zatrzymanie kamery i spróbuj ponownie.")
            return
        self.manager.begin()
        self.stage, self.step, self.capturing = "collecting", 0, False
        self._show_step()

    def _show_step(self):
        self.heading.configure(text=f"Punkt {self.step + 1}/5 — {NAMES[self.step]}")
        self.instructions.configure(
            text=INSTRUCTIONS[self.step] + " Gdy pozycja będzie wygodna, wybierz „Zbierz próbki”."
        )
        self.status.configure(
            text="Nie wykonuj ruchu oczami zamiast głową. Utrzymaj wygodną pozycję."
        )
        self.progress.set(0)
        self._update_buttons()
        self._draw_target()

    def capture(self):
        if self.stage != "collecting":
            return
        if not self.on_begin():
            self.tracking_unavailable("Kamera nie jest jeszcze gotowa. Spróbuj ponownie.")
            return
        self.manager.begin_step(POINTS[self.step])
        self.on_collect(True)
        self.capturing = True
        self._last_sample = None
        self._capture_started = time.monotonic()
        self.status.configure(text="Zbieranie próbek… utrzymaj głowę nieruchomo.")
        self._update_buttons()

    def receive_sample(self, sample):
        if not self.capturing or self.stage != "collecting":
            return
        if self._last_sample is not None and sample.captured_at <= self._last_sample:
            return
        if self._last_sample is not None and sample.captured_at - self._last_sample > 1.0:
            self.manager.interrupt_step()
        self._last_sample = sample.captured_at
        complete = self.manager.add_sample(sample.position)
        self.progress.set(len(self.manager.samples) / MIN_SAMPLES)
        if sample.position is None:
            self.status.configure(text="Nie wykryto twarzy. Ustaw głowę w polu kamery.")
        elif complete:
            self.capturing = False
            self.on_collect(False)
            self.status.configure(
                text="Punkt zapisany w pamięci. Wybierz „Dalej” lub „Powtórz punkt”."
            )
            self._update_buttons()
        else:
            self.status.configure(
                text=f"Próbki: {len(self.manager.samples)}/{MIN_SAMPLES}. Czekam na stabilną pozycję."
            )

    def advance(self):
        if self.capturing or POINTS[self.step] not in self.manager.points:
            return
        if self.step < 4:
            self.step += 1
            self._show_step()
            return
        try:
            parameters = self.manager.calculate()
        except CalibrationError as exc:
            self.status.configure(text=str(exc))
            return
        self.on_preview(parameters)
        self.stage = "preview"
        self.heading.configure(text="Kalibracja zakończona — sprawdź ruch kursora")
        self.instructions.configure(
            text="Poruszaj głową i sprawdź zasięg kursora. Zapisz wynik albo powtórz kalibrację."
        )
        self.status.configure(
            text="Podgląd nie zmienia zapisanego pliku. Anulowanie przywróci poprzednie ustawienia."
        )
        self._update_buttons()
        self._draw_target()

    def go_back(self):
        if self.stage == "collecting" and self.step > 0:
            self.capturing = False
            self.on_collect(False)
            self.manager.interrupt_step()
            self.step -= 1
            self._show_step()

    def tracking_unavailable(self, message):
        if self.stage == "collecting":
            self.capturing = False
            self.on_collect(False)
            self.manager.interrupt_step()
            self.progress.set(0)
            self.status.configure(text=message)
            self._update_buttons()

    def _tick(self):
        if self._closed:
            return
        if self.capturing:
            now = time.monotonic()
            if now - self._capture_started > 10:
                self.tracking_unavailable(
                    "Brak stabilnych pomiarów. Sprawdź kamerę i powtórz punkt."
                )
            elif self._last_sample is not None and now - self._last_sample > 1:
                self.manager.interrupt_step()
                self.progress.set(0)
                self.status.configure(text="Brak nowych klatek. Sprawdź kamerę lub powtórz punkt.")
        self._tick_id = self.after(100, self._tick)

    def save(self):
        if self.stage != "preview":
            return
        try:
            self.on_save(self.manager.candidate)
        except (OSError, CalibrationError):
            logger.exception("Unable to save calibration")
            self.on_preview(self.manager.active)
            self.status.configure(
                text="Nie można zapisać kalibracji. Przywrócono poprzednie ustawienia. Spróbuj ponownie lub anuluj."
            )
            return
        self._finish()

    def restore(self):
        if self.on_reset():
            self._finish()
        else:
            self.status.configure(
                text="Nie można usunąć zapisanej kalibracji. Sprawdź uprawnienia."
            )

    def cancel(self):
        if not self._closed:
            self.on_cancel()
            self._finish()

    def _finish(self):
        self._closed = True
        if self._tick_id is not None:
            self.after_cancel(self._tick_id)
            self._tick_id = None
        self.destroy()
