import sys
import time
import threading
import queue
import json
import os
import platform
from pathlib import Path

# --- Импорты для GUI (PySide6) ---
from PySide6.QtCore import Qt, Signal, QObject, QSize
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QInputDialog, QMessageBox,
    QTextEdit, QSpinBox, QCheckBox, QFormLayout, QFrame, QGraphicsDropShadowEffect
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

# --- Настройки симуляции камеры ---
CAMERA_GAIN = 1.0           # Множитель для чувствительности камеры (1.0 = 100% точность)
MIN_STEP_THRESHOLD = 0    # Минимальный модуль дельты, чтобы отправлять движение
DEBUG_CAMERA_MOVEMENT = True  # Детальное логирование движений камеры

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
    SendInput = user32.SendInput
    # Альтернатива: старый mouse_event API
    mouse_event = user32.mouse_event
    
    # Константы для mouse_event
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

    kernel32 = ctypes.windll.kernel32

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

# Сигналы для безопасного обновления GUI из других потоков
class WorkerSignals(QObject):
    log_message = Signal(str)
    recording_stopped = Signal()
    playback_finished = Signal()

# --- Основной класс приложения ---
class MacroApp(QWidget):
    def __init__(self):
        super().__init__()
        self.recorded_events = []
        self.is_recording = False
        self.is_playing = False
        self.signals = WorkerSignals()
        os.makedirs(MACROS_DIR, exist_ok=True)
        self._build_ui()
        self._apply_styles()  # Применяем дизайн
        self.refresh_macro_list()
        self.signals.log_message.connect(self.log)
        self.signals.recording_stopped.connect(self.on_recording_finished)
        self.signals.playback_finished.connect(self.on_playback_finished)
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

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_edit.append(f"[{timestamp}] {message}")

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

        # Состояние кнопок и "центр" для ПКМ
        pressed_buttons = set()
        rmb_center = None  # (cx, cy) координаты - текущий центр для дельта-расчета
        last_mouse_pos = None  # Последняя известная позиция мыши
        
        if DEBUG_CAMERA_MOVEMENT:
            self.signals.log_message.emit("[INIT DEBUG] Starting playback with fresh state")

        # Обратный отсчет
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
            rmb_center = None  # Сброс центра для каждого цикла
            last_mouse_pos = None  # Сброс последней позиции для каждого цикла

            for event in events:
                if not self.is_playing:
                    break

                event_type, event_args = event
                event_offset = event_args[-1]
                target_time = playback_start_time + event_offset
                sleep_duration = target_time - time.perf_counter()
                if sleep_duration > 0:
                    time.sleep(sleep_duration)

                # КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: состояние перед каждым событием
                if DEBUG_CAMERA_MOVEMENT and event_type.startswith('mouse'):
                    self.signals.log_message.emit(
                        f"[STATE DEBUG] Before {event_type}: pressed={pressed_buttons} "
                        f"rmb_center={rmb_center} last_pos={last_mouse_pos}"
                    )

                try:
                    if event_type == 'mouse_pos':
                        # Исходная позиция только один раз для старта
                        x, y = event_args[0], event_args[1]
                        mouse_controller.position = (x, y)
                        last_mouse_pos = (x, y)
                        if DEBUG_CAMERA_MOVEMENT:
                            self.signals.log_message.emit(f"[CAM DEBUG] Initial mouse_pos: ({x}, {y})")

                    elif event_type == 'mouse_move':
                        x, y = event_args[0], event_args[1]
                        
                        # КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: состояние кнопок
                        if DEBUG_CAMERA_MOVEMENT:
                            rmb_pressed = mouse.Button.right in pressed_buttons
                            self.signals.log_message.emit(
                                f"[MOVE DEBUG] pos({x},{y}) RMB={rmb_pressed} rmb_center={rmb_center} "
                                f"last_pos={last_mouse_pos}"
                            )
                        
                        # БОЛЕЕ НАДЕЖНАЯ ПРОВЕРКА: проверяем состояние ПКМ более тщательно
                        rmb_pressed = mouse.Button.right in pressed_buttons
                        if DEBUG_CAMERA_MOVEMENT:
                            self.signals.log_message.emit(f"[RMB CHECK] RMB pressed: {rmb_pressed}, rmb_center: {rmb_center}")
                        
                        if rmb_pressed and rmb_center is not None:
                            # ПРАВИЛЬНАЯ ЛОГИКА: инкрементальное движение от предыдущей позиции
                            # Используем last_mouse_pos для расчета дельты, а не rmb_center
                            if last_mouse_pos is not None:
                                dx = int((x - last_mouse_pos[0]) * CAMERA_GAIN)
                                dy = int((y - last_mouse_pos[1]) * CAMERA_GAIN)
                                
                                # КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: расчет дельты
                                if DEBUG_CAMERA_MOVEMENT:
                                    self.signals.log_message.emit(
                                        f"[DELTA DEBUG] Calculated: prev({last_mouse_pos[0]},{last_mouse_pos[1]}) "
                                        f"curr({x},{y}) = delta({dx},{dy}) gain={CAMERA_GAIN}"
                                    )
                                
                                # Отправляем движение если оно значимое
                                if abs(dx) >= MIN_STEP_THRESHOLD or abs(dy) >= MIN_STEP_THRESHOLD:
                                    if DEBUG_CAMERA_MOVEMENT:
                                        self.signals.log_message.emit(
                                            f"[SEND DEBUG] Calling send_relative_line({dx}, {dy})"
                                        )
                                    send_relative_line(dx, dy)
                                else:
                                    if DEBUG_CAMERA_MOVEMENT:
                                        self.signals.log_message.emit(
                                            f"[SKIP DEBUG] Delta too small: ({dx},{dy}) < threshold={MIN_STEP_THRESHOLD}"
                                        )
                            else:
                                if DEBUG_CAMERA_MOVEMENT:
                                    self.signals.log_message.emit("[ERROR DEBUG] last_mouse_pos is None during RMB drag!")
                            
                            # НЕ обновляем rmb_center - он остается точкой нажатия ПКМ
                            # НИЧЕГО абсолютного не двигаем, когда ПКМ зажата
                        else:
                            # Вне режима камеры — обычное абсолютное перемещение
                            mouse_controller.position = (x, y)
                            if DEBUG_CAMERA_MOVEMENT and mouse.Button.right not in pressed_buttons:
                                self.signals.log_message.emit(f"[NORMAL MOVE] Absolute position: ({x}, {y})")
                        last_mouse_pos = (x, y)

                    elif event_type == 'mouse_move_relative':
                        raw_dx, raw_dy = int(event_args[0]), int(event_args[1])
                        rmb_pressed = mouse.Button.right in pressed_buttons
                        scaled_dx = int(raw_dx * CAMERA_GAIN)
                        scaled_dy = int(raw_dy * CAMERA_GAIN)

                        if DEBUG_CAMERA_MOVEMENT:
                            self.signals.log_message.emit(
                                f"[REL MOVE DEBUG] raw Δ({raw_dx},{raw_dy}) scaled=({scaled_dx},{scaled_dy}) "
                                f"RMB={rmb_pressed} last_pos={last_mouse_pos}"
                            )

                        if rmb_pressed:
                            if abs(scaled_dx) >= MIN_STEP_THRESHOLD or abs(scaled_dy) >= MIN_STEP_THRESHOLD:
                                if DEBUG_CAMERA_MOVEMENT:
                                    self.signals.log_message.emit(
                                        f"[REL SEND DEBUG] Calling send_relative_line({scaled_dx}, {scaled_dy})"
                                    )
                                send_relative_line(scaled_dx, scaled_dy)
                            else:
                                if DEBUG_CAMERA_MOVEMENT:
                                    self.signals.log_message.emit(
                                        f"[REL SKIP DEBUG] Δ({scaled_dx},{scaled_dy}) < threshold={MIN_STEP_THRESHOLD}"
                                    )
                        else:
                            if DEBUG_CAMERA_MOVEMENT:
                                self.signals.log_message.emit(
                                    "[REL WARNING] Received relative movement without RMB pressed; ignoring."
                                )

                        if last_mouse_pos is not None:
                            last_mouse_pos = (last_mouse_pos[0] + raw_dx, last_mouse_pos[1] + raw_dy)
                        else:
                            last_mouse_pos = (raw_dx, raw_dy)

                    elif event_type == 'mouse_press':
                        x, y, button_str = event_args[0], event_args[1], event_args[2]
                        button = MOUSE_BUTTONS.get(button_str)
                        
                        # КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: перед нажатием
                        if DEBUG_CAMERA_MOVEMENT:
                            self.signals.log_message.emit(
                                f"[PRESS DEBUG] button={button_str} pos({x},{y}) "
                                f"pressed_before={pressed_buttons}"
                            )
                        
                        # Перед нажатием — ставим абсолют, чтобы клик попал
                        mouse_controller.position = (x, y)
                        if button:
                            pressed_buttons.add(button)
                            mouse_controller.press(button)
                            if button == mouse.Button.right:
                                # При нажатии ПКМ устанавливаем центр и инициализируем последнюю позицию
                                rmb_center = (x, y)
                                last_mouse_pos = (x, y)  # Важно для правильного старта инкрементальных расчетов
                                if DEBUG_CAMERA_MOVEMENT:
                                    self.signals.log_message.emit(
                                        f"[RMB PRESS DEBUG] RMB pressed at: ({x}, {y}), "
                                        f"rmb_center={rmb_center}, last_mouse_pos={last_mouse_pos}"
                                    )

                    elif event_type == 'mouse_release':
                        x, y, button_str = event_args[0], event_args[1], event_args[2]
                        button = MOUSE_BUTTONS.get(button_str)
                        
                        # КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: перед отпусканием
                        if DEBUG_CAMERA_MOVEMENT:
                            self.signals.log_message.emit(
                                f"[RELEASE DEBUG] button={button_str} pos({x},{y}) "
                                f"pressed_before={pressed_buttons} rmb_center={rmb_center}"
                            )
                        
                        mouse_controller.position = (x, y)
                        if button:
                            mouse_controller.release(button)
                            pressed_buttons.discard(button)
                            if button == mouse.Button.right:
                                if DEBUG_CAMERA_MOVEMENT:
                                    self.signals.log_message.emit(
                                        f"[RMB RELEASE DEBUG] RMB released at: ({x}, {y}), "
                                        f"resetting rmb_center from {rmb_center} to None"
                                    )
                                rmb_center = None  # сброс «центра» по отпусканию
                                # last_mouse_pos не сбрасываем - он нужен для следующих движений

                    elif event_type == 'mouse_scroll':
                        mouse_controller.scroll(event_args[0], event_args[1])
                        if DEBUG_CAMERA_MOVEMENT:
                            self.signals.log_message.emit(f"[CAM DEBUG] Scroll: dx={event_args[0]}, dy={event_args[1]}")

                    elif event_type == 'key_press':
                        key = SPECIAL_KEYS.get(event_args[0]) or event_args[0]
                        keyboard_controller.press(key)

                    elif event_type == 'key_release':
                        key = SPECIAL_KEYS.get(event_args[0]) or event_args[0]
                        keyboard_controller.release(key)

                except Exception as e:
                    self.signals.log_message.emit(f"Ошибка при воспроизведении: {e}")

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

    def update_ui_for_playback(self, is_playing, name, loops):
        if is_playing:
            self.signals.log_message.emit(f"Подготовка к '{name}'. Повторов: {'∞' if loops <= 0 else loops}.")
        self.play_button.setEnabled(not is_playing)  # фикс синтаксиса (никаких '!' в Python)
        self.record_button.setEnabled(not is_playing)
        self.stop_playback_button.setEnabled(is_playing)

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