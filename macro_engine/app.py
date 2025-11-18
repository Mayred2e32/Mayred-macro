from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .config import SettingsRepository
from .storage import MacroStorage
from .ui import MacroEngineController, MacroEngineWindow


class MacroEngineApp:
    def __init__(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.settings_repo = SettingsRepository()
        self.storage = MacroStorage()
        self.controller = MacroEngineController(self.storage, self.settings_repo)
        self.window = MacroEngineWindow(self.controller)

    def run(self) -> int:
        self.window.show()
        return self.app.exec()


def main() -> int:
    app = MacroEngineApp()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
