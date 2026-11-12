"""Cursor-feel profile from the stability test: smoothing, dead zone and sensitivity.

The five-point calibration (core.calibration) decides *where* the cursor goes.
This profile decides *how* it gets there. Sensitivity is only tuned when no
five-point calibration is active, because a calibrated mapping already spans
the screen and extra gain would push the cursor to the edges too early.
"""

import json
import logging
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from core.cursor_controller import CursorSettings

logger = logging.getLogger(__name__)

AMPLITUDE_TARGET = 0.15
MIN_STABILITY_SAMPLES = 10


@dataclass(frozen=True)
class CursorProfile:
    smoothing: float
    dead_zone: float
    sensitivity: float | None = None

    def __post_init__(self):
        # Reuse the controller's own limits so a profile can never be rejected later.
        CursorSettings(
            sensitivity=1.9 if self.sensitivity is None else self.sensitivity,
            smoothing=self.smoothing,
            dead_zone=self.dead_zone,
        )

    def cursor_changes(self):
        changes = {"smoothing": self.smoothing, "dead_zone": self.dead_zone}
        if self.sensitivity is not None:
            changes["sensitivity"] = self.sensitivity
        return changes


def _spread(values, pct=95):
    """Robust spread: distance between the percentile and the median."""
    if len(values) < 2:
        return 0.0
    ordered = sorted(values)
    last = len(ordered) - 1
    median = ordered[len(ordered) // 2]
    return abs(ordered[min(last, max(0, round(pct / 100 * last)))] - median)


def measure_jitter(samples):
    xs = [sample[0] for sample in samples]
    ys = [sample[1] for sample in samples]
    return (_spread(xs) + _spread(ys)) / 2.0


def compute_profile(stability_samples, peak=None, fine_mode=False):
    """Build a profile; ``peak`` is the head amplitude, or None to keep sensitivity."""
    if len(stability_samples) < MIN_STABILITY_SAMPLES:
        raise ValueError("Not enough stability samples")
    jitter = measure_jitter(stability_samples)
    smoothing = max(0.55, min(0.95, 0.70 + jitter * 25.0))
    dead_zone = max(1.0, min(10.0, 1.5 + jitter * 60.0))
    if fine_mode:
        smoothing = min(smoothing, 0.90)
        dead_zone = min(dead_zone, 6.0)
    sensitivity = None
    if peak is not None:
        sensitivity = max(1.0, min(3.0, AMPLITUDE_TARGET / max(peak, 1e-3)))
        if fine_mode:
            sensitivity = max(1.0, sensitivity * 0.6)
    return CursorProfile(smoothing=smoothing, dead_zone=dead_zone, sensitivity=sensitivity)


def default_profile_path():
    return (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config"))
        / "AeroAssist"
        / "cursor_profile.json"
    )


class CursorProfileStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_profile_path()

    def save(self, profile):
        payload = json.dumps({"version": 1, "profile": asdict(profile)}, allow_nan=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self):
        try:
            if self.path.stat().st_size > 4096:
                raise ValueError("Cursor profile exceeds size limit")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or data.get("version") != 1
                or not isinstance(data.get("profile"), dict)
            ):
                raise ValueError("Unsupported cursor profile schema")
            values = data["profile"]
            if not all(
                v is None or (isinstance(v, (int, float)) and math.isfinite(v))
                for v in values.values()
            ):
                raise ValueError("Invalid cursor profile values")
            return CursorProfile(**values)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError):
            logger.warning("Unable to load cursor profile", exc_info=True)
            return None

    def clear(self):
        self.path.unlink(missing_ok=True)
