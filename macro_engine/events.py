from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Sequence

RECORDING_FORMAT_VERSION = 3


@dataclass
class MacroEvent:
    type: str
    timestamp: float
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "timestamp": self.timestamp, "data": self.data}

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "MacroEvent":
        return cls(
            type=str(payload.get("type", "")),
            timestamp=float(payload.get("timestamp", 0.0)),
            data=dict(payload.get("data", {})),
        )


@dataclass
class CameraSample:
    timestamp: float
    angle_dx: float
    angle_dy: float
    raw_dx: float
    raw_dy: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CameraSample":
        return cls(
            timestamp=float(payload.get("timestamp", 0.0)),
            angle_dx=float(payload.get("angle_dx", 0.0)),
            angle_dy=float(payload.get("angle_dy", 0.0)),
            raw_dx=float(payload.get("raw_dx", 0.0)),
            raw_dy=float(payload.get("raw_dy", 0.0)),
        )


@dataclass
class CameraSegment:
    press_event_index: int
    release_event_index: int
    press_timestamp: float
    release_timestamp: float
    samples: List[CameraSample] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max(0.0, self.release_timestamp - self.press_timestamp)

    def sum_angles(self) -> tuple[float, float]:
        total_x = sum(sample.angle_dx for sample in self.samples)
        total_y = sum(sample.angle_dy for sample in self.samples)
        return total_x, total_y

    def to_dict(self) -> Dict[str, Any]:
        return {
            "press_event_index": self.press_event_index,
            "release_event_index": self.release_event_index,
            "press_timestamp": self.press_timestamp,
            "release_timestamp": self.release_timestamp,
            "samples": [sample.to_dict() for sample in self.samples],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CameraSegment":
        samples_payload = payload.get("samples", [])
        samples = [CameraSample.from_dict(sample) for sample in samples_payload]
        return cls(
            press_event_index=int(payload.get("press_event_index", -1)),
            release_event_index=int(payload.get("release_event_index", -1)),
            press_timestamp=float(payload.get("press_timestamp", 0.0)),
            release_timestamp=float(payload.get("release_timestamp", 0.0)),
            samples=samples,
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass
class MacroRecording:
    name: str
    created_at: float
    events: List[MacroEvent] = field(default_factory=list)
    camera_segments: List[CameraSegment] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": RECORDING_FORMAT_VERSION,
            "name": self.name,
            "created_at": self.created_at,
            "events": [event.to_dict() for event in self.events],
            "camera_segments": [segment.to_dict() for segment in self.camera_segments],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "MacroRecording":
        events_payload: Sequence[Dict[str, Any]] = payload.get("events", [])  # type: ignore[arg-type]
        segments_payload: Sequence[Dict[str, Any]] = payload.get("camera_segments", [])  # type: ignore[arg-type]
        events = [MacroEvent.from_dict(event) for event in events_payload]
        segments = [CameraSegment.from_dict(segment) for segment in segments_payload]
        return cls(
            name=str(payload.get("name", "macro")),
            created_at=float(payload.get("created_at", 0.0)),
            events=events,
            camera_segments=segments,
            metadata=dict(payload.get("metadata", {})),
        )

    def describe(self) -> Dict[str, Any]:
        camera_total_dx = sum(seg.sum_angles()[0] for seg in self.camera_segments)
        camera_total_dy = sum(seg.sum_angles()[1] for seg in self.camera_segments)
        return {
            "events": len(self.events),
            "camera_segments": len(self.camera_segments),
            "camera_total_dx_deg": camera_total_dx,
            "camera_total_dy_deg": camera_total_dy,
        }


__all__ = [
    "MacroEvent",
    "CameraSample",
    "CameraSegment",
    "MacroRecording",
    "RECORDING_FORMAT_VERSION",
]
