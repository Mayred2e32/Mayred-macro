from __future__ import annotations

import threading
from typing import List, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import SettingsRepository
from .playback import PlaybackSession
from .recording import RecordingSession
from .storage import MacroStorage


class MacroEngineController(QObject):
    log_signal = Signal(str)
    macros_signal = Signal(list)
    state_signal = Signal(str)

    def __init__(self, storage: MacroStorage, settings_repo: SettingsRepository):
        super().__init__()
        self.storage = storage
        self.settings_repo = settings_repo
        bundle = settings_repo.bundle
        self.settings = bundle.settings
        self.calibration = bundle.resolve_calibration()
        self.recorder: Optional[RecordingSession] = None
        self.playback_thread: Optional[threading.Thread] = None
        self.playback_stop_event: Optional[threading.Event] = None
        self.mode = "idle"
        self.macros_signal.emit(self.storage.list_recordings())

    def start_recording(self):
        if self.mode != "idle":
            self.log_signal.emit("⚠️ Нельзя начать запись: занят другой операцией.")
            return
        self.recorder = RecordingSession(self.settings, self.calibration)
        self.recorder.start()
        self.mode = "recording"
        self.state_signal.emit(self.mode)
        self.log_signal.emit("⏺️ Начата запись макроса. Нажмите Stop для сохранения.")

    def stop_recording(self, name: Optional[str] = None):
        if self.mode != "recording" or not self.recorder:
            self.log_signal.emit("ℹ️ Нет активной записи.")
            return

        def worker():
            try:
                recording = self.recorder.stop()
            except Exception as exc:  # pragma: no cover
                self.log_signal.emit(f"❌ Ошибка остановки записи: {exc}")
                return
            finally:
                self.recorder = None
            if name:
                recording.name = name
            try:
                path = self.storage.save(recording, name)
                self.log_signal.emit(f"💾 Макрос сохранен: {path.name}")
            except Exception as exc:
                self.log_signal.emit(f"❌ Ошибка сохранения: {exc}")
            self.macros_signal.emit(self.storage.list_recordings())
            self.mode = "idle"
            self.state_signal.emit(self.mode)

        threading.Thread(target=worker, daemon=True).start()

    def play_macro(self, slug: str):
        if self.mode != "idle":
            self.log_signal.emit("⚠️ Занято другой операцией.")
            return
        try:
            recording = self.storage.load(slug)
        except FileNotFoundError:
            self.log_signal.emit("❌ Макрос не найден.")
            return
        session = PlaybackSession(self.settings, self.calibration)
        self.playback_stop_event = threading.Event()
        self.mode = "playback"
        self.state_signal.emit(self.mode)
        self.log_signal.emit(f"▶️ Воспроизведение: {recording.name}")

        def worker():
            try:
                result = session.play(recording, self.playback_stop_event)
                for line in result.diagnostics:
                    self.log_signal.emit(line)
                self.log_signal.emit(
                    f"✅ Камера: сегментов={result.segments}, max_error={result.max_error_deg:.3f}°, avg_error={result.avg_error_deg:.3f}°"
                )
            except Exception as exc:  # pragma: no cover
                self.log_signal.emit(f"❌ Ошибка воспроизведения: {exc}")
            finally:
                self.mode = "idle"
                self.state_signal.emit(self.mode)
                self.playback_stop_event = None
                self.playback_thread = None

        self.playback_thread = threading.Thread(target=worker, daemon=True)
        self.playback_thread.start()

    def stop_playback(self):
        if self.mode != "playback" or not self.playback_stop_event:
            self.log_signal.emit("ℹ️ Воспроизведение не активно.")
            return
        self.playback_stop_event.set()
        self.log_signal.emit("⏹️ Запрошена остановка воспроизведения.")

    def delete_macro(self, slug: str):
        try:
            self.storage.delete(slug)
        except Exception as exc:
            self.log_signal.emit(f"❌ Ошибка удаления: {exc}")
            return
        self.macros_signal.emit(self.storage.list_recordings())
        self.log_signal.emit("🗑️ Макрос удален.")

    def refresh(self):
        self.macros_signal.emit(self.storage.list_recordings())


