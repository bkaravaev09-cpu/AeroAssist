"""On-screen keyboard for accessibility - fixed version."""

import ctypes
import time
from ctypes import wintypes

import customtkinter as ctk

user32 = ctypes.windll.user32


# ----------------- Win32 SendInput (Unicode) -----------------
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _anonymous_ = ("_union",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("_union", _INPUT_UNION),
    ]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004


def send_unicode_char(char):
    """Send Unicode character via Win32 SendInput (works with RU/EN)."""
    code = ord(char)
    inputs = (INPUT * 2)()
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].ki.wVk = 0
    inputs[0].ki.wScan = code
    inputs[0].ki.dwFlags = KEYEVENTF_UNICODE
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].ki.wVk = 0
    inputs[1].ki.wScan = code
    inputs[1].ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))


def send_special_key(vk_code):
    """Send special key via Win32 SendInput (Backspace, Enter, Space)."""
    inputs = (INPUT * 2)()
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].ki.wVk = vk_code
    inputs[0].ki.wScan = 0
    inputs[0].ki.dwFlags = 0
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].ki.wVk = vk_code
    inputs[1].ki.wScan = 0
    inputs[1].ki.dwFlags = KEYEVENTF_KEYUP
    user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))


class OnScreenKeyboard(ctk.CTkToplevel):
    """Large-key on-screen keyboard with visual feedback for eye-tracking users."""

    def __init__(self, master=None):
        super().__init__(master)

        self.title("AeroAssist Keyboard")
        self.attributes("-topmost", True)
        self.overrideredirect(True)
        self.resizable(False, False)

        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        kb_w, kb_h = 1000, 320
        pos_x = (screen_w - kb_w) // 2
        pos_y = screen_h - kb_h - 30
        self.geometry(f"{kb_w}x{kb_h}+{pos_x}+{pos_y}")

        self.configure(fg_color="#181818")
        self.current_lang = "RU"
        self.rows_frame = None
        self.active_button = None  # Track which button is pressed for visual feedback

        self._set_no_activate()
        self._target_hwnd = user32.GetForegroundWindow()
        self._render_keyboard()

    def _set_no_activate(self):
        """Keep focus on the app behind the keyboard (no window stealing)."""
        self.update_idletasks()
        hwnd = user32.GetParent(self.winfo_id()) or self.winfo_id()
        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOPMOST = 0x00000008
        current_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, current_style | WS_EX_NOACTIVATE | WS_EX_TOPMOST)

    def toggle_language(self):
        self.current_lang = "EN" if self.current_lang == "RU" else "RU"
        self._render_keyboard()

    def _highlight_button(self, btn, color="#4a9eff", duration_ms=150):
        """Visual feedback: flash button when pressed."""
        original = btn.cget("fg_color")
        btn.configure(fg_color=color)
        self.after(duration_ms, lambda: btn.configure(fg_color=original))

    def _restore_target_focus(self):
        """Return keyboard focus to the window that had it before the OSK opened."""
        osk_hwnd = user32.GetParent(self.winfo_id()) or self.winfo_id()
        current = user32.GetForegroundWindow()
        if current == osk_hwnd:
            target = getattr(self, "_target_hwnd", None)
            if target and user32.IsWindow(target):
                user32.SetForegroundWindow(target)
                time.sleep(0.03)

    def _handle_key_click(self, key, btn=None):
        """Handle key press with OSK focus management."""
        self._restore_target_focus()
        if btn is not None:
            self._highlight_button(btn)
        if key == "CLOSE":
            self.destroy()
        elif key == "LANG":
            self.toggle_language()
        elif key == "BKSP":
            send_special_key(0x08)
        elif key == "ENTER":
            send_special_key(0x0D)
        elif key == "SPACE":
            send_special_key(0x20)
        else:
            send_unicode_char(key.lower())

    def _render_keyboard(self):
        if self.rows_frame:
            self.rows_frame.destroy()

        self.rows_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.rows_frame.pack(fill="both", expand=True, padx=6, pady=6)

        if self.current_lang == "RU":
            layout = [
                ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "BKSP"],
                ["Ё", "Й", "Ц", "У", "К", "Е", "Н", "Г", "Ш", "Щ", "З", "Х", "Ъ"],
                ["Ф", "Ы", "В", "А", "П", "Р", "О", "Л", "Д", "Ж", "Э", "ENTER"],
                ["LANG", "Я", "Ч", "С", "М", "И", "Т", "Ь", "Б", "Ю", "SPACE", "CLOSE"],
            ]
        else:
            layout = [
                ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "BKSP"],
                ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
                ["A", "S", "D", "F", "G", "H", "J", "K", "L", "ENTER"],
                ["LANG", "Z", "X", "C", "V", "B", "N", "M", "SPACE", "CLOSE"],
            ]

        for row in layout:
            row_frame = ctk.CTkFrame(self.rows_frame, fg_color="transparent")
            row_frame.pack(pady=2, fill="x")

            for key in row:
                # Large buttons for eye-tracking precision
                btn_w = 70
                color = "#2a2a2a"
                hover = "#3d3d3d"
                btn_text = key

                if key == "LANG":
                    btn_text = f"ЯЗЫК {self.current_lang}"
                    btn_w = 90
                    color = "#1f618d"
                    hover = "#2874a6"
                elif key == "SPACE":
                    btn_w = 200
                elif key in ("BKSP", "ENTER"):
                    btn_w = 100
                    color = "#2e4053"
                    hover = "#34495e"
                elif key == "CLOSE":
                    btn_w = 90
                    color = "#7b241c"
                    hover = "#922b21"

                btn = ctk.CTkButton(
                    row_frame,
                    text=btn_text,
                    width=btn_w,
                    height=52,
                    font=("Arial", 14, "bold"),
                    fg_color=color,
                    hover_color=hover,
                    command=lambda k=key, b=None: self._handle_key_click(k, b),
                )
                btn.pack(side="left", padx=3, pady=2, expand=(key == "SPACE"))

    def destroy(self):
        """Safe destroy with visual cleanup."""
        try:
            super().destroy()
        except Exception:
            pass
