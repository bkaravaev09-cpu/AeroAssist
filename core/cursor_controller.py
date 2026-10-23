"""Pure cursor calculations; no webcam, GUI, or desktop automation imports."""

import math
import threading
from dataclasses import dataclass, replace

from core.calibration import CalibrationParameters


@dataclass(frozen=True)
class CursorSettings:
    sensitivity: float = 1.9
    smoothing: float = 0.74
    dead_zone: float = 2.0
    max_step: float = 80.0
    max_head_step: float = 0.20

    def __post_init__(self):
        limits = {
            "sensitivity": (1.0, 3.0),
            "smoothing": (0.0, 0.95),
            "dead_zone": (0.0, 20.0),
            "max_step": (1.0, 500.0),
            "max_head_step": (0.01, 1.0),
        }
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError(f"{name} must be finite and between {low} and {high}")


DEFAULT_CURSOR_SETTINGS = CursorSettings()


class CursorController:
    def __init__(self, screen_width, screen_height, settings=DEFAULT_CURSOR_SETTINGS):
        if not all(isinstance(value, int) and value > 0 for value in (screen_width, screen_height)):
            raise ValueError("Screen dimensions must be positive integers")
        self.width, self.height = screen_width, screen_height
        self._lock = threading.Lock()
        self._settings = settings
        self._calibration = None
        self._position = (float(screen_width // 2), float(screen_height // 2))
        self._reset_locked()

    @property
    def settings(self):
        with self._lock:
            return self._settings

    @property
    def position(self):
        with self._lock:
            return self._position

    def configure(self, **changes):
        with self._lock:
            self._settings = replace(self._settings, **changes)

    @property
    def calibration(self):
        with self._lock:
            return self._calibration

    def set_calibration(self, parameters):
        if parameters is not None and not isinstance(parameters, CalibrationParameters):
            raise ValueError("Expected validated calibration parameters")
        with self._lock:
            self._calibration = parameters
            self._reset_locked()

    def reset(self):
        """Discard filter/drift history while retaining the last safe cursor position."""
        with self._lock:
            self._reset_locked()

    def _reset_locked(self):
        self._accepted_target = self._position
        self._drift_x = self._drift_y = 0.0
        self._anchor_x = self._anchor_y = 0.0
        self._needs_anchor = True
        self._last_head = None

    @staticmethod
    def _valid(*values):
        return all(isinstance(value, (int, float)) and math.isfinite(value) for value in values)

    @staticmethod
    def response_curve(offset, upward=False):
        if abs(offset) < 0.015:
            return offset * 0.9
        scaled = abs(offset) ** (1.25 if upward else 1.15) * (2.3 if upward else 1.9)
        return math.copysign(scaled, offset)

    def _clamp(self, x, y):
        return (min(self.width - 1.0, max(0.0, x)), min(self.height - 1.0, max(0.0, y)))

    def update_target(self, x, y):
        """Filter pixel targets; ignored samples never poison movement state."""
        with self._lock:
            if not self._valid(x, y):
                self._reset_locked()
                return None
            return self._update_target_locked(x, y)

    def _update_target_locked(self, x, y):
        target = self._clamp(x, y)
        # Compare with the last accepted target, not the immediately preceding
        # sample: sub-threshold slow movement can accumulate past the dead zone.
        reaches_edge = any(
            target[axis] in (0.0, limit - 1.0) and target[axis] != self._accepted_target[axis]
            for axis, limit in enumerate((self.width, self.height))
        )
        if reaches_edge or math.dist(target, self._accepted_target) >= self._settings.dead_zone:
            self._accepted_target = target
        alpha = 1.0 - self._settings.smoothing
        dx = (self._accepted_target[0] - self._position[0]) * alpha
        dy = (self._accepted_target[1] - self._position[1]) * alpha
        distance = math.hypot(dx, dy)
        if distance > self._settings.max_step:
            scale = self._settings.max_step / distance
            dx, dy = dx * scale, dy * scale
        self._position = self._clamp(self._position[0] + dx, self._position[1] + dy)
        return self._position

    def update_head(self, nose_x, nose_y, center_x, center_y):
        """Map normalized head offsets, preserving nonlinear response and edge drift."""
        with self._lock:
            if not self._valid(nose_x, nose_y, center_x, center_y) or not all(
                0.0 <= value <= 1.0 for value in (nose_x, nose_y, center_x, center_y)
            ):
                self._reset_locked()
                return None
            if (
                self._last_head is not None
                and math.dist((nose_x, nose_y), self._last_head) > self._settings.max_head_step
            ):
                self._reset_locked()
            self._last_head = (nose_x, nose_y)
            raw_x, raw_y = nose_x - center_x, nose_y - center_y
            gain = self._settings.sensitivity / DEFAULT_CURSOR_SETTINGS.sensitivity
            if self._calibration is not None:
                if self._needs_anchor:
                    self._needs_anchor = False
                    return self._position
                target = self._calibration.map_head(nose_x, nose_y, self.width, self.height, gain)
                return self._update_target_locked(*target)
            base_x = self.response_curve(raw_x) * self.width * gain + self.width / 2
            base_y = (
                self.response_curve(raw_y, upward=raw_y < 0) * self.height * gain + self.height / 2
            )
            if self._needs_anchor:
                # The first valid sample after loss/restart holds position.
                # This is a transient continuity offset, not user calibration.
                self._anchor_x = self._position[0] - base_x
                self._anchor_y = self._position[1] - base_y
                self._needs_anchor = False
                return self._position
            if abs(raw_x) > 0.07:
                self._drift_x += math.copysign(
                    18.0 * gain * max(1.0, (abs(raw_x) - 0.07) / 0.07), raw_x
                )
            else:
                self._drift_x *= 0.85
            if abs(raw_y) > 0.06:
                self._drift_y += math.copysign(
                    18.0 * gain * max(1.0, (abs(raw_y) - 0.06) / 0.07), raw_y
                )
            else:
                self._drift_y *= 0.85
            base_x += self._anchor_x
            base_y += self._anchor_y
            target_x, target_y = base_x + self._drift_x, base_y + self._drift_y
            clamped_x, clamped_y = self._clamp(target_x, target_y)
            # Avoid accumulating drift beyond an edge and delaying the return.
            self._drift_x = clamped_x - base_x
            self._drift_y = clamped_y - base_y
            return self._update_target_locked(clamped_x, clamped_y)
