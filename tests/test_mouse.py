from unittest.mock import patch

from core import mouse_controller as mouse


def test_cursor_smoothing_and_click_forwarding():
    with (
        patch.object(mouse.pyautogui, "size", return_value=(1000, 800)),
        patch.object(mouse.pyautogui, "moveTo") as move,
        patch.object(mouse.pyautogui, "click") as click,
    ):
        controller = mouse.MouseController(smoothing_factor=0.5)
        controller.move(1.0, 0.0)
        move.assert_called_once_with(750.0, 200.0)
        assert (controller.prev_x, controller.prev_y) == (750.0, 200.0)
        controller.click("right")
        click.assert_called_once_with(button="right")
