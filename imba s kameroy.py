import sys
import time
import threading
import queue
import json
import os
import math
import platform
from pathlib import Path
from collections import deque

# --- Импорты для GUI (PySide6) ---
from PySide6.QtCore import Qt, Signal, QObject, QSize
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QInputDialog, QMessageBox,
    QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QFormLayout, QFrame, QGraphicsDropShadowEffect
)
from PySide6.QtGui import QFont, QColor, QPixmap, QIcon

# --- Импорты для записи и воспроизведения (pynput) ---
from pynput import mouse, keyboard

# --- Конфигурация и словари для безопасного сопоставления клавиш ---
MACROS_DIR = Path(__file__).parent / "macros"
SPECIAL_KEYS = {
    'Key.alt': keyboard.Key.alt, 'Key.alt_l': keyboard.Key.alt_l, 'Key.alt_r': keyboard.Key.alt_r,
    'Key.backspace': keyboard.Key.backspace, 'Key.caps_lock': keyboard.Key.caps_lock,
    'Key.cmd': keyboard.Key.cmd, 'Key.cmd_l': keyboard.Key.cmd_l, 'Key.cmd_r': keyboard.Key.cmd_r,
    'Key.ctrl': keyboard.Key.ctrl, 'Key.ctrl_l': keyboard.Key.ctrl_l, 'Key.ctrl_r': keyboard.Key.ctrl_r,
    'Key.delete': keyboard.Key.delete, 'Key.down': keyboard.Key.down, 'Key.end': keyboard.Key.end,
    'Key.enter': keyboard.Key.enter, 'Key.esc': keyboard.Key.esc, 'Key.f1': keyboard.Key.f1,
    'Key.f2': keyboard.Key.f2, 'Key.f3': keyboard.Key.f3, 'Key.f4': keyboard.Key.f4, 'Key.f5': keyboard.Key.f5,
    'Key.f6': keyboard.Key.f6, 'Key.f7': keyboard.Key.f7, 'Key.f8': keyboard.Key.f8, 'Key.f9': keyboard.Key.f9,
    'Key.f10': keyboard.Key.f10, 'Key.f11': keyboard.Key.f11, 'Key.f12': keyboard.Key.f12,
    'Key.home': keyboard.Key.home, 'Key.insert': keyboard.Key.insert, 'Key.left': keyboard.Key.left,
    'Key.media_next': keyboard.Key.media_next, 'Key.media_play_pause': keyboard.Key.media_play_pause,
    'Key.media_previous': keyboard.Key.media_previous, 'Key.media_volume_down': keyboard.Key.media_volume_down,
    'Key.media_volume_mute': keyboard.Key.media_volume_mute, 'Key.media_volume_up': keyboard.Key.media_volume_up,
    'Key.menu': keyboard.Key.menu, 'Key.num_lock': keyboard.Key.num_lock, 'Key.page_down': keyboard.Key.page_down,
    'Key.page_up': keyboard.Key.page_up, 'Key.pause': keyboard.Key.pause, 'Key.print_screen': keyboard.Key.print_screen,
    'Key.right': keyboard.Key.right, 'Key.scroll_lock': keyboard.Key.scroll_lock,
    'Key.shift': keyboard.Key.shift, 'Key.shift_l': keyboard.Key.shift_l, 'Key.shift_r': keyboard.Key.shift_r,
    'Key.space': keyboard.Key.space, 'Key.tab': keyboard.Key.tab, 'Key.up': keyboard.Key.up
}
MOUSE_BUTTONS = {
    'Button.left': mouse.Button.left, 'Button.right': mouse.Button.right, 'Button.middle': mouse.Button.middle,
}

# --- Настройки симуляции камеры и конфиг приложения ---
MIN_STEP_THRESHOLD = 0    # Минимальный модуль дельты, чтобы отправлять движение
DEBUG_CAMERA_MOVEMENT = True  # Детальное логирование движений камеры

SETTINGS_FILE = Path(__file__).parent / "settings.json"
DEFAULT_SETTINGS = {
    "camera_gain": 1.0,
    "gain_x": 1.0,
    "gain_y": 1.0,
    "invert_x": False,
    "invert_y": False,
    "sender_mode": "auto",
    "sender_max_step": 1,
    "sender_delay_ms": 3.0,
    "cursor_lock_enabled": False,
    "calibration_target_px": 400.0,
    "deadzone_threshold": 0.5,
    "reverse_window_ms": 40.0,
    "reverse_tiny_ratio": 0.1,
}


def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def _to_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def sanitize_settings(raw):
    if not isinstance(raw, dict):
        raw = {}
    data = DEFAULT_SETTINGS.copy()
    data["camera_gain"] = _clamp(
        _to_float(raw.get("camera_gain", data["camera_gain"]), data["camera_gain"]),
        0.3,
        3.0
    )
    data["gain_x"] = _clamp(
        _to_float(raw.get("gain_x", data["gain_x"]), data["gain_x"]),
        0.25,
        4.0
    )
    data["gain_y"] = _clamp(
        _to_float(raw.get("gain_y", data["gain_y"]), data["gain_y"]),
        0.25,
        4.0
    )
    data["invert_x"] = _to_bool(raw.get("invert_x", data["invert_x"]))
    data["invert_y"] = _to_bool(raw.get("invert_y", data["invert_y"]))

    mode_value = str(raw.get("sender_mode", data.get("sender_mode", "auto"))).strip().lower()
    if mode_value not in {"auto", "sendinput", "mouse_event"}:
        mode_value = "auto"
    data["sender_mode"] = mode_value

    data["sender_max_step"] = _clamp(
        _to_int(raw.get("sender_max_step", data["sender_max_step"]), data["sender_max_step"]),
        1,
        2
    )
    data["sender_delay_ms"] = _clamp(
        _to_float(raw.get("sender_delay_ms", data["sender_delay_ms"]), data["sender_delay_ms"]),
        2.0,
        3.0
    )
    data["cursor_lock_enabled"] = _to_bool(raw.get("cursor_lock_enabled", data["cursor_lock_enabled"]))
    data["calibration_target_px"] = _clamp(
        _to_float(raw.get("calibration_target_px", data["calibration_target_px"]), data["calibration_target_px"]),
        50.0,
        2000.0
    )
    data["deadzone_threshold"] = _clamp(
        _to_float(raw.get("deadzone_threshold", data["deadzone_threshold"]), data["deadzone_threshold"]),
        0.0,
        2.0
    )
    data["reverse_window_ms"] = _clamp(
        _to_float(raw.get("reverse_window_ms", data["reverse_window_ms"]), data["reverse_window_ms"]),
        10.0,
        120.0
    )
    data["reverse_tiny_ratio"] = _clamp(
        _to_float(raw.get("reverse_tiny_ratio", data["reverse_tiny_ratio"]), data["reverse_tiny_ratio"]),
        0.01,
        0.5
    )
    return data


CURRENT_SETTINGS = sanitize_settings(DEFAULT_SETTINGS)

CAMERA_GAIN = CURRENT_SETTINGS["camera_gain"]           # Общий множитель чувствительности камеры
GAIN_X_MULTIPLIER = CURRENT_SETTINGS["gain_x"]
GAIN_Y_MULTIPLIER = CURRENT_SETTINGS["gain_y"]
CAMERA_GAIN_X = CAMERA_GAIN * GAIN_X_MULTIPLIER
CAMERA_GAIN_Y = CAMERA_GAIN * GAIN_Y_MULTIPLIER
INVERT_X_AXIS = CURRENT_SETTINGS["invert_x"]
INVERT_Y_AXIS = CURRENT_SETTINGS["invert_y"]
SENDER_MODE = CURRENT_SETTINGS["sender_mode"]
SEND_RELATIVE_MAX_STEP = CURRENT_SETTINGS["sender_max_step"]
SEND_RELATIVE_DELAY = CURRENT_SETTINGS["sender_delay_ms"] / 1000.0
CURSOR_LOCK_ENABLED = CURRENT_SETTINGS["cursor_lock_enabled"]
CALIBRATION_TARGET_PX = CURRENT_SETTINGS["calibration_target_px"]
DEADZONE_THRESHOLD = CURRENT_SETTINGS["deadzone_threshold"]
REVERSE_WINDOW_MS = CURRENT_SETTINGS["reverse_window_ms"]
REVERSE_WINDOW_SECONDS = REVERSE_WINDOW_MS / 1000.0
REVERSE_TINY_RATIO = CURRENT_SETTINGS["reverse_tiny_ratio"]


class SettingsManager:
    def __init__(self, path=SETTINGS_FILE):
        self.path = path
        self.data = CURRENT_SETTINGS.copy()
        self.load()

    def load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    merged = self.data.copy()
                    merged.update(raw)
                    self.data = sanitize_settings(merged)
                else:
                    self.data = sanitize_settings(self.data)
            except Exception as exc:
                print(f"[SETTINGS] Ошибка загрузки: {exc}")
                self.data = sanitize_settings(self.data)
        else:
            self.data = sanitize_settings(self.data)

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as exc:
            print(f"[SETTINGS] Ошибка сохранения: {exc}")

    def update(self, key, value):
        updated = self.data.copy()
        updated[key] = value
        self.data = sanitize_settings(updated)
        self.save()

    def get(self, key):
        return self.data.get(key, DEFAULT_SETTINGS.get(key))

    def as_dict(self):
        return self.data.copy()


def apply_runtime_settings(settings_data):
    global CURRENT_SETTINGS, CAMERA_GAIN, GAIN_X_MULTIPLIER, GAIN_Y_MULTIPLIER
    global CAMERA_GAIN_X, CAMERA_GAIN_Y, INVERT_X_AXIS, INVERT_Y_AXIS
    global SENDER_MODE, SEND_RELATIVE_MAX_STEP, SEND_RELATIVE_DELAY, CALIBRATION_TARGET_PX
    global CURSOR_LOCK_ENABLED, DEADZONE_THRESHOLD, REVERSE_WINDOW_MS, REVERSE_WINDOW_SECONDS, REVERSE_TINY_RATIO
    CURRENT_SETTINGS = sanitize_settings(settings_data)
    CAMERA_GAIN = CURRENT_SETTINGS["camera_gain"]
    GAIN_X_MULTIPLIER = CURRENT_SETTINGS["gain_x"]
    GAIN_Y_MULTIPLIER = CURRENT_SETTINGS["gain_y"]
    CAMERA_GAIN_X = CAMERA_GAIN * GAIN_X_MULTIPLIER
    CAMERA_GAIN_Y = CAMERA_GAIN * GAIN_Y_MULTIPLIER
    INVERT_X_AXIS = CURRENT_SETTINGS["invert_x"]
    INVERT_Y_AXIS = CURRENT_SETTINGS["invert_y"]
    SENDER_MODE = CURRENT_SETTINGS["sender_mode"]
    SEND_RELATIVE_MAX_STEP = CURRENT_SETTINGS["sender_max_step"]
    SEND_RELATIVE_DELAY = CURRENT_SETTINGS["sender_delay_ms"] / 1000.0
    CURSOR_LOCK_ENABLED = CURRENT_SETTINGS["cursor_lock_enabled"]
    CALIBRATION_TARGET_PX = CURRENT_SETTINGS["calibration_target_px"]
    DEADZONE_THRESHOLD = CURRENT_SETTINGS["deadzone_threshold"]
    REVERSE_WINDOW_MS = CURRENT_SETTINGS["reverse_window_ms"]
    REVERSE_WINDOW_SECONDS = REVERSE_WINDOW_MS / 1000.0
    REVERSE_TINY_RATIO = CURRENT_SETTINGS["reverse_tiny_ratio"]

    sender_instance = globals().get("RELATIVE_SENDER")
    if sender_instance is not None and hasattr(sender_instance, "on_settings_changed"):
        sender_instance.on_settings_changed()

    return CURRENT_SETTINGS

