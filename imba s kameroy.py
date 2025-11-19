import sys
import time
import threading
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
MACROS_DIR = Path(_file_).parent / "macros"
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
CAMERA_GAIN = 0.7           # Увеличь до 10–30, если вращается слабо
MIN_STEP_THRESHOLD = 1    # Минимальный модуль дельты, чтобы отправлять движение

# --- Низкоуровневый хелпер для относительного движения (Windows: SendInput) ---
IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    # Константы и структуры для SendInput
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
    INPUT_MOUSE = 0
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_MOVE_NOCOALESCE = 0x2000  # важно для игр: не склеивать события

    class MOUSEINPUT(ctypes.Structure):
        fields = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class INPUT(ctypes.Structure):
        class _I(ctypes.Union):
            fields = [("mi", MOUSEINPUT)]
        anonymous = ("i",)
        fields = [("type", wintypes.DWORD), ("i", _I)]

    user32 = ctypes.windll.user32
    SendInput = user32.SendInput

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
        """Разбиваем смещение на шаги по 1 пикселю и шлем пачкой (без коалесинга)."""
        dx = int(dx); dy = int(dy)
        if dx == 0 and dy == 0:
            return

        steps = max(abs(dx), abs(dy))
        step_x = dx / float(steps)
        step_y = dy / float(steps)
        cur_x = 0.0
        cur_y = 0.0
        prev_ix = 0
        prev_iy = 0

        batch = []
        BATCH_SIZE = 128

        for _ in range(steps):
            cur_x += step_x
            cur_y += step_y
            ix = int(round(cur_x))
            iy = int(round(cur_y))
            sx = ix - prev_ix
            sy = iy - prev_iy
            if sx != 0 or sy != 0:
                batch.append(_build_move_input(sx, sy))
                prev_ix = ix
                prev_iy = iy
                if len(batch) >= BATCH_SIZE:
                    arr = (INPUT * len(batch))(*batch)
                    SendInput(len(batch), arr, ctypes.sizeof(INPUT))
                    batch.clear()

        if batch:
            arr = (INPUT * len(batch))(*batch)
            SendInput(len(batch), arr, ctypes.sizeof(INPUT))

else:
    # На Linux/macOS используем pynput.Controller().move как относительное перемещение
    from pynput import mouse as _mouse

    def send_relative_line(dx: int, dy: int):
        dx = int(dx); dy = int(dy)
        if dx == 0 and dy == 0:
            return
        steps = max(abs(dx), abs(dy))
        step_x = dx / float(steps)
        step_y = dy / float(steps)
        cur_x = 0.0
        cur_y = 0.0
        prev_ix = 0
        prev_iy = 0
        ctrl = _mouse.Controller()
        for _ in range(steps):
            cur_x += step_x
            cur_y += step_y
            ix = int(round(cur_x))
            iy = int(round(cur_y))
            sx = ix - prev_ix
            sy = iy - prev_iy
            if sx != 0 or sy != 0:
                ctrl.move(sx, sy)
                prev_ix = ix
                prev_iy = iy

# Сигналы для безопасного обновления GUI из других потоков
class WorkerSignals(QObject):
    log_message = Signal(str)
    recording_stopped = Signal()
    playback_finished = Signal()

# --- Основной класс приложения ---
class MacroApp(QWidget):
    def _init_(self):
        super()._init_()
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
        self.recorded_events.append(('mouse_pos', (mouse_controller.position[0], mouse_controller.position[1], 0.0)))

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
            if not self.is_recording: return
            action = 'mouse_press' if pressed else 'mouse_release'
            self.recorded_events.append((action, (x, y, str(button), get_offset())))

        def on_scroll(x, y, dx, dy):
            if not self.is_recording: return
            self.recorded_events.append(('mouse_scroll', (dx, dy, get_offset())))

        def on_move(x, y):
            if not self.is_recording: return
            self.recorded_events.append(('mouse_move', (x, y, get_offset())))

        k_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        m_listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll, on_move=on_move)
        k_listener.start(); m_listener.start()
        while self.is_recording: time.sleep(0.1)
        k_listener.stop(); m_listener.stop()
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
        rmb_center = None  # (cx, cy) координаты на момент нажатия ПКМ

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

            for event in events:
                if not self.is_playing:
                    break

                event_type, event_args = event
                event_offset = event_args[-1]
                target_time = playback_start_time + event_offset
                sleep_duration = target_time - time.perf_counter()
                if sleep_duration > 0:
                    time.sleep(sleep_duration)

                try:
                    if event_type == 'mouse_pos':
                        # Исходная позиция только один раз для старта
                        x, y = event_args[0], event_args[1]
                        mouse_controller.position = (x, y)

                    elif event_type == 'mouse_move':
                        x, y = event_args[0], event_args[1]
                        if mouse.Button.right in pressed_buttons and rmb_center is not None:
                            # Дельта от центра (то, что Roblox реально использует при захвате)
                            dx = int((x - rmb_center[0]) * CAMERA_GAIN)
                            dy = int((y - rmb_center[1]) * CAMERA_GAIN)
                            if abs(dx) >= MIN_STEP_THRESHOLD or abs(dy) >= MIN_STEP_THRESHOLD:
                                send_relative_line(dx, dy)
                            # НИЧЕГО абсолютного не двигаем, когда ПКМ зажата
                        else:
                            # Вне режима камеры — обычное абсолютное перемещение
                            mouse_controller.position = (x, y)

                    elif event_type == 'mouse_press':
                        x, y, button_str = event_args[0], event_args[1], event_args[2]
                        button = MOUSE_BUTTONS.get(button_str)
                        # Перед нажатием — ставим абсолют, чтобы клик попал
                        mouse_controller.position = (x, y)
                        if button:
                            pressed_buttons.add(button)
                            mouse_controller.press(button)
                            if button == mouse.Button.right:
                                # Зафиксировать центр на момент нажатия ПКМ
                                rmb_center = (x, y)

                    elif event_type == 'mouse_release':
                        x, y, button_str = event_args[0], event_args[1], event_args[2]
                        button = MOUSE_BUTTONS.get(button_str)
                        mouse_controller.position = (x, y)
                        if button:
                            mouse_controller.release(button)
                            pressed_buttons.discard(button)
                            if button == mouse.Button.right:
                                rmb_center = None  # сброс «центра» по отпусканию

                    elif event_type == 'mouse_scroll':
                        mouse_controller.scroll(event_args[0], event_args[1])

                    elif event_type == 'key_press':
                        key = SPECIAL_KEYS.get(event_args[0]) or event_args[0]
                        keyboard_controller.press(key)

                    elif event_type == 'key_release':
                        key = SPECIAL_KEYS.get(event_args[0]) or event_args[0]
                        keyboard_controller.release(key)

                except Exception as e:
                    self.signals.log_message.emit(f"Ошибка: {e}")

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

if _name_ == "_main_":
    app = QApplication(sys.argv)
    window = MacroApp()
    window.show()
    sys.exit(app.exec())
