# Cursor smoothing and stability

`core/cursor_controller.py` performs cursor calculations without OpenCV, Tk, Win32,
or webcam input. `VisionTracker` supplies normalized nose coordinates and its
existing neutral reference, then sends the rounded result through the existing
Win32 mouse function. Eye gestures, voice mappings, FaceMesh processing, camera
initialization, and worker exclusion are preserved.

## Defaults and controls

All settings are defined in the immutable `CursorSettings` / `DEFAULT_CURSOR_SETTINGS`.
The controller validates setting changes and applies them under a short lock so
the GUI can configure movement safely while the camera worker updates it.

| Setting | Default | Meaning |
| --- | --- | --- |
| Sensitivity | 1.9 | Range 1–3; scales head displacement and edge drift by sensitivity / 1.9. |
| Smoothing strength | 0.74 | GUI range 0–0.95; EMA alpha = 1 − strength. Larger values smooth more. |
| Dead zone | 2 pixels | Euclidean distance from the last accepted target; GUI range 0–10 pixels. |
| Maximum cursor step | 80 pixels/frame | Limits vector displacement after EMA, including diagonal motion. |
| Maximum head sample step | 0.20 | A larger normalized inter-frame change is treated as a discontinuity. |

The default EMA alpha is 0.26, matching the previous response for ordinary
movement. Smoothing and sensitivity are independent. The Polish controls add
`Wygładzanie ruchu`, `Strefa martwa`, and `Przywróć ustawienia domyślne` beside
`Czułość kursora`. Reset updates the three visible settings atomically and updates
their sliders. Settings are in-memory only; no profiles or persistence are added.

## Movement algorithm

1. Reject nonfinite or out-of-range normalized head coordinates. Invalid samples
   and missing faces hold the last commanded cursor position and reset movement
   history. Invalid nose samples cannot enter the existing initial calibration.
2. Preserve the existing nonlinear horizontal/upward response curves and head-tilt
   edge drift (thresholds 0.07 horizontally, 0.06 vertically, baseline 18 pixels
   per frame). Drift decays at neutral and cannot accumulate outside the screen.
3. Compare the clamped target with the last **accepted** target. Ignore distances
   below the dead zone and accept equality. Comparing with the last accepted
   target allows small intentional increments to accumulate and avoids repeated
   toggling from small noise around a crossed threshold.
4. Compute `position += (target - position) * (1 - smoothing)`. Clamp the movement
   vector to the maximum step, then clamp coordinates to `[0, width-1]` and
   `[0, height-1]`. The EMA can settle toward an accepted target even while new
   small target noise is ignored. Rounding lets the cursor reach the final edge.

On worker start/end, missing face, invalid input, or an implausibly large head
sample change, reset drift and filter history while retaining the last safe
position. The first reacquired sample establishes a transient mapping offset and
holds that position. Subsequent motion is relative to that sample; head tilt can
still reach every edge. This continuity offset is not a personalized calibration
profile and does not replace the existing initial face/eye calibration.

## Reproducible before/after comparison

These are deterministic calculations, not evidence of real-device comfort or
recognition accuracy. The previous implementation used a fixed alpha of 0.26,
had no dead zone or step limit, and did not reset its movement history on face loss.

| Synthetic case | Previous behavior | New behavior at defaults |
| --- | --- | --- |
| Alternating ±1 pixel around x=500, 100 warm-up samples | 0.298851 px steady peak-to-peak output jitter | 0 px output jitter |
| Target jumps +400 pixels horizontally | First EMA step: 104 px | First step capped at 80 px |
| Target moves 500.5, 501, 501.5, 502 | Every sample affects output | First three ignored; 502 accepted, so slow motion remains possible |
| First valid sample after tracking loss | Old state moves toward the new absolute target | First sample holds last commanded position; following motion resumes smoothly |
| Sensitivity slider changes | Attribute was assigned but unused by movement | Gain changes the response; 3.0 produces three times the small-signal displacement of 1.0 |

The comparisons and edge/recovery behavior are covered by
`tests/test_cursor_controller.py` and `tests/test_vision.py`. Tests mock desktop
automation, camera, microphone, and Windows audio. Existing gesture callbacks,
preview, shutdown, and voice tests remain part of the suite.

## Manual testing and limits

Windows GUI smoke testing with mocked tracker/voice verifies rendering, scrolling,
setting changes, and reset. No webcam or real mouse automation is used in that
check. Physical-device comfort, precision, response time, and prolonged use have
**not** been verified.

On Windows with a webcam:

1. Keep the head still; compare small-signal jitter with dead zone 0 and 2 pixels.
2. Move slowly in all directions and select small controls; adjust the dead zone
   if slow motion feels delayed.
3. Move quickly across the screen, then near every edge; confirm bounded steps,
   continued tilt-to-edge motion, and a smooth return toward neutral.
4. Change sensitivity and smoothing independently during tracking; try smoothing
   0, 0.74, and 0.95. Restore defaults and check all sliders.
5. Pause/resume several times; briefly leave the camera view and return at a
   different head position. Confirm no initial cursor jump.
6. Verify left-eye click, four-blink pause, long-eye-closure voice activation,
   preview, and shutdown still work.

Strong smoothing/dead zones trade response time for stability. The step limit and
head discontinuity guard can suppress unusually rapid intentional movement.
Timing remains frame-based, as in the original drift algorithm; this change does
not claim frame-rate-independent speed. Mapping uses the primary screen and last
commanded position, so manual mouse movement while paused is not synchronized.
The first reacquired position becomes a new transient reference; head-tilt drift
remains available to reach boundaries. No full calibration, database, cloud
integration, or additional dependency is introduced.
