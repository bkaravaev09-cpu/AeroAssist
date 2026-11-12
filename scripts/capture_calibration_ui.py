"""Exercise and capture the real wizard using synthetic head samples, never devices."""

import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402
from core.calibration import MIN_SAMPLES, CalibrationManager, HeadSample  # noqa: E402
from scripts.capture_preview_ui import capture_window  # noqa: E402


def run():
    destination = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
    destination.mkdir(parents=True, exist_ok=True)
    errors = []
    with TemporaryDirectory() as temporary:
        manager = CalibrationManager(Path(temporary) / "calibration.json")

        def begin(app):
            app._tracking_state = "running"
            app._stop_event.clear()
            return True

        with (
            patch.object(main, "VisionTracker", return_value=MagicMock()),
            patch.object(main, "PolishVoiceAssistant", return_value=MagicMock()),
            patch.object(main, "CalibrationManager", return_value=manager),
            patch.object(main.AeroAssistApp, "_begin_calibration", begin),
        ):
            app = main.AeroAssistApp()
            app.report_callback_exception = lambda *args: errors.append(args)
            try:
                app.open_calibration()
                wizard = app.calibration_window
                wizard.report_callback_exception = lambda *args: errors.append(args)
                wizard.geometry("840x590+20+20")
                wizard.attributes("-topmost", True)
                capture_window(wizard, destination / "calibration-intro.png")
                wizard.focus_force()
                wizard.primary.focus_set()
                wizard.update()
                wizard.event_generate("<Return>")
                assert wizard.stage == "collecting"
                positions = ((0.5, 0.5), (0.4, 0.5), (0.65, 0.5), (0.5, 0.35), (0.5, 0.7))
                for step, position in enumerate(positions):
                    wizard.capture()
                    for index in range(MIN_SAMPLES):
                        wizard.receive_sample(
                            HeadSample(app._session_id, position, time.monotonic() + index * 0.001)
                        )
                    if step in (0, 1):
                        wizard.status.configure(text="Próbki testowe — bez użycia kamery")
                        capture_window(wizard, destination / f"calibration-point-{step}.png")
                    wizard.advance()
                assert wizard.stage == "preview"
                capture_window(wizard, destination / "calibration-preview.png")
                wizard.save_button.focus_set()
                wizard.update()
                wizard.event_generate("<Return>")
                assert manager.active is not None and manager.path.exists()
                assert not errors, errors
                print(
                    "Synthetic Windows wizard check passed: five points, preview and save; no camera or mouse used."
                )
            finally:
                app.close()


if __name__ == "__main__":
    run()
