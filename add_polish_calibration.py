with open('main.py', 'r', encoding='utf-8') as f:
    c = f.read()

# Add Polish calibration button after btn_toggle
old = '        self.btn_toggle.pack(pady=10, padx=40, fill="x")\n'
new = '''        self.btn_toggle.pack(pady=10, padx=40, fill="x")

        # Polish calibration button - new feature
        self.btn_calibration = ctk.CTkButton(
            content,
            text="Kalibracja kursora",
            command=self.calibrate_cursor,
            height=38,
            fg_color="#27ae60",
            hover_color="#2ecc71",
            font=("Arial", 13, "bold"),
        )
        self.btn_calibration.pack(pady=5, padx=40, fill="x")
'''

c = c.replace(old, new)

# Replace info box text with Polish only
old_info = '"Status: Zatrzymany"'
new_info = '"Status: Zatrzymany"'
# Already Polish, but let's make sure all UI text is Polish
old_hint = 'Czućło kursora'
new_hint = 'Czułość kursora'
c = c.replace(old_hint, new_hint)
# Fix any mixed text in info_box
old_text = 'Wygładzanie ruchu (więcej = płycej)'
new_text = 'Wygładzanie ruchu (więcej = płynniej)'
c = c.replace(old_text, new_text)

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(c)

print('Polish calibration button added')
