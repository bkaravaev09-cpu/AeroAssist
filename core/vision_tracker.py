import cv2
import mediapipe as mp
import pyautogui
import numpy as np
import time

pyautogui.FAILSAFE = False

class VisionTracker:
    def __init__(self):
        self.screen_w, self.screen_h = pyautogui.size()
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        
        # Виртуальные координаты курсора
        self.cur_x = self.screen_w // 2
        self.cur_y = self.screen_h // 2
        self.accum_drift_x = 0.0
        self.accum_drift_y = 0.0
        
        self.smoothing = 0.25
        self.sensitivity = 1.9
        
        # Джойстик-зона у краев
        self.edge_threshold_x = 0.07
        self.edge_threshold_y = 0.06
        self.drift_speed = 22.0
        
        # Адаптивный порог EAR
        self.calibration_frames = []
        self.blink_threshold = 0.15
        self.is_calibrated = False
        
        # Ассистент (> 1.5 сек закрытия обоих глаз)
        self.eyes_closed_start = None
        self.assistant_triggered = False

        # Экстренный выход (4 моргания)
        self.both_eyes_was_closed = False
        self.blink_timestamps = []
        self.max_blink_window = 2.8
        self.last_blink_registered = 0

    def calculate_ear(self, landmarks, top_idx, bot_idx, left_idx, right_idx):
        top = np.array([landmarks[top_idx].x, landmarks[top_idx].y])
        bot = np.array([landmarks[bot_idx].x, landmarks[bot_idx].y])
        left = np.array([landmarks[left_idx].x, landmarks[left_idx].y])
        right = np.array([landmarks[right_idx].x, landmarks[right_idx].y])
        
        vertical = np.linalg.norm(top - bot)
        horizontal = np.linalg.norm(left - right)
        return vertical / (horizontal + 1e-6)

    def process_frame(self, frame, on_assistant_trigger=None, on_shutdown_trigger=None):
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(frame_rgb)

        if not results.multi_face_landmarks:
            return

        landmarks = results.multi_face_landmarks[0].landmark
        now = time.time()

        # Вычисление EAR
        left_ear = self.calculate_ear(landmarks, 159, 145, 33, 133)
        right_ear = self.calculate_ear(landmarks, 386, 374, 362, 263)
        avg_ear = (left_ear + right_ear) / 2.0

        # Автокалибровка под разрез глаз
        if not self.is_calibrated:
            self.calibration_frames.append(avg_ear)
            if len(self.calibration_frames) >= 25:
                normal_open_ear = np.median(self.calibration_frames)
                self.blink_threshold = normal_open_ear * 0.65
                self.is_calibrated = True
                print(f"[КАЛИБРОВКА] Базовый EAR: {normal_open_ear:.4f} | Порог моргания: {self.blink_threshold:.4f}")

        left_closed = left_ear < self.blink_threshold
        right_closed = right_ear < self.blink_threshold
        both_closed = left_closed and right_closed

        # 1. Распознавание 4 быстрых морганий (Выход)
        if both_closed:
            if not self.both_eyes_was_closed and (now - self.last_blink_registered > 0.18):
                self.both_eyes_was_closed = True
                self.last_blink_registered = now
                self.blink_timestamps.append(now)
                self.blink_timestamps = [t for t in self.blink_timestamps if now - t <= self.max_blink_window]
                print(f"[ДЕТЕКТОР] Моргание зафиксировано: {len(self.blink_timestamps)}/4")

                if len(self.blink_timestamps) >= 4:
                    print("[СИСТЕМА] Сработало 4 моргания — выход!")
                    self.blink_timestamps.clear()
                    if on_shutdown_trigger:
                        on_shutdown_trigger()
                    return
        else:
            self.both_eyes_was_closed = False

        # 2. Долгое закрытие обоих глаз (> 1.5 сек) -> Ассистент
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

        # 3. Движение головы и непрерывный дрейф джойстика
        nose = landmarks[4]
        offset_x = nose.x - 0.5
        offset_y = nose.y - 0.5

        if abs(offset_x) > self.edge_threshold_x:
            sign = 1 if offset_x > 0 else -1
            factor = (abs(offset_x) - self.edge_threshold_x) / 0.08
            self.accum_drift_x += sign * self.drift_speed * max(1.0, factor)

        if abs(offset_y) > self.edge_threshold_y:
            sign = 1 if offset_y > 0 else -1
            factor = (abs(offset_y) - self.edge_threshold_y) / 0.08
            self.accum_drift_y += sign * self.drift_speed * max(1.0, factor)

        target_x = (offset_x * self.sensitivity * self.screen_w + self.screen_w / 2) + self.accum_drift_x
        target_y = (offset_y * self.sensitivity * self.screen_h + self.screen_h / 2) + self.accum_drift_y

        self.cur_x += (target_x - self.cur_x) * self.smoothing
        self.cur_y += (target_y - self.cur_y) * self.smoothing

        final_x = int(np.clip(self.cur_x, 0, self.screen_w - 1))
        final_y = int(np.clip(self.cur_y, 0, self.screen_h - 1))
        self.cur_x, self.cur_y = final_x, final_y

        pyautogui.moveTo(final_x, final_y)

        # 4. Единственный клик: подмигивание левым глазом
        if left_closed and not right_closed:
            pyautogui.click()
            time.sleep(0.3)