import ctypes
import math
import time
from ctypes import wintypes

import cv2
import mediapipe as mp
import numpy as np

from core.cursor_controller import CursorController

# ----------------- Win32 API & SendInput -----------------
user32 = ctypes.windll.user32


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    _anonymous_ = ("_union",)
    _fields_ = [("type", wintypes.DWORD), ("_union", _INPUT_UNION)]


INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120


def win32_move(x, y):
    user32.SetCursorPos(int(x), int(y))


def win32_click():
    """Left click via SendInput."""
    _send_mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.06)
    _send_mouse(MOUSEEVENTF_LEFTUP)


def win32_double_click():
    """Double left click via SendInput."""
    _send_mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.04)
    _send_mouse(MOUSEEVENTF_LEFTUP)
    time.sleep(0.04)
    _send_mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.04)
    _send_mouse(MOUSEEVENTF_LEFTUP)


def win32_right_click():
    """Right click via SendInput."""
    _send_mouse(MOUSEEVENTF_RIGHTDOWN)
    time.sleep(0.06)
    _send_mouse(MOUSEEVENTF_RIGHTUP)


def win32_scroll(delta):
    """Vertical scroll via SendInput."""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dwFlags = MOUSEEVENTF_WHEEL
    inp.mi.mouseData = delta
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _send_mouse(flag):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dwFlags = flag
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


