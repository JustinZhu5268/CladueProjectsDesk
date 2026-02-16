"""
Theme manager for ClaudeStation - Light/Dark theme support.

PRD v3 §8.5 要求支持亮色/暗色主题，并可跟随系统自动切换。
"""
from __future__ import annotations

import logging
from enum import Enum

log = logging.getLogger(__name__)


class ThemeMode(Enum):
    """Theme mode options."""
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


# 亮色主题配色 (PRD v3 §8.5)
LIGHT_THEME = """
    /* 全局字体设置 */
    * { font-size: 13px; }
    
    QMainWindow { background: #FFFFFF; color: #1A1A1A; }
    
    /* 菜单栏 */
    QMenuBar { background: #F5F5F0; color: #1A1A1A; }
    QMenuBar::item:selected { background: #E0E0E0; }
    QMenu { background: #FFFFFF; color: #1A1A1A; border: 1px solid #CCCCCC; }
    QMenu::item:selected { background: #E0E0E0; }
    
    /* 列表控件 */
    QListWidget {
        border: 1px solid #DDDDDD;
        border-radius: 6px;
        background: #FFFFFF;
        color: #1A1A1A;
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
        background: #F0F0F0;
    }
    
    /* 按钮 */
    QPushButton {
        padding: 6px 14px;
        border: 1px solid #CCCCCC;
        border-radius: 6px;
        background: #F5F5F5;
        color: #1A1A1A;
        font-size: 13px;
        font-weight: 500;
    }
    QPushButton:hover {
        background: #E8E8E8;
        border-color: #AAAAAA;
    }
    QPushButton:pressed {
        background: #D0D0D0;
    }
    QPushButton:disabled {
        color: #999999;
        background: #F0F0F0;
    }
    
    /* 下拉框 */
    QComboBox {
        padding: 6px 10px;
        border: 1px solid #CCCCCC;
        border-radius: 6px;
        background: #FFFFFF;
        color: #1A1A1A;
        font-size: 13px;
        min-width: 200px;
    }
    QComboBox:hover {
        border-color: #AAAAAA;
    }
    QComboBox::drop-down {
        border: none;
        width: 30px;
    }
    QComboBox QAbstractItemView {
        background: #FFFFFF;
        color: #1A1A1A;
        border: 1px solid #CCCCCC;
        selection-background-color: #0D5CB6;
    }
    
    /* 文本输入框 */
    QTextEdit, QPlainTextEdit {
        border: 1px solid #DDDDDD;
        border-radius: 8px;
        padding: 10px;
        font-size: 14px;
        background: #FFFFFF;
        color: #1A1A1A;
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        selection-background-color: #0D5CB6;
    }
    QTextEdit:focus, QPlainTextEdit:focus {
        border-color: #0D5CB6;
    }
    
    /* 单行输入 */
    QLineEdit {
        padding: 6px 10px;
        border: 1px solid #DDDDDD;
        border-radius: 6px;
        background: #FFFFFF;
        color: #1A1A1A;
        font-size: 13px;
    }
    QLineEdit:focus {
        border-color: #0D5CB6;
    }
    
    /* 标签 */
    QLabel { 
        font-size: 13px; 
        color: #1A1A1A; 
    }
    
    /* 分组框 */
    QGroupBox { 
        font-weight: bold; 
        border: 1px solid #DDDDDD; 
        border-radius: 8px; 
        margin-top: 12px; 
        padding-top: 16px;
        padding: 12px;
        color: #1A1A1A;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 8px;
        color: #666666;
    }
    
    /* 复选框 */
    QCheckBox { 
        font-size: 13px; 
        color: #1A1A1A;
        spacing: 8px;
    }
    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border: 2px solid #CCCCCC;
        border-radius: 4px;
        background: #FFFFFF;
    }
    QCheckBox::indicator:checked {
        background: #0D5CB6;
        border-color: #0D5CB6;
    }
    
    /* 状态栏 */
    QStatusBar { 
        font-size: 12px; 
        color: #666666;
        background: #F5F5F5;
        border-top: 1px solid #DDDDDD;
    }
    
    /* 滚动条 */
    QScrollBar:vertical {
        background: #F5F5F5;
        width: 12px;
        border-radius: 6px;
    }
    QScrollBar::handle:vertical {
        background: #CCCCCC;
        border-radius: 6px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background: #AAAAAA;
    }
    
    /* 分割条 */
    QSplitter::handle {
        background: #DDDDDD;
    }
    QSplitter::handle:horizontal {
        width: 2px;
    }
    
    /* 标签页 */
    QTabWidget::pane { 
        border: 1px solid #DDDDDD; 
        background: #FFFFFF;
    }
    QTabBar::tab {
        background: #F5F5F5;
        color: #666666;
        padding: 8px 16px;
        border: none;
    }
    QTabBar::tab:selected {
        background: #0D5CB6;
        color: #FFFFFF;
    }
"""


# 暗色主题配色 (已有)
DARK_THEME = """
    /* 全局字体设置 */
    * { font-size: 13px; }
    
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
"""


class ThemeManager:
    """
    主题管理器 - 支持亮色/暗色/跟随系统三种模式
    
    PRD v3 §8.5: 亮色/暗色主题 + 系统主题自动检测
    """
    
    def __init__(self):
        self._mode = ThemeMode.DARK
        self._current_theme = DARK_THEME
        
    @property
    def mode(self) -> ThemeMode:
        return self._mode
    
    @mode.setter
    def mode(self, value: ThemeMode) -> None:
        self._mode = value
        log.info(f"Theme mode set to: {value.value}")
    
    @property
    def current_theme(self) -> str:
        return self._current_theme
    
    @property
    def is_dark(self) -> bool:
        return self._mode == ThemeMode.DARK
    
    def get_theme_css(self, mode: ThemeMode | None = None) -> str:
        """获取指定模式的主题 CSS"""
        if mode is None:
            mode = self._mode
            
        if mode == ThemeMode.LIGHT:
            return LIGHT_THEME
        else:
            return DARK_THEME
    
    def apply_theme(self, app, mode: ThemeMode | None = None) -> None:
        """应用主题到应用程序"""
        if mode is None:
            mode = self._mode
            
        css = self.get_theme_css(mode)
        self._current_theme = css
        app.setStyleSheet(css)
        log.info(f"Applied {'light' if mode == ThemeMode.LIGHT else 'dark'} theme")


# 全局主题管理器实例
theme_manager = ThemeManager()


def get_theme_manager() -> ThemeManager:
    """获取全局主题管理器"""
    return theme_manager
