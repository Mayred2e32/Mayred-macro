from macro_engine.camera import CameraTrajectory, SubPixelAccumulator
from macro_engine.config import CameraCalibrationProfile, MacroSettings
from macro_engine.events import CameraSample, CameraSegment


def _build_segment() -> CameraSegment:
    samples = [
        CameraSample(timestamp=0.02, angle_dx=0.5, angle_dy=0.0, raw_dx=6, raw_dy=0),
        CameraSample(timestamp=0.04, angle_dx=0.4, angle_dy=0.1, raw_dx=5, raw_dy=1),
        CameraSample(timestamp=0.06, angle_dx=0.3, angle_dy=0.2, raw_dx=4, raw_dy=2),
    ]
    return CameraSegment(
        press_event_index=0,
        release_event_index=5,
        press_timestamp=0.0,
        release_timestamp=0.08,
        samples=samples,
        metadata={},
    )


def test_camera_resample_preserves_rotation():
    calibration = CameraCalibrationProfile(counts_per_degree_x=10.0, counts_per_degree_y=10.0)
    segment = _build_segment()
    trajectory = CameraTrajectory(segment, calibration)
    resampled = trajectory.resample(target_rate_hz=200.0)
    assert resampled, "resample should produce samples"
    recorded_dx = sum(sample.angle_dx for sample in segment.samples)
    resampled_dx = sum(sample.angle_dx for sample in resampled)
    assert abs(recorded_dx - resampled_dx) < 0.05


def test_subpixel_accumulator_batches_counts():
    accumulator = SubPixelAccumulator(max_step=2)
    emitted = accumulator.feed(3.6, 0.0)
    assert sum(step for step, _ in emitted) == 3
    # Remaining 0.6 should flush later
    tail = accumulator.flush()
    assert sum(step for step, _ in tail) == 1  # rounds remaining fraction
