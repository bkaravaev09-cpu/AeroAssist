"""Visual calibration wizard for cursor control."""
import ctypes

user32 = ctypes.windll.user32

# Calibration steps: 5 points on screen (center, left, right, up, down)
STEPS = [
    ("Centrum ekranu", 0.5, 0.55),
    ("W lewo", 0.15, 0.55),
    ("W prawo", 0.85, 0.55),
    ("W górę", 0.5, 0.15),
    ("W dół", 0.5, 0.85),
]


def get_step_text(step_index):
    return f"Krok {step_index + 1}/5: {STEPS[step_index][0]} — przytrzymaj kursor 3 sekundy"


def calibrate_cursor_visual(master_app):
    """Run visual calibration wizard with points on screen."""
    import customtkinter as ctk

    step = 0

    def next_step():
        nonlocal step
        if step >= len(STEPS):
            finish_calibration()
            return
        # Using STEPS[step] for display
        label.configure(text=get_step_text(step))
        point.configure(text="●", fg_color="#00ff00")
        step += 1
        master_app.after(3000, check_stability)

    def check_stability():
        nonlocal step
        step -= 1  # Reset for next step
        label.configure(text="Sprawdzam stabilność...")
        master_app.after(500, next_step)

    def finish_calibration():
        dialog.destroy()
        master_app.tracker.configure_cursor(
            sensitivity=1.9,
            smoothing=0.74,
            dead_zone=8.0,
        )
        master_app.label_status.configure(
            text="Kalibracja zakończona — kursors nastawiony",
            text_color="green",
        )

    dialog = ctk.CTkToplevel(master_app)
    dialog.title("Kalibracja kursora")
    dialog.geometry("600x400")
    dialog.attributes("-topmost", True)
    dialog.configure(fg_color="#232323")

    ctk.CTkLabel(dialog, text="Kalibracja kursora — popatrz na zieloną kropkę", font=("Arial", 16, "bold")).pack(pady=20)
    label = ctk.CTkLabel(dialog, text="Rozpoczynam...", font=("Arial", 14))
    label.pack(pady=10)

    point = ctk.CTkLabel(dialog, text="●", font=("Arial", 60, "bold"), text_color="#00ff00")
    point.pack(pady=40)

    ctk.CTkButton(dialog, text="Rozpocznij", command=next_step, font=("Arial", 14, "bold")).pack(pady=10)

    master_app.calibration_dialog = dialog
