with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Import visual calibration
old_import = 'from core.voice_assistant import PolishVoiceAssistant'
new_import = 'from core.voice_assistant import PolishVoiceAssistant\nfrom core.visual_calibration import calibrate_cursor_visual'
content = content.replace(old_import, new_import)

# Fix calibration methods to use visual wizard
old_start = '        dialog = ctk.CTkToplevel(self)\n        dialog.title(\'Калибровка kursора\')'
new_start = '        calibrate_cursor_visual(self)\n        return\n        # Legacy simple dialog removed — using visual wizard'
content = content.replace(old_start, new_start)

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Visual calibration integrated')
