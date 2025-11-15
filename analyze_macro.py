#!/usr/bin/env python3
"""
Тестовый скрипт для проверки записи и воспроизведения RMB drag событий
"""

import json
import time
from pathlib import Path

def analyze_macro_file(filename):
    """Анализирует сохраненный макрос файл"""
    print(f"\n=== АНАЛИЗ ФАЙЛА: {filename} ===")
    
    try:
        with open(filename, 'r') as f:
            events = json.load(f)
        
        print(f"Всего событий: {len(events)}")
        
        # Анализируем типы событий
        event_types = {}
        mouse_events = []
        rmb_press_events = []
        rmb_release_events = []
        rmb_move_events = []
        
        for i, event in enumerate(events):
            event_type, event_args = event
            event_types[event_type] = event_types.get(event_type, 0) + 1
            
            if event_type.startswith('mouse'):
                mouse_events.append((i, event_type, event_args))
                
                if event_type == 'mouse_press' and event_args[2] == 'Button.right':
                    rmb_press_events.append((i, event_args))
                elif event_type == 'mouse_release' and event_args[2] == 'Button.right':
                    rmb_release_events.append((i, event_args))
                elif event_type == 'mouse_move':
                    rmb_move_events.append((i, event_args))
        
        print(f"\nТипы событий:")
        for event_type, count in event_types.items():
            print(f"  {event_type}: {count}")
        
        print(f"\nRMB события:")
        print(f"  RMB нажатий: {len(rmb_press_events)}")
        print(f"  RMB отпусканий: {len(rmb_release_events)}")
        print(f"  Всего mouse_move: {len(rmb_move_events)}")
        
        # Анализируем последовательность RMB событий
        if rmb_press_events:
            print(f"\nАнализ RMB drag последовательностей:")
            for press_idx, press_args in rmb_press_events:
                press_time = press_args[3]
                print(f"  RMB нажатие #{press_idx} в времени {press_time:.3f}s на позиции ({press_args[0]}, {press_args[1]})")
                
                # Ищем соответствующее отпускание
                for release_idx, release_args in rmb_release_events:
                    if release_args[3] > press_time:
                        release_time = release_args[3]
                        duration = release_time - press_time
                        print(f"    → RMB отпускание #{release_idx} в времени {release_time:.3f}s на позиции ({release_args[0]}, {release_args[1]})")
                        print(f"    → Длительность: {duration:.3f}s")
                        
                        # Считаем движения между нажатием и отпусканием
                        moves_in_drag = []
                        for move_idx, move_args in rmb_move_events:
                            if press_time < move_args[2] < release_time:
                                moves_in_drag.append((move_idx, move_args))
                        
                        print(f"    → Движений во время drag: {len(moves_in_drag)}")
                        
                        if moves_in_drag:
                            first_move = moves_in_drag[0][1]
                            last_move = moves_in_drag[-1][1]
                            total_dx = last_move[0] - first_move[0]
                            total_dy = last_move[1] - first_move[1]
                            print(f"    → Общее смещение: ({total_dx}, {total_dy})")
                            
                            # Показываем первые несколько движений
                            print(f"    → Первые 5 движений:")
                            for j, (move_idx, move_args) in enumerate(moves_in_drag[:5]):
                                print(f"      {j+1}. pos({move_args[0]}, {move_args[1]}) time={move_args[2]:.3f}s")
                        
                        break
        
        # Проверяем временные интервалы
        if len(events) > 1:
            print(f"\nАнализ временных интервалов:")
            intervals = []
            for i in range(1, len(events)):
                prev_time = events[i-1][1][-1]
                curr_time = events[i][1][-1]
                interval = curr_time - prev_time
                intervals.append(interval)
            
            if intervals:
                min_interval = min(intervals)
                max_interval = max(intervals)
                avg_interval = sum(intervals) / len(intervals)
                print(f"  Минимальный интервал: {min_interval:.6f}s")
                print(f"  Максимальный интервал: {max_interval:.6f}s")
                print(f"  Средний интервал: {avg_interval:.6f}s")
                
                # Показываем самые короткие интервалы (возможно проблема)
                short_intervals = [(i, interval) for i, interval in enumerate(intervals) if interval < 0.001]
                if short_intervals:
                    print(f"  Интервалы < 1мс: {len(short_intervals)}")
                    for i, interval in short_intervals[:5]:
                        event_type = events[i+1][0]
                        print(f"    Событие {i+1} ({event_type}): {interval:.6f}s")
    
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