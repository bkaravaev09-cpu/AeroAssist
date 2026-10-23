"""Replace hardware boundaries before importing any application modules."""

import ctypes
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

for name in ("customtkinter", "cv2", "mediapipe", "winsound", "pyautogui", "pyttsx3"):
    sys.modules[name] = MagicMock(name=name)
sys.modules["customtkinter"].CTk = type("HeadlessWindow", (), {})
ctypes.windll = SimpleNamespace(user32=MagicMock())
ctypes.windll.user32.GetSystemMetrics.side_effect = lambda axis: (1920, 1080)[axis]

import main  # noqa: E402


@pytest.fixture
def app():
    instance = main.AeroAssistApp.__new__(main.AeroAssistApp)
    instance.title = MagicMock()
    instance.geometry = MagicMock()
    instance.resizable = MagicMock()
    instance.protocol = MagicMock()
    instance._build_ui = MagicMock()
    instance.after = MagicMock()
    instance.__init__()
    instance.btn_toggle = MagicMock()
    instance.label_status = MagicMock()
    instance.tracker = MagicMock()
    instance.assistant = MagicMock()
    instance.after.reset_mock()
    instance.destroy = MagicMock()
    return instance
