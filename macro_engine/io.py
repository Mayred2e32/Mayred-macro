from __future__ import annotations

import platform
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

IS_WINDOWS = platform.system() == "Windows"


@dataclass
class RawMousePacket:
    dx: int
    dy: int
    timestamp: float
    right_down: bool = False
    right_up: bool = False
    wheel: int = 0


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


class HighPriorityContext:
    """Raises Windows thread priority and timer resolution for deterministic playback."""

    def __init__(self):
        self._period_set = False
        self._thread_handle = None
        self._previous_priority = None

    def __enter__(self):
        if not IS_WINDOWS:
            return self
        try:
            if timeBeginPeriod and timeBeginPeriod(1) == 0:
                self._period_set = True
        except Exception:
            self._period_set = False
        try:
            self._thread_handle = kernel32.GetCurrentThread()
            prev = kernel32.GetThreadPriority(self._thread_handle)
            if prev != THREAD_PRIORITY_ERROR_RETURN:
                self._previous_priority = prev
            kernel32.SetThreadPriority(self._thread_handle, THREAD_PRIORITY_HIGHEST)
        except Exception:
            self._thread_handle = None
        return self

    def __exit__(self, exc_type, exc, tb):
        if IS_WINDOWS:
            if self._thread_handle and self._previous_priority is not None:
                try:
                    kernel32.SetThreadPriority(self._thread_handle, self._previous_priority)
                except Exception:
                    pass
            if self._period_set:
                try:
                    timeEndPeriod(1)
                except Exception:
                    pass


if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    def _ensure(attr: str, ctype) -> None:
        if not hasattr(wintypes, attr):
            setattr(wintypes, attr, ctype)

    _ensure("LRESULT", ctypes.c_ssize_t)
    _ensure("WPARAM", ctypes.c_size_t)
    _ensure("LPARAM", ctypes.c_ssize_t)
    _ensure("HANDLE", ctypes.c_void_p)
    _ensure("HWND", wintypes.HANDLE)
    _ensure("HINSTANCE", wintypes.HANDLE)
    _ensure("HMODULE", wintypes.HANDLE)
    _ensure("HMENU", wintypes.HANDLE)
    _ensure("HICON", wintypes.HANDLE)
    _ensure("HCURSOR", wintypes.HANDLE)
    _ensure("HBRUSH", wintypes.HANDLE)
    _ensure("HDC", wintypes.HANDLE)
    _ensure("ATOM", ctypes.c_ushort)
    _ensure("UINT", ctypes.c_uint)
    _ensure("DWORD", ctypes.c_uint32)
    _ensure("ULONG_PTR", ctypes.c_size_t)

    WNDPROC = ctypes.WINFUNCTYPE(
        wintypes.LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    WM_INPUT = 0x00FF
    RID_INPUT = 0x10000003
    RIM_TYPEMOUSE = 0
    RIDEV_INPUTSINK = 0x00000100
    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002

    RI_MOUSE_RIGHT_BUTTON_DOWN = 0x0004
    RI_MOUSE_RIGHT_BUTTON_UP = 0x0008
    RI_MOUSE_WHEEL = 0x0400

    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_MOVE_NOCOALESCE = 0x2000

    THREAD_PRIORITY_HIGHEST = 2
    THREAD_PRIORITY_ERROR_RETURN = 0x7FFFFFFF

    # --- Ctypes structures ---
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
        _fields_ = [("mouse", RAWMOUSE)]

    class RAWINPUT(ctypes.Structure):
        _anonymous_ = ("data",)
        _fields_ = [
            ("header", RAWINPUTHEADER),
            ("data", RAWINPUTDATA),
        ]

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

    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

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
        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT)]

        _anonymous_ = ("i",)
        _fields_ = [("type", wintypes.DWORD), ("i", _U)]

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    winmm = ctypes.windll.winmm

    SendInput = user32.SendInput
    mouse_event = user32.mouse_event
    timeBeginPeriod = winmm.timeBeginPeriod
    timeEndPeriod = winmm.timeEndPeriod

    _RAW_SINGLETON: Optional["RawMouseStream"] = None

    @WNDPROC
    def _raw_input_wnd_proc(hwnd, msg, w_param, l_param):
        listener = _RAW_SINGLETON
        if msg == WM_INPUT and listener is not None:
            listener._process_raw_input(l_param)
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, w_param, l_param)

    class RawMouseStream(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True)
            self.queue: "queue.Queue[RawMousePacket]" = queue.Queue()
            self._stop = threading.Event()
            self._ready = threading.Event()
            self._hwnd = None
            self._class_name = f"MacroRawInput_{int(time.time()*1000)}"
            self._error: Optional[Exception] = None

        @staticmethod
        def is_supported() -> bool:
            return True

        def start_stream(self) -> None:
            self.start()
            if not self._ready.wait(timeout=2.0):
                raise RuntimeError("Raw input listener failed to initialize")
            if self._error:
                raise self._error

        def stop_stream(self) -> None:
            self._stop.set()
            if self._hwnd:
                user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            self.join(timeout=1.0)

        def run(self):
            global _RAW_SINGLETON
            try:
                self._create_window()
            except Exception as exc:
                self._error = exc
                self._ready.set()
                return
            _RAW_SINGLETON = self
            self._ready.set()
            self._message_loop()
            _RAW_SINGLETON = None

        def _create_window(self):
            h_instance = kernel32.GetModuleHandleW(None)
            wndclass = WNDCLASS()
            wndclass.style = 0
            wndclass.lpfnWndProc = _raw_input_wnd_proc
            wndclass.cbClsExtra = 0
            wndclass.cbWndExtra = 0
            wndclass.hInstance = h_instance
            wndclass.hIcon = None
            wndclass.hCursor = None
            wndclass.hbrBackground = None
            wndclass.lpszMenuName = None
            wndclass.lpszClassName = self._class_name

            atom = user32.RegisterClassW(ctypes.byref(wndclass))
            if not atom:
                err = kernel32.GetLastError()
                if err != 1410:  # already registered
                    raise ctypes.WinError(err)

            self._hwnd = user32.CreateWindowExW(
                0,
                self._class_name,
                self._class_name,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                h_instance,
                None,
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
            while not self._stop.is_set():
                ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if ret in (0, -1):
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        def _process_raw_input(self, l_param):
            size = wintypes.UINT(0)
            if user32.GetRawInputData(l_param, RID_INPUT, None, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER)) == 0xFFFFFFFF:
                return
            if size.value == 0:
                return
            buffer = ctypes.create_string_buffer(size.value)
            if user32.GetRawInputData(
                l_param,
                RID_INPUT,
                buffer,
                ctypes.byref(size),
                ctypes.sizeof(RAWINPUTHEADER),
            ) == 0xFFFFFFFF:
                return
            raw = ctypes.cast(buffer, ctypes.POINTER(RAWINPUT)).contents
            if raw.header.dwType != RIM_TYPEMOUSE:
                return
            dx = int(raw.mouse.lLastX)
            dy = int(raw.mouse.lLastY)
            flags = int(raw.mouse.usButtonFlags)
            wheel = 0
            if flags & RI_MOUSE_WHEEL:
                wheel = ctypes.c_short(raw.mouse.usButtonData).value
            packet = RawMousePacket(
                dx=dx,
                dy=dy,
                timestamp=time.perf_counter(),
                right_down=bool(flags & RI_MOUSE_RIGHT_BUTTON_DOWN),
                right_up=bool(flags & RI_MOUSE_RIGHT_BUTTON_UP),
                wheel=wheel,
            )
            if dx != 0 or dy != 0 or packet.right_down or packet.right_up:
                self.queue.put(packet)

    class _Win32RelativeMouseSender:
        def __init__(self, max_step: int, delay_seconds: float, mode: str):
            self.max_step = max(1, int(max_step))
            self.delay_seconds = max(0.0, float(delay_seconds))
            self.mode = mode
            self._input = INPUT()

        def send(self, dx: int, dy: int) -> None:
            dx = int(dx)
            dy = int(dy)
            if dx == 0 and dy == 0:
                return
            remaining_x = dx
            remaining_y = dy
            while remaining_x or remaining_y:
                step_x = _clamp(remaining_x, -self.max_step, self.max_step)
                step_y = _clamp(remaining_y, -self.max_step, self.max_step)
                self._dispatch(step_x, step_y)
                remaining_x -= step_x
                remaining_y -= step_y
                if self.delay_seconds > 0:
                    time.sleep(self.delay_seconds)

        def _dispatch(self, dx: int, dy: int):
            if self.mode == "mouse_event":
                mouse_event(MOUSEEVENTF_MOVE, dx, dy, 0, 0)
                return
            self._input.type = 0  # INPUT_MOUSE
            self._input.mi.dx = dx
            self._input.mi.dy = dy
            self._input.mi.mouseData = 0
            self._input.mi.time = 0
            self._input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_MOVE_NOCOALESCE
            SendInput(1, ctypes.byref(self._input), ctypes.sizeof(self._input))

    RelativeSenderImpl = _Win32RelativeMouseSender

