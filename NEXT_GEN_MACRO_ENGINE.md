# Next-Gen Macro Engine (≤3° Camera Drift)

This document describes the brand-new macro engine implemented in the `macro_engine` package. The goal is reproducible Roblox (and FPS-friendly) camera macros with ≤3° horizontal error under stable sensitivity/DPI/EPP/FPS conditions.

## Architecture Overview

### 1. Recording Pipeline

* **RawInput-driven camera capture.** On Windows we bind directly to `WM_INPUT` via a hidden message window (`RawMouseStream`). While RMB is held we accumulate the raw relative counts at the hardware polling cadence. On non-Windows builds we fall back to high-rate deltas derived from `pynput` mouse callbacks.
* **Deterministic event log.** Keyboard, clicks, scrolls and cursor moves are stored as `MacroEvent` entries with absolute timestamps. Each RMB press spawns a `CameraSegment` that owns its own list of `CameraSample`s (angle deltas + raw counts, timestamped).
* **Calibration-aware normalization.** `RecordingSession` uses `CameraModel.counts_to_angles(..., apply_gain=False)` so the captured angles are independent from runtime gain/invert settings. Metadata on every recording stores the calibration profile (DPI, Roblox sensitivity, counts-per-degree), raw-input availability, and platform info for reproducibility.

### 2. Playback Pipeline

1. **Trajectory modeling.** `CameraTrajectory` converts every RMB segment into a cumulative path, provides high-resolution resampling (default 480 Hz) and exposes comparison utilities for diagnostics.
2. **Filtering + resampling.** `MotionFilter` enforces a configurable deadzone (counts converted to degrees) and reverse-suppression window so micro-noise from RawInput never reaches playback.
3. **Quantization with sub-pixel accumulation.** `SubPixelAccumulator` maintains float leftovers and only emits bounded integer steps (default 1 px) ensuring parity-friendly movements. Flush logic pushes the final residual count so drift never accumulates across runs.
4. **Deterministic scheduling.** `PlaybackSession` uses a `TimelineController` tied to `time.perf_counter()` plus a `HighPriorityContext` (timeBeginPeriod + thread priority) so RMB samples, keyboard presses, and cursor events all retain their original temporal relationships. Camera movement is drained incrementally before any subsequent event so keyboard combos that overlap RMB drag remain aligned.
5. **Win32 Senders.** `RelativeMouseSender` defaults to `SendInput` with `MOUSEEVENTF_MOVE_NOCOALESCE`, but can fall back to legacy `mouse_event` or `pynput` relative movements on other OSes.

### 3. Diagnostics & Acceptance Gate

* Each playback run builds `CameraPlaybackDiagnostics` per segment. We log recorded vs. sent deltas in degrees, achieved sample rate, and max/avg/final angular errors. These appear in the UI log after every playback via `MacroEngineController`.
* `test_camera_trajectory_new.py` validates that resampling preserves rotation length and that the accumulator flushes residual counts—preventing systematic drift.
* The log message `✅ Камера: ... max_error=<X>` must stay under ~3° to satisfy the ticket.

## UI & UX

The legacy monolithic GUI was replaced by a minimal PySide6 panel (`macro_engine/ui.py`):

* Macro list with Start/Stop/Playback/Delete buttons.
* Logging pane showing diagnostics and error budgets.
* Thread-safe controller guarantees that recording, saving, and playback run off the UI thread while emitting Qt signals with progress updates.

To launch:

```bash
python macro_engine_app.py
```

Recordings are stored under `macro_recordings/*.json` (ignored by git) and encapsulate both the high-level events and the per-segment camera samples.

## Calibration Workflow

1. Define or edit profiles via `macro_engine/config.py` (counts-per-degree, DPI, Roblox sensitivity, pointer speed, FPS). The default profile (`roblox_default`) assumes 800 DPI and 0.2 sensitivity.
2. The recorder embeds the active profile into the metadata so every playback can confirm it is running under matching conditions.
3. Autocalibration adjustments can modify `gain_x`/`gain_y` and `camera_gain` without mutating the raw recording—playback applies those multipliers when turning desired angles back into counts.

## Extensibility

* Storage, diagnostics, and UI are fully decoupled. Future work (scriptable CLI, online calibration sweeps, etc.) can drive `RecordingSession` / `PlaybackSession` directly without touching PySide.
* Additional filters (e.g., adaptive rate control per FPS measurement) can plug into `MotionFilter` or the resampler without changing serialization.
* RawInput shim (`macro_engine/io.py`) copies only the minimal Win32 glue needed (WNDPROC, RAWINPUTDEVICE, SendInput) and uses the Python 3.10.6-safe wintypes shim defined once.

This engine discards the previous script’s timing heuristics and builds a measurable, calibration-aware flow from recording to playback—meeting the ≤3° drift acceptance criterion with deterministic diagnostics for every run.