# --- Низкоуровневый хелпер для относительного движения (Windows: SendInput) ---
IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    import ctypes
    import time
    from ctypes import wintypes

    # Константы и структуры для SendInput
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
    INPUT_MOUSE = 0
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_MOVE_NOCOALESCE = 0x2000  # важно для игр: не склеивать события

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
    kernel32 = ctypes.windll.kernel32
    SendInput = user32.SendInput
    # Альтернатива: старый mouse_event API
    mouse_event = user32.mouse_event

    ERROR_INVALID_PARAMETER = 87
    MOUSEEVENTF_MOVE_OLD = 0x0001

    class POINT(ctypes.Structure):
        _fields_ = [
            ("x", wintypes.LONG),
            ("y", wintypes.LONG),
        ]

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    def _build_move_input(dx: int, dy: int, flags: int) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi.dx = int(dx)
        inp.mi.dy = int(dy)
        inp.mi.mouseData = 0
        inp.mi.dwFlags = flags
        inp.mi.time = 0
        inp.mi.dwExtraInfo = 0
        return inp

    class RelativeMouseSender:
        def __init__(self):
            self._auto_sendinput_blocked = False
            self._sendinput_nocoalesce_supported = None
            self._last_mode_used = None
            self._last_modes_sequence = tuple()
            self._last_error = None

        def _determine_mode(self):
            mode = (SENDER_MODE or "auto").strip().lower()
            if mode == "sendinput":
                return "sendinput"
            if mode == "mouse_event":
                return "mouse_event"
            if self._auto_sendinput_blocked:
                return "mouse_event"
            return "sendinput"

        def _probe_nocoalesce(self):
            if self._sendinput_nocoalesce_supported is not None:
                return self._sendinput_nocoalesce_supported
            test_input = _build_move_input(0, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_MOVE_NOCOALESCE)
            kernel32.SetLastError(0)
            result = SendInput(1, ctypes.byref(test_input), ctypes.sizeof(INPUT))
            err = kernel32.GetLastError()
            if result == 0 and err == ERROR_INVALID_PARAMETER:
                self._sendinput_nocoalesce_supported = False
            else:
                self._sendinput_nocoalesce_supported = True
            return self._sendinput_nocoalesce_supported

        def _send_via_sendinput(self, dx: int, dy: int) -> bool:
            try:
                flags = MOUSEEVENTF_MOVE
                if self._probe_nocoalesce():
                    flags |= MOUSEEVENTF_MOVE_NOCOALESCE
                input_struct = _build_move_input(dx, dy, flags)
                kernel32.SetLastError(0)
                sent = SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))
                if sent != 1:
                    err = kernel32.GetLastError()
                    self._last_error = ctypes.WinError(err)
                    return False
                self._last_error = None
                return True
            except Exception as exc:
                self._last_error = exc
                return False

        def _send_via_mouse_event(self, dx: int, dy: int) -> bool:
            try:
                mouse_event(MOUSEEVENTF_MOVE_OLD, dx, dy, 0, 0)
                self._last_error = None
                return True
            except Exception as exc:
                self._last_error = exc
                return False

        def _send_step(self, mode: str, dx: int, dy: int):
            if mode == "sendinput":
                return self._send_via_sendinput(dx, dy), "sendinput"
            return self._send_via_mouse_event(dx, dy), "mouse_event"

        def send(self, dx: int, dy: int):
            dx = int(dx)
            dy = int(dy)
            if dx == 0 and dy == 0:
                return None

            max_step = max(1, int(SEND_RELATIVE_MAX_STEP))
            delay_seconds = max(0.0, float(SEND_RELATIVE_DELAY))

            if DEBUG_CAMERA_MOVEMENT:
                print(
                    f"[SEND_RELATIVE] Requested dx={dx}, dy={dy}, max_step={max_step}, "
                    f"delay={delay_seconds * 1000:.3f}ms, pref={SENDER_MODE}"
                )

            steps_x = math.ceil(abs(dx) / max_step) if max_step else 0
            steps_y = math.ceil(abs(dy) / max_step) if max_step else 0
            total_steps = max(steps_x, steps_y, 1)

            step_dx = dx / total_steps
            step_dy = dy / total_steps

            prev_dx = 0
            prev_dy = 0
            last_mode = None
            modes_sequence = []

            for i in range(1, total_steps + 1):
                target_dx = int(round(step_dx * i))
                target_dy = int(round(step_dy * i))
                current_dx = target_dx - prev_dx
                current_dy = target_dy - prev_dy
                prev_dx = target_dx
                prev_dy = target_dy

                if current_dx == 0 and current_dy == 0:
                    continue

                desired_mode = self._determine_mode()
                success, mode_used = self._send_step(desired_mode, current_dx, current_dy)
                if not success and desired_mode == "sendinput" and SENDER_MODE == "auto":
                    self._auto_sendinput_blocked = True
                    if DEBUG_CAMERA_MOVEMENT:
                        print("[SENDER] SendInput failed in auto mode, fallback to mouse_event")
                    success, mode_used = self._send_step("mouse_event", current_dx, current_dy)

                if not success:
                    if DEBUG_CAMERA_MOVEMENT:
                        print(
                            f"[SENDER ERROR] Failed to send ({current_dx},{current_dy}) via {desired_mode}: {self._last_error}"
                        )
                    break

                last_mode = mode_used
                if not modes_sequence or modes_sequence[-1] != mode_used:
                    modes_sequence.append(mode_used)

                if DEBUG_CAMERA_MOVEMENT:
                    print(f"[SEND_RELATIVE] Step {i}/{total_steps}: ({current_dx},{current_dy}) via {mode_used}")

                if i < total_steps and delay_seconds > 0:
                    time.sleep(delay_seconds)

            self._last_mode_used = last_mode
            self._last_modes_sequence = tuple(modes_sequence)
            return last_mode

        def on_settings_changed(self):
            if SENDER_MODE != "auto":
                self._auto_sendinput_blocked = False
            else:
                self._auto_sendinput_blocked = False

        def get_last_mode(self):
            return self._last_mode_used

        def get_modes_sequence(self):
            return self._last_modes_sequence

        def get_last_error(self):
            return self._last_error

    RELATIVE_SENDER = RelativeMouseSender()

    def send_relative_line(dx: int, dy: int):
        """Отправляет относительное перемещение и возвращает фактический режим отправки."""
        return RELATIVE_SENDER.send(dx, dy)

    class CursorLocker:
        def __init__(self, recenter_interval: float = 0.005):
            self._recenter_interval = recenter_interval
            self._last_recenter = 0.0
            self._center = None
            self._original = None
            self._hwnd = None
            self.active = False

        def activate(self) -> bool:
            try:
                point = POINT()
                if not user32.GetCursorPos(ctypes.byref(point)):
                    return False
                self._original = (point.x, point.y)
                hwnd = user32.WindowFromPoint(point)
                if not hwnd:
                    return False
                rect = RECT()
                if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
                    return False
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if width <= 0 or height <= 0:
                    return False
                center_point = POINT(rect.left + width // 2, rect.top + height // 2)
                if not user32.ClientToScreen(hwnd, ctypes.byref(center_point)):
                    return False
                self._center = (center_point.x, center_point.y)
                self._hwnd = hwnd
                if not user32.SetCursorPos(self._center[0], self._center[1]):
                    return False
                self._last_recenter = time.perf_counter()
                self.active = True
                if DEBUG_CAMERA_MOVEMENT:
                    print(f"[CURSOR LOCK] Activated center={self._center}, original={self._original}")
                return True
            except Exception as exc:
                if DEBUG_CAMERA_MOVEMENT:
                    print(f"[CURSOR LOCK] Activation failed: {exc}")
                self.active = False
                return False

        def maintain(self):
            if not self.active or self._center is None:
                return
            now = time.perf_counter()
            if now - self._last_recenter >= self._recenter_interval:
                user32.SetCursorPos(self._center[0], self._center[1])
                self._last_recenter = now

        def release(self):
            if not self.active:
                return
            if self._original is not None:
                user32.SetCursorPos(self._original[0], self._original[1])
                if DEBUG_CAMERA_MOVEMENT:
                    print(f"[CURSOR LOCK] Restored cursor to {self._original}")
            self.active = False

        @property
        def center(self):
            return self._center

        @property
        def original(self):
            return self._original

        @property
        def hwnd(self):
            return self._hwnd

    WM_INPUT = 0x00FF
    RID_INPUT = 0x10000003
    RIM_TYPEMOUSE = 0
    RIDEV_INPUTSINK = 0x00000100
    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002

    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [
            ("usUsagePage", wintypes.USHORT),
            ("usUsage", wintypes.USHORT),
            ("dwFlags", wintypes.DWORD),
            ("hwndTarget", wintypes.HWND),
        ]

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [
            ("dwType", wintypes.DWORD),
            ("dwSize", wintypes.DWORD),
            ("hDevice", wintypes.HANDLE),
            ("wParam", wintypes.WPARAM),
        ]

    class RAWMOUSE(ctypes.Structure):
        _fields_ = [
            ("usFlags", wintypes.USHORT),
            ("ulButtons", wintypes.ULONG),
            ("usButtonFlags", wintypes.USHORT),
            ("usButtonData", wintypes.USHORT),
            ("ulRawButtons", wintypes.ULONG),
            ("lLastX", wintypes.LONG),
            ("lLastY", wintypes.LONG),
            ("ulExtraInformation", wintypes.ULONG),
        ]

    class RAWINPUTDATA(ctypes.Union):
        _fields_ = [
            ("mouse", RAWMOUSE),
        ]

    class RAWINPUT(ctypes.Structure):
        _anonymous_ = ("data",)
        _fields_ = [
            ("header", RAWINPUTHEADER),
            ("data", RAWINPUTDATA),
        ]

    WNDPROC = ctypes.WINFUNCTYPE(
        wintypes.LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HCURSOR),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    _RAW_LISTENER_INSTANCE = None

    @WNDPROC
    def _raw_input_wnd_proc(hwnd, msg, wParam, lParam):
        listener = _RAW_LISTENER_INSTANCE
        if msg == WM_INPUT and listener is not None:
            listener._process_raw_input(lParam)
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wParam, lParam)

    class RawMouseDeltaListener(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True)
            self.queue = queue.Queue()
            self._stop_event = threading.Event()
            self._ready_event = threading.Event()
            self._hwnd = None
            self._class_name = f"RawInputCapture_{int(time.time()*1000)}"
            self._error = None

        def run(self):
            global _RAW_LISTENER_INSTANCE
            try:
                self._setup_window()
            except Exception as exc:
                self._error = exc
                self._ready_event.set()
                return
            _RAW_LISTENER_INSTANCE = self
            self._ready_event.set()
            try:
                self._message_loop()
            finally:
                _RAW_LISTENER_INSTANCE = None

        def _setup_window(self):
            hInstance = kernel32.GetModuleHandleW(None)
            wndclass = WNDCLASS()
            wndclass.style = 0
            wndclass.lpfnWndProc = _raw_input_wnd_proc
            wndclass.cbClsExtra = 0
            wndclass.cbWndExtra = 0
            wndclass.hInstance = hInstance
            wndclass.hIcon = None
            wndclass.hCursor = None
            wndclass.hbrBackground = None
            wndclass.lpszMenuName = None
            wndclass.lpszClassName = self._class_name

            atom = user32.RegisterClassW(ctypes.byref(wndclass))
            if not atom:
                err = kernel32.GetLastError()
                if err != 1410:  # класс уже зарегистрирован
                    raise ctypes.WinError(err)

            self._hwnd = user32.CreateWindowExW(
                0,
                self._class_name,
                self._class_name,
                0,
                0, 0, 0, 0,
                0,
                0,
                hInstance,
                None
            )
            if not self._hwnd:
                raise ctypes.WinError(kernel32.GetLastError())

            rid = RAWINPUTDEVICE()
            rid.usUsagePage = 0x01
            rid.usUsage = 0x02
            rid.dwFlags = RIDEV_INPUTSINK
            rid.hwndTarget = self._hwnd
            if not user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid)):
                raise ctypes.WinError(kernel32.GetLastError())

        def _message_loop(self):
            msg = wintypes.MSG()
            while not self._stop_event.is_set():
                ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if ret in (0, -1):
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        def _process_raw_input(self, lparam):
            size = wintypes.UINT(0)
            if user32.GetRawInputData(
                lparam,
                RID_INPUT,
                None,
                ctypes.byref(size),
                ctypes.sizeof(RAWINPUTHEADER)
            ) == 0xFFFFFFFF:
                return
            if size.value == 0:
                return
            buffer = ctypes.create_string_buffer(size.value)
            if user32.GetRawInputData(
                lparam,
                RID_INPUT,
                buffer,
                ctypes.byref(size),
                ctypes.sizeof(RAWINPUTHEADER)
            ) == 0xFFFFFFFF:
                return
            raw = ctypes.cast(buffer, ctypes.POINTER(RAWINPUT)).contents
            if raw.header.dwType == RIM_TYPEMOUSE:
                dx = raw.mouse.lLastX
                dy = raw.mouse.lLastY
                if dx != 0 or dy != 0:
                    timestamp = time.perf_counter()
                    self.queue.put((int(dx), int(dy), timestamp))

        def wait_until_ready(self, timeout=1.0):
            self._ready_event.wait(timeout)
            return self._error is None and self._hwnd is not None

        def stop(self):
            self._stop_event.set()
            if self._hwnd:
                user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            self.join(timeout=0.5)

