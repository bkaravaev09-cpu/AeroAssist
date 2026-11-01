with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add visual hint overlay text after info_box
hint_text = '''
        # Visual gesture hints (Phase 4)
        self.gesture_hint = ctk.CTkLabel(
            content,
            text="💡 Подсказки: Левое моргание = клик | 4 моргания = пауза | Глаза >1.5с = голос",
            text_color="#50e3c2",
            font=("Arial", 11, "bold"),
        )
        self.gesture_hint.pack(pady=5, padx=30, fill="x")
'''

# Insert after info_box.configure
content = content.replace('        self.info_box.configure(state="disabled")', '        self.info_box.configure(state="disabled")\n' + hint_text)

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Visual hint added")
