with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Insert callback after line 31 (index 30)
lines.insert(31, '        self.assistant.set_keyboard_callback(self._keyboard_action_from_voice)\n')

# Add method after line 49 (before _poll_worker_events or somewhere safe)
# Find a safe insertion point - after _build_ui or after reset_cursor_settings
method = '''
    def _keyboard_action_from_voice(self, action, *args):
        """Safe callback from voice thread to execute keyboard actions on GUI thread."""
        def run_action():
            if action == "toggle":
                self.toggle_keyboard_ui()
            elif action == "close":
                if hasattr(self, 'keyboard_window') and self.keyboard_window is not None:
                    try:
                        self.keyboard_window.destroy()
                    except Exception:
                        pass
                    self.keyboard_window = None
            elif action == "language":
                if hasattr(self, 'keyboard_window') and self.keyboard_window is not None:
                    try:
                        self.keyboard_window.toggle_language()
                    except Exception:
                        pass
        self.after(0, run_action)

'''

# Find line with "def toggle_keyboard_ui" - insert before it?
# Let's insert after the class definition or near the top methods
# Actually, insert right after the class definition (before any method)
# But easiest: find the line with "def _poll_worker_events" and insert before it
for i, line in enumerate(lines):
    if 'def _poll_worker_events' in line:
        lines.insert(i, method)
        break

with open('main.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("Done")
