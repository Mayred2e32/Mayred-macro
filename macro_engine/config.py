from __future__ import annotations

import json
import platform
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

CONFIG_PATH = Path(__file__).resolve().parent / "macro_engine_settings.json"


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


@dataclass
class MacroSettings:
    """High level playback/recording tuning knobs."""

    camera_gain: float = 1.0
    gain_x: float = 1.0
    gain_y: float = 1.0
    invert_x: bool = False
    invert_y: bool = False
    target_rate_hz: float = 480.0
    sender_max_step: int = 1
    sender_delay_ms: float = 1.5
    deadzone_threshold: float = 0.35
    reverse_window_ms: float = 30.0
    reverse_tiny_ratio: float = 0.08
    strict_mode: bool = False

    def sanitize(self) -> "MacroSettings":
        return MacroSettings(
            camera_gain=_clamp(float(self.camera_gain), 0.25, 3.0),
            gain_x=_clamp(float(self.gain_x), 0.25, 4.0),
            gain_y=_clamp(float(self.gain_y), 0.25, 4.0),
            invert_x=bool(self.invert_x),
            invert_y=bool(self.invert_y),
            target_rate_hz=_clamp(float(self.target_rate_hz), 90.0, 960.0),
            sender_max_step=max(1, int(self.sender_max_step)),
            sender_delay_ms=_clamp(float(self.sender_delay_ms), 0.0, 4.0),
            deadzone_threshold=_clamp(float(self.deadzone_threshold), 0.0, 2.5),
            reverse_window_ms=_clamp(float(self.reverse_window_ms), 5.0, 120.0),
            reverse_tiny_ratio=_clamp(float(self.reverse_tiny_ratio), 0.0, 1.0),
            strict_mode=bool(self.strict_mode),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MacroSettings":
        base = cls()
        merged = {**base.to_dict(), **(data or {})}
        return cls(**merged).sanitize()


@dataclass
class CameraCalibrationProfile:
    """Per-game calibration that maps raw counts to camera degrees."""

    name: str = "roblox_default"
    dpi: int = 800
    roblox_sensitivity: float = 0.2
    counts_per_degree_x: float = 12.5
    counts_per_degree_y: float = 12.5
    fps: float = 120.0
    epp_enabled: bool = False
    windows_pointer_speed: int = 6
    notes: str = "Roblox standard sensitivity"

    def sanitize(self) -> "CameraCalibrationProfile":
        dpi = max(50, int(self.dpi))
        counts_x = max(0.1, float(self.counts_per_degree_x))
        counts_y = max(0.1, float(self.counts_per_degree_y))
        return CameraCalibrationProfile(
            name=str(self.name or "calibration"),
            dpi=dpi,
            roblox_sensitivity=float(self.roblox_sensitivity),
            counts_per_degree_x=counts_x,
            counts_per_degree_y=counts_y,
            fps=_clamp(float(self.fps), 30.0, 360.0),
            epp_enabled=bool(self.epp_enabled),
            windows_pointer_speed=max(1, min(20, int(self.windows_pointer_speed))),
            notes=str(self.notes or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CameraCalibrationProfile":
        base = cls()
        merged = {**base.to_dict(), **(data or {})}
        return cls(**merged).sanitize()

    @property
    def degrees_per_count_x(self) -> float:
        return 1.0 / self.counts_per_degree_x

    @property
    def degrees_per_count_y(self) -> float:
        return 1.0 / self.counts_per_degree_y

    def degrees_from_counts(self, dx: float, dy: float) -> tuple[float, float]:
        return dx * self.degrees_per_count_x, dy * self.degrees_per_count_y

    def counts_from_degrees(self, angle_dx: float, angle_dy: float) -> tuple[float, float]:
        return angle_dx * self.counts_per_degree_x, angle_dy * self.counts_per_degree_y


@dataclass
class SettingsBundle:
    settings: MacroSettings
    calibrations: Dict[str, CameraCalibrationProfile]
    active_calibration: str
    platform_info: Optional[str] = None

    def resolve_calibration(self, name: Optional[str] = None) -> CameraCalibrationProfile:
        if name and name in self.calibrations:
            return self.calibrations[name]
        if self.active_calibration in self.calibrations:
            return self.calibrations[self.active_calibration]
        # Fallback to first calibration
        return next(iter(self.calibrations.values())).sanitize()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "settings": self.settings.to_dict(),
            "calibrations": {key: cal.to_dict() for key, cal in self.calibrations.items()},
            "active_calibration": self.active_calibration,
            "platform_info": self.platform_info,
        }


DEFAULT_SETTINGS = MacroSettings().sanitize()
DEFAULT_CALIBRATION = CameraCalibrationProfile().sanitize()
DEFAULT_BUNDLE = SettingsBundle(
    settings=DEFAULT_SETTINGS,
    calibrations={DEFAULT_CALIBRATION.name: DEFAULT_CALIBRATION},
    active_calibration=DEFAULT_CALIBRATION.name,
    platform_info=platform.platform(),
)


class SettingsRepository:
    """Loads/saves engine-wide settings and calibrations."""

    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self._bundle = DEFAULT_BUNDLE
        self.load()

    @property
    def bundle(self) -> SettingsBundle:
        return self._bundle

    def load(self) -> None:
        if not self.path.exists():
            self._bundle = DEFAULT_BUNDLE
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            self._bundle = DEFAULT_BUNDLE
            return

        settings = MacroSettings.from_dict(payload.get("settings", {}))
        calibrations_payload = payload.get("calibrations", {})
        calibrations: Dict[str, CameraCalibrationProfile] = {}
        if isinstance(calibrations_payload, dict):
            for name, cal_data in calibrations_payload.items():
                calibrations[name] = CameraCalibrationProfile.from_dict({"name": name, **(cal_data or {})})
        elif isinstance(calibrations_payload, list):
            for cal_data in calibrations_payload:
                cal = CameraCalibrationProfile.from_dict(cal_data or {})
                calibrations[cal.name] = cal
        if not calibrations:
            calibrations = {DEFAULT_CALIBRATION.name: DEFAULT_CALIBRATION}

        active = payload.get("active_calibration") or DEFAULT_CALIBRATION.name
        if active not in calibrations:
            active = next(iter(calibrations.keys()))

        self._bundle = SettingsBundle(
            settings=settings,
            calibrations=calibrations,
            active_calibration=active,
            platform_info=payload.get("platform_info", platform.platform()),
        )

    def save(self) -> None:
        bundle_dict = self._bundle.to_dict()
        self.path.write_text(json.dumps(bundle_dict, indent=4, ensure_ascii=False), encoding="utf-8")

    def update_settings(self, **kwargs: Any) -> MacroSettings:
        settings_data = {**self._bundle.settings.to_dict(), **kwargs}
        self._bundle = SettingsBundle(
            settings=MacroSettings.from_dict(settings_data),
            calibrations=self._bundle.calibrations,
            active_calibration=self._bundle.active_calibration,
            platform_info=self._bundle.platform_info,
        )
        self.save()
        return self._bundle.settings

    def upsert_calibration(self, calibration: CameraCalibrationProfile, make_active: bool = False) -> None:
        cal = calibration.sanitize()
        updated = dict(self._bundle.calibrations)
        updated[cal.name] = cal
        active = cal.name if make_active else self._bundle.active_calibration
        self._bundle = SettingsBundle(
            settings=self._bundle.settings,
            calibrations=updated,
            active_calibration=active,
            platform_info=self._bundle.platform_info,
        )
        self.save()

    def set_active_calibration(self, name: str) -> CameraCalibrationProfile:
        if name not in self._bundle.calibrations:
            raise KeyError(f"Calibration '{name}' not found")
        self._bundle = SettingsBundle(
            settings=self._bundle.settings,
            calibrations=self._bundle.calibrations,
            active_calibration=name,
            platform_info=self._bundle.platform_info,
        )
        self.save()
        return self._bundle.calibrations[name]


__all__ = [
    "MacroSettings",
    "CameraCalibrationProfile",
    "SettingsBundle",
    "SettingsRepository",
    "DEFAULT_SETTINGS",
    "DEFAULT_CALIBRATION",
]
