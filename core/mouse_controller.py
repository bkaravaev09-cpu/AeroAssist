import pyautogui

# Отключаем сбой при попадании курсора в угол экрана
pyautogui.FAILSAFE = False


class MouseController:
    def __init__(self, smoothing_factor=0.25):
        self.screen_w, self.screen_h = pyautogui.size()
        self.smoothing = smoothing_factor
        self.prev_x, self.prev_y = self.screen_w // 2, self.screen_h // 2

    def move(self, target_norm_x, target_norm_y):
        target_x = int(target_norm_x * self.screen_w)
        target_y = int(target_norm_y * self.screen_h)

        # Экспоненциальное сглаживание: new = prev + alpha * (target - prev)
        curr_x = self.prev_x + self.smoothing * (target_x - self.prev_x)
        curr_y = self.prev_y + self.smoothing * (target_y - self.prev_y)

        pyautogui.moveTo(curr_x, curr_y)
        self.prev_x, self.prev_y = curr_x, curr_y

    def click(self, button="left"):
        pyautogui.click(button=button)
