"""Visual calibration wizard - 5 points with dwell time."""
import ctypes

user32 = ctypes.windll.user32

STEPS = [
    ("1/5: Popatrz w CENTRUM ekranu i przytrzymaj 3 sekundy", 0.5, 0.55),
    ("2/5: Popatrz w LEWO i przytrzymaj 3 sekundy", 0.15, 0.55),
    ("3/5: Popatrz w PRAWO i przytrzymaj 3 sekundy", 0.85, 0.55),
    ("4/5: Popatrz w GÓRĘ i przytrzymaj 3 sekundy", 0.5, 0.15),
    ("5/5: Popatrz w DÓŁ i przytrzymaj 3 sekundy", 0.5, 0.85),
]


def calibrate_cursor_visual(master_app):

    import customtkinter as ctk

    step = 0

    def finish():
        dialog.destroy()
        master_app.tracker.configure_cursor(
            sensitivity=1.2, smoothing=0.85, dead_zone=8.0
        )
        master_app.label_status.configure(
            text="Kalibracja zakończona. Kursors ustawiony.",
            text_color="green"
        )

    def show_step():
        nonlocal step
        if step >= len(STEPS):
            finish()
            return
        label.configure(text=STEPS[step][0])
        # Show green dot
        dot.configure(text="●", text_color="#00ff00")
        master_app.after(3000, lambda: advance())

    def advance():
        nonlocal step
        step += 1
        show_step()

    dialog = ctk.CTkToplevel(master_app)
    dialog.title("Kalibracja kursora - 5 kroków")
    dialog.geometry("700x450")
    dialog.attributes("-topmost", True)
    dialog.configure(fg_color="#181818")

    ctk.CTkLabel(dialog, text="Kalibracja kursora — 5 punktów", font=("Arial", 18, "bold"), text_color="#2ecc71").pack(pady=15)
    label = ctk.CTkLabel(dialog, text=STEPS[0][0], font=("Arial", 16), wraplength=620)
    label.pack(pady=20)
    dot = ctk.CTkLabel(dialog, text="●", font=("Arial", 80, "bold"), text_color="#00ff00")
    dot.pack(pady=30)

    ctk.CTkButton(dialog, text="Rozpocznij kalibrację", command=lambda: show_step(), font=("Arial", 14, "bold")).pack(pady=10)

    master_app.calibration_dialog = dialog
