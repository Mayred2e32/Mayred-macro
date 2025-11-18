from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

from pynput import keyboard, mouse

from .camera import (
    CameraModel,
    CameraTrajectory,
    MotionFilter,
    SubPixelAccumulator,
    summarize_playback,
)
from .config import CameraCalibrationProfile, MacroSettings
from .events import CameraSample, CameraSegment, MacroEvent, MacroRecording
from .io import HighPriorityContext, RelativeMouseSender


class TimelineController:
    def __init__(self):
        self._base = None

    def reset(self):
        self._base = time.perf_counter()

    def sleep_until(self, timestamp: float):
        if self._base is None:
            self.reset()
        target = self._base + max(0.0, float(timestamp))
        while True:
            now = time.perf_counter()
            remaining = target - now
            if remaining <= 0:
                break
            if remaining > 0.002:
                time.sleep(remaining - 0.001)
            else:
                time.sleep(max(remaining, 0.00005))


@dataclass
class PlaybackResult:
    diagnostics: List[str] = field(default_factory=list)
    max_error_deg: float = 0.0
    avg_error_deg: float = 0.0
    segments: int = 0


@dataclass
class _SampleAction:
    timestamp: float
    steps: List[tuple[int, int]]
    diagnostic_sample: CameraSample


class CameraPlaybackRunner:
    def __init__(
        self,
        segment: CameraSegment,
        settings: MacroSettings,
        calibration: CameraCalibrationProfile,
        sender: RelativeMouseSender,
        index: int,
    ):
        self.segment = segment
        self.settings = settings
        self.calibration = calibration
        self.sender = sender
        self.index = index
        self.camera_model = CameraModel(calibration, settings)
        self.filter = MotionFilter(settings, calibration)
        self._actions = self._prepare_actions()
        self._cursor = 0
        self._diag_samples = [action.diagnostic_sample for action in self._actions]
        self._completed = False

    def _prepare_actions(self) -> List[_SampleAction]:
        trajectory = CameraTrajectory(self.segment, self.calibration)
        resampled = trajectory.resample(self.settings.target_rate_hz)
        accumulator = SubPixelAccumulator(self.settings.sender_max_step)
        actions: List[_SampleAction] = []
        for sample in resampled:
            filtered_dx, filtered_dy = self.filter.apply(sample.angle_dx, sample.angle_dy, sample.timestamp)
            if filtered_dx == 0.0 and filtered_dy == 0.0:
                continue
            counts_x, counts_y = self.camera_model.angles_to_counts(filtered_dx, filtered_dy, include_gain=True)
            emitted = accumulator.feed(counts_x, counts_y)
            if not emitted:
                continue
            sum_x = sum(step_x for step_x, _ in emitted)
            sum_y = sum(step_y for _, step_y in emitted)
            angle_x, angle_y = self.camera_model.counts_to_angles(sum_x, sum_y, apply_gain=False)
            diag_sample = CameraSample(
                timestamp=sample.timestamp,
                angle_dx=angle_x,
                angle_dy=angle_y,
                raw_dx=sum_x,
                raw_dy=sum_y,
            )
            actions.append(_SampleAction(timestamp=sample.timestamp, steps=emitted, diagnostic_sample=diag_sample))
        flush_steps = accumulator.flush()
        if flush_steps:
            sum_x = sum(step_x for step_x, _ in flush_steps)
            sum_y = sum(step_y for _, step_y in flush_steps)
            angle_x, angle_y = self.camera_model.counts_to_angles(sum_x, sum_y, apply_gain=False)
            diag_sample = CameraSample(
                timestamp=self.segment.release_timestamp,
                angle_dx=angle_x,
                angle_dy=angle_y,
                raw_dx=sum_x,
                raw_dy=sum_y,
            )
            actions.append(_SampleAction(timestamp=self.segment.release_timestamp, steps=flush_steps, diagnostic_sample=diag_sample))
        return actions

    def drain_until(
        self,
        target_timestamp: float,
        timeline: TimelineController,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        stop_event = stop_event or threading.Event()
        while self._cursor < len(self._actions):
            action = self._actions[self._cursor]
            if action.timestamp > target_timestamp + 1e-6:
                break
            if stop_event.is_set():
                return
            timeline.sleep_until(action.timestamp)
            for step_x, step_y in action.steps:
                if stop_event.is_set():
                    return
                self.sender.send(step_x, step_y)
            self._cursor += 1

    def finalize(
        self,
        timeline: TimelineController,
        stop_event: Optional[threading.Event] = None,
    ):
        if self._completed:
            return None
        self.drain_until(self.segment.release_timestamp, timeline, stop_event)
        self._completed = True
        diagnostics = summarize_playback(
            self.segment,
            self._diag_samples,
            self.calibration,
            self.settings.target_rate_hz,
        )
        diagnostics.segment_index = self.index
        return diagnostics


class PlaybackSession:
    def __init__(self, settings: MacroSettings, calibration: CameraCalibrationProfile):
        self.settings = settings
        self.calibration = calibration
        self.sender = RelativeMouseSender(
            max_step=settings.sender_max_step,
            delay_seconds=settings.sender_delay_ms / 1000.0,
        )
        self.timeline = TimelineController()
        self.mouse_controller = mouse.Controller()
        self.keyboard_controller = keyboard.Controller()

    def play(self, recording: MacroRecording, stop_event: Optional[threading.Event] = None) -> PlaybackResult:
        stop_event = stop_event or threading.Event()
        self.timeline.reset()
        diagnostics: List[str] = []
        diag_objects: List = []
        segments_by_press = {segment.press_event_index: segment for segment in recording.camera_segments}
        active_runner: Optional[CameraPlaybackRunner] = None

        with HighPriorityContext():
            for idx, event in enumerate(recording.events):
                if stop_event.is_set():
                    break
                if active_runner is not None:
                    active_runner.drain_until(event.timestamp, self.timeline, stop_event)
                self.timeline.sleep_until(event.timestamp)
                diag = self._dispatch_event(
                    idx,
                    event,
                    segments_by_press,
                    diag_objects,
                    stop_event,
                    active_runner,
                )
                if isinstance(diag, CameraPlaybackRunner):
                    active_runner = diag
                elif diag is not None:
                    diag_objects.append(diag)
                    active_runner = None

            if active_runner is not None:
                diag = active_runner.finalize(self.timeline, stop_event)
                if diag:
                    diag_objects.append(diag)

        diagnostics = [diag_obj.as_text() for diag_obj in diag_objects]
        max_error = max((diag_obj.max_error_deg for diag_obj in diag_objects), default=0.0)
        avg_error = (
            sum(diag_obj.max_error_deg for diag_obj in diag_objects) / len(diag_objects)
            if diag_objects
            else 0.0
        )
        return PlaybackResult(diagnostics=diagnostics, max_error_deg=max_error, avg_error_deg=avg_error, segments=len(diag_objects))

    def _dispatch_event(
        self,
        index: int,
        event: MacroEvent,
        segments_by_press,
        diag_objects,
        stop_event: threading.Event,
        active_runner: Optional[CameraPlaybackRunner],
    ):
        event_type = event.type
        data = event.data
        if event_type == "mouse_move":
            x = data.get("x")
            y = data.get("y")
            if x is not None and y is not None:
                self.mouse_controller.position = (int(x), int(y))
            return None
        if event_type == "mouse_scroll":
            dx = data.get("dx", 0)
            dy = data.get("dy", 0)
            self.mouse_controller.scroll(dx, dy)
            return None
        if event_type in {"mouse_press", "mouse_release"}:
            button = self._resolve_mouse_button(data.get("button"))
            if not button:
                return None
            if event_type == "mouse_press":
                self.mouse_controller.press(button)
                if button == mouse.Button.right and index in segments_by_press:
                    segment = segments_by_press[index]
                    runner = CameraPlaybackRunner(
                        segment,
                        self.settings,
                        self.calibration,
                        self.sender,
                        index=len(diag_objects) + 1,
                    )
                    return runner
                return None
            else:
                self.mouse_controller.release(button)
                if button == mouse.Button.right and active_runner is not None:
                    return active_runner.finalize(self.timeline, stop_event)
                return None
        if event_type == "key_press":
            key = self._resolve_key(data.get("key"))
            if key:
                self.keyboard_controller.press(key)
            return None
        if event_type == "key_release":
            key = self._resolve_key(data.get("key"))
            if key:
                self.keyboard_controller.release(key)
            return None
        return None

    @staticmethod
    def _resolve_mouse_button(value: Optional[str]):
        if not value:
            return None
        value = value.replace("Button.", "")
        mapping = {
            "left": mouse.Button.left,
            "right": mouse.Button.right,
            "middle": mouse.Button.middle,
        }
        return mapping.get(value.lower())

    @staticmethod
    def _resolve_key(value: Optional[str]):
        if not value:
            return None
        if value.startswith("Key."):
            attr = value.split(".", 1)[1]
            return getattr(keyboard.Key, attr, None)
        if len(value) == 1:
            return keyboard.KeyCode.from_char(value)
        return keyboard.KeyCode.from_char(value[0])


__all__ = ["PlaybackSession", "TimelineController", "PlaybackResult"]
