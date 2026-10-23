"""GUI-only rendering and a constant-space worker-to-GUI frame handoff."""

import threading
import time
from dataclasses import dataclass

import customtkinter as ctk
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps


@dataclass(frozen=True)
class PreviewFrame:
    session_id: int
    bgr: np.ndarray
    landmarks: tuple[tuple[float, float], ...]
    fps: float
    captured_at: float


class LatestFrameBuffer:
    """Hold at most one frame; the GUI never makes the producer wait on rendering."""

    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None

    def publish(self, frame):
        with self._lock:
            self._frame = frame

    def take(self):
        with self._lock:
            frame, self._frame = self._frame, None
            return frame

    def clear(self):
        self.take()


def frame_to_image(frame, size, landmarks=()):
    """Validate BGR input, convert once, and fit without stretching or cropping."""
    if (
        not isinstance(frame, np.ndarray)
        or frame.dtype != np.uint8
        or frame.ndim != 3
        or frame.shape[2] != 3
        or not frame.shape[0]
        or not frame.shape[1]
    ):
        raise ValueError("Expected a nonempty uint8 BGR image with three channels")
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(rgb)
    if landmarks:
        draw = ImageDraw.Draw(image)
        width, height = image.size
        # Sparse face outline plus eyes, nose, and head reference points.
        regions = (
            (
                (
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
                ),
                "#cbd5e1",
            ),
            ((33, 160, 158, 133, 153, 144), "#50e3c2"),
            ((362, 385, 387, 263, 373, 380), "#ffce56"),
            ((4,), "#ff7f7f"),
            ((10, 152, 234, 454), "#a6a0ff"),
        )
        for indices, color in regions:
            points = [
                (landmarks[i][0] * width, landmarks[i][1] * height)
                for i in indices
                if i < len(landmarks)
            ]
            if len(points) > 2 and len(indices) > 4:
                draw.line(points + [points[0]], fill=color, width=2)
            for x, y in points:
                draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
    return ImageOps.contain(image, size, Image.Resampling.LANCZOS)


class CameraPreview(ctk.CTkFrame):
    def __init__(self, master, width=480, height=270, **kwargs):
        super().__init__(master, **kwargs)
        self._image_size = (width, height)
        self._image = None
        blank = Image.new("RGBA", (1, 1))
        self._placeholder_image = ctk.CTkImage(light_image=blank, dark_image=blank, size=(1, 1))
        self._last_frame_at = None
        self.show_landmarks = ctk.BooleanVar(value=True)
        self.video = ctk.CTkLabel(self, text="Kamera nieaktywna", width=1, height=height)
        self.video.pack(padx=8, pady=8, fill="x")
        self.indicators = ctk.CTkLabel(self, text="", justify="left", anchor="w", wraplength=440)
        self.indicators.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkCheckBox(self, text="Pokaż punkty twarzy", variable=self.show_landmarks).pack(
            anchor="w", padx=12, pady=(0, 12)
        )
        self.reset()
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        width = max(1, min(480, int(event.width / self._get_widget_scaling()) - 24))
        self._image_size = (width, max(1, int(width * 9 / 16)))
        self.video.configure(height=self._image_size[1], wraplength=width)
        self.indicators.configure(wraplength=width)

    def _set_indicators(self, camera, face, tracking, fps):
        self.indicators.configure(
            text=(
                f"Kamera: {'Aktywna' if camera else 'Nieaktywna'}  ·  "
                f"{'Wykryto twarz' if face else 'Nie wykryto twarzy'}\n"
                f"Śledzenie: {'Aktywne' if tracking else 'Wstrzymane'}  ·  FPS: {fps:.1f}"
            )
        )

    def reset(self, message="Kamera nieaktywna"):
        # CTkLabel 5.2 leaves its Tk image attached when configured with None.
        # A persistent blank image releases the old frame without a dangling Tk image name.
        self.video.configure(image=self._placeholder_image, text=message)
        self._image = None
        self._last_frame_at = None
        self._set_indicators(False, False, False, 0.0)

    def show_frame(self, packet):
        try:
            image = frame_to_image(
                packet.bgr,
                self._image_size,
                packet.landmarks if self.show_landmarks.get() else (),
            )
        except (ValueError, cv2.error):
            self.reset("Brak poprawnego obrazu z kamery")
            return
        # Creating and assigning CTkImage must happen on the GUI thread.
        self._image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        self.video.configure(image=self._image, text="")
        self._last_frame_at = packet.captured_at
        self._set_indicators(True, bool(packet.landmarks), True, packet.fps)

    def expire(self, now=None):
        if self._last_frame_at is not None and (
            (time.monotonic() if now is None else now) - self._last_frame_at > 1.0
        ):
            self.reset("Brak nowych klatek z kamery")
