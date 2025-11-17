#!/usr/bin/env python3
"""
Тестовый скрипт для проверки записи и воспроизведения RMB drag событий
"""

import json
import math
from pathlib import Path

FIRST_DELTAS_TO_SHOW = 15

def analyze_macro_file(filename):
    print(f"\n=== АНАЛИЗ ФАЙЛА: {filename} ===")

    try:
        with open(filename, 'r', encoding='utf-8') as f:
            events = json.load(f)

        print(f"Всего событий: {len(events)}")

        event_types = {}
        for event_type, _ in events:
            event_types[event_type] = event_types.get(event_type, 0) + 1

        print("\nТипы событий:")
        for event_type, count in sorted(event_types.items()):
            print(f"  {event_type}: {count}")

        segments = []
        current_segment = None
        all_relative_moves = []

        for idx, (event_type, event_args) in enumerate(events):
            if event_type == 'mouse_move_relative':
                all_relative_moves.append((idx, event_args))
            if event_type == 'mouse_press' and len(event_args) >= 4 and event_args[2] == 'Button.right':
                current_segment = {
                    'press_idx': idx,
                    'press_time': event_args[-1],
                    'press_pos': (event_args[0], event_args[1]),
                    'relative_moves': [],
                    'absolute_moves': [],
                }
            elif event_type == 'mouse_move_relative' and current_segment:
                current_segment['relative_moves'].append((idx, event_args))
            elif event_type == 'mouse_move' and current_segment:
                current_segment['absolute_moves'].append((idx, event_args))
            elif event_type == 'mouse_release' and len(event_args) >= 4 and event_args[2] == 'Button.right' and current_segment:
                current_segment['release_idx'] = idx
                current_segment['release_time'] = event_args[-1]
                current_segment['release_pos'] = (event_args[0], event_args[1])
                segments.append(current_segment)
                current_segment = None

        if not segments:
            print("\nПКМ-сегменты не найдены.")
        else:
            print(f"\nНайдено ПКМ-сегментов: {len(segments)}")
            total_rel_dx = 0
            total_rel_dy = 0
            total_rel_count = 0
            total_rel_duration = 0.0
            total_abs_dx = 0.0
            total_abs_dy = 0.0
            for seg_idx, segment in enumerate(segments, 1):
                press_time = segment.get('press_time')
                release_time = segment.get('release_time')
                duration = (release_time - press_time) if (press_time is not None and release_time is not None) else None
                rel_moves = segment['relative_moves']
                abs_moves = segment['absolute_moves']

                rel_sum_dx = sum(args[0] for _, args in rel_moves)
                rel_sum_dy = sum(args[1] for _, args in rel_moves)
                rel_length = math.hypot(rel_sum_dx, rel_sum_dy)
                rel_rate = (len(rel_moves) / duration) if duration and duration > 0 else len(rel_moves)
                abs_sum_dx = sum(abs(args[0]) for _, args in rel_moves)
                abs_sum_dy = sum(abs(args[1]) for _, args in rel_moves)
                avg_abs_dx = (abs_sum_dx / len(rel_moves)) if rel_moves else 0.0
                avg_abs_dy = (abs_sum_dy / len(rel_moves)) if rel_moves else 0.0

                total_rel_dx += rel_sum_dx
                total_rel_dy += rel_sum_dy
                total_abs_dx += abs_sum_dx
                total_abs_dy += abs_sum_dy
                total_rel_count += len(rel_moves)
                if duration and duration > 0:
                    total_rel_duration += duration

                print(f"\n--- ПКМ сегмент #{seg_idx} ---")
                print(f"  Индексы событий: press={segment['press_idx']} → release={segment.get('release_idx')}")
                if duration is not None:
                    print(f"  Длительность: {duration:.4f} с")
                print(f"  Относительных движений: {len(rel_moves)} (частота {rel_rate:.1f}/с)")
                print(f"    Сумма Δ: ({rel_sum_dx}, {rel_sum_dy}), длина={rel_length:.2f} px")
                print(f"    Средняя |Δ|: X={avg_abs_dx:.2f}, Y={avg_abs_dy:.2f}")

                if len(rel_moves) > 1:
                    intervals = [rel_moves[i + 1][1][2] - rel_moves[i][1][2] for i in range(len(rel_moves) - 1)]
                    avg_interval = sum(intervals) / len(intervals)
                    print(
                        f"    Интервалы: min={min(intervals):.4f} с, max={max(intervals):.4f} с, avg={avg_interval:.4f} с"
                    )

                if rel_moves:
                    print(f"    Первые дельты (до {FIRST_DELTAS_TO_SHOW} шт.):")
                    for idx_move, (move_idx, move_args) in enumerate(rel_moves[:FIRST_DELTAS_TO_SHOW], 1):
                        move_time = move_args[2]
                        rel_time = (move_time - press_time) if press_time is not None else move_time
                        print(
                            f"      #{idx_move}: Δ({move_args[0]},{move_args[1]}) @ {rel_time:.4f} с (event #{move_idx})"
                        )

                if abs_moves:
                    print(f"  Абсолютных движений в сегменте: {len(abs_moves)}")
                    first_abs = abs_moves[0][1]
                    last_abs = abs_moves[-1][1]
                    abs_dx = last_abs[0] - first_abs[0]
                    abs_dy = last_abs[1] - first_abs[1]
                    print(f"    Сумма абсолютных сдвигов: ({abs_dx}, {abs_dy})")

            if total_rel_count:
                total_rel_length = math.hypot(total_rel_dx, total_rel_dy)
                avg_rate = total_rel_count / total_rel_duration if total_rel_duration > 0 else total_rel_count
                avg_abs_dx_overall = total_abs_dx / total_rel_count if total_rel_count else 0.0
                avg_abs_dy_overall = total_abs_dy / total_rel_count if total_rel_count else 0.0
                print("\nСуммарно по всем ПКМ-сегментам:")
                print(f"  Общая сумма Δ: ({total_rel_dx}, {total_rel_dy}), длина={total_rel_length:.2f} px")
                print(
                    f"  Всего относительных движений: {total_rel_count}, суммарная длительность={total_rel_duration:.4f} с, "
                    f"средняя частота {avg_rate:.1f}/с"
                )
                print(f"  Средняя |Δ|: X={avg_abs_dx_overall:.2f}, Y={avg_abs_dy_overall:.2f}")

        if all_relative_moves:
            print(f"\nПервые {min(FIRST_DELTAS_TO_SHOW, len(all_relative_moves))} относительных движений по всему макросу:")
            for idx_move, (move_idx, move_args) in enumerate(all_relative_moves[:FIRST_DELTAS_TO_SHOW], 1):
                move_time = move_args[2]
                print(f"  #{idx_move}: Δ({move_args[0]},{move_args[1]}) @ {move_time:.4f} с (event #{move_idx})")
            all_sum_dx = sum(args[0] for _, args in all_relative_moves)
            all_sum_dy = sum(args[1] for _, args in all_relative_moves)
            all_length = math.hypot(all_sum_dx, all_sum_dy)
            avg_abs_dx_all = sum(abs(args[0]) for _, args in all_relative_moves) / len(all_relative_moves)
            avg_abs_dy_all = sum(abs(args[1]) for _, args in all_relative_moves) / len(all_relative_moves)
            first_time = all_relative_moves[0][1][2]
            last_time = all_relative_moves[-1][1][2]
            span = max(0.0, last_time - first_time)
            overall_rate = len(all_relative_moves) / span if span > 0 else len(all_relative_moves)
            print(f"  Всего относительных событий: {len(all_relative_moves)}, span={span:.4f} с, средняя частота {overall_rate:.1f}/с")
            print(f"  Сумма Δ по макросу: ({all_sum_dx}, {all_sum_dy}), длина={all_length:.2f} px")
            print(f"  Средняя |Δ|: X={avg_abs_dx_all:.2f}, Y={avg_abs_dy_all:.2f}")
            if len(all_relative_moves) > 1:
                rel_intervals = [
                    all_relative_moves[i + 1][1][2] - all_relative_moves[i][1][2]
                    for i in range(len(all_relative_moves) - 1)
                ]
                rel_intervals = [interval for interval in rel_intervals if interval >= 0]
                if rel_intervals:
                    print(
                        f"  Интервалы Δ: min={min(rel_intervals):.4f} с, max={max(rel_intervals):.4f} с, avg={sum(rel_intervals)/len(rel_intervals):.4f} с"
                    )

        if len(events) > 1:
            intervals = []
            for i in range(1, len(events)):
                prev_time = events[i - 1][1][-1]
                curr_time = events[i][1][-1]
                intervals.append(curr_time - prev_time)

            if intervals:
                print("\nАнализ временных интервалов (между последовательными событиями):")
                print(f"  Минимальный интервал: {min(intervals):.6f} с")
                print(f"  Максимальный интервал: {max(intervals):.6f} с")
                print(f"  Средний интервал: {sum(intervals) / len(intervals):.6f} с")
                short_intervals = [(i, interval) for i, interval in enumerate(intervals) if interval < 0.001]
                if short_intervals:
                    print(f"  Интервалы < 1мс: {len(short_intervals)}")
                    for i, interval in short_intervals[:5]:
                        event_type = events[i + 1][0]
                        print(f"    Событие {i + 1} ({event_type}): {interval:.6f} с")

    except Exception as e:
        print(f"Ошибка при анализе файла: {e}")

def list_macro_files():
    """Показывает все доступные файлы макросов"""
    macros_dir = Path("macros")
    if not macros_dir.exists():
        print("Директория macros не найдена")
        return []
    
    macro_files = list(macros_dir.glob("*.json"))
    print(f"\n=== НАЙДЕННЫЕ ФАЙЛЫ МАКРОСОВ ===")
    for i, file in enumerate(macro_files):
        print(f"{i+1}. {file.name}")
    
    return macro_files

def main():
    print("=== АНАЛИЗАТОР МАКРОСОВ RMB DRAG ===")
    
    macro_files = list_macro_files()
    
    if not macro_files:
        print("Файлы макросов не найдены. Сначала запишите макрос с RMB drag.")
        return
    
    # Анализируем все файлы
    for file in macro_files:
        analyze_macro_file(file)
    
    print(f"\n=== РЕКОМЕНДАЦИИ ===")
    print("1. Убедитесь что в макросе есть события RMB press и RMB release")
    print("2. Между RMB press и RMB release должны быть mouse_move события")
    print("3. Временные интервалы между событиями должны быть реалистичными")
    print("4. Если интервалы слишком короткие (< 1мс) - может быть проблема с записью")

if __name__ == "__main__":
    main()