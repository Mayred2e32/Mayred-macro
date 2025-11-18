#!/usr/bin/env python3
"""
Тестовый скрипт для проверки функции send_relative_line
Запускается отдельно для проверки отправки относительных движений мыши
"""

import time
import platform
import sys

# Копируем нужные константы и функции из основного файла
CAMERA_GAIN = 1.0
DEBUG_CAMERA_MOVEMENT = True

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    def _ensure_wintype(attr, ctype):
        if not hasattr(wintypes, attr):
            setattr(wintypes, attr, ctype)

    _ensure_wintype("LRESULT", ctypes.c_ssize_t)
    _ensure_wintype("WPARAM", ctypes.c_size_t)
    _ensure_wintype("LPARAM", ctypes.c_ssize_t)

    _ensure_wintype("HANDLE", ctypes.c_void_p)
    _ensure_wintype("HWND", wintypes.HANDLE)
    _ensure_wintype("HINSTANCE", wintypes.HANDLE)
    _ensure_wintype("HMODULE", wintypes.HANDLE)
    _ensure_wintype("HMENU", wintypes.HANDLE)
    _ensure_wintype("HICON", wintypes.HANDLE)
    _ensure_wintype("HCURSOR", wintypes.HANDLE)
    _ensure_wintype("HBRUSH", wintypes.HANDLE)
    _ensure_wintype("HDC", wintypes.HANDLE)

    _ensure_wintype("ATOM", ctypes.c_ushort)
    _ensure_wintype("UINT", ctypes.c_uint)
    _ensure_wintype("DWORD", ctypes.c_uint32)
    _ensure_wintype("ULONG_PTR", ctypes.c_size_t)

    # Константы и структуры для SendInput
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
    INPUT_MOUSE = 0
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_MOVE_NOCOALESCE = 0x2000

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class INPUT(ctypes.Structure):
        class _I(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT)]
        _anonymous_ = ("i",)
        _fields_ = [("type", wintypes.DWORD), ("i", _I)]

    user32 = ctypes.windll.user32
    SendInput = user32.SendInput
    mouse_event = user32.mouse_event
    MOUSEEVENTF_MOVE_OLD = 0x0001

    def _build_move_input(dx: int, dy: int) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi.dx = int(dx)
        inp.mi.dy = int(dy)
        inp.mi.mouseData = 0
        inp.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_MOVE_NOCOALESCE
        inp.mi.time = 0
        inp.mi.dwExtraInfo = 0
        return inp

    def send_relative_line(dx: int, dy: int):
        """Улучшенная реализация: разбиваем на маленькие шаги с задержками для игр."""
        dx = int(dx); dy = int(dy)
        if dx == 0 and dy == 0:
            return

        # КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: каждый вызов функции
        if DEBUG_CAMERA_MOVEMENT:
            print(f"[SEND_RELATIVE] Called with dx={dx}, dy={dy}")

        # РАЗБИВАЕМ НА МАЛЕНЬКИЕ ШАГИ с задержками
        # Это помогает играм лучше обрабатывать движения
        max_step = 3  # максимальный шаг за один раз
        steps_x = abs(dx) // max_step + (1 if abs(dx) % max_step != 0 else 0)
        steps_y = abs(dy) // max_step + (1 if abs(dy) % max_step != 0 else 0)
        total_steps = max(steps_x, steps_y, 1)
        
        step_dx = dx / total_steps
        step_dy = dy / total_steps
        
        for i in range(total_steps):
            current_dx = int(step_dx * (i + 1)) - int(step_dx * i)
            current_dy = int(step_dy * (i + 1)) - int(step_dy * i)
            
            if current_dx != 0 or current_dy != 0:
                # Используем mouse_event для лучшей совместимости с играми
                mouse_event(MOUSEEVENTF_MOVE_OLD, current_dx, current_dy, 0, 0)
                
                if DEBUG_CAMERA_MOVEMENT:
                    print(f"[SEND_RELATIVE] Step {i+1}/{total_steps}: ({current_dx},{current_dy})")
                
                # Небольшая задержка между шагами для игр
                if i < total_steps - 1:  # не задерживаем после последнего шага
                    time.sleep(0.001)  # 1ms задержка
        
        if DEBUG_CAMERA_MOVEMENT:
            print(f"[SEND_RELATIVE] Completed: total delta=({dx},{dy}) in {total_steps} steps")

