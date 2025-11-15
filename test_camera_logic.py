#!/usr/bin/env python3
"""
Тест для проверки логики воспроизведения движения камеры RMB drag
Этот файл демонстрирует правильную последовательность событий
"""

# Симуляция событий макроса с движением камеры RMB drag
test_events = [
    # Начальная позиция мыши
    ('mouse_pos', (100, 100, 0.0)),
    
    # Нажатие ПКМ (начало движения камеры)
    ('mouse_press', (100, 100, 'Button.right', 0.5)),
    
    # Движение мыши с зажатой ПКМ (движение камеры)
    ('mouse_move', (110, 105, 0.6)),   # +10 вправо, +5 вниз
    ('mouse_move', (120, 115, 0.7)),  # +10 вправо, +10 вниз
    ('mouse_move', (125, 125, 0.8)),  # +5 вправо, +10 вниз
    ('mouse_move', (130, 135, 0.9)),  # +5 вправо, +10 вниз
    
    # Отпускание ПКМ (конец движения камеры)
    ('mouse_release', (130, 135, 'Button.right', 1.0)),
    
    # Обычное движение мыши (без ПКМ)
    ('mouse_move', (200, 200, 1.1)),
]

def simulate_camera_logic():
    """
    Симуляция исправленной логики воспроизведения камеры
    """
    print("=== Симуляция исправленной логики RMB drag ===")
    
    pressed_buttons = set()
    rmb_center = None
    last_mouse_pos = None
    
    for event in test_events:
        event_type, event_args = event
        
        if event_type == 'mouse_pos':
            x, y = event_args[0], event_args[1]
            print(f"🎯 Начальная позиция: ({x}, {y})")
            last_mouse_pos = (x, y)
            
        elif event_type == 'mouse_press':
            x, y, button_str = event_args[0], event_args[1], event_args[2]
            if button_str == 'Button.right':
                pressed_buttons.add('right')
                rmb_center = (x, y)
                last_mouse_pos = (x, y)
                print(f"🔫 ПКМ нажата в точке: ({x}, {y})")
                print(f"   - rmb_center установлен: {rmb_center}")
                print(f"   - last_mouse_pos инициализирован: {last_mouse_pos}")
                
        elif event_type == 'mouse_move':
            x, y = event_args[0], event_args[1]
            
            if 'right' in pressed_buttons and rmb_center is not None:
                if last_mouse_pos is not None:
                    dx = int((x - last_mouse_pos[0]))
                    dy = int((y - last_mouse_pos[1]))
                    print(f"📹 Движение камеры: ({x}, {y})")
                    print(f"   - Предыдущая позиция: {last_mouse_pos}")
                    print(f"   - Инкрементальная дельта: ({dx}, {dy})")
                    print(f"   - Отправляем относительное движение: send_relative_line({dx}, {dy})")
                last_mouse_pos = (x, y)
            else:
                print(f"🖱️ Обычное движение: ({x}, {y})")
                last_mouse_pos = (x, y)
                
        elif event_type == 'mouse_release':
            x, y, button_str = event_args[0], event_args[1], event_args[2]
            if button_str == 'Button.right':
                pressed_buttons.discard('right')
                print(f"🔫 ПКМ отпущена в точке: ({x}, {y})")
                print(f"   - rmb_center сброшен: None")
                print(f"   - last_mouse_pos сохранен: {last_mouse_pos}")
                rmb_center = None
    
    print("\n✅ Симуляция завершена успешно!")
    print("Ключевые преимущества исправленной логики:")
    print("1. Инкрементальные дельты рассчитываются от предыдущей позиции")
    print("2. Нет накопления ошибок от обновления центра во время движения")
    print("3. Четкое разделение между точкой нажатия (rmb_center) и инкрементальными расчетами")

if __name__ == "__main__":
    simulate_camera_logic()