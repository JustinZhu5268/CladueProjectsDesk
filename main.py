"""ClaudeStation - Claude Desktop Client.

Entry point for the application.
"""
from __future__ import annotations

import sys
import logging
import json
from pathlib import Path

# Must configure logging before any other imports
from config import setup_logging, APP_NAME, APP_VERSION, LOG_PATH

setup_logging()
log = logging.getLogger(__name__)


# 主题配置路径
THEME_CONFIG_FILE = Path.home() / APP_NAME / "theme_config.json"


def load_theme_config() -> dict:
    """Load theme configuration from file."""
    try:
        if THEME_CONFIG_FILE.exists():
            with open(THEME_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"mode": "dark"}


def save_theme_config(config: dict) -> None:
    """Save theme configuration to file."""
    try:
        THEME_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(THEME_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def main():
    log.info("=" * 60)
    log.info("%s v%s starting", APP_NAME, APP_VERSION)
    log.info("Log file: %s", LOG_PATH)
    log.info("Python: %s", sys.version)
    log.info("=" * 60)

    # Initialize database
    from data.database import db
    try:
        db.initialize()
        log.info("Database initialized")
    except Exception:
        log.exception("Failed to initialize database")
        sys.exit(1)

    # Check for PySide6
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
    except ImportError:
        log.error("PySide6 not installed. Run: pip install PySide6 PySide6-Addons")
        print("\n[ERROR] PySide6 not installed.")
        print("  Run: pip install PySide6 PySide6-Addons\n")
        sys.exit(1)

    # Check for anthropic
    try:
        import anthropic
        log.info("anthropic SDK version: %s", anthropic.__version__)
    except ImportError:
        log.error("anthropic SDK not installed")
        print("\n[ERROR] anthropic SDK not installed.")
        print("  Run: pip install anthropic\n")
        sys.exit(1)

    # Enable High DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    # PRD v3 §8.5: 支持亮色/暗色主题
    from utils.theme_manager import LIGHT_THEME, DARK_THEME
    
    theme_config = load_theme_config()
    theme_mode = theme_config.get("mode", "dark")
    
    # 根据保存的配置应用主题
    if theme_mode == "light":
        app.setStyleSheet(LIGHT_THEME)
    else:
        app.setStyleSheet(DARK_THEME)

    # Create and show main window
    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    log.info("Application ready")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
