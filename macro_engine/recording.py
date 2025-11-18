from __future__ import annotations

import platform
import queue
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from pynput import keyboard, mouse

from .camera import CameraModel
from .config import CameraCalibrationProfile, MacroSettings
from .events import CameraSample, CameraSegment, MacroEvent, MacroRecording
from .io import RawMousePacket, RawMouseStream


@dataclass
class _CameraSegmentState:
    press_event_index: int
    press_timestamp: float
    samples: List[CameraSample]


class RecordingSession:
    """Captures keyboard/mouse activity with raw RMB drag fidelity."""

    def __init__(self, settings: MacroSettings, calibration: CameraCalibrationProfile):
        self.settings = settings
        self.calibration = calibration
        self.camera_model = CameraModel(calibration, settings)
        self._events: List[MacroEvent] = []
        self._segments: List[CameraSegment] = []
        self._segment_state: Optional[_CameraSegmentState] = None
        self._mouse_listener: Optional[mouse.Listener] = None
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._raw_stream: Optional[RawMouseStream] = None
        self._raw_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._perf_zero = 0.0
        self._start_wall_time = 0.0
        self._running = False
        self._rmb_pressed = False
        self._last_mouse_pos: Optional[tuple[float, float]] = None
        self._metadata: Dict[str, object] = {
            "platform": platform.platform(),
            "raw_input": False,
        }

    def start(self) -> None:
        if self._running:
            raise RuntimeError("Recording already active")
        self._running = True
        self._stop_event.clear()
        self._perf_zero = time.perf_counter()
        self._start_wall_time = time.time()
        self._start_raw_stream()
        self._mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll,
        )
        self._mouse_listener.start()
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._keyboard_listener.start()

    def stop(self) -> MacroRecording:
        if not self._running:
            raise RuntimeError("Recording not started")
        self._stop_event.set()
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener.join()
        if self._keyboard_listener:
            self._keyboard_listener.stop()
            self._keyboard_listener.join()
        if self._raw_stream:
            self._raw_stream.stop_stream()
        if self._raw_thread:
            self._raw_thread.join(timeout=1.0)
        self._finalize_camera_segment(time.perf_counter() - self._perf_zero, len(self._events) - 1)
        self._running = False
        metadata = {
            **self._metadata,
            "settings": self.settings.to_dict(),
            "calibration": self.calibration.to_dict(),
            "created_at": self._start_wall_time,
        }
        recording = MacroRecording(
            name=time.strftime("macro_%Y%m%d_%H%M%S", time.localtime(self._start_wall_time)),
            created_at=self._start_wall_time,
            events=list(self._events),
            camera_segments=list(self._segments),
            metadata=metadata,
        )
        self._events.clear()
        self._segments.clear()
        return recording

    # --- Listener plumbing ---
    def _start_raw_stream(self) -> None:
        if RawMouseStream and RawMouseStream.is_supported():
            try:
                self._raw_stream = RawMouseStream()
                self._raw_stream.start_stream()
                self._metadata["raw_input"] = True
            except Exception:
                self._raw_stream = None
                self._metadata["raw_input"] = False
        if self._raw_stream:
            self._raw_thread = threading.Thread(target=self._consume_raw_stream, daemon=True)
            self._raw_thread.start()

    def _consume_raw_stream(self) -> None:
        assert self._raw_stream is not None
        while not self._stop_event.is_set():
            try:
                packet = self._raw_stream.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            self._handle_raw_packet(packet)

    def _handle_raw_packet(self, packet: RawMousePacket) -> None:
        if not self._rmb_pressed or self._segment_state is None:
            return
        timestamp = packet.timestamp - self._perf_zero
        self._append_camera_delta(packet.dx, packet.dy, timestamp)

    def _append_camera_delta(self, dx: float, dy: float, timestamp: float) -> None:
        if self._segment_state is None:
            return
        angle_dx, angle_dy = self.camera_model.counts_to_angles(dx, dy, apply_gain=False)
        sample = CameraSample(
            timestamp=timestamp,
            angle_dx=angle_dx,
            angle_dy=angle_dy,
            raw_dx=dx,
            raw_dy=dy,
        )
        self._segment_state.samples.append(sample)

    def _current_time(self) -> float:
        return time.perf_counter() - self._perf_zero

    def _append_event(self, event_type: str, data: Dict[str, object]) -> int:
        timestamp = self._current_time()
        event = MacroEvent(type=event_type, timestamp=timestamp, data=data)
        self._events.append(event)
        return len(self._events) - 1

    def _on_mouse_move(self, x: float, y: float):
        timestamp = self._current_time()
        if self._last_mouse_pos is None:
            self._last_mouse_pos = (x, y)
        dx = x - self._last_mouse_pos[0]
        dy = y - self._last_mouse_pos[1]
        self._last_mouse_pos = (x, y)
        event_index = self._append_event("mouse_move", {"x": x, "y": y})
        if self._rmb_pressed and self._raw_stream is None:
            self._append_camera_delta(dx, dy, timestamp)
        return event_index

    def _on_mouse_click(self, x: float, y: float, button: mouse.Button, pressed: bool):
        button_name = button.name if hasattr(button, "name") else str(button)
        event_index = self._append_event(
            "mouse_press" if pressed else "mouse_release",
            {"button": button_name, "x": x, "y": y},
        )
        if button == mouse.Button.right:
            self._rmb_pressed = pressed
            if pressed:
                self._start_camera_segment(event_index)
            else:
                self._finalize_camera_segment(self._current_time(), event_index)
        return event_index

    def _on_mouse_scroll(self, x: float, y: float, dx: float, dy: float):
        self._append_event("mouse_scroll", {"x": x, "y": y, "dx": dx, "dy": dy})

    def _on_key_press(self, key):
        self._append_event("key_press", {"key": str(key)})

    def _on_key_release(self, key):
        self._append_event("key_release", {"key": str(key)})

    # --- Camera segment lifecycle ---
    def _start_camera_segment(self, event_index: int) -> None:
        timestamp = self._events[event_index].timestamp
        self._segment_state = _CameraSegmentState(event_index, timestamp, [])

    def _finalize_camera_segment(self, release_timestamp: float, release_event_index: int) -> None:
        if not self._segment_state:
            return
        samples = [sample for sample in self._segment_state.samples if sample.angle_dx or sample.angle_dy]
        segment = CameraSegment(
            press_event_index=self._segment_state.press_event_index,
            release_event_index=release_event_index,
            press_timestamp=self._segment_state.press_timestamp,
            release_timestamp=release_timestamp,
            samples=samples,
            metadata={"raw_input": bool(self._raw_stream)},
        )
        self._segments.append(segment)
        self._segment_state = None


__all__ = ["RecordingSession"]
