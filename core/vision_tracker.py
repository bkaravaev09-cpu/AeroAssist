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
        
        # Текущее виртуальное положение курсора
        self.cur_x = self.screen_w // 2
        self.cur_y = self.screen_h // 2
        
        self.smoothing = 0.28
        self.sensitivity = 2.0
        
        # Зона джойстика (доводка до краев экрана)
        self.edge_threshold_x = 0.08  # порог наклона головы от центра
        self.edge_threshold_y = 0.07
        self.drift_speed = 24         # скорость доводки (пикселей/кадр)
        
        # Пороги моргания
        self.blink_threshold = 0.22   # рабочий порог EAR для большинства веб-камер
        self.dwell_time = 0.9
        self.hover_start = None
        self.last_pos = (self.cur_x, self.cur_y)
        
        # Детектор ассистента (> 1.5 сек закрыты оба глаза)
        self.eyes_closed_start = None
        self.assistant_triggered = False

        # Детектор 4 морганий (выключение)
        self.both_eyes_was_closed = False
        self.blink_timestamps = []
        self.max_blink_window = 3.0   # 4 моргания за 3 секунды
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

        # 1. Вычисление EAR для обоих глаз
        # Левый глаз: 159 (верх), 145 (низ), 33 (внеш), 133 (внутр)
        # Правый глаз: 386 (верх), 374 (низ), 362 (внутр), 263 (внеш)
        left_ear = self.calculate_ear(landmarks, 159, 145, 33, 133)
        right_ear = self.calculate_ear(landmarks, 386, 374, 362, 263)

        left_closed = left_ear < self.blink_threshold
        right_closed = right_ear < self.blink_threshold
        both_closed = left_closed and right_closed

        # 2. Логика 4 морганий (Экстренное завершение)
        if both_closed:
            if not self.both_eyes_was_closed and (now - self.last_blink_registered > 0.15):
                self.both_eyes_was_closed = True
                self.last_blink_registered = now
                self.blink_timestamps.append(now)
                # Оставляем только моргания за последние 3 секунды
                self.blink_timestamps = [t for t in self.blink_timestamps if now - t <= self.max_blink_window]
                print(f"[ДЕТЕКТОР] Моргание зафиксировано: {len(self.blink_timestamps)}/4")

                if len(self.blink_timestamps) >= 4:
                    print("[СИСТЕМА] Сработало 4 моргания — завершение работы!")
                    self.blink_timestamps.clear()
                    if on_shutdown_trigger:
                        on_shutdown_trigger()
                    return
        else:
            self.both_eyes_was_closed = False

        # 3. Удержание обоих глаз закрытыми (> 1.5 сек) -> Ассистент
        if both_closed:
            if self.eyes_closed_start is None:
                self.eyes_closed_start = now
            elif (now - self.eyes_closed_start > 1.5) and not self.assistant_triggered:
                self.assistant_triggered = True
                print("[ГОЛОС] Удержание глаз обнаружено -> запуск ассистента")
                if on_assistant_trigger:
                    on_assistant_trigger()
        else:
            self.eyes_closed_start = None
            self.assistant_triggered = False

        # Если глаза закрыты для команд, курсор не двигаем
        if both_closed:
            return

        # 4. Движение носа и постоянная доводка к краям
        nose = landmarks[4]
        offset_x = nose.x - 0.5
        offset_y = nose.y - 0.5

        # Базовая цель по положению головы
        target_x = offset_x * self.sensitivity * self.screen_w + self.screen_w / 2
        target_y = offset_y * self.sensitivity * self.screen_h + self.screen_h / 2

        # Сглаживание
        self.cur_x += (target_x - self.cur_x) * self.smoothing
        self.cur_y += (target_y - self.cur_y) * self.smoothing

        # Режим непрерывного сдвига (джойстик у краев)
        drift_active = False
        if abs(offset_x) > self.edge_threshold_x:
            sign = 1 if offset_x > 0 else -1
            strength = (abs(offset_x) - self.edge_threshold_x) / 0.08
            self.cur_x += sign * self.drift_speed * max(1.0, strength)
            drift_active = True

        if abs(offset_y) > self.edge_threshold_y:
            sign = 1 if offset_y > 0 else -1
            strength = (abs(offset_y) - self.edge_threshold_y) / 0.08
            self.cur_y += sign * self.drift_speed * max(1.0, strength)
            drift_active = True

        # Ограничение экраном
        final_x = int(np.clip(self.cur_x, 0, self.screen_w - 1))
        final_y = int(np.clip(self.cur_y, 0, self.screen_h - 1))
        pyautogui.moveTo(final_x, final_y)

        # 5. Клик подмигиванием левого глаза
        if left_closed and not right_closed:
            pyautogui.click()
            time.sleep(0.25)
            return

        # 6. Dwell-клик (клик при фиксации взгляда на одном месте)
        cur_pos = (final_x, final_y)
        dist = np.linalg.norm(np.array(cur_pos) - np.array(self.last_pos))
        if dist < 14 and not drift_active:
            if self.hover_start is None:
                self.hover_start = now
            elif now - self.hover_start > self.dwell_time:
                pyautogui.click()
                self.hover_start = None
        else:
            self.hover_start = now
        self.last_pos = cur_pos