else:
    # На Linux/macOS используем pynput.Controller().move как относительное перемещение
    from pynput import mouse as _mouse

    def send_relative_line(dx: int, dy: int):
        dx = int(dx); dy = int(dy)
        if dx == 0 and dy == 0:
            return
            
        # КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: каждый вызов функции
        if DEBUG_CAMERA_MOVEMENT:
            print(f"[SEND_RELATIVE LINUX] Called with dx={dx}, dy={dy}")
            
        steps = max(abs(dx), abs(dy))
        step_x = dx / float(steps)
        step_y = dy / float(steps)
        cur_x = 0.0
        cur_y = 0.0
        prev_ix = 0
        prev_iy = 0
        ctrl = _mouse.Controller()
        events_sent = 0
        
        for _ in range(steps):
            cur_x += step_x
            cur_y += step_y
            ix = int(round(cur_x))
            iy = int(round(cur_y))
            sx = ix - prev_ix
            sy = iy - prev_iy
            if sx != 0 or sy != 0:
                ctrl.move(sx, sy)
                events_sent += 1
                prev_ix = ix
                prev_iy = iy
                
        if DEBUG_CAMERA_MOVEMENT:
            print(f"[SEND_RELATIVE LINUX] Total events sent: {events_sent}, final delta=({dx},{dy})")

def test_send_relative_line():
    """Тестируем функцию send_relative_line с различными параметрами"""
    print("=== ТЕСТИРОВАНИЕ SEND_RELATIVE_LINE ===")
    print(f"Платформа: {platform.system()}")
    print("Убедитесь что курсор мыши виден и не заблокирован")
    print("Наблюдайте за движением курсора в течение 10 секунд")
    print()
    
    # Ждем 3 секунды чтобы пользователь подготовился
    print("Подготовка...")
    for i in range(3, 0, -1):
        print(f"Тест начнется через {i}...")
        time.sleep(1)
    
    print("НАЧАЛО ТЕСТОВ!")
    
    # Тест 1: Простое движение вправо
    print("\n--- Тест 1: Движение вправо на 50 пикселей ---")
    send_relative_line(50, 0)
    time.sleep(1)
    
    # Тест 2: Простое движение влево
    print("\n--- Тест 2: Движение влево на 50 пикселей ---")
    send_relative_line(-50, 0)
    time.sleep(1)
    
    # Тест 3: Движение вниз
    print("\n--- Тест 3: Движение вниз на 30 пикселей ---")
    send_relative_line(0, 30)
    time.sleep(1)
    
    # Тест 4: Движение вверх
    print("\n--- Тест 4: Движение вверх на 30 пикселей ---")
    send_relative_line(0, -30)
    time.sleep(1)
    
    # Тест 5: Диагональное движение
    print("\n--- Тест 5: Диагональное движение (вправо-вниз) ---")
    send_relative_line(40, 40)
    time.sleep(1)
    
    # Тест 6: Маленькое движение
    print("\n--- Тест 6: Маленькое движение (1 пиксель) ---")
    send_relative_line(1, 1)
    time.sleep(1)
    
    # Тест 7: Большое движение
    print("\n--- Тест 7: Большое движение (100 пикселей вправо) ---")
    send_relative_line(100, 0)
    time.sleep(1)
    
    # Тест 8: Обратное большое движение
    print("\n--- Тест 8: Большое движение (100 пикселей влево) ---")
    send_relative_line(-100, 0)
    time.sleep(1)
    
    print("\n=== ТЕСТЫ ЗАВЕРШЕНЫ ===")
    print("Если курсор двигался плавно и предсказуемо - функция работает корректно")
    print("Если курсор не двигался или двигался рывками - проблема в функции отправки")

if __name__ == "__main__":
    test_send_relative_line()