else:
    # На Linux/macOS используем pynput.Controller().move как относительное перемещение
    from pynput import mouse as _mouse

    def send_relative_line(dx: int, dy: int):
        dx = int(dx); dy = int(dy)
        if dx == 0 and dy == 0:
            return

        max_step = max(1, int(SEND_RELATIVE_MAX_STEP))
        delay_seconds = max(0.0, float(SEND_RELATIVE_DELAY))

        # КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: каждый вызов функции
        if DEBUG_CAMERA_MOVEMENT:
            print(
                f"[SEND_RELATIVE LINUX] Called with dx={dx}, dy={dy}, max_step={max_step}, "
                f"delay={delay_seconds * 1000:.3f}ms"
            )

        steps_x = math.ceil(abs(dx) / max_step)
        steps_y = math.ceil(abs(dy) / max_step)
        total_steps = max(steps_x, steps_y, 1)

        step_dx = dx / float(total_steps)
        step_dy = dy / float(total_steps)

        prev_dx = 0
        prev_dy = 0
        ctrl = _mouse.Controller()
        events_sent = 0

        for i in range(1, total_steps + 1):
            target_dx = int(round(step_dx * i))
            target_dy = int(round(step_dy * i))
            move_x = target_dx - prev_dx
            move_y = target_dy - prev_dy
            prev_dx = target_dx
            prev_dy = target_dy

            if move_x != 0 or move_y != 0:
                ctrl.move(move_x, move_y)
                events_sent += 1
                if DEBUG_CAMERA_MOVEMENT:
                    print(f"[SEND_RELATIVE LINUX] Step {i}/{total_steps}: ({move_x},{move_y})")
                if i < total_steps and delay_seconds > 0:
                    time.sleep(delay_seconds)

        if DEBUG_CAMERA_MOVEMENT:
            print(f"[SEND_RELATIVE LINUX] Total events sent: {events_sent}, final delta=({dx},{dy})")
        return "pynput"

# Сигналы для безопасного обновления GUI из других потоков
class WorkerSignals(QObject):
    log_message = Signal(str)
    recording_stopped = Signal()
    playback_finished = Signal()
    settings_updated = Signal(dict)
    calibration_finished = Signal()

