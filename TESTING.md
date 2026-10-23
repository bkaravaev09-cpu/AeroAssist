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
clock; worker tests control thread state rather than depending on timing.

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
