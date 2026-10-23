"""Replace hardware boundaries before importing any application modules."""

import ctypes
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import cv2 as opencv
import pytest

for name in ("customtkinter", "cv2", "mediapipe", "winsound", "pyautogui", "pyttsx3"):
    sys.modules[name] = MagicMock(name=name)
sys.modules["customtkinter"].CTk = type("HeadlessWindow", (), {})
sys.modules["customtkinter"].CTkFrame = type("HeadlessFrame", (), {})
ctypes.windll = SimpleNamespace(user32=MagicMock())
ctypes.windll.user32.GetSystemMetrics.side_effect = lambda axis: (1920, 1080)[axis]

import main  # noqa: E402


@pytest.fixture
def real_cv2():
    """Pure image operations are safe; capture access remains mocked."""
    return opencv


@pytest.fixture
def app():
    instance = main.AeroAssistApp.__new__(main.AeroAssistApp)
    instance.title = MagicMock()
    instance.geometry = MagicMock()
    instance.winfo_screenheight = MagicMock(return_value=1080)
    instance._get_window_scaling = MagicMock(return_value=1.0)
    instance.minsize = MagicMock()
    instance.resizable = MagicMock()
    instance.protocol = MagicMock()
    instance._build_ui = MagicMock()
    instance.after = MagicMock()
    instance.__init__()
    instance.btn_toggle = MagicMock()
    instance.label_status = MagicMock()
    instance.preview = MagicMock()
    instance.slider_sens = MagicMock()
    instance.slider_smoothing = MagicMock()
    instance.slider_dead_zone = MagicMock()
    instance.tracker = MagicMock()
    instance.assistant = MagicMock()
    instance.after.reset_mock()
    instance.destroy = MagicMock()
    return instance