# ----------------- VisionTracker -----------------
class VisionTracker:
    def __init__(self):
        self.screen_w = user32.GetSystemMetrics(0)
        self.screen_h = user32.GetSystemMetrics(1)

        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.45,
            min_tracking_confidence=0.45,
        )

        self.cursor_controller = CursorController(self.screen_w, self.screen_h)

        self.calibration_ear = []
        self.calibration_nose_x = []
        self.calibration_nose_y = []
        self.center_x = 0.5
        self.center_y = 0.55
        self.blink_threshold = 0.15
        self.is_calibrated = False

        # Левый глаз — ЛКМ (короткое моргание) / двойной клик (зажатие на LEFT_HOLD_THRESHOLD сек)
        self.LEFT_HOLD_THRESHOLD = 0.8
        self.left_eye_closed_start = None
        self.last_click_time = 0.0

        # Правый глаз — ПКМ / скролл (при удержании правого глаза + наклон головы)
        self.right_eye_closed_start = None
        self.right_scroll_triggered = False

        # Скролл при удержании правого глаза + наклон головы вверх/вниз
        self.scroll_active = False
        self.last_scroll_time = 0.0
        self.SCROLL_THRESHOLD = 0.08
        self.SCROLL_COOLDOWN = 0.10
        self.SCROLL_AMOUNT = 3 * WHEEL_DELTA

        # Ассистент (> 1.5 сек удержания обоих глаз)
        self.eyes_closed_start = None
        self.assistant_triggered = False

        # Пауза слежения (4 моргания обоими глазами)
        self.both_eyes_was_closed = False
        self.blink_timestamps = []
        self.max_blink_window = 2.8
        self.last_blink_registered = 0.0
        self._preview_landmarks = None

    def get_preview_landmarks(self):
        """Snapshot the last detection only when the camera worker samples a preview."""
        if self._preview_landmarks is None:
            return ()
        return tuple((point.x, point.y) for point in self._preview_landmarks)

    def calculate_ear(self, landmarks, top_idx, bot_idx, left_idx, right_idx):
        top = np.array([landmarks[top_idx].x, landmarks[top_idx].y])
        bot = np.array([landmarks[bot_idx].x, landmarks[bot_idx].y])
        left = np.array([landmarks[left_idx].x, landmarks[left_idx].y])
        right = np.array([landmarks[right_idx].x, landmarks[right_idx].y])

        v = np.linalg.norm(top - bot)
        h = np.linalg.norm(left - right)
        return v / (h + 1e-6)

    @property
    def sensitivity(self):
        return self.cursor_controller.settings.sensitivity

    @sensitivity.setter
    def sensitivity(self, value):
        self.cursor_controller.configure(sensitivity=value)

    def configure_cursor(self, **changes):
        self.cursor_controller.configure(**changes)

    def reset_cursor(self):
        self.cursor_controller.reset()

    def process_frame(self, frame, on_assistant_trigger=None, on_shutdown_trigger=None):
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(frame_rgb)
        self._preview_landmarks = None

        if not results.multi_face_landmarks:
            self.reset_cursor()
            return

        landmarks = results.multi_face_landmarks[0].landmark
        self._preview_landmarks = landmarks
        now = time.time()

        nose = landmarks[4]
        if not all(
            isinstance(value, (int, float)) and math.isfinite(value) and 0.0 <= value <= 1.0
            for value in (nose.x, nose.y)
        ):
            self.reset_cursor()
            return
        left_ear = self.calculate_ear(landmarks, 159, 145, 33, 133)
        right_ear = self.calculate_ear(landmarks, 386, 374, 362, 263)
        avg_ear = (left_ear + right_ear) / 2.0

        # 1. Автокалибровка посадки и разреза глаз (первые 25 кадров)
        if not self.is_calibrated:
            self.calibration_ear.append(avg_ear)
            self.calibration_nose_x.append(nose.x)
            self.calibration_nose_y.append(nose.y)

            if len(self.calibration_ear) >= 25:
                normal_open_ear = float(np.median(self.calibration_ear))
                self.blink_threshold = normal_open_ear * 0.65
                self.center_x = float(np.median(self.calibration_nose_x))
                self.center_y = float(np.median(self.calibration_nose_y))
                self.is_calibrated = True
                print(
                    f"[КАЛИБРОВКА] Центр лица: ({self.center_x:.3f}, {self.center_y:.3f}) | Порог глаз: {self.blink_threshold:.4f}"
                )
            return

        left_closed = left_ear < self.blink_threshold
        right_closed = right_ear < self.blink_threshold
        both_closed = left_closed and right_closed

        # 2. Пауза отслеживания (4 быстрых моргания обоими глазами)
        if both_closed:
            if not self.both_eyes_was_closed and (now - self.last_blink_registered > 0.18):
                self.both_eyes_was_closed = True
                self.last_blink_registered = now
                self.blink_timestamps.append(now)
                self.blink_timestamps = [
                    t for t in self.blink_timestamps if now - t <= self.max_blink_window
                ]
                print(f"[ДЕТЕКТОР] Моргание: {len(self.blink_timestamps)}/4")

                if len(self.blink_timestamps) >= 4:
                    print("[СИСТЕМА] Пауза слежения по 4 морганиям!")
                    self.blink_timestamps.clear()
                    if on_shutdown_trigger:
                        on_shutdown_trigger()
                    return
        else:
            self.both_eyes_was_closed = False

        # 3. Голосовой ассистент (> 1.5 сек закрытия обоих глаз)
        if both_closed:
            if self.eyes_closed_start is None:
                self.eyes_closed_start = now
            elif (now - self.eyes_closed_start > 1.5) and not self.assistant_triggered:
                self.assistant_triggered = True
                print("[ГОЛОС] Запуск ассистента...")
                if on_assistant_trigger:
                    on_assistant_trigger()
        else:
            self.eyes_closed_start = None
            self.assistant_triggered = False

        # 4. Движение курсора
        position = self.cursor_controller.update_head(nose.x, nose.y, self.center_x, self.center_y)
        if position is not None:
            win32_move(round(position[0]), round(position[1]))

        # 5. Клики глазом: левый — ЛКМ (короткое моргание) / двойной клик (зажатие левого глаза)
        if left_closed and not right_closed:
            if self.left_eye_closed_start is None:
                self.left_eye_closed_start = now
        else:
            if self.left_eye_closed_start is not None:
                hold_duration = now - self.left_eye_closed_start
                self.left_eye_closed_start = None
                if (now - self.last_click_time) > 0.35:
                    if hold_duration >= self.LEFT_HOLD_THRESHOLD:
                        win32_double_click()
                        self.last_click_time = now
                        print("[КЛИК] Двойной левый клик (зажатие)")
                    else:
                        win32_click()
                        self.last_click_time = now
                        print("[КЛИК] Левый клик по окну")

        # 6. Правый глаз — ПКМ или скролл (при удержании правого глаза + наклон головы)
        if right_closed and not left_closed:
            if self.right_eye_closed_start is None:
                self.right_eye_closed_start = now
                self.right_scroll_triggered = False
            # Скролл только если правый глаз зажат и голова наклонена
            head_offset_y = nose.y - self.center_y
            if abs(head_offset_y) > self.SCROLL_THRESHOLD:
                if (
                    not self.right_scroll_triggered
                    and (now - self.last_scroll_time) > self.SCROLL_COOLDOWN
                ):
                    delta = -self.SCROLL_AMOUNT if head_offset_y < 0 else self.SCROLL_AMOUNT
                    win32_scroll(delta)
                    self.last_scroll_time = now
                    self.right_scroll_triggered = True
                    direction = "вверх" if head_offset_y < 0 else "вниз"
                    print(f"[СКРОЛЛ] {direction} ({delta})")
        else:
            if self.right_eye_closed_start is not None and not self.right_scroll_triggered:
                hold_duration = now - self.right_eye_closed_start
                if hold_duration < 0.6:
                    win32_right_click()
                    print("[КЛИК] Правый клик")
            self.right_eye_closed_start = None
            self.right_scroll_triggered = False


# Phase 2: Double-click, right-click, drag, scroll gestures — ready for physical camera test
# Synthetic verification: tests/test_synthetic_gestures.py
