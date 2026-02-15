"""ClaudeStation - Claude Desktop Client.

Entry point for the application.
"""
from __future__ import annotations

import sys
import logging

# Must configure logging before any other imports
from config import setup_logging, APP_NAME, APP_VERSION, LOG_PATH

setup_logging()
log = logging.getLogger(__name__)


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

    # Apply basic stylesheet
        # 应用暗黑样式表
    app.setStyleSheet("""
    QMainWindow { background: #1E1E1E; color: #E5E5E5; }
    
    /* 菜单栏 */
    QMenuBar { background: #2D2D2D; color: #E5E5E5; }
    QMenuBar::item:selected { background: #404040; }
    QMenu { background: #2D2D2D; color: #E5E5E5; border: 1px solid #404040; }
    QMenu::item:selected { background: #404040; }
    
    /* 列表控件 */
    QListWidget {
        border: 1px solid #3A3A3A;
        border-radius: 6px;
        background: #252525;
        color: #E5E5E5;
        font-size: 13px;
        outline: none;
        padding: 4px;
    }
    QListWidget::item {
        padding: 8px 12px;
        border-radius: 4px;
        margin: 2px 0;
    }
    QListWidget::item:selected {
        background: #0D5CB6;
        color: #FFFFFF;
    }
    QListWidget::item:hover {
        background: #3A3A3A;
    }
    
    /* 按钮 */
    QPushButton {
        padding: 6px 14px;
        border: 1px solid #3A3A3A;
        border-radius: 6px;
        background: #2D2D2D;
        color: #E5E5E5;
        font-size: 13px;
        font-weight: 500;
    }
    QPushButton:hover {
        background: #3A3A3A;
        border-color: #4A4A4A;
    }
    QPushButton:pressed {
        background: #404040;
    }
    QPushButton:disabled {
        color: #666666;
        background: #252525;
    }
    
    /* 下拉框 */
    QComboBox {
        padding: 6px 10px;
        border: 1px solid #3A3A3A;
        border-radius: 6px;
        background: #252525;
        color: #E5E5E5;
        font-size: 13px;
        min-width: 200px;
    }
    QComboBox:hover {
        border-color: #4A4A4A;
    }
    QComboBox::drop-down {
        border: none;
        width: 30px;
    }
    QComboBox QAbstractItemView {
        background: #2D2D2D;
        color: #E5E5E5;
        border: 1px solid #3A3A3A;
        selection-background-color: #0D5CB6;
    }
    
    /* 文本输入框 */
    QTextEdit, QPlainTextEdit {
        border: 1px solid #3A3A3A;
        border-radius: 8px;
        padding: 10px;
        font-size: 14px;
        background: #252525;
        color: #E5E5E5;
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        selection-background-color: #0D5CB6;
    }
    QTextEdit:focus, QPlainTextEdit:focus {
        border-color: #0D5CB6;
    }
    
    /* 单行输入 */
    QLineEdit {
        padding: 6px 10px;
        border: 1px solid #3A3A3A;
        border-radius: 6px;
        background: #252525;
        color: #E5E5E5;
        font-size: 13px;
    }
    QLineEdit:focus {
        border-color: #0D5CB6;
    }
    
    /* 标签 */
    QLabel { 
        font-size: 13px; 
        color: #E5E5E5; 
    }
    
    /* 分组框 */
    QGroupBox { 
        font-weight: bold; 
        border: 1px solid #3A3A3A; 
        border-radius: 8px; 
        margin-top: 12px; 
        padding-top: 16px;
        padding: 12px;
        color: #E5E5E5;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 8px;
        color: #AAAAAA;
    }
    
    /* 复选框 */
    QCheckBox { 
        font-size: 13px; 
        color: #E5E5E5;
        spacing: 8px;
    }
    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border: 2px solid #3A3A3A;
        border-radius: 4px;
        background: #252525;
    }
    QCheckBox::indicator:checked {
        background: #0D5CB6;
        border-color: #0D5CB6;
    }
    
    /* 状态栏 */
    QStatusBar { 
        font-size: 12px; 
        color: #888888;
        background: #252525;
        border-top: 1px solid #3A3A3A;
    }
    
    /* 滚动条 */
    QScrollBar:vertical {
        background: #252525;
        width: 12px;
        border-radius: 6px;
    }
    QScrollBar::handle:vertical {
        background: #3A3A3A;
        border-radius: 6px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background: #4A4A4A;
    }
    
    /* 分割条 */
    QSplitter::handle {
        background: #3A3A3A;
    }
    QSplitter::handle:horizontal {
        width: 2px;
    }
    
    /* 标签页 */
    QTabWidget::pane { 
        border: 1px solid #3A3A3A; 
        background: #252525;
    }
    QTabBar::tab {
        background: #2D2D2D;
        color: #888888;
        padding: 8px 16px;
        border: none;
    }
    QTabBar::tab:selected {
        background: #0D5CB6;
        color: #FFFFFF;
    }
    """)
    # Create and show main window
    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    log.info("Application ready")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
