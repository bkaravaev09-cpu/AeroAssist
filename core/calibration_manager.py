"""Calibration profile management — no camera needed."""
import json
import os

PROFILE_PATH = "profiles/user_calibration.json"


def save_profile(center_x, center_y, blink_threshold, ear_samples, sensitivity=1.9, smoothing=0.74, dead_zone=2.0):
    profile = {
        "center_x": center_x,
        "center_y": center_y,
        "blink_threshold": blink_threshold,
        "calibration_ear_samples": [float(x) for x in ear_samples[-25:]],
        "cursor_settings": {
            "sensitivity": sensitivity,
            "smoothing": smoothing,
            "dead_zone": dead_zone,
        },
    }
    os.makedirs(os.path.dirname(PROFILE_PATH) if os.path.dirname(PROFILE_PATH) else ".", exist_ok=True)
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    print(f"[Calibration] Profile saved to {PROFILE_PATH}")


def load_profile():
    if not os.path.exists(PROFILE_PATH):
        return None
    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        profile = json.load(f)
    return profile


if __name__ == "__main__":
    # Synthetic profile creation for testing
    save_profile(0.52, 0.58, 0.14, [0.28, 0.29, 0.30, 0.28, 0.27])
    loaded = load_profile()
    print(f"Synthetic profile loaded: center=({loaded['center_x']}, {loaded['center_y']})")
