from __future__ import annotations

import math
import statistics
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .config import CameraCalibrationProfile, MacroSettings
from .events import CameraSample, CameraSegment


@dataclass
class CameraComparison:
    max_error_deg: float
    mean_error_deg: float
    final_error_deg: float
    recorded_total_deg: float
    playback_total_deg: float

    @property
    def drift_deg(self) -> float:
        return self.final_error_deg


@dataclass
class CameraPlaybackDiagnostics:
    segment_index: int
    recorded_sum_deg: Tuple[float, float]
    playback_sum_deg: Tuple[float, float]
    max_error_deg: float
    mean_error_deg: float
    final_error_deg: float
    achieved_rate_hz: float
    sent_samples: int

    def as_text(self) -> str:
        return (
            f"Segment #{self.segment_index}: recorded Δ=({self.recorded_sum_deg[0]:.3f}, {self.recorded_sum_deg[1]:.3f})°, "
            f"playback Δ=({self.playback_sum_deg[0]:.3f}, {self.playback_sum_deg[1]:.3f})°, error≤{self.max_error_deg:.3f}°"
        )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


class CameraModel:
    def __init__(self, calibration: CameraCalibrationProfile, settings: MacroSettings):
        self.calibration = calibration
        self.settings = settings

    @property
    def gain_x(self) -> float:
        return self.settings.camera_gain * self.settings.gain_x

    @property
    def gain_y(self) -> float:
        return self.settings.camera_gain * self.settings.gain_y

    def counts_to_angles(self, dx: float, dy: float, apply_gain: bool = False) -> tuple[float, float]:
        angle_x = dx / self.calibration.counts_per_degree_x
        angle_y = dy / self.calibration.counts_per_degree_y
        if apply_gain:
            angle_x *= self.gain_x
            angle_y *= self.gain_y
        if self.settings.invert_x:
            angle_x *= -1.0
        if self.settings.invert_y:
            angle_y *= -1.0
        return angle_x, angle_y

    def angles_to_counts(self, angle_dx: float, angle_dy: float, include_gain: bool = True) -> tuple[float, float]:
        dx = angle_dx
        dy = angle_dy
        if include_gain:
            dx *= self.gain_x
            dy *= self.gain_y
        if self.settings.invert_x:
            dx *= -1.0
        if self.settings.invert_y:
            dy *= -1.0
        return (
            dx * self.calibration.counts_per_degree_x,
            dy * self.calibration.counts_per_degree_y,
        )

    @property
    def deadzone_deg(self) -> float:
        counts = max(0.0, float(self.settings.deadzone_threshold))
        if not counts:
            return 0.0
        return counts / self.calibration.counts_per_degree_x


class MotionFilter:
    def __init__(self, settings: MacroSettings, calibration: CameraCalibrationProfile):
        self.deadzone_deg = settings.deadzone_threshold / calibration.counts_per_degree_x if settings.deadzone_threshold else 0.0
        self.reverse_window = settings.reverse_window_ms / 1000.0
        self.reverse_tiny_ratio = settings.reverse_tiny_ratio
        self._history: deque[tuple[float, float, float]] = deque()

    def apply(self, dx: float, dy: float, timestamp: float) -> tuple[float, float]:
        magnitude = math.hypot(dx, dy)
        if magnitude < self.deadzone_deg:
            return 0.0, 0.0
        if not self._history:
            self._history.append((timestamp, dx, dy))
            return dx, dy
        last_ts, last_dx, last_dy = self._history[-1]
        if timestamp - last_ts <= self.reverse_window:
            last_mag = math.hypot(last_dx, last_dy)
            if last_mag > 0 and magnitude < last_mag * max(0.0, self.reverse_tiny_ratio):
                reversed_x = dx != 0.0 and math.copysign(1.0, dx) != math.copysign(1.0, last_dx)
                reversed_y = dy != 0.0 and math.copysign(1.0, dy) != math.copysign(1.0, last_dy)
                if reversed_x or reversed_y:
                    return 0.0, 0.0
        self._history.append((timestamp, dx, dy))
        while self._history and timestamp - self._history[0][0] > self.reverse_window:
            self._history.popleft()
        return dx, dy


class CumulativeSeries:
    def __init__(self, start: float, end: float, samples: Sequence[CameraSample]):
        ordered = sorted(samples, key=lambda sample: sample.timestamp)
        self.times: List[float] = [start]
        self.cum_x: List[float] = [0.0]
        self.cum_y: List[float] = [0.0]
        total_x = 0.0
        total_y = 0.0
        for sample in ordered:
            timestamp = _clamp(sample.timestamp, start, end)
            total_x += sample.angle_dx
            total_y += sample.angle_dy
            self.times.append(timestamp)
            self.cum_x.append(total_x)
            self.cum_y.append(total_y)
        if self.times[-1] < end:
            self.times.append(end)
            self.cum_x.append(total_x)
            self.cum_y.append(total_y)

    def value_at(self, timestamp: float) -> tuple[float, float]:
        if timestamp <= self.times[0]:
            return 0.0, 0.0
        if timestamp >= self.times[-1]:
            return self.cum_x[-1], self.cum_y[-1]
        idx = bisect_right(self.times, timestamp) - 1
        idx = max(0, min(idx, len(self.times) - 2))
        left_time = self.times[idx]
        right_time = self.times[idx + 1]
        if right_time <= left_time:
            return self.cum_x[idx], self.cum_y[idx]
        ratio = (timestamp - left_time) / (right_time - left_time)
        x = self.cum_x[idx] + (self.cum_x[idx + 1] - self.cum_x[idx]) * ratio
        y = self.cum_y[idx] + (self.cum_y[idx + 1] - self.cum_y[idx]) * ratio
        return x, y

    @property
    def total_vector(self) -> tuple[float, float]:
        return self.cum_x[-1], self.cum_y[-1]

    @property
    def total_length(self) -> float:
        return math.hypot(*self.total_vector)