class MacroEngineWindow(QWidget):
    def __init__(self, controller: MacroEngineController):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Macro Engine 3°")
        self.resize(700, 480)
        self._build_ui()
        self._connect_signals()
        self.controller.refresh()

    def _build_ui(self):
        main_layout = QVBoxLayout()
        list_layout = QHBoxLayout()

        self.macro_list = QListWidget()
        self.macro_list.setSelectionMode(QAbstractItemView.SingleSelection)
        list_layout.addWidget(self.macro_list, 2)

        buttons_layout = QVBoxLayout()
        self.record_button = QPushButton("Start Recording")
        self.stop_button = QPushButton("Stop / Save")
        self.play_button = QPushButton("Play Selected")
        self.stop_playback_button = QPushButton("Stop Playback")
        self.refresh_button = QPushButton("Refresh")
        self.delete_button = QPushButton("Delete")
        for button in [
            self.record_button,
            self.stop_button,
            self.play_button,
            self.stop_playback_button,
            self.refresh_button,
            self.delete_button,
        ]:
            button.setMinimumHeight(34)
            buttons_layout.addWidget(button)
        buttons_layout.addStretch()
        list_layout.addLayout(buttons_layout, 1)

        main_layout.addLayout(list_layout)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        main_layout.addWidget(QLabel("Diagnostics"))
        main_layout.addWidget(self.log_view)
        self.status_label = QLabel("Idle")
        main_layout.addWidget(self.status_label)
        self.setLayout(main_layout)

    def _connect_signals(self):
        self.record_button.clicked.connect(self.controller.start_recording)
        self.stop_button.clicked.connect(self._stop_recording)
        self.play_button.clicked.connect(self._play_selected)
        self.stop_playback_button.clicked.connect(self.controller.stop_playback)
        self.refresh_button.clicked.connect(self.controller.refresh)
        self.delete_button.clicked.connect(self._delete_selected)

        self.controller.log_signal.connect(self._append_log)
        self.controller.macros_signal.connect(self._populate_macros)
        self.controller.state_signal.connect(self._update_state)

    def _append_log(self, message: str):
        self.log_view.append(message)
        self.log_view.ensureCursorVisible()

    def _populate_macros(self, entries: List[dict]):
        self.macro_list.clear()
        for entry in entries:
            item = QListWidgetItem(entry.get("name", entry.get("slug", "macro")))
            item.setData(Qt.UserRole, entry.get("slug"))
            self.macro_list.addItem(item)

    def _update_state(self, state: str):
        self.status_label.setText(state.capitalize())
        recording_active = state == "recording"
        playback_active = state == "playback"
        self.record_button.setEnabled(state == "idle")
        self.play_button.setEnabled(state == "idle")
        self.stop_button.setEnabled(recording_active)
        self.delete_button.setEnabled(state == "idle")
        self.stop_playback_button.setEnabled(playback_active)

    def _selected_slug(self) -> Optional[str]:
        item = self.macro_list.currentItem()
        if not item:
            return None
        return item.data(Qt.UserRole)

    def _stop_recording(self):
        if self.controller.mode != "recording":
            QMessageBox.information(self, "Stop", "Запись не выполняется")
            return
        name, ok = QInputDialog.getText(self, "Save macro", "Name", text="macro")
        if not ok:
            name = None
        self.controller.stop_recording(name)

    def _play_selected(self):
        slug = self._selected_slug()
        if not slug:
            QMessageBox.information(self, "Play", "Выберите макрос")
            return
        self.controller.play_macro(slug)

    def _delete_selected(self):
        slug = self._selected_slug()
        if not slug:
            QMessageBox.information(self, "Delete", "Выберите макрос")
            return
        if QMessageBox.question(self, "Delete", "Удалить выбранный макрос?") == QMessageBox.Yes:
            self.controller.delete_macro(slug)


def launch_app():
    app = QApplication.instance() or QApplication([])
    controller = MacroEngineController(MacroStorage(), SettingsRepository())
    window = MacroEngineWindow(controller)
    window.show()
    return app.exec()


__all__ = ["launch_app", "MacroEngineWindow", "MacroEngineController"]
