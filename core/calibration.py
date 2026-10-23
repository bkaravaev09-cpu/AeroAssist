"""Hardware-independent five-point head calibration and local parameter storage."""

import json
import logging
import math
import os
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

logger = logging.getLogger(__name__)
POINTS = ("center", "left", "right", "top", "bottom")
MIN_SAMPLES = 20
STABILITY_TOLERANCE = 0.01
MIN_RANGE = 0.01


class CalibrationError(ValueError):
    """An actionable Polish message suitable for displaying in the wizard."""


def valid_position(position):
    return (
        isinstance(position, (tuple, list))
        and len(position) == 2
        and all(
            isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(v)
            and 0 <= v <= 1
            for v in position
        )
    )


@dataclass(frozen=True)
class CalibrationParameters:
    center_x: float
    center_y: float
    left_x: float
    right_x: float
    top_y: float
    bottom_y: float

    def __post_init__(self):
        if not all(
            isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(v)
            and 0 <= v <= 1
            for v in asdict(self).values()
        ):
            raise CalibrationError("Nieprawidłowe wartości kalibracji. Powtórz pomiary.")
        if (
            min(
                self.center_x - self.left_x,
                self.right_x - self.center_x,
                self.center_y - self.top_y,
                self.bottom_y - self.center_y,
            )
            < MIN_RANGE
        ):
            raise CalibrationError(
                "Zakres ruchu jest zbyt mały lub kierunki są odwrócone. Powtórz odpowiedni punkt."
            )

    @property
    def horizontal_range(self):
        return self.right_x - self.left_x

    @property
    def vertical_range(self):
        return self.bottom_y - self.top_y

    def map_head(self, x, y, width, height, gain=1.0):
        if not valid_position((x, y)) or not all(
            isinstance(v, (int, float)) and math.isfinite(v) and v > 0
            for v in (width, height, gain)
        ):
            raise CalibrationError("Brak poprawnej pozycji głowy lub wymiarów ekranu.")
        rx = self.right_x - self.center_x if x >= self.center_x else self.center_x - self.left_x
        ry = self.bottom_y - self.center_y if y >= self.center_y else self.center_y - self.top_y
        nx = 0.5 + 0.5 * (x - self.center_x) / rx * gain
        ny = 0.5 + 0.5 * (y - self.center_y) / ry * gain
        return (min(1.0, max(0.0, nx)) * (width - 1), min(1.0, max(0.0, ny)) * (height - 1))


@dataclass(frozen=True)
class HeadSample:
    session_id: int
    position: tuple[float, float] | None
    captured_at: float


def default_calibration_path():
    return (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config"))
        / "AeroAssist"
        / "calibration.json"
    )


class CalibrationManager:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_calibration_path()
        self.active = None
        self.candidate = None
        self.points = {}
        self.current_point = None
        self.samples = deque(maxlen=MIN_SAMPLES)

    def begin(self):
        self.points.clear()
        self.candidate = None
        self.current_point = None
        self.samples.clear()

    def begin_step(self, point):
        if point not in POINTS:
            raise CalibrationError("Nieznany punkt kalibracji.")
        self.current_point = point
        self.points.pop(point, None)
        self.candidate = None
        self.samples.clear()

    def interrupt_step(self):
        self.samples.clear()

    def add_sample(self, position):
        if self.current_point is None or not valid_position(position):
            self.interrupt_step()
            return False
        self.samples.append(tuple(position))
        if len(self.samples) < MIN_SAMPLES:
            return False
        center = (median(p[0] for p in self.samples), median(p[1] for p in self.samples))
        if any(
            abs(p[axis] - center[axis]) > STABILITY_TOLERANCE
            for p in self.samples
            for axis in (0, 1)
        ):
            return False
        self.points[self.current_point] = center
        return True

    def calculate(self):
        if any(point not in self.points for point in POINTS):
            raise CalibrationError("Brakuje stabilnych pomiarów. Uzupełnij wszystkie pięć punktów.")
        center = self.points["center"]
        candidate = CalibrationParameters(
            center[0],
            center[1],
            self.points["left"][0],
            self.points["right"][0],
            self.points["top"][1],
            self.points["bottom"][1],
        )
        self.candidate = candidate
        return candidate

    def save(self, parameters):
        if not isinstance(parameters, CalibrationParameters):
            raise CalibrationError("Brak poprawnej kalibracji do zapisania.")
        payload = json.dumps(
            {"version": 1, "parameters": asdict(parameters)}, allow_nan=False, indent=2
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.active = parameters

    def load(self):
        try:
            if self.path.stat().st_size > 4096:
                raise ValueError("Calibration file exceeds size limit")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or set(data) != {"version", "parameters"}
                or type(data["version"]) is not int
                or data["version"] != 1
                or not isinstance(data["parameters"], dict)
            ):
                raise ValueError("Unsupported calibration schema")
            self.active = CalibrationParameters(**data["parameters"])
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            logger.warning("Unable to load valid calibration parameters", exc_info=True)
        return self.active

    def restore_defaults(self):
        self.path.unlink(missing_ok=True)
        self.active = None
        self.begin()