else:
    timeBeginPeriod = None  # type: ignore[assignment]
    timeEndPeriod = None  # type: ignore[assignment]
    THREAD_PRIORITY_HIGHEST = 0
    THREAD_PRIORITY_ERROR_RETURN = 0

    class RawMouseStream:
        def __init__(self):
            raise RuntimeError("Raw input is only supported on Windows")

        @staticmethod
        def is_supported() -> bool:
            return False

        def start_stream(self) -> None:  # pragma: no cover - non-Windows fallback
            raise RuntimeError("Raw input unsupported on this platform")

        def stop_stream(self) -> None:
            return

    class _PynputRelativeMouseSender:
        def __init__(self, max_step: int, delay_seconds: float, mode: str):
            from pynput import mouse

            self.max_step = max(1, int(max_step))
            self.delay_seconds = max(0.0, float(delay_seconds))
            self._controller = mouse.Controller()

        def send(self, dx: int, dy: int) -> None:
            dx = int(dx)
            dy = int(dy)
            if dx == 0 and dy == 0:
                return
            remaining_x = dx
            remaining_y = dy
            while remaining_x or remaining_y:
                step_x = _clamp(remaining_x, -self.max_step, self.max_step)
                step_y = _clamp(remaining_y, -self.max_step, self.max_step)
                self._controller.move(step_x, step_y)
                remaining_x -= step_x
                remaining_y -= step_y
                if self.delay_seconds > 0:
                    time.sleep(self.delay_seconds)

    RelativeSenderImpl = _PynputRelativeMouseSender


class RelativeMouseSender:
    def __init__(self, max_step: int = 1, delay_seconds: float = 0.0015, mode: str = "auto"):
        self.impl = RelativeSenderImpl(max_step=max_step, delay_seconds=delay_seconds, mode=mode)

    def send(self, dx: int, dy: int) -> None:
        self.impl.send(dx, dy)


__all__ = [
    "RawMouseStream",
    "RawMousePacket",
    "RelativeMouseSender",
    "HighPriorityContext",
    "IS_WINDOWS",
]
