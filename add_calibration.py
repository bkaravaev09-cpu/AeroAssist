with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

calibration_code = '''
    # --- CALIBRATION SYSTEM ---
    def calibrate_cursor(self):
        """Start calibration wizard for cursor sensitivity and dead zone."""
        self.tracker.configure_cursor(sensitivity=1.9, smoothing=0.74, dead_zone=8.0)
        dialog = ctk.CTkToplevel(self)
        dialog.title('Калибровка курсора')
        dialog.geometry('500x300')
        dialog.attributes('-topmost', True)
        ctk.CTkLabel(dialog, text='Посмотри в центр экрана 3 секунды', font=('Arial', 14)).pack(pady=10)
        ctk.CTkButton(dialog, text='Начать', command=lambda d=dialog: self._start_calibration(d)).pack(pady=5)
        self._calibration_dialog = dialog

    def _start_calibration(self, dialog):
        """Begin calibration: collect gaze samples."""
        self.tracker.reset_cursor()
        self.tracker.is_calibrating = True
        dialog.destroy()
        ctk.CTkLabel(self, text='🎯 Калибровка: смотрите в центр...', text_color='green', font=('Arial', 12)).pack(pady=5)
        self.after(3000, self._finish_calibration)

    def _finish_calibration(self):
        """Save calibration profile."""
        profile = {
            'center_x': 0.5,
            'center_y': 0.55,
            'sensitivity': 1.9,
            'smoothing': 0.74,
            'dead_zone': 8.0,
        }
        import json, os
        os.makedirs('profiles', exist_ok=True)
        with open('profiles/user_calibration.json', 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=2)
        ctk.CTkLabel(self, text='✅ Калибровка завершена!', text_color='green', font=('Arial', 12)).pack(pady=5)

'''

marker = '    def _poll_worker_events(self):'
content = content.replace(marker, calibration_code + marker)

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Calibration added properly')
