"""Capture only AeroAssist's window using synthetic pixels, never a webcam.

Run on Windows: .venv/Scripts/python.exe scripts/capture_preview_ui.py
"""

import math
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image, ImageDraw, ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402
from ui.camera_preview import PreviewFrame  # noqa: E402


def capture_window(app, path):
    """Capture only the mapped application's client bounds, excluding the desktop."""
    app.lift()
    app.update()
    app.after(300, app.quit)
    app.mainloop()
    x, y = app.winfo_rootx(), app.winfo_rooty()
    if x + app.winfo_width() > app.winfo_screenwidth() or (
        y + app.winfo_height() > app.winfo_screenheight() - 50
    ):
        raise RuntimeError("Application bounds exceed the work area; refusing desktop capture")
    ImageGrab.grab(bbox=(x, y, x + app.winfo_width(), y + app.winfo_height())).save(path)


def synthetic_frame():
    image = Image.new("RGB", (640, 360), "#18222e")
    draw = ImageDraw.Draw(image)
    for x in range(0, 640, 40):
        draw.line((x, 0, x, 360), fill="#253344")
    for y in range(0, 360, 40):
        draw.line((0, y, 640, y), fill="#253344")
    draw.ellipse((220, 45, 420, 325), fill="#344355")
    draw.text((16, 14), "SYNTHETIC TEST FRAME - NO CAMERA", fill="white")
    points = [(0.5, 0.5)] * 478
    outline = (
        10,
        338,
        297,
        332,
        284,
        251,
        389,
        356,
        454,
        323,
        361,
        288,
        397,
        365,
        379,
        378,
        400,
        377,
        152,
        148,
        176,
        149,
        150,
        136,
        172,
        58,
        132,
        93,
        234,
        127,
        162,
        21,
        54,
        103,
        67,
        109,
    )
    for n, index in enumerate(outline):
        angle = -math.pi / 2 + n * 2 * math.pi / len(outline)
        points[index] = (0.5 + math.cos(angle) * 0.15, 0.5 + math.sin(angle) * 0.38)
    for eye, center in (
        ((33, 160, 158, 133, 153, 144), 0.43),
        ((362, 385, 387, 263, 373, 380), 0.57),
    ):
        for n, index in enumerate(eye):
            angle = n * 2 * math.pi / len(eye)
            points[index] = (center + math.cos(angle) * 0.04, 0.43 + math.sin(angle) * 0.02)
    points[4] = (0.5, 0.57)
    return np.asarray(image)[:, :, ::-1].copy(), tuple(points)


def run():
    destination = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
    destination.mkdir(parents=True, exist_ok=True)
    with (
        patch.object(main, "VisionTracker", return_value=MagicMock()),
        patch.object(main, "PolishVoiceAssistant", return_value=MagicMock()),
    ):
        app = main.AeroAssistApp()
    try:
        app.geometry("580x590+30+20")
        app.attributes("-topmost", True)
        app.update()
        capture_window(app, destination / "preview-inactive.png")
        bgr, landmarks = synthetic_frame()
        app.preview.show_frame(PreviewFrame(0, bgr, landmarks, 29.7, time.monotonic()))
        app.btn_toggle.configure(text="Zatrzymaj sterowanie", fg_color="#C0392B")
        app.label_status.configure(text="Podgląd testowy — bez użycia kamery")
        app.update()
        capture_window(app, destination / "preview-synthetic.png")
        app.preview.show_landmarks.set(False)
        app.preview.show_frame(PreviewFrame(0, bgr, landmarks, 29.7, time.monotonic()))
        app.update()
        capture_window(app, destination / "preview-landmarks-off.png")
        app.info_box.master._parent_canvas.yview_moveto(1.0)
        capture_window(app, destination / "preview-controls.png")
        app.info_box.master._parent_canvas.yview_moveto(0.0)
        app.geometry("380x590+30+20")
        app._tracking_error = "Nie można otworzyć kamery. Sprawdź połączenie i uprawnienia."
        app._set_stopped_state()
        app.update()
        app.info_box.master._parent_canvas.yview_moveto(0.0)
        capture_window(app, destination / "preview-small-error.png")
    finally:
        app.close()


if __name__ == "__main__":
    run()