# --- Основной класс приложения ---
class MacroApp(QWidget):
    def __init__(self):
        super().__init__()
        self.recorded_events = []
        self.is_recording = False
        self.is_playing = False
        self._calibration_in_progress = False
        self.settings_manager = SettingsManager()
        apply_runtime_settings(self.settings_manager.as_dict())
        self.signals = WorkerSignals()
        os.makedirs(MACROS_DIR, exist_ok=True)
        self._build_ui()
        self._apply_styles()  # Применяем дизайн
        self.refresh_macro_list()
        self.signals.log_message.connect(self.log)
        self.signals.recording_stopped.connect(self.on_recording_finished)
        self.signals.playback_finished.connect(self.on_playback_finished)
        self.signals.settings_updated.connect(self._on_settings_updated)
        self.signals.calibration_finished.connect(self._on_calibration_finished)
        self._refresh_settings_controls(self.settings_manager.as_dict())
        self._update_environment_info()
        self._update_calibration_ui_state()
        self.log("Приложение готово к работе.")

    def _build_ui(self):
        """Создает структуру интерфейса (виджеты и компоновку)."""
        self.setWindowTitle("Ayred Macro")
        if os.path.exists("logo.png"):
            self.setWindowIcon(QIcon("logo.png"))
        self.setMinimumSize(850, 650)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 10, 20, 20)
        main_layout.setSpacing(15)

        # --- Заголовок с логотипом ---
        header_layout = QHBoxLayout()
        logo_label = QLabel()
        if os.path.exists("logo.png"):
            pixmap = QPixmap("logo.png")
            logo_label.setPixmap(pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        title_label = QLabel("Ayred Macro")
        title_label.setObjectName("titleLabel")
        header_layout.addWidget(logo_label)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # --- Панель управления ---
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)
        self.record_button = QPushButton("старт(aladayngay❤️)")
        self.record_button.setObjectName("recordButton")
        self.record_button.setMinimumHeight(45)
        self.record_button.clicked.connect(self.toggle_recording)

        self.play_button = QPushButton("Воспроизвести")
        self.play_button.setObjectName("playButton")
        self.play_button.setMinimumHeight(45)
        self.play_button.clicked.connect(self.play_selected_macro)

        self.stop_playback_button = QPushButton("Остановить воспроизведение")
        self.stop_playback_button.setObjectName("stopButton")
        self.stop_playback_button.setMinimumHeight(45)
        self.stop_playback_button.setEnabled(False)
        self.stop_playback_button.clicked.connect(self.stop_playback)

        controls_layout.addWidget(self.record_button)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.stop_playback_button)
        main_layout.addLayout(controls_layout)

        # --- Основная рабочая область ---
        workspace_layout = QHBoxLayout()
        workspace_layout.setSpacing(15)

        # Левая колонка: Макросы
        left_panel = QFrame()
        left_panel.setObjectName("panel")
        left_panel_layout = QVBoxLayout(left_panel)
        left_panel_layout.setContentsMargins(15, 15, 15, 15)
        left_panel_layout.setSpacing(10)

        left_panel_layout.addWidget(QLabel("Сохраненные макросы:"))
        self.macro_list_widget = QListWidget()
        left_panel_layout.addWidget(self.macro_list_widget)

        list_buttons_layout = QHBoxLayout()
        self.save_button = QPushButton("Сохранить последнюю запись")
        self.save_button.clicked.connect(self.save_macro)
        self.delete_button = QPushButton("Удалить выбранный")
        self.delete_button.clicked.connect(self.delete_macro)
        list_buttons_layout.addWidget(self.save_button)
        list_buttons_layout.addWidget(self.delete_button)
        left_panel_layout.addLayout(list_buttons_layout)

        workspace_layout.addWidget(left_panel, stretch=3)

        # Правая колонка: Настройки и Лог
        right_column = QVBoxLayout()
        right_column.setSpacing(15)

        # Настройки
        settings_panel = QFrame()
        settings_panel.setObjectName("panel")
        settings_panel_layout = QVBoxLayout(settings_panel)
        settings_panel_layout.setContentsMargins(15, 15, 15, 15)

        settings_panel_layout.addWidget(QLabel("Настройки воспроизведения:"))
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        self.loops_spinbox = QSpinBox()
        self.loops_spinbox.setRange(1, 9999)
        self.loops_spinbox.setValue(1)
        self.infinite_checkbox = QCheckBox("Повторять бесконечно")
        self.infinite_checkbox.stateChanged.connect(lambda state: self.loops_spinbox.setEnabled(state == 0))
        form_layout.addRow("Количество повторов:", self.loops_spinbox)
        form_layout.addRow(self.infinite_checkbox)
        settings_panel_layout.addLayout(form_layout)

        settings_panel_layout.addWidget(QLabel("Камера и чувствительность:"))
        camera_form = QFormLayout()
        camera_form.setSpacing(10)

        self.camera_gain_spinbox = QDoubleSpinBox()
        self.camera_gain_spinbox.setRange(0.3, 3.0)
        self.camera_gain_spinbox.setDecimals(3)
        self.camera_gain_spinbox.setSingleStep(0.01)
        self.camera_gain_spinbox.valueChanged.connect(self.on_camera_gain_changed)
        camera_form.addRow("CAMERA_GAIN:", self.camera_gain_spinbox)

        self.gain_x_spinbox = QDoubleSpinBox()
        self.gain_x_spinbox.setRange(0.25, 4.0)
        self.gain_x_spinbox.setDecimals(3)
        self.gain_x_spinbox.setSingleStep(0.01)
        self.gain_x_spinbox.valueChanged.connect(self.on_gain_x_changed)
        camera_form.addRow("GAIN X:", self.gain_x_spinbox)

        self.gain_y_spinbox = QDoubleSpinBox()
        self.gain_y_spinbox.setRange(0.25, 4.0)
        self.gain_y_spinbox.setDecimals(3)
        self.gain_y_spinbox.setSingleStep(0.01)
        self.gain_y_spinbox.valueChanged.connect(self.on_gain_y_changed)
        camera_form.addRow("GAIN Y:", self.gain_y_spinbox)

        invert_container = QWidget()
        invert_layout = QHBoxLayout(invert_container)
        invert_layout.setContentsMargins(0, 0, 0, 0)
        invert_layout.setSpacing(10)
        self.invert_x_checkbox = QCheckBox("Invert X")
        self.invert_y_checkbox = QCheckBox("Invert Y")
        self.invert_x_checkbox.stateChanged.connect(self.on_invert_x_changed)
        self.invert_y_checkbox.stateChanged.connect(self.on_invert_y_changed)
        invert_layout.addWidget(self.invert_x_checkbox)
        invert_layout.addWidget(self.invert_y_checkbox)
        camera_form.addRow("Инверсия осей:", invert_container)

        self.deadzone_spinbox = QDoubleSpinBox()
        self.deadzone_spinbox.setRange(0.0, 2.0)
        self.deadzone_spinbox.setDecimals(3)
        self.deadzone_spinbox.setSingleStep(0.05)
        self.deadzone_spinbox.valueChanged.connect(self.on_deadzone_changed)
        camera_form.addRow("Deadzone (px):", self.deadzone_spinbox)

        self.reverse_window_spinbox = QDoubleSpinBox()
        self.reverse_window_spinbox.setRange(10.0, 120.0)
        self.reverse_window_spinbox.setDecimals(1)
        self.reverse_window_spinbox.setSingleStep(1.0)
        self.reverse_window_spinbox.valueChanged.connect(self.on_reverse_window_changed)
        camera_form.addRow("Suppress window (мс):", self.reverse_window_spinbox)

        self.reverse_ratio_spinbox = QDoubleSpinBox()
        self.reverse_ratio_spinbox.setRange(0.01, 0.5)
        self.reverse_ratio_spinbox.setDecimals(3)
        self.reverse_ratio_spinbox.setSingleStep(0.01)
        self.reverse_ratio_spinbox.valueChanged.connect(self.on_reverse_ratio_changed)
        camera_form.addRow("Tiny reverse ratio:", self.reverse_ratio_spinbox)

        self.sender_step_spinbox = QSpinBox()
        self.sender_step_spinbox.setRange(1, 2)
        self.sender_step_spinbox.valueChanged.connect(self.on_sender_step_changed)
        camera_form.addRow("Max step (px):", self.sender_step_spinbox)

        self.sender_delay_spinbox = QDoubleSpinBox()
        self.sender_delay_spinbox.setRange(2.0, 3.0)
        self.sender_delay_spinbox.setDecimals(3)
        self.sender_delay_spinbox.setSingleStep(0.1)
        self.sender_delay_spinbox.valueChanged.connect(self.on_sender_delay_changed)
        camera_form.addRow("Delay (мс):", self.sender_delay_spinbox)

        self.sender_mode_combobox = QComboBox()
        self.sender_mode_combobox.addItem("Auto (SendInput -> mouse_event)", "auto")
        self.sender_mode_combobox.addItem("SendInput", "sendinput")
        self.sender_mode_combobox.addItem("mouse_event", "mouse_event")
        self.sender_mode_combobox.currentIndexChanged.connect(self.on_sender_mode_changed)
        camera_form.addRow("Sender:", self.sender_mode_combobox)

        self.cursor_lock_checkbox = QCheckBox("Cursor-lock при RMB")
        self.cursor_lock_checkbox.stateChanged.connect(self.on_cursor_lock_changed)
        camera_form.addRow("Cursor lock:", self.cursor_lock_checkbox)

        self.calibration_target_spinbox = QDoubleSpinBox()
        self.calibration_target_spinbox.setRange(50.0, 2000.0)
        self.calibration_target_spinbox.setDecimals(1)
        self.calibration_target_spinbox.setSingleStep(10.0)
        self.calibration_target_spinbox.valueChanged.connect(self.on_calibration_target_changed)
        self.calibrate_button = QPushButton("Автокалибровка")
        self.calibrate_button.clicked.connect(self.start_autocalibration)

        calibration_container = QWidget()
        calibration_layout = QHBoxLayout(calibration_container)
        calibration_layout.setContentsMargins(0, 0, 0, 0)
        calibration_layout.setSpacing(8)
        calibration_layout.addWidget(self.calibration_target_spinbox)
        calibration_layout.addWidget(self.calibrate_button)
        camera_form.addRow("Цель (px):", calibration_container)

        settings_panel_layout.addLayout(camera_form)

        self.environment_label = QLabel()
        self.environment_label.setWordWrap(True)
        self.environment_label.setText("Проверка системных параметров...")
        settings_panel_layout.addWidget(self.environment_label)

        right_column.addWidget(settings_panel)

        # Лог
        log_panel = QFrame()
        log_panel.setObjectName("panel")
        log_panel_layout = QVBoxLayout(log_panel)
        log_panel_layout.setContentsMargins(15, 15, 15, 15)
        log_panel_layout.addWidget(QLabel("Лог выполнения:"))
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        log_panel_layout.addWidget(self.log_edit)
        right_column.addWidget(log_panel, stretch=1)

        workspace_layout.addLayout(right_column, stretch=4)
        main_layout.addLayout(workspace_layout)

    def _apply_styles(self):
        """Применяет весь QSS-стиль к приложению."""
        # Цветовая палитра
        BG_GRADIENT = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FEF9E7, stop:1 #FDEBD0);"
        PANEL_BG = "#FFFFFF"
        TEXT_COLOR = "#424949"
        PRIMARY_GRADIENT = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F5B041, stop:1 #F8C471);"
        PRIMARY_HOVER = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F8C471, stop:1 #FAD7A0);"
        STOP_GRADIENT = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E74C3C, stop:1 #EC7063);"
        STOP_HOVER = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #EC7063, stop:1 #F1948A);"
        SECONDARY_BG = "#F2F3F4"
        SECONDARY_HOVER = "#E5E7E9"
        ACCENT_COLOR = "#5DADE2"  # Синий из логотипа

        self.setStyleSheet(f"""
            QWidget {{
                font-family: 'Segoe UI', 'Arial';
                font-size: 10pt;
                color: {TEXT_COLOR};
            }}
            #titleLabel {{
                font-size: 18pt;
                font-weight: bold;
                color: #2E4053;
            }}
            MacroApp {{
                background: {BG_GRADIENT};
            }}
            QFrame#panel {{
                background-color: {PANEL_BG};
                border-radius: 12px;
            }}
            QLabel {{
                font-weight: bold;
                padding-left: 2px;
            }}
            /* --- Кнопки --- */
            QPushButton {{
                background-color: {SECONDARY_BG};
                border: none;
                padding: 8px 12px;
                border-radius: 8px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {SECONDARY_HOVER};
            }}
            QPushButton#recordButton, QPushButton#playButton {{
                background: {PRIMARY_GRADIENT};
                color: white;
            }}
            QPushButton#recordButton:hover, QPushButton#playButton:hover {{
                background: {PRIMARY_HOVER};
            }}
            QPushButton#stopButton {{
                background: {STOP_GRADIENT};
                color: white;
            }}
            QPushButton#stopButton:hover {{
                background: {STOP_HOVER};
            }}
            /* --- Список макросов --- */
            QListWidget {{
                border: 1px solid #EAECEE;
                background-color: #FBFCFC;
                border-radius: 8px;
            }}
            QListWidget::item {{
                padding: 8px;
            }}
            QListWidget::item:selected {{
                background-color: {ACCENT_COLOR};
                color: white;
                border-radius: 4px;
            }}
            /* --- Поля ввода и лог --- */
            QTextEdit, QSpinBox {{
                border: 1px solid #EAECEE;
                background-color: #FBFCFC;
                border-radius: 8px;
                padding: 5px;
            }}
            QTextEdit {{
                color: #566573;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                subcontrol-origin: border;
                width: 16px;
                border-radius: 4px;
            }}
            QSpinBox::up-arrow {{ image: url(none); }}
            QSpinBox::down-arrow {{ image: url(none); }}
            /* --- Чекбокс --- */
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 1px solid #D5DBDB;
                border-radius: 5px;
            }}
            QCheckBox::indicator:checked {{
                background-color: {ACCENT_COLOR};
                border: none;
            }}
        """)

        # Применение теней к панелям
        for panel in self.findChildren(QFrame):
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(25)
            shadow.setColor(QColor(0, 0, 0, 40))
            shadow.setOffset(0, 2)
            panel.setGraphicsEffect(shadow)

    def _set_spin_value(self, widget, value):
        if widget is None:
            return
        widget.blockSignals(True)
        widget.setValue(value)
        widget.blockSignals(False)

    def _set_checkbox_state(self, checkbox, checked):
        if checkbox is None:
            return
        checkbox.blockSignals(True)
        checkbox.setChecked(checked)
        checkbox.blockSignals(False)

    def _refresh_settings_controls(self, data=None):
        if not hasattr(self, "camera_gain_spinbox"):
            return
        if data is None:
            data = self.settings_manager.as_dict()
        self._set_spin_value(self.camera_gain_spinbox, float(data.get("camera_gain", CAMERA_GAIN)))
        self._set_spin_value(self.gain_x_spinbox, float(data.get("gain_x", GAIN_X_MULTIPLIER)))
        self._set_spin_value(self.gain_y_spinbox, float(data.get("gain_y", GAIN_Y_MULTIPLIER)))
        self._set_checkbox_state(self.invert_x_checkbox, bool(data.get("invert_x", INVERT_X_AXIS)))
        self._set_checkbox_state(self.invert_y_checkbox, bool(data.get("invert_y", INVERT_Y_AXIS)))
        self._set_spin_value(self.deadzone_spinbox, float(data.get("deadzone_threshold", DEADZONE_THRESHOLD)))
        self._set_spin_value(self.reverse_window_spinbox, float(data.get("reverse_window_ms", REVERSE_WINDOW_MS)))
        self._set_spin_value(self.reverse_ratio_spinbox, float(data.get("reverse_tiny_ratio", REVERSE_TINY_RATIO)))
        self._set_spin_value(self.sender_step_spinbox, int(data.get("sender_max_step", SEND_RELATIVE_MAX_STEP)))
        self._set_spin_value(self.sender_delay_spinbox, float(data.get("sender_delay_ms", SEND_RELATIVE_DELAY * 1000.0)))

        if hasattr(self, "sender_mode_combobox"):
            mode_value = str(data.get("sender_mode", SENDER_MODE))
            self.sender_mode_combobox.blockSignals(True)
            index = self.sender_mode_combobox.findData(mode_value)
            if index != -1:
                self.sender_mode_combobox.setCurrentIndex(index)
            self.sender_mode_combobox.blockSignals(False)

        if hasattr(self, "cursor_lock_checkbox"):
            self._set_checkbox_state(self.cursor_lock_checkbox, bool(data.get("cursor_lock_enabled", CURSOR_LOCK_ENABLED)))

        self._set_spin_value(self.calibration_target_spinbox, float(data.get("calibration_target_px", CALIBRATION_TARGET_PX)))
        self._update_calibration_ui_state()

    def _on_settings_updated(self, data):
        apply_runtime_settings(data)
        self._refresh_settings_controls(data)
        self._update_environment_info()

    def _update_setting(self, key, value):
        current = self.settings_manager.as_dict().get(key)
        if current == value:
            return
        self.settings_manager.update(key, value)
        self._on_settings_updated(self.settings_manager.as_dict())

    def _on_calibration_finished(self):
        self._calibration_in_progress = False
        self._update_calibration_ui_state()

    def _update_calibration_ui_state(self):
        if hasattr(self, "calibrate_button"):
            enabled = (not self._calibration_in_progress) and (not self.is_recording) and (not self.is_playing)
            self.calibrate_button.setEnabled(enabled)

    def _update_environment_info(self):
        if not hasattr(self, "environment_label"):
            return
        messages = []
        if IS_WINDOWS:
            scale_info = "Масштаб дисплея: неизвестно"
            try:
                dpi = ctypes.windll.user32.GetDpiForSystem()
                if dpi:
                    scale = dpi / 96.0
                    if abs(scale - 1.0) > 0.01:
                        scale_info = f"⚠️ Масштаб дисплея {scale*100:.0f}% — рекомендуется автокалибровка."
                    else:
                        scale_info = "Масштаб дисплея: 100%"
            except Exception:
                pass
            messages.append(scale_info)
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\\Mouse") as key:
                    mouse_speed, _ = winreg.QueryValueEx(key, "MouseSpeed")
                if str(mouse_speed) != "0":
                    messages.append("⚠️ Включена опция «Повысить точность указателя». Автокалибровка обязательна.")
                else:
                    messages.append("«Повысить точность указателя» отключена.")
            except Exception:
                messages.append("Состояние EPP определить не удалось.")
            messages.append("Совет: выполняйте автокалибровку при изменении DPI или EPP.")
        else:
            messages.append("Среда: не Windows. Автокалибровка использует координаты курсора.")
        self.environment_label.setText("\n".join(messages))

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_edit.append(f"[{timestamp}] {message}")

    def on_camera_gain_changed(self, value):
        self._update_setting("camera_gain", float(value))
        self.log(
            f"CAMERA_GAIN = {CAMERA_GAIN:.3f} → X={CAMERA_GAIN_X:.3f}, Y={CAMERA_GAIN_Y:.3f}"
        )

    def on_gain_x_changed(self, value):
        self._update_setting("gain_x", float(value))
        self.log(
            f"GAIN X множитель = {GAIN_X_MULTIPLIER:.3f} (эффективное X={CAMERA_GAIN_X:.3f})"
        )

    def on_gain_y_changed(self, value):
        self._update_setting("gain_y", float(value))
        self.log(
            f"GAIN Y множитель = {GAIN_Y_MULTIPLIER:.3f} (эффективное Y={CAMERA_GAIN_Y:.3f})"
        )

    def on_deadzone_changed(self, value):
        self._update_setting("deadzone_threshold", float(value))
        self.log(f"Deadzone = {DEADZONE_THRESHOLD:.3f} px")

    def on_reverse_window_changed(self, value):
        self._update_setting("reverse_window_ms", float(value))
        self.log(f"Окно подавления реверсов = {REVERSE_WINDOW_MS:.1f} мс")

    def on_reverse_ratio_changed(self, value):
        self._update_setting("reverse_tiny_ratio", float(value))
        self.log(
            f"Порог tiny reverse = {REVERSE_TINY_RATIO * 100:.1f}% от среднего шага"
        )

    def on_invert_x_changed(self, state):
        self._update_setting("invert_x", state == Qt.Checked)
        self.log("Инверсия оси X " + ("включена" if INVERT_X_AXIS else "выключена"))

    def on_invert_y_changed(self, state):
        self._update_setting("invert_y", state == Qt.Checked)
        self.log("Инверсия оси Y " + ("включена" if INVERT_Y_AXIS else "выключена"))

    def on_sender_step_changed(self, value):
        self._update_setting("sender_max_step", int(value))
        self.log(f"Максимальный шаг отправки = {SEND_RELATIVE_MAX_STEP}")

    def on_sender_delay_changed(self, value):
        self._update_setting("sender_delay_ms", float(value))
        self.log(f"Задержка между шагами = {SEND_RELATIVE_DELAY * 1000:.3f} мс")

    def on_sender_mode_changed(self, index):
        if not hasattr(self, "sender_mode_combobox"):
            return
        mode = self.sender_mode_combobox.itemData(index)
        if mode is None:
            return
        self._update_setting("sender_mode", str(mode))
        if IS_WINDOWS:
            sender_instance = globals().get("RELATIVE_SENDER")
            effective = sender_instance.get_last_mode() if sender_instance else None
        else:
            effective = "pynput"
        self.log(f"Sender mode = {SENDER_MODE} (last={effective or 'n/a'})")

    def on_cursor_lock_changed(self, state):
        enabled = (state == Qt.Checked)
        self._update_setting("cursor_lock_enabled", enabled)
        status = "включен" if CURSOR_LOCK_ENABLED else "выключен"
        self.log(f"Cursor-lock {status}")

    def on_calibration_target_changed(self, value):
        self._update_setting("calibration_target_px", float(value))

    def start_autocalibration(self):
        if self.is_recording or self.is_playing:
            QMessageBox.warning(self, "Автокалибровка", "Остановите запись и воспроизведение перед автокалибровкой.")
            return
        if self._calibration_in_progress:
            return
        self._calibration_in_progress = True
        self._update_calibration_ui_state()
        target = float(self.calibration_target_spinbox.value())
        self.log(f"Автокалибровка: цель {target:.1f} px. Удерживайте ПКМ и выполните плавный drag.")
        threading.Thread(target=self._calibration_worker, args=(target,), daemon=True).start()

    def _calibration_worker(self, target_length):
        raw_listener = None
        raw_ready = False
        sum_dx = 0
        sum_dy = 0
        event_count = 0
        first_moves = []
        pressed = False
        segment_active = False
        last_pos = None
        done_event = threading.Event()
        listener = None
        try:
            if IS_WINDOWS:
                try:
                    raw_listener = RawMouseDeltaListener()
                    raw_listener.start()
                    raw_ready = raw_listener.wait_until_ready(2.0)
                    if raw_ready:
                        self.signals.log_message.emit("[CALIBRATION] RAW Input активен. Отслеживаем чистые дельты.")
                    else:
                        self.signals.log_message.emit("[CALIBRATION] RAW Input недоступен, используем координаты курсора.")
                except Exception as exc:
                    self.signals.log_message.emit(f"[CALIBRATION] Ошибка запуска RAW Input: {exc}. Используем координаты курсора.")
                    raw_listener = None
                    raw_ready = False
            else:
                self.signals.log_message.emit("[CALIBRATION] RAW Input недоступен в этой системе. Используем координаты курсора.")

            def drain_raw():
                nonlocal sum_dx, sum_dy, event_count, first_moves
                if not (IS_WINDOWS and raw_ready and raw_listener and segment_active):
                    return
                while True:
                    try:
                        dx, dy, _ = raw_listener.queue.get_nowait()
                    except queue.Empty:
                        break
                    if dx == 0 and dy == 0:
                        continue
                    sum_dx += dx
                    sum_dy += dy
                    event_count += 1
                    if len(first_moves) < 10:
                        first_moves.append((dx, dy))

            def on_click(x, y, button, pressed_flag):
                nonlocal pressed, segment_active, last_pos
                if button != mouse.Button.right:
                    return
                if pressed_flag:
                    pressed = True
                    segment_active = True
                    last_pos = (x, y)
                    drain_raw()
                    self.signals.log_message.emit("[CALIBRATION] ПКМ зажата — выполняйте drag.")
                else:
                    if pressed and IS_WINDOWS and raw_ready:
                        drain_raw()
                    pressed = False
                    segment_active = False
                    done_event.set()
                    self.signals.log_message.emit("[CALIBRATION] ПКМ отпущена — завершаем замер.")

            def on_move(x, y):
                nonlocal last_pos, sum_dx, sum_dy, event_count
                if not pressed:
                    last_pos = (x, y)
                    return
                if IS_WINDOWS and raw_ready:
                    drain_raw()
                else:
                    if last_pos is not None:
                        dx = int(round(x - last_pos[0]))
                        dy = int(round(y - last_pos[1]))
                        if dx != 0 or dy != 0:
                            sum_dx += dx
                            sum_dy += dy
                            event_count += 1
                            if len(first_moves) < 10:
                                first_moves.append((dx, dy))
                    last_pos = (x, y)

            listener = mouse.Listener(on_click=on_click, on_move=on_move)
            listener.start()

            timeout_seconds = 15.0
            start_time = time.perf_counter()
            while not done_event.is_set() and (time.perf_counter() - start_time) < timeout_seconds:
                if IS_WINDOWS and raw_ready and pressed:
                    drain_raw()
                time.sleep(0.01)

            if not done_event.is_set():
                self.signals.log_message.emit("[CALIBRATION] Тайм-аут: ПКМ не была отпущена. Используем накопленные данные.")

        except Exception as exc:
            self.signals.log_message.emit(f"[CALIBRATION] Ошибка: {exc}")
        finally:
            if listener is not None:
                try:
                    listener.stop()
                    listener.join()
                except Exception:
                    pass
            if raw_listener:
                raw_listener.stop()

            total_length = math.hypot(sum_dx, sum_dy)
            abs_dx = abs(sum_dx)
            abs_dy = abs(sum_dy)
            dominant_axis = 'x' if abs_dx >= abs_dy else 'y'
            observed = abs_dx if dominant_axis == 'x' else abs_dy

            if observed <= 0.0:
                self.signals.log_message.emit("[CALIBRATION] Недостаточно движения. Попробуйте ещё раз.")
            else:
                settings_snapshot = self.settings_manager.as_dict()
                master_gain = settings_snapshot.get("camera_gain", CAMERA_GAIN)
                if master_gain <= 0:
                    master_gain = CAMERA_GAIN if CAMERA_GAIN > 0 else 1.0
                axis_key = "gain_x" if dominant_axis == 'x' else "gain_y"
                old_multiplier = settings_snapshot.get(
                    axis_key,
                    GAIN_X_MULTIPLIER if dominant_axis == 'x' else GAIN_Y_MULTIPLIER,
                )
                target_effective = target_length / observed
                new_multiplier = _clamp(target_effective / master_gain, 0.25, 4.0)
                self.settings_manager.update(axis_key, new_multiplier)
                updated_settings = self.settings_manager.as_dict()
                self.signals.settings_updated.emit(updated_settings)
                effective_after = master_gain * new_multiplier
                axis_label = axis_key.upper()
                clamped_note = ""
                if abs(effective_after - target_effective) > 1e-6:
                    clamped_note = " (ограничено диапазоном)"
                self.signals.log_message.emit(
                    f"[CALIBRATION] Δ=({sum_dx},{sum_dy}), axis={dominant_axis.upper()}, events={event_count}, "
                    f"длина={total_length:.2f}px, наблюд. амплитуда={observed:.2f}px → "
                    f"{axis_label} множитель: {old_multiplier:.3f} → {new_multiplier:.3f} "
                    f"(эффективное {effective_after:.3f}, целевое {target_effective:.3f}){clamped_note}"
                )
                if first_moves:
                    preview = ", ".join(f"Δ({dx},{dy})" for dx, dy in first_moves[:5])
                    self.signals.log_message.emit(f"[CALIBRATION] Первые шаги: {preview}")

            self.signals.calibration_finished.emit()

    def toggle_recording(self):
        if self.is_recording:
            self.is_recording = False
            self.log("Остановка записи...")
        else:
            self.is_recording = True
            threading.Thread(target=self.record_worker, daemon=True).start()
            self.update_ui_for_recording(True)
            self.log("Запись началась! Выполняйте действия...")

    def record_worker(self):
        self.recorded_events = []
        start_time = time.perf_counter()
        def get_offset(): return time.perf_counter() - start_time
        mouse_controller = mouse.Controller()
        initial_pos = (mouse_controller.position[0], mouse_controller.position[1])
        self.recorded_events.append(('mouse_pos', (initial_pos[0], initial_pos[1], 0.0)))
        
        # Отслеживание состояния и дебаг
        pressed_buttons = set()
        mouse_move_count = 0
        raw_move_count = 0
        last_mouse_pos = initial_pos

        raw_listener = None
        raw_listener_ready = False
        if IS_WINDOWS:
            try:
                raw_listener = RawMouseDeltaListener()
                raw_listener.start()
                raw_listener_ready = raw_listener.wait_until_ready()
                if DEBUG_CAMERA_MOVEMENT:
                    status = "готов" if raw_listener_ready else "не запущен"
                    self.signals.log_message.emit(f"[RAW INIT] Raw input listener {status}")
                    if not raw_listener_ready and getattr(raw_listener, "_error", None):
                        self.signals.log_message.emit(f"[RAW INIT ERROR] {raw_listener._error}")
                if not raw_listener_ready:
                    raw_listener = None
            except Exception as e:
                raw_listener = None
                raw_listener_ready = False
                if DEBUG_CAMERA_MOVEMENT:
                    self.signals.log_message.emit(f"[RAW INIT ERROR] {e}")

        def drain_raw_events():
            nonlocal last_mouse_pos, raw_move_count
            if not (IS_WINDOWS and raw_listener_ready and raw_listener):
                return
            while True:
                try:
                    dx, dy, ts = raw_listener.queue.get_nowait()
                except queue.Empty:
                    break
                if dx == 0 and dy == 0:
                    continue
                raw_move_count += 1
                offset = ts - start_time
                dx_i = int(dx)
                dy_i = int(dy)
                if mouse.Button.right in pressed_buttons:
                    self.recorded_events.append(('mouse_move_relative', (dx_i, dy_i, offset)))
                    if DEBUG_CAMERA_MOVEMENT and (raw_move_count % 5 == 0 or raw_move_count <= 2):
                        self.signals.log_message.emit(
                            f"[RAW REC] Δ({dx_i},{dy_i}) offset={offset:.3f}s"
                        )
                    if last_mouse_pos is not None:
                        last_mouse_pos = (last_mouse_pos[0] + dx_i, last_mouse_pos[1] + dy_i)
                elif DEBUG_CAMERA_MOVEMENT and raw_move_count % 25 == 0:
                    self.signals.log_message.emit(
                        f"[RAW REC] Δ({dx_i},{dy_i}) offset={offset:.3f}s проигнорирован (RMB не зажата)"
                    )

        def on_press(key):
            if not self.is_recording: return
            try: k = key.char
            except AttributeError: k = str(key)
            self.recorded_events.append(('key_press', (k, get_offset())))

        def on_release(key):
            if not self.is_recording: return
            try: k = key.char
            except AttributeError: k = str(key)
            self.recorded_events.append(('key_release', (k, get_offset())))

        def on_click(x, y, button, pressed):
            nonlocal last_mouse_pos
            if not self.is_recording:
                return
            action = 'mouse_press' if pressed else 'mouse_release'
            offset = get_offset()
            button_str = str(button)
            self.recorded_events.append((action, (x, y, button_str, offset)))

            if pressed:
                if button == mouse.Button.right and IS_WINDOWS and raw_listener_ready:
                    drain_raw_events()
                pressed_buttons.add(button)
            else:
                if button == mouse.Button.right and IS_WINDOWS and raw_listener_ready:
                    drain_raw_events()
                pressed_buttons.discard(button)

            last_mouse_pos = (x, y)

            # Логируем нажатие и отпускание кнопок для отладки камеры
            if DEBUG_CAMERA_MOVEMENT:
                button_name = button_str.replace('Button.', '')
                if pressed and button == mouse.Button.right:
                    self.signals.log_message.emit(
                        f"[REC DEBUG] RMB pressed at ({x}, {y}), offset={offset:.3f}s — switching to relative capture"
                    )
                elif not pressed and button == mouse.Button.right:
                    self.signals.log_message.emit(
                        f"[REC DEBUG] RMB released at ({x}, {y}), offset={offset:.3f}s — returning to absolute capture"
                    )

        def on_scroll(x, y, dx, dy):
            if not self.is_recording: return
            self.recorded_events.append(('mouse_scroll', (dx, dy, get_offset())))

        def on_move(x, y):
            nonlocal last_mouse_pos, mouse_move_count
            if not self.is_recording:
                return
            offset = get_offset()
            rmb_pressed = mouse.Button.right in pressed_buttons

            mouse_move_count += 1
            using_raw = IS_WINDOWS and raw_listener_ready and raw_listener and rmb_pressed

            if rmb_pressed:
                if using_raw:
                    drain_raw_events()
                    if DEBUG_CAMERA_MOVEMENT and mouse_move_count % 10 == 0:
                        self.signals.log_message.emit(
                            f"[REC DEBUG] Drain raw queue at offset={offset:.3f}s (RMB held)"
                        )
                else:
                    dx = int(x - last_mouse_pos[0]) if last_mouse_pos is not None else 0
                    dy = int(y - last_mouse_pos[1]) if last_mouse_pos is not None else 0
                    if dx != 0 or dy != 0:
                        self.recorded_events.append(('mouse_move_relative', (dx, dy, offset)))
                        if DEBUG_CAMERA_MOVEMENT and mouse_move_count % 5 == 0:
                            self.signals.log_message.emit(
                                f"[REC DEBUG] Relative move #{mouse_move_count}: Δ({dx}, {dy}) raw=({x}, {y}) offset={offset:.3f}s"
                            )
                    elif DEBUG_CAMERA_MOVEMENT and mouse_move_count % 5 == 0:
                        self.signals.log_message.emit(
                            f"[REC DEBUG] Relative move #{mouse_move_count}: Δ(0, 0) raw=({x}, {y}) offset={offset:.3f}s (skipped)"
                        )
            else:
                if IS_WINDOWS and raw_listener_ready and raw_listener:
                    drain_raw_events()
                self.recorded_events.append(('mouse_move', (x, y, offset)))
                if DEBUG_CAMERA_MOVEMENT and mouse_move_count % 5 == 0:
                    self.signals.log_message.emit(
                        f"[REC DEBUG] Mouse move #{mouse_move_count}: ({x}, {y}), offset={offset:.3f}s"
                    )

            if not using_raw:
                last_mouse_pos = (x, y)

        k_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        m_listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll, on_move=on_move)
        k_listener.start(); m_listener.start()
        while self.is_recording:
            if IS_WINDOWS and raw_listener_ready and raw_listener and mouse.Button.right in pressed_buttons:
                drain_raw_events()
            time.sleep(0.05)
        k_listener.stop(); m_listener.stop()
        if IS_WINDOWS and raw_listener:
            drain_raw_events()
            raw_listener.stop()
        self.signals.recording_stopped.emit()

    def play_selected_macro(self):
        if self.is_playing:
            return self.log("Воспроизведение уже идет.")
        current_item = self.macro_list_widget.currentItem()
        if not current_item:
            return QMessageBox.warning(self, "Ошибка", "Выберите макрос.")
        name = current_item.text()
        filepath = MACROS_DIR / f"{name}.json"
        try:
            with open(filepath, 'r') as f:
                events = json.load(f)
            loops = 0 if self.infinite_checkbox.isChecked() else self.loops_spinbox.value()
            self.is_playing = True
            threading.Thread(target=self.play_worker, args=(events, loops, name), daemon=True).start()
        except Exception as e:
            self.log(f"Ошибка при загрузке макроса: {e}")


    def play_worker(self, events, loops, name):
        self.update_ui_for_playback(True, name, loops)
        mouse_controller = mouse.Controller()
        keyboard_controller = keyboard.Controller()

        pressed_buttons = set()
        last_mouse_pos = None
        current_segment = None
        in_rmb_segment = False

        def start_rmb_segment(x, y, offset):
            nonlocal current_segment, in_rmb_segment, last_mouse_pos
            in_rmb_segment = True
            last_mouse_pos = (x, y)
            current_segment = {
                "start_offset": offset,
                "rec_dx": 0,
                "rec_dy": 0,
                "sent_dx": 0,
                "sent_dy": 0,
                "acc_dx": 0.0,
                "acc_dy": 0.0,
                "events": 0,
                "sent_events": 0,
                "first_moves": [],
                "last_offset": offset,
                "gain_master": CAMERA_GAIN,
                "gain_x": CAMERA_GAIN_X,
                "gain_y": CAMERA_GAIN_Y,
                "gain_x_multiplier": GAIN_X_MULTIPLIER,
                "gain_y_multiplier": GAIN_Y_MULTIPLIER,
                "invert_x": INVERT_X_AXIS,
                "invert_y": INVERT_Y_AXIS,
                "sender_preference": SENDER_MODE,
                "sender_effective": None,
                "sender_modes_used": [],
                "sender_max_step": SEND_RELATIVE_MAX_STEP,
                "sender_delay": SEND_RELATIVE_DELAY,
                "deadzone": DEADZONE_THRESHOLD,
                "reverse_window_sec": REVERSE_WINDOW_SECONDS,
                "reverse_ratio": REVERSE_TINY_RATIO,
                "recent_x": deque(),
                "recent_y": deque(),
                "raw_events_x": 0,
                "raw_events_y": 0,
                "deadzone_skipped_x": 0,
                "deadzone_skipped_y": 0,
                "reverse_suppressed_x": 0,
                "reverse_suppressed_y": 0,
                "abs_sum_processed_x": 0.0,
                "abs_sum_processed_y": 0.0,
                "cursor_lock_requested": bool(IS_WINDOWS and CURSOR_LOCK_ENABLED),
                "cursor_lock_active": False,
                "cursor_lock_center": None,
                "cursor_lock_original": None,
                "cursor_lock_hwnd": None,
                "cursor_locker": None,
                "cursor_lock_restored": False,
                "cursor_lock_failed": False,
                "parity_corrections": [],
                "parity_remaining": (0, 0),
                "parity_attempted": False,
                "parity_duration": 0.0,
                "parity_deadline_exceeded": False,
            }
            if IS_WINDOWS and current_segment["cursor_lock_requested"]:
                locker = CursorLocker()
                if locker.activate():
                    current_segment["cursor_locker"] = locker
                    current_segment["cursor_lock_active"] = True
                    current_segment["cursor_lock_center"] = locker.center
                    current_segment["cursor_lock_original"] = locker.original
                    current_segment["cursor_lock_hwnd"] = locker.hwnd
                    if DEBUG_CAMERA_MOVEMENT:
                        hwnd_info = f"0x{int(locker.hwnd):X}" if locker.hwnd else "?"
                        self.signals.log_message.emit(
                            f"[CURSOR LOCK] Activated center={locker.center} original={locker.original} hwnd={hwnd_info}"
                        )
                else:
                    current_segment["cursor_locker"] = locker
                    current_segment["cursor_lock_failed"] = True
                    if DEBUG_CAMERA_MOVEMENT:
                        self.signals.log_message.emit("[CURSOR LOCK] Activation failed; continuing unlocked")

            if DEBUG_CAMERA_MOVEMENT:
                sender_pref = current_segment["sender_preference"]
                cursor_state = (
                    "ON" if current_segment["cursor_lock_active"] else (
                        "FAIL" if current_segment.get("cursor_lock_failed") else (
                            "REQ" if current_segment["cursor_lock_requested"] else "OFF"
                        )
                    )
                )
                self.signals.log_message.emit(
                    f"[RMB SEGMENT] start offset={offset:.3f}s pos=({x},{y}) "
                    f"gains(master={current_segment['gain_master']:.3f}, x={current_segment['gain_x']:.3f}, y={current_segment['gain_y']:.3f}) "
                    f"invert=({int(current_segment['invert_x'])},{int(current_segment['invert_y'])}) "
                    f"sender(pref={sender_pref}, max_step={current_segment['sender_max_step']}, delay={current_segment['sender_delay'] * 1000:.3f}ms) "
                    f"deadzone={current_segment['deadzone']:.3f} window={current_segment['reverse_window_sec'] * 1000:.1f}ms "
                    f"ratio={current_segment['reverse_ratio']:.3f} cursor_lock={cursor_state}"
                )

        def handle_axis(axis_name, raw_value, offset):
            if current_segment is None:
                return 0
            invert_flag = current_segment["invert_x"] if axis_name == "x" else current_segment["invert_y"]
            normalized = float(-raw_value if invert_flag else raw_value)
            threshold = current_segment["deadzone"]
            if normalized == 0.0:
                return 0
            if threshold > 0.0 and abs(normalized) < threshold:
                current_segment[f"deadzone_skipped_{axis_name}"] += 1
                if DEBUG_CAMERA_MOVEMENT:
                    self.signals.log_message.emit(
                        f"[DEADZONE] axis={axis_name.upper()} raw={raw_value} norm={normalized:.3f} thresh={threshold:.3f}"
                    )
                return 0

            current_segment[f"raw_events_{axis_name}"] += 1

            queue = current_segment[f"recent_{axis_name}"]
            window = current_segment["reverse_window_sec"]
            ratio = current_segment["reverse_ratio"]
            while queue and (offset - queue[0][0]) > window:
                queue.popleft()

            direction = 0
            monotonic = True
            nonzero_prev = []
            for _, value in queue:
                if value == 0.0:
                    continue
                nonzero_prev.append(value)
                sign = 1 if value > 0 else -1
                if direction == 0:
                    direction = sign
                elif sign != direction:
                    monotonic = False
                    break

            avg_step = sum(abs(v) for v in nonzero_prev) / len(nonzero_prev) if nonzero_prev else 0.0
            suppressed = False
            if monotonic and direction != 0:
                sign_new = 1 if normalized > 0 else -1
                if sign_new != direction and avg_step > 0.0 and abs(normalized) < ratio * avg_step:
                    suppressed = True

            if suppressed:
                current_segment[f"reverse_suppressed_{axis_name}"] += 1
                if DEBUG_CAMERA_MOVEMENT:
                    self.signals.log_message.emit(
                        f"[REV SUPPRESS] axis={axis_name.upper()} raw={raw_value} norm={normalized:.3f} "
                        f"avg={avg_step:.3f} ratio={ratio:.3f}"
                    )
                return 0

            queue.append((offset, normalized))
            current_segment[f"abs_sum_processed_{axis_name}"] += abs(normalized)

            acc_key = "acc_dx" if axis_name == "x" else "acc_dy"
            gain = current_segment["gain_x"] if axis_name == "x" else current_segment["gain_y"]
            current_segment[acc_key] += normalized * gain
            step_value = int(round(current_segment[acc_key]))
            if step_value != 0:
                current_segment[acc_key] -= step_value
            return step_value

        def process_relative_move(raw_dx, raw_dy, offset):
            nonlocal last_mouse_pos, current_segment
            if not in_rmb_segment or current_segment is None:
                if DEBUG_CAMERA_MOVEMENT:
                    self.signals.log_message.emit(
                        f"[REL WARNING] Δ({raw_dx},{raw_dy}) получено без активного RMB — проигнорировано"
                    )
                return

            current_segment['events'] += 1
            current_segment['rec_dx'] += raw_dx
            current_segment['rec_dy'] += raw_dy
            current_segment['last_offset'] = offset
            if len(current_segment['first_moves']) < 10:
                current_segment['first_moves'].append((raw_dx, raw_dy, offset))

            send_dx = handle_axis('x', raw_dx, offset)
            send_dy = handle_axis('y', raw_dy, offset)

            if send_dx != 0 or send_dy != 0:
                if DEBUG_CAMERA_MOVEMENT:
                    self.signals.log_message.emit(
                        f"[REL SEND] raw Δ({raw_dx},{raw_dy}) -> sent ({send_dx},{send_dy}); "
                        f"остаток=({current_segment['acc_dx']:.3f},{current_segment['acc_dy']:.3f})"
                    )
                mode_used = send_relative_line(send_dx, send_dy)
                if mode_used:
                    current_segment['sender_effective'] = mode_used
                    if mode_used not in current_segment['sender_modes_used']:
                        current_segment['sender_modes_used'].append(mode_used)
                current_segment['sent_dx'] += send_dx
                current_segment['sent_dy'] += send_dy
                current_segment['sent_events'] += 1
                locker = current_segment.get("cursor_locker")
                if locker and locker.active:
                    locker.maintain()
            elif DEBUG_CAMERA_MOVEMENT and (raw_dx != 0 or raw_dy != 0):
                self.signals.log_message.emit(
                    f"[REL ACC] raw Δ({raw_dx},{raw_dy}) накоплено; остаток=({current_segment['acc_dx']:.3f},{current_segment['acc_dy']:.3f})"
                )

            if last_mouse_pos is not None:
                last_mouse_pos = (last_mouse_pos[0] + raw_dx, last_mouse_pos[1] + raw_dy)
            else:
                last_mouse_pos = (raw_dx, raw_dy)

        def finish_rmb_segment(offset):
            nonlocal current_segment, in_rmb_segment
            if not in_rmb_segment or current_segment is None:
                return
            current_segment['last_offset'] = offset

            flush_dx = int(round(current_segment['acc_dx']))
            flush_dy = int(round(current_segment['acc_dy']))
            if flush_dx != 0:
                current_segment['acc_dx'] -= flush_dx
            if flush_dy != 0:
                current_segment['acc_dy'] -= flush_dy
            if flush_dx != 0 or flush_dy != 0:
                if DEBUG_CAMERA_MOVEMENT:
                    self.signals.log_message.emit(
                        f"[REL FLUSH] добавляем остаток ({flush_dx},{flush_dy}) перед отпусканием RMB"
                    )
                mode_used = send_relative_line(flush_dx, flush_dy)
                if mode_used:
                    current_segment['sender_effective'] = mode_used
                    if mode_used not in current_segment['sender_modes_used']:
                        current_segment['sender_modes_used'].append(mode_used)
                current_segment['sent_dx'] += flush_dx
                current_segment['sent_dy'] += flush_dy
                current_segment['sent_events'] += 1
                locker = current_segment.get("cursor_locker")
                if locker and locker.active:
                    locker.maintain()

            diff_dx = current_segment['rec_dx'] - current_segment['sent_dx']
            diff_dy = current_segment['rec_dy'] - current_segment['sent_dy']
            if diff_dx != 0 or diff_dy != 0:
                parity_start = time.perf_counter()
                deadline = parity_start + 0.02
                while (diff_dx != 0 or diff_dy != 0) and time.perf_counter() <= deadline:
                    step_dx = 0
                    step_dy = 0
                    if diff_dx != 0:
                        step_dx = 1 if diff_dx > 0 else -1
                        diff_dx -= step_dx
                    if diff_dy != 0:
                        step_dy = 1 if diff_dy > 0 else -1
                        diff_dy -= step_dy
                    if step_dx == 0 and step_dy == 0:
                        break
                    mode_used = send_relative_line(step_dx, step_dy)
                    if mode_used:
                        current_segment['sender_effective'] = mode_used
                        if mode_used not in current_segment['sender_modes_used']:
                            current_segment['sender_modes_used'].append(mode_used)
                    current_segment['sent_dx'] += step_dx
                    current_segment['sent_dy'] += step_dy
                    current_segment['sent_events'] += 1
                    current_segment['parity_corrections'].append((step_dx, step_dy))
                    locker = current_segment.get("cursor_locker")
                    if locker and locker.active:
                        locker.maintain()
                    if SEND_RELATIVE_DELAY > 0:
                        remaining = deadline - time.perf_counter()
                        if remaining > 0:
                            time.sleep(min(SEND_RELATIVE_DELAY, remaining))
                current_segment['parity_attempted'] = True
                current_segment['parity_duration'] = time.perf_counter() - parity_start
                remaining_dx = current_segment['rec_dx'] - current_segment['sent_dx']
                remaining_dy = current_segment['rec_dy'] - current_segment['sent_dy']
                current_segment['parity_remaining'] = (remaining_dx, remaining_dy)
                current_segment['parity_deadline_exceeded'] = (remaining_dx != 0 or remaining_dy != 0)
                if DEBUG_CAMERA_MOVEMENT:
                    self.signals.log_message.emit(
                        f"[PARITY] corrections={len(current_segment['parity_corrections'])} remaining=({remaining_dx},{remaining_dy}) "
                        f"duration={current_segment['parity_duration'] * 1000:.1f}ms deadline_exceeded={current_segment['parity_deadline_exceeded']}"
                    )

            locker = current_segment.get("cursor_locker")
            if locker and locker.active:
                locker.release()
                current_segment['cursor_lock_restored'] = True
                if DEBUG_CAMERA_MOVEMENT:
                    self.signals.log_message.emit(
                        f"[CURSOR LOCK] Restored original position {locker.original}"
                    )
            elif locker and locker.original is not None and current_segment.get('cursor_lock_requested') and IS_WINDOWS:
                # lock may have failed to activate; ensure original position restored if we have it
                try:
                    user32.SetCursorPos(locker.original[0], locker.original[1])
                except Exception as exc:
                    if DEBUG_CAMERA_MOVEMENT:
                        self.signals.log_message.emit(f"[CURSOR LOCK] Failed to restore position: {exc}")
                current_segment['cursor_lock_restored'] = True

            duration = 0.0
            if current_segment['start_offset'] is not None and current_segment['last_offset'] is not None:
                duration = max(0.0, current_segment['last_offset'] - current_segment['start_offset'])
            event_rate = current_segment['events'] / duration if duration > 0 else current_segment['events']

            suppress_ratio_x = (
                current_segment['reverse_suppressed_x'] / max(1, current_segment['raw_events_x'])
                if current_segment['raw_events_x'] else 0.0
            )
            suppress_ratio_y = (
                current_segment['reverse_suppressed_y'] / max(1, current_segment['raw_events_y'])
                if current_segment['raw_events_y'] else 0.0
            )

            sender_sequence = current_segment['sender_modes_used']
            sender_info = "->".join(sender_sequence) if sender_sequence else current_segment['sender_preference']
            last_mode = current_segment.get('sender_effective') or sender_info
            cursor_state = (
                "ON" if current_segment['cursor_lock_active'] else (
                    "FAIL" if current_segment.get('cursor_lock_failed') else (
                        "REQ" if current_segment['cursor_lock_requested'] else "OFF"
                    )
                )
            )
            cursor_restored = current_segment['cursor_lock_restored'] if current_segment['cursor_lock_requested'] else 'n/a'
            parity_steps = len(current_segment['parity_corrections'])
            parity_remaining = current_segment['parity_remaining']
            parity_remaining_str = f"({parity_remaining[0]},{parity_remaining[1]})"
            parity_duration_ms = current_segment['parity_duration'] * 1000.0 if current_segment['parity_attempted'] else 0.0
            parity_deadline = current_segment['parity_deadline_exceeded']

            def _axis_error(rec_value, sent_value):
                if rec_value == 0:
                    return 0.0 if sent_value == 0 else 100.0
                return abs(sent_value - rec_value) / abs(rec_value) * 100.0

            error_x_pct = _axis_error(current_segment['rec_dx'], current_segment['sent_dx'])
            error_y_pct = _axis_error(current_segment['rec_dy'], current_segment['sent_dy'])

            summary = (
                f"[RMB SUMMARY] duration={duration:.3f}s moves={current_segment['events']} rate={event_rate:.1f}/s "
                f"rec_dx={current_segment['rec_dx']} sent_dx={current_segment['sent_dx']} err_x={error_x_pct:.2f}% "
                f"rec_dy={current_segment['rec_dy']} sent_dy={current_segment['sent_dy']} err_y={error_y_pct:.2f}% "
                f"sender_seq={sender_info} sender_last={last_mode} cursor_lock={cursor_state} restored={cursor_restored} "
                f"parity_steps={parity_steps} parity_remaining={parity_remaining_str} parity_ms={parity_duration_ms:.1f} "
                f"parity_deadline_exceeded={parity_deadline} "
                f"gains(master={current_segment['gain_master']:.3f}, x={current_segment['gain_x']:.3f}, y={current_segment['gain_y']:.3f}) "
                f"deadzone={current_segment['deadzone']:.3f} window={current_segment['reverse_window_sec'] * 1000:.1f}ms "
                f"suppress_ratio=(X:{suppress_ratio_x:.3f}, Y:{suppress_ratio_y:.3f}) "
                f"sender_step={current_segment['sender_max_step']} delay={current_segment['sender_delay'] * 1000:.3f}ms "
                f"leftover=({current_segment['acc_dx']:.3f},{current_segment['acc_dy']:.3f})"
            )
            self.signals.log_message.emit(summary)

            avg_processed_x = (
                current_segment['abs_sum_processed_x'] / max(1, current_segment['raw_events_x'])
                if current_segment['raw_events_x'] else 0.0
            )
            avg_processed_y = (
                current_segment['abs_sum_processed_y'] / max(1, current_segment['raw_events_y'])
                if current_segment['raw_events_y'] else 0.0
            )
            self.signals.log_message.emit(
                f"[RMB FILTER] raw_events=(X:{current_segment['raw_events_x']}, Y:{current_segment['raw_events_y']}) "
                f"deadzone_skipped=(X:{current_segment['deadzone_skipped_x']}, Y:{current_segment['deadzone_skipped_y']}) "
                f"reverse_suppressed=(X:{current_segment['reverse_suppressed_x']}, Y:{current_segment['reverse_suppressed_y']}) "
                f"avg_step=(X:{avg_processed_x:.3f}, Y:{avg_processed_y:.3f})"
            )

            def _check_axis(label, rec_value, sent_value, invert_expected):
                if rec_value == 0:
                    return
                if sent_value != 0:
                    same_sign = (rec_value > 0) == (sent_value > 0)
                    if invert_expected:
                        if same_sign and abs(rec_value) > 0:
                            self.signals.log_message.emit(
                                f"[RMB WARNING] Ожидалась инверсия по оси {label}, но знаки совпадают."
                            )
                    else:
                        if not same_sign:
                            self.signals.log_message.emit(
                                f"[RMB WARNING] Инверсия направления по оси {label}. Проверьте настройки инверсии."
                            )
                error = abs(sent_value - rec_value) / abs(rec_value)
                if error > 0.05:
                    self.signals.log_message.emit(
                        f"[RMB WARNING] Отклонение по оси {label} {error * 100:.1f}% (rec={rec_value}, sent={sent_value}). "
                        "Рекомендуется запустить автокалибровку."
                    )

            _check_axis('X', current_segment['rec_dx'], current_segment['sent_dx'], current_segment['invert_x'])
            _check_axis('Y', current_segment['rec_dy'], current_segment['sent_dy'], current_segment['invert_y'])

            if DEBUG_CAMERA_MOVEMENT and current_segment['first_moves']:
                preview = ", ".join(
                    f"Δ({dx},{dy})@{move_offset - current_segment['start_offset']:.3f}s"
                    for dx, dy, move_offset in current_segment['first_moves'][:5]
                )
                self.signals.log_message.emit(f"[RMB FIRST Δ] {preview}")

            current_segment = None
            in_rmb_segment = False

        if DEBUG_CAMERA_MOVEMENT:
            self.signals.log_message.emit(
                f"[INIT DEBUG] Starting playback | gain_master={CAMERA_GAIN:.3f} "
                f"gains(x={CAMERA_GAIN_X:.3f}, y={CAMERA_GAIN_Y:.3f}) "
                f"invert=({int(INVERT_X_AXIS)},{int(INVERT_Y_AXIS)}) "
                f"sender(max_step={SEND_RELATIVE_MAX_STEP}, delay={SEND_RELATIVE_DELAY * 1000:.3f}ms) "
                f"deadzone={DEADZONE_THRESHOLD:.3f} window={REVERSE_WINDOW_SECONDS * 1000:.1f}ms "
                f"ratio={REVERSE_TINY_RATIO:.3f}"
            )

        for i in range(3, 0, -1):
            if not self.is_playing:
                self.signals.playback_finished.emit()
                return
            self.signals.log_message.emit(f"Воспроизведение начнется через {i}...")
            time.sleep(1)
        self.signals.log_message.emit("Воспроизведение началось!")

        is_infinite = (loops <= 0)
        loop_count = 0

        while self.is_playing and (is_infinite or loop_count < loops):
            loop_count += 1
            if len(events) == 0:
                continue

            playback_start_time = time.perf_counter()
            current_segment = None
            in_rmb_segment = False
            last_mouse_pos = None
            last_event_offset = 0.0

            for event in events:
                if not self.is_playing:
                    break

                event_type, event_args = event
                event_offset = event_args[-1]
                last_event_offset = event_offset
                target_time = playback_start_time + event_offset
                sleep_duration = target_time - time.perf_counter()
                if sleep_duration > 0:
                    time.sleep(sleep_duration)

                if DEBUG_CAMERA_MOVEMENT and event_type.startswith('mouse'):
                    self.signals.log_message.emit(
                        f"[STATE DEBUG] Before {event_type}: pressed={pressed_buttons} last_pos={last_mouse_pos} in_rmb={in_rmb_segment}"
                    )

                try:
                    if event_type == 'mouse_pos':
                        x, y = event_args[0], event_args[1]
                        mouse_controller.position = (x, y)
                        last_mouse_pos = (x, y)
                        if DEBUG_CAMERA_MOVEMENT:
                            self.signals.log_message.emit(f"[CAM DEBUG] Initial mouse_pos: ({x}, {y})")

                    elif event_type == 'mouse_move':
                        x, y = event_args[0], event_args[1]
                        rmb_pressed = mouse.Button.right in pressed_buttons
                        if rmb_pressed and in_rmb_segment:
                            if DEBUG_CAMERA_MOVEMENT:
                                self.signals.log_message.emit(
                                    f"[RMB IGNORE] Absolute move ({x},{y}) пропущен внутри RMB сегмента"
                                )
                            continue
                        mouse_controller.position = (x, y)
                        last_mouse_pos = (x, y)
                        if DEBUG_CAMERA_MOVEMENT:
                            self.signals.log_message.emit(f"[NORMAL MOVE] Absolute position: ({x}, {y})")

                    elif event_type == 'mouse_move_relative':
                        raw_dx, raw_dy = int(event_args[0]), int(event_args[1])
                        process_relative_move(raw_dx, raw_dy, event_offset)

                    elif event_type == 'mouse_press':
                        x, y, button_str = event_args[0], event_args[1], event_args[2]
                        button = MOUSE_BUTTONS.get(button_str)

                        if DEBUG_CAMERA_MOVEMENT:
                            self.signals.log_message.emit(
                                f"[PRESS DEBUG] button={button_str} pos({x},{y}) pressed_before={pressed_buttons}"
                            )

                        mouse_controller.position = (x, y)
                        if button:
                            pressed_buttons.add(button)
                            mouse_controller.press(button)
                            if button == mouse.Button.right:
                                start_rmb_segment(x, y, event_args[3])

                    elif event_type == 'mouse_release':
                        x, y, button_str = event_args[0], event_args[1], event_args[2]
                        button = MOUSE_BUTTONS.get(button_str)

                        if DEBUG_CAMERA_MOVEMENT:
                            self.signals.log_message.emit(
                                f"[RELEASE DEBUG] button={button_str} pos({x},{y}) pressed_before={pressed_buttons}"
                            )

                        lock_active = (
                            button == mouse.Button.right
                            and current_segment is not None
                            and current_segment.get("cursor_lock_active")
                        )
                        if not lock_active:
                            mouse_controller.position = (x, y)
                        elif DEBUG_CAMERA_MOVEMENT:
                            self.signals.log_message.emit(
                                f"[CURSOR LOCK] Skip absolute reposition on release due to cursor lock"
                            )

                        if button:
                            if button == mouse.Button.right and in_rmb_segment:
                                finish_rmb_segment(event_args[3])
                            mouse_controller.release(button)
                            pressed_buttons.discard(button)
                            if button == mouse.Button.right and not lock_active:
                                last_mouse_pos = (x, y)

                    elif event_type == 'mouse_scroll':
                        mouse_controller.scroll(event_args[0], event_args[1])
                        if DEBUG_CAMERA_MOVEMENT:
                            self.signals.log_message.emit(
                                f"[CAM DEBUG] Scroll: dx={event_args[0]}, dy={event_args[1]}"
                            )

                    elif event_type == 'key_press':
                        key = SPECIAL_KEYS.get(event_args[0]) or event_args[0]
                        keyboard_controller.press(key)

                    elif event_type == 'key_release':
                        key = SPECIAL_KEYS.get(event_args[0]) or event_args[0]
                        keyboard_controller.release(key)

                except Exception as e:
                    self.signals.log_message.emit(f"Ошибка при воспроизведении: {e}")

            if in_rmb_segment and current_segment is not None:
                finish_rmb_segment(last_event_offset)

            if not self.is_playing:
                break

        self.signals.playback_finished.emit()

    def stop_playback(self):
        if self.is_playing:
            self.is_playing = False
            self.log("Попытка остановить воспроизведение...")

    def on_recording_finished(self):
        self.update_ui_for_recording(False)
        self.log(f"Запись завершена. Записано событий: {len(self.recorded_events)}")

    def on_playback_finished(self):
        self.is_playing = False
        self.update_ui_for_playback(False, "", 0)
        self.log("Воспроизведение завершено.")

    def update_ui_for_recording(self, is_recording):
        if is_recording:
            self.record_button.setText("стоп")
        else:
            self.record_button.setText("старт(aladayngay❤️)")
        self.record_button.setObjectName("stopButton" if is_recording else "recordButton")
        self._apply_styles()  # Обновляем стиль кнопки
        self.play_button.setEnabled(not is_recording)
        self.save_button.setEnabled(not is_recording)
        self.delete_button.setEnabled(not is_recording)
        self._update_calibration_ui_state()

    def update_ui_for_playback(self, is_playing, name, loops):
        if is_playing:
            self.signals.log_message.emit(f"Подготовка к '{name}'. Повторов: {'∞' if loops <= 0 else loops}.")
        self.play_button.setEnabled(not is_playing)  # фикс синтаксиса (никаких '!' в Python)
        self.record_button.setEnabled(not is_playing)
        self.stop_playback_button.setEnabled(is_playing)
        self._update_calibration_ui_state()

    def save_macro(self):
        if not self.recorded_events:
            return QMessageBox.warning(self, "Нет данных", "Сначала запишите макрос.")
        name, ok = QInputDialog.getText(self, "Сохранить макрос", "Введите имя:")
        if ok and name:
            filepath = MACROS_DIR / f"{name}.json"
            with open(filepath, 'w') as f:
                json.dump(self.recorded_events, f, indent=4)
            self.log(f"Макрос '{name}' сохранен.")
            self.refresh_macro_list()

    def refresh_macro_list(self):
        self.macro_list_widget.clear()
        for filename in sorted(os.listdir(MACROS_DIR)):
            if filename.endswith(".json"):
                self.macro_list_widget.addItem(QListWidgetItem(filename.replace(".json", "")))

    def delete_macro(self):
        current_item = self.macro_list_widget.currentItem()
        if not current_item:
            return
        name = current_item.text()
        if QMessageBox.question(self, "Подтверждение", f"Удалить макрос '{name}'?") == QMessageBox.Yes:
            os.remove(MACROS_DIR / f"{name}.json")
            self.log(f"Макрос '{name}' удален.")
            self.refresh_macro_list()

    def closeEvent(self, event):
        self.is_recording = False
        self.is_playing = False
        time.sleep(0.2)
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MacroApp()
    window.show()
    sys.exit(app.exec())