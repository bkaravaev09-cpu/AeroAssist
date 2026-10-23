# Automated checks

AeroAssist uses Python 3.11. In PowerShell, from the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

To apply formatting, run `python -m ruff format .` using the virtual environment.
Runtime dependencies are in `requirements.txt`; test and quality tools are in
`requirements-dev.txt`. The runtime list pins direct dependencies instead of
keeping an environment export. NumPy 1.26 and OpenCV 4 preserve compatibility
with MediaPipe 0.10.14 and its `solutions.face_mesh` API. Only the contrib OpenCV
distribution is installed, avoiding two packages providing the same `cv2` module.

## Test boundaries

`tests/conftest.py` replaces CustomTkinter, OpenCV, MediaPipe, Win32 cursor APIs,
Windows sound, PyAutoGUI, and text-to-speech before application imports. Voice
tests patch the microphone, recognizer, and browser. NumPy and the application's
gesture logic remain real. No GUI window, device, speech service, browser, or
desktop automation is needed. Gesture tests use synthetic landmarks and a mocked
clock. Worker tests cover deterministic state transitions and use real threads
with synchronization Events to hold camera release open during rapid clicks and
shutdown, without depending on sleep-based timing.

Tests cover camera initialization, fallback and release; tracking start/stop and
worker exclusion; camera and processing failures; eye gestures and callback
debouncing; sensitivity assignment and mouse smoothing; voice activation,
session exclusion and errors; and shutdown resource ordering.

The sensitivity test covers the existing slider-to-tracker assignment. The current
vision movement algorithm does not consume that attribute; changing its behavior
is outside this testing setup.

Shutdown keeps the GUI event loop available while existing workers finish before
closing FaceMesh and the window. Device drivers or speech services that block
indefinitely can delay shutdown. These unit tests do not establish physical-device
behavior, recognition accuracy, or real desktop compatibility.

## Camera lifecycle manual test plan

Run these checks on Windows with a real webcam; they are not automated hardware
verification:

1. Start tracking, wait for the active status, then stop. Confirm the camera LED
   goes off and the start button becomes available after cleanup.
2. Rapidly click start/stop, including while the camera is opening. Confirm the
   interface stays responsive and a new session starts only after stopping ends.
3. Start without a webcam (or with camera permission denied). Confirm a Polish
   error appears and reconnecting the camera allows a new attempt.
4. Disconnect the webcam while tracking. Confirm tracking stops with a Polish
   error instead of retrying forever; reconnect and restart.
5. Blink both eyes four times quickly. Confirm tracking pauses, then restart.
   Verify the left-eye click and long-eye-closure voice trigger still work.
6. Close while opening, tracking, stopping, or listening to a voice command.
   Confirm no new session can start, the interface continues processing events,
   and the window closes after workers finish and resources are released.

The GUI polls a session-tagged queue every 50 ms. Each camera session owns its
stop Event and capture, and only its worker calls OpenCV camera methods. Up to
two failed reads are retried with an interruptible delay; the third consecutive
failure ends the session. Stop disables restart until the completion event is
received and the old thread has exited. Technical failures are logged with
tracebacks; camera errors remain visible in the Polish status label until retry.

## GitHub Actions and merge protection

`.github/workflows/ci.yml` installs runtime and development dependencies on
`windows-latest` with Python 3.11. On PRs targeting `main` and pushes to `main`,
it checks dependency compatibility, Ruff formatting, Ruff linting, and pytest.
The workflow has only `contents: read` permission and does not expose secrets.

To enforce passing checks before merging, a repository administrator must enable
a branch protection rule or ruleset for `main`, require pull requests, and make
**Python 3.11 checks** a required status check after its first workflow run.
The workflow file alone does not prevent merging a failed PR. Repository settings
are not modified by this change.
