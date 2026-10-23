import ctypes
import time
from ctypes import wintypes

import cv2
import mediapipe as mp
import numpy as np

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


def win32_move(x, y):
    user32.SetCursorPos(int(x), int(y))


def win32_click():
    """Аппаратный клик через SendInput, пробивающий системные окна и osk.exe"""
    inp_down = INPUT()
    inp_down.type = INPUT_MOUSE
    inp_down.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
    user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))

    time.sleep(0.06)

    inp_up = INPUT()
    inp_up.type = INPUT_MOUSE
    inp_up.mi.dwFlags = MOUSEEVENTF_LEFTUP
    user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))


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

        self.cur_x = float(self.screen_w // 2)
        self.cur_y = float(self.screen_h // 2)
        self.accum_drift_x = 0.0
        self.accum_drift_y = 0.0

        # Сглаживание и джойстик-зона
        self.smoothing = 0.26
        self.edge_threshold_x = 0.07
        self.edge_threshold_y = 0.06
        self.drift_speed = 18.0

        # Автокалибровка
        self.calibration_ear = []
        self.calibration_nose_x = []
        self.calibration_nose_y = []
        self.center_x = 0.5
        self.center_y = 0.55
        self.blink_threshold = 0.15
        self.is_calibrated = False

        # Debounce кликов левым глазом
        self.left_eye_was_closed = False
        self.last_click_time = 0.0

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

    def _apply_curve(self, offset, is_upward=False):
        """Нелинейная кривая: высокая точность в центре + комфортный ход к краям"""
        sign = 1.0 if offset >= 0 else -1.0
        abs_off = abs(offset)

        # Зона мелких точных движений
        if abs_off < 0.015:
            return offset * 0.9

        if is_upward:
            scaled = (abs_off**1.25) * 2.3
            return sign * scaled
        else:
            scaled = (abs_off**1.15) * 1.9
            return sign * scaled

    def process_frame(self, frame, on_assistant_trigger=None, on_shutdown_trigger=None):
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(frame_rgb)
        self._preview_landmarks = None

        if not results.multi_face_landmarks:
            return

        landmarks = results.multi_face_landmarks[0].landmark
        self._preview_landmarks = landmarks
        now = time.time()

        nose = landmarks[4]
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
        raw_offset_x = nose.x - self.center_x
        raw_offset_y = nose.y - self.center_y

        norm_curve_x = self._apply_curve(raw_offset_x, is_upward=False)
        norm_curve_y = self._apply_curve(raw_offset_y, is_upward=(raw_offset_y < 0))

        # Доводка джойстиком при наклонах головы
        if abs(raw_offset_x) > self.edge_threshold_x:
            sign = 1 if raw_offset_x > 0 else -1
            strength = (abs(raw_offset_x) - self.edge_threshold_x) / 0.07
            self.accum_drift_x += sign * self.drift_speed * max(1.0, strength)
        else:
            self.accum_drift_x *= 0.85

        if abs(raw_offset_y) > self.edge_threshold_y:
            sign = 1 if raw_offset_y > 0 else -1
            strength = (abs(raw_offset_y) - self.edge_threshold_y) / 0.07
            self.accum_drift_y += sign * self.drift_speed * max(1.0, strength)
        else:
            self.accum_drift_y *= 0.85

        base_x = norm_curve_x * self.screen_w + self.screen_w / 2
        base_y = norm_curve_y * self.screen_h + self.screen_h / 2

        target_x = base_x + self.accum_drift_x
        target_y = base_y + self.accum_drift_y

        # Обрезка дрейфа за экраном
        if target_x < 0:
            target_x = 0.0
            self.accum_drift_x = -base_x
        elif target_x > self.screen_w - 1:
            target_x = float(self.screen_w - 1)
            self.accum_drift_x = (self.screen_w - 1) - base_x

        # Обработка выдвижной нижней панели задач Windows
        if target_y >= self.screen_h - 4:
            target_y = float(self.screen_h - 1)
            self.accum_drift_y = (self.screen_h - 1) - base_y
        elif target_y < 0:
            target_y = 0.0
            self.accum_drift_y = -base_y

        self.cur_x += (target_x - self.cur_x) * self.smoothing
        self.cur_y += (target_y - self.cur_y) * self.smoothing

        send_y = int(self.cur_y)
        if target_y >= self.screen_h - 2 and (self.screen_h - 1 - send_y) < 15:
            send_y = self.screen_h - 1

        win32_move(int(self.cur_x), send_y)

        # 5. Одиночный клик левым глазом (SendInput)
        if left_closed and not right_closed:
            if not self.left_eye_was_closed and (now - self.last_click_time > 0.35):
                self.left_eye_was_closed = True
                self.last_click_time = now
                win32_click()
                print("[КЛИК] Левый клик по окну")
        else:
            self.left_eye_was_closed = False
