from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MacroEvent = Tuple[str, Sequence[Any]]


@dataclass
class SegmentReport:
    index: int
    press_event_index: int
    release_event_index: int
    duration: float
    relative_moves: int
    absolute_moves: int
    sum_dx: int
    sum_dy: int
    avg_rate_hz: float
    min_interval_ms: float
    max_interval_ms: float
    avg_interval_ms: float
    first_deltas: List[Tuple[int, int, float]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def length(self) -> float:
        return math.hypot(self.sum_dx, self.sum_dy)


@dataclass
class MacroDiagnosis:
    report: str
    issues: List[str] = field(default_factory=list)
    segments: List[SegmentReport] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    totals: Dict[str, Any] = field(default_factory=dict)


class MacroAnalyzer:
    """Offline analyzer for recorded macro data."""

    FIRST_DELTAS = 15

    def analyze(
        self,
        events: Iterable[MacroEvent],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MacroDiagnosis:
        events_list = list(events)
        issues: List[str] = []
        metadata = metadata or {}

        event_type_counts: Dict[str, int] = {}
        for event_type, _ in events_list:
            event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1

        segments: List[SegmentReport] = []
        current_segment: Optional[Dict[str, Any]] = None

        def _finalise_segment() -> None:
            nonlocal current_segment
            if not current_segment:
                return
            rel_count = len(current_segment["relative"])
            abs_count = len(current_segment["absolute"])
            start_idx = current_segment["press_idx"]
            end_idx = current_segment.get("release_idx", start_idx)
            press_time = current_segment.get("press_time")
            release_time = current_segment.get("release_time", press_time)
            duration = 0.0
            if (press_time is not None) and (release_time is not None):
                duration = max(0.0, release_time - press_time)

            rel_sum_dx = sum(dx for dx, *_ in current_segment["relative"])
            rel_sum_dy = sum(dy for _, dy, *_ in current_segment["relative"])
            first_moves = [
                (dx, dy, ts if press_time is None else ts - press_time)
                for dx, dy, ts in current_segment["relative"][: self.FIRST_DELTAS]
            ]

            intervals = [
                (current_segment["relative"][i + 1][2] - current_segment["relative"][i][2])
                for i in range(len(current_segment["relative"]) - 1)
            ]
            intervals_ms = [max(0.0, interval * 1000.0) for interval in intervals]
            avg_interval_ms = statistics.mean(intervals_ms) if intervals_ms else 0.0
            min_interval_ms = min(intervals_ms) if intervals_ms else 0.0
            max_interval_ms = max(intervals_ms) if intervals_ms else 0.0
            avg_rate = rel_count / duration if duration > 0 else float(rel_count)

            segment_warnings: List[str] = []
            if abs_count:
                segment_warnings.append(
                    "Обнаружены абсолютные перемещения внутри RMB сегмента — они будут проигнорированы при воспроизведении."
                )
            if not rel_count:
                segment_warnings.append("Сегмент не содержит относительных движений мыши.")
            if duration <= 0 and rel_count:
                segment_warnings.append("Нулевой интервал времени между press/release при наличии относительных движений.")

            segments.append(
                SegmentReport(
                    index=len(segments) + 1,
                    press_event_index=start_idx,
                    release_event_index=end_idx,
                    duration=duration,
                    relative_moves=rel_count,
                    absolute_moves=abs_count,
                    sum_dx=rel_sum_dx,
                    sum_dy=rel_sum_dy,
                    avg_rate_hz=avg_rate,
                    min_interval_ms=min_interval_ms,
                    max_interval_ms=max_interval_ms,
                    avg_interval_ms=avg_interval_ms,
                    first_deltas=first_moves,
                    warnings=segment_warnings,
                )
            )
            current_segment = None

        for idx, (event_type, args) in enumerate(events_list):
            timestamp = None
            if isinstance(args, Sequence) and args:
                possible_timestamp = args[-1]
                if isinstance(possible_timestamp, (int, float)):
                    timestamp = float(possible_timestamp)

            if event_type == "mouse_press" and len(args) >= 3 and args[2] == "Button.right":
                _finalise_segment()
                current_segment = {
                    "press_idx": idx,
                    "press_time": timestamp,
                    "relative": [],
                    "absolute": [],
                }
            elif event_type == "mouse_release" and len(args) >= 3 and args[2] == "Button.right":
                if current_segment is not None:
                    current_segment["release_idx"] = idx
                    current_segment["release_time"] = timestamp
                _finalise_segment()
            elif event_type == "mouse_move_relative" and current_segment is not None:
                if len(args) >= 3:
                    dx, dy = int(args[0]), int(args[1])
                    ts = float(args[2])
                elif len(args) >= 2:
                    dx, dy = int(args[0]), int(args[1])
                    ts = timestamp if timestamp is not None else 0.0
                else:
                    dx = dy = 0
                    ts = timestamp if timestamp is not None else 0.0
                current_segment["relative"].append((dx, dy, ts))
            elif event_type == "mouse_move" and current_segment is not None:
                if len(args) >= 3:
                    ts = float(args[2])
                else:
                    ts = timestamp if timestamp is not None else 0.0
                current_segment["absolute"].append((args, ts))

        _finalise_segment()

        if not segments:
            issues.append("ПКМ сегменты не найдены. Проверьте, что запись содержит нажатия правой кнопки мыши.")

        rel_total_count = sum(seg.relative_moves for seg in segments)
        rel_total_dx = sum(seg.sum_dx for seg in segments)
        rel_total_dy = sum(seg.sum_dy for seg in segments)
        total_duration = sum(seg.duration for seg in segments)
        avg_rate_total = rel_total_count / total_duration if total_duration > 0 else float(rel_total_count)

        totals = {
            "event_counts": event_type_counts,
            "segments": len(segments),
            "relative_moves": rel_total_count,
            "sum_dx": rel_total_dx,
            "sum_dy": rel_total_dy,
            "avg_rate_hz": avg_rate_total,
        }

        lines: List[str] = []
        lines.append("=== MACRO DIAGNOSTICS REPORT ===")
        if metadata:
            lines.append("-- Метаданные записи --")
            for key, value in sorted(metadata.items()):
                lines.append(f"{key}: {value}")
            lines.append("")

        lines.append("-- Общая статистика --")
        lines.append(f"Всего событий: {len(events_list)}")
        if event_type_counts:
            lines.append("Типы событий:")
            for event_name, count in sorted(event_type_counts.items()):
                lines.append(f"  {event_name}: {count}")
        lines.append(f"ПКМ сегментов: {len(segments)}")
        lines.append(f"Всего относительных движений: {rel_total_count}")
        lines.append(f"Сумма Δ: ({rel_total_dx}, {rel_total_dy}) | длина {math.hypot(rel_total_dx, rel_total_dy):.2f} px")
        lines.append(f"Средняя частота относительных движений: {avg_rate_total:.2f} Гц")

        for seg in segments:
            lines.append("")
            lines.append(f"--- ПКМ сегмент #{seg.index} ---")
            lines.append(
                f"События: press={seg.press_event_index} → release={seg.release_event_index}; длительность {seg.duration:.4f} с"
            )
            lines.append(
                f"Относительных движений: {seg.relative_moves} (частота {seg.avg_rate_hz:.2f}/с) | Δ=({seg.sum_dx}, {seg.sum_dy})"
            )
            lines.append(
                f"Интервалы Δ: min={seg.min_interval_ms:.3f}мс max={seg.max_interval_ms:.3f}мс avg={seg.avg_interval_ms:.3f}мс"
            )
            if seg.absolute_moves:
                lines.append(f"Абсолютных событий внутри сегмента: {seg.absolute_moves}")
            if seg.first_deltas:
                lines.append("Первые относительные дельты:")
                for idx_move, (dx, dy, rel_time) in enumerate(seg.first_deltas, 1):
                    lines.append(f"  #{idx_move}: Δ({dx},{dy}) @ {rel_time:.4f} с")
            for warning in seg.warnings:
                lines.append(f"⚠️ {warning}")
                issues.append(warning)

        if rel_total_count and rel_total_count <= 5:
            issues.append("Очень мало относительных движений мыши — возможна некорректная запись.")

        lines.append("")
        if issues:
            lines.append("-- Обнаруженные проблемы --")
            for issue in issues:
                lines.append(f" • {issue}")
        else:
            lines.append("Проблем не обнаружено.")

        return MacroDiagnosis(
            report="\n".join(lines),
            issues=issues,
            segments=segments,
            metadata=metadata,
            totals=totals,
        )