class CameraTrajectory:
    def __init__(self, segment: CameraSegment, calibration: CameraCalibrationProfile):
        self.segment = segment
        self.calibration = calibration
        self.series = CumulativeSeries(segment.press_timestamp, segment.release_timestamp, segment.samples)
        self.duration = max(0.0, segment.release_timestamp - segment.press_timestamp)

    def resample(self, target_rate_hz: float) -> List[CameraSample]:
        target_rate_hz = max(1.0, float(target_rate_hz))
        if not self.segment.samples or self.duration <= 0:
            return []
        step = 1.0 / target_rate_hz
        timestamps: List[float] = []
        t = self.segment.press_timestamp + step
        while t < self.segment.release_timestamp - 1e-6:
            timestamps.append(t)
            t += step
        timestamps.append(self.segment.release_timestamp)
        output: List[CameraSample] = []
        prev_x = 0.0
        prev_y = 0.0
        for timestamp in timestamps:
            cum_x, cum_y = self.series.value_at(timestamp)
            delta_x = cum_x - prev_x
            delta_y = cum_y - prev_y
            prev_x = cum_x
            prev_y = cum_y
            raw_dx = delta_x * self.calibration.counts_per_degree_x
            raw_dy = delta_y * self.calibration.counts_per_degree_y
            output.append(
                CameraSample(
                    timestamp=timestamp,
                    angle_dx=delta_x,
                    angle_dy=delta_y,
                    raw_dx=raw_dx,
                    raw_dy=raw_dy,
                )
            )
        return output

    def compare_with(self, playback_samples: Sequence[CameraSample]) -> CameraComparison:
        playback_series = CumulativeSeries(self.segment.press_timestamp, self.segment.release_timestamp, playback_samples)
        checkpoints = sorted(set(self.series.times + playback_series.times))
        errors: List[float] = []
        for checkpoint in checkpoints:
            rec_x, rec_y = self.series.value_at(checkpoint)
            pb_x, pb_y = playback_series.value_at(checkpoint)
            errors.append(math.hypot(rec_x - pb_x, rec_y - pb_y))
        max_error = max(errors) if errors else 0.0
        mean_error = statistics.mean(errors) if errors else 0.0
        rec_final = self.series.total_vector
        pb_final = playback_series.total_vector
        final_error = math.hypot(rec_final[0] - pb_final[0], rec_final[1] - pb_final[1])
        return CameraComparison(
            max_error_deg=max_error,
            mean_error_deg=mean_error,
            final_error_deg=final_error,
            recorded_total_deg=self.series.total_length,
            playback_total_deg=playback_series.total_length,
        )


class SubPixelAccumulator:
    def __init__(self, max_step: int):
        self.max_step = max(1, int(max_step))
        self._buffer_x = 0.0
        self._buffer_y = 0.0

    def feed(self, counts_x: float, counts_y: float) -> List[tuple[int, int]]:
        self._buffer_x += counts_x
        self._buffer_y += counts_y
        emitted: List[tuple[int, int]] = []
        while True:
            send_x = 0
            send_y = 0
            if abs(self._buffer_x) >= 1.0:
                magnitude = min(self.max_step, int(abs(self._buffer_x)))
                if magnitude == 0:
                    magnitude = 1
                send_x = magnitude if self._buffer_x > 0 else -magnitude
                self._buffer_x -= send_x
            if abs(self._buffer_y) >= 1.0:
                magnitude = min(self.max_step, int(abs(self._buffer_y)))
                if magnitude == 0:
                    magnitude = 1
                send_y = magnitude if self._buffer_y > 0 else -magnitude
                self._buffer_y -= send_y
            if send_x == 0 and send_y == 0:
                break
            emitted.append((send_x, send_y))
        return emitted

    def flush(self) -> List[tuple[int, int]]:
        flushed = []
        if self._buffer_x or self._buffer_y:
            remainder_x = int(round(self._buffer_x))
            remainder_y = int(round(self._buffer_y))
            if remainder_x or remainder_y:
                flushed.append((remainder_x, remainder_y))
                self._buffer_x -= remainder_x
                self._buffer_y -= remainder_y
        return flushed


def summarize_playback(
    segment: CameraSegment,
    playback_samples: Sequence[CameraSample],
    calibration: CameraCalibrationProfile,
    target_rate_hz: float,
) -> CameraPlaybackDiagnostics:
    trajectory = CameraTrajectory(segment, calibration)
    comparison = trajectory.compare_with(playback_samples)
    recorded_sum = trajectory.series.total_vector
    playback_series = CumulativeSeries(segment.press_timestamp, segment.release_timestamp, playback_samples)
    playback_sum = playback_series.total_vector
    samples_sent = len(playback_samples)
    achieved_rate = samples_sent / trajectory.duration if trajectory.duration > 0 else float(samples_sent)
    return CameraPlaybackDiagnostics(
        segment_index=segment.press_event_index,
        recorded_sum_deg=recorded_sum,
        playback_sum_deg=playback_sum,
        max_error_deg=comparison.max_error_deg,
        mean_error_deg=comparison.mean_error_deg,
        final_error_deg=comparison.final_error_deg,
        achieved_rate_hz=achieved_rate,
        sent_samples=samples_sent,
    )


__all__ = [
    "CameraModel",
    "CameraTrajectory",
    "CameraComparison",
    "CameraPlaybackDiagnostics",
    "MotionFilter",
    "SubPixelAccumulator",
    "summarize_playback",
]
