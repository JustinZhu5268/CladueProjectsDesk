"""Main application window with three-panel layout."""
from __future__ import annotations
from utils.markdown_renderer import render_markdown, get_chat_html_template, escape_js_string
import os
import sys
import base64
import json
import time
import logging
import atexit
from pathlib import Path
from functools import partial
import re

# #region agent log
DEBUG_LOG_PATH = r"c:\Users\Think\Desktop\ClaudeStation\claude_station\.cursor\debug.log"
def _dlog(location, message, data=None, hypothesis_id=None):
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "log_%s" % int(time.time()*1000), "timestamp": int(time.time()*1000), "location": location, "message": message, "data": data or {}, "hypothesisId": hypothesis_id or ""}) + "\n")
    except Exception:
        pass
# #endregion

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QComboBox,
    QTextEdit, QPlainTextEdit, QLineEdit, QFileDialog, QMessageBox,
    QInputDialog, QMenu, QFrame, QToolButton, QStatusBar, QSlider,
    QCheckBox, QApplication, QAbstractItemView,
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QSize
from PySide6.QtGui import QAction, QKeySequence, QIcon, QFont, QShortcut
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QObject, Slot

from config import (
    APP_NAME, APP_VERSION, MODELS, DEFAULT_MODEL,
    SIDEBAR_WIDTH, RIGHT_PANEL_WIDTH, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
)
from core.project_manager import ProjectManager, Project
from core.conversation_manager import ConversationManager, Conversation, Message
from core.document_processor import DocumentProcessor
from core.context_builder import ContextBuilder
from core.context_compressor import ContextCompressor, CompressionWorker
from core.token_tracker import TokenTracker, UsageInfo
from api.claude_client import ClaudeClient, StreamEvent
from utils.key_manager import KeyManager
from utils.markdown_renderer import render_markdown, get_chat_html_template
from ui.settings_dialog import SettingsDialog
from data.database import db

log = logging.getLogger(__name__)


# ── App State File (for persisting last conversation) ───────────────────────
APP_STATE_FILE = Path.home() / APP_NAME / "app_state.json"

def _load_app_state() -> dict:
    """Load app state from JSON file."""
    try:
        if APP_STATE_FILE.exists():
            with open(APP_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_app_state(state: dict) -> None:
    """Save app state to JSON file."""
    try:
        APP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(APP_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# Register save on exit
atexit.register(lambda: _save_app_state(_app_state_cache))

# In-memory cache for app state
_app_state_cache: dict = {}

def _get_app_state() -> dict:
    """Get cached app state, loading if needed."""
    global _app_state_cache
    if not _app_state_cache:
        _app_state_cache = _load_app_state()
    return _app_state_cache

def _set_app_state_value(key: str, value) -> None:
    """Set a value in app state and persist."""
    global _app_state_cache
    state = _get_app_state()
    state[key] = value
    _app_state_cache = state
    _save_app_state(state)


class ChatBridge(QObject):
    """Exposed to chat page via QWebChannel: insert ref text into input."""

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._main_window = main_window

    @Slot(str)
    def insertRef(self, text: str) -> None:
        if not text:
            return
        self._main_window.input_box.insertPlainText(text)
        QApplication.clipboard().setText(text)
        preview = text[:12] + ("..." if len(text) > 12 else "")
        self._main_window.statusBar().showMessage("已引用并复制: " + preview, 2000)

    @Slot(str)
    def showStatus(self, message: str) -> None:
        """Show status message in main window."""
        self._main_window.statusBar().showMessage(message, 3000)

    @Slot(str, str)
    def downloadMarkdown(self, content: str, filename: str) -> None:
        """Download Markdown content as a file."""
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        
        # 使用用户建议的默认文件名
        default_name = filename if filename else "document.md"
        
        path, _ = QFileDialog.getSaveFileName(
            self._main_window, 
            "保存 Markdown 文件", 
            default_name,
            "Markdown (*.md)"
        )
        
        if path:
            try:
                Path(path).write_text(content, encoding="utf-8")
                self._main_window.statusBar().showMessage(f"已保存: {path}", 3000)
            except Exception as e:
                log.error("Failed to save markdown file: %s", e)
                self._main_window.statusBar().showMessage(f"保存失败: {str(e)}", 3000)


class ChatWebPage(QWebEnginePage):
    """Chat page with QWebChannel so JS can call insertRef when UID is clicked."""

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self._bridge = ChatBridge(main_window, self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("chatHost", self._bridge)
        self.setWebChannel(self._channel)


class APIWorker(QThread):
    """Background thread for API calls."""
    text_delta = Signal(str)
    thinking_delta = Signal(str)
    finished = Signal(str, str, object)
    error = Signal(str)

    def __init__(self, client: ClaudeClient, messages: list, system: list,
                 model: str, max_tokens: int, thinking: dict | None = None,
                 project_id: str = "", conversation_id: str = ""):
        super().__init__()
        self.client = client
        self.messages = messages
        self.system = system
        self.model = model
        self.max_tokens = max_tokens
        self.thinking_cfg = thinking
        self.project_id = project_id
        self.conversation_id = conversation_id
        self._cancelled = False

    def run(self):
        full_text = ""
        thinking_text = ""
        usage = None
        try:
            for event in self.client.stream_message(
                messages=self.messages,
                system_content=self.system,
                model=self.model,
                max_tokens=self.max_tokens,
                thinking=self.thinking_cfg,
                project_id=self.project_id,
                conversation_id=self.conversation_id,
            ):
                if self._cancelled:
                    log.info("Streaming cancelled by user")
                    break
                if event.type == "text":
                    full_text += event.text
                    self.text_delta.emit(full_text)
                elif event.type == "thinking":
                    thinking_text += event.text
                    self.thinking_delta.emit(event.text)
                elif event.type == "error":
                    self.error.emit(event.error)
                    return
                elif event.type == "done":
                    full_text = event.text
                    usage = event.usage
        except Exception as e:
            log.exception("Worker thread exception")
            self.error.emit(str(e))
            return

        self.finished.emit(full_text, thinking_text, usage)

    def cancel(self):
        self._cancelled = True


class MainWindow(QMainWindow):
    """Three-panel main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.resize(1300, 800)

        self.project_mgr = ProjectManager()
        self.conv_mgr = ConversationManager()
        self.doc_processor = DocumentProcessor()
        self.context_builder = ContextBuilder()
        self.token_tracker = TokenTracker()
        self.key_manager = KeyManager()
        self.client = ClaudeClient()

        self.current_project: Project | None = None
        self.current_conv: Conversation | None = None
        self.worker: APIWorker | None = None
        self.compression_worker: CompressionWorker | None = None  # PRD v3: 压缩工作线程
        self.is_streaming = False
        self._accumulated_thinking = ""
        self._inject_chat_history_connected = False
        self._pending_history_messages = None

        self._build_ui()
        self._setup_shortcuts()
        self._setup_context_menu()
        self._init_client()
        self._refresh_projects()

        log.info("Main window initialized")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 获取当前主题颜色
        top_bar_bg = "#252525"
        top_bar_border = "#3A3A3A"
        label_color = "#AAAAAA"
        try:
            import json
            from pathlib import Path
            theme_file = Path.home() / "ClaudeStation" / "theme_config.json"
            if theme_file.exists():
                with open(theme_file, "r", encoding="utf-8") as f:
                    theme_data = json.load(f)
                    if theme_data.get("mode") == "light":
                        top_bar_bg = "#F5F5F0"
                        top_bar_border = "#CCCCCC"
                        label_color = "#1A1A1A"
        except:
            pass
        
        top_bar = QFrame()
        top_bar.setStyleSheet(f"""
            QFrame {{ 
                background: {top_bar_bg}; 
                border-bottom: 1px solid {top_bar_border}; 
                padding: 4px; 
            }}
            QLabel {{ color: {label_color}; font-size: 13px; }}
        """)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 6, 12, 6)

        top_layout.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(280)
        
        for mid, minfo in MODELS.items():
            display_text = f"{minfo.display_name} ${minfo.input_price}/${minfo.output_price}"
            self.model_combo.addItem(display_text, mid)
        
        default_idx = self.model_combo.findData(DEFAULT_MODEL)
        self.model_combo.setCurrentIndex(default_idx if default_idx >= 0 else 0)
        
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        top_layout.addWidget(self.model_combo)

        top_layout.addSpacing(20)

        self.thinking_check = QCheckBox("Extended Thinking")
        top_layout.addWidget(self.thinking_check)

        thinking_budget_layout = QHBoxLayout()
        self.thinking_budget = QComboBox()
        self.thinking_budget.setEnabled(False)
        
        self.thinking_budget.addItem("1024 — 快速推理", 1024)
        self.thinking_budget.addItem("2048 — 标准分析 (推荐)", 2048)
        self.thinking_budget.addItem("4096 — 深度思考", 4096)
        self.thinking_budget.addItem("8192 — 复杂问题", 8192)
        self.thinking_budget.addItem("16384 — 极限推理", 16384)
        self.thinking_budget.setCurrentIndex(1)
        
        self.thinking_recommend_label = QLabel("")
        self.thinking_recommend_label.setStyleSheet("color: #888; font-size: 11px;")
        self.thinking_recommend_label.setVisible(False)
        
        thinking_budget_layout.addWidget(QLabel("Budget:"))
        thinking_budget_layout.addWidget(self.thinking_budget)
        thinking_budget_layout.addWidget(self.thinking_recommend_label, 1)
        
        self.thinking_check.toggled.connect(self.thinking_budget.setEnabled)
        self.thinking_check.toggled.connect(self._on_thinking_toggled)
        
        top_layout.addLayout(thinking_budget_layout)
        top_layout.addSpacing(20)

        top_layout.addStretch()

        btn_settings = QPushButton("Settings")
        btn_settings.clicked.connect(self._open_settings)
        top_layout.addWidget(btn_settings)

        main_layout.addWidget(top_bar)

        # PRD v3 §8.6: 搜索栏
        search_bar = QFrame()
        search_bar.setStyleSheet("""
            QFrame { 
                background: #2A2A2A; 
                border-bottom: 1px solid #3A3A3A; 
                padding: 4px;
            }
        """)
        search_layout = QHBoxLayout(search_bar)
        search_layout.setContentsMargins(12, 4, 12, 4)
        
        search_layout.addWidget(QLabel("🔍"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索当前对话... (Ctrl+F)")
        self.search_box.setStyleSheet("""
            QLineEdit {
                background: #3A3A3A;
                color: #E5E5E5;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QLineEdit:focus {
                border-color: #D97706;
            }
        """)
        self.search_box.setMinimumWidth(250)
        self.search_box.returnPressed.connect(self._search_messages)
        search_layout.addWidget(self.search_box)
        
        self.btn_search_prev = QPushButton("↑")
        self.btn_search_prev.setFixedSize(28, 28)
        self.btn_search_prev.setToolTip("上一条匹配")
        self.btn_search_prev.setStyleSheet("""
            QPushButton { background: #3A3A3A; color: #AAA; border: 1px solid #555; border-radius: 4px; }
            QPushButton:hover { background: #454545; color: #FFF; }
        """)
        self.btn_search_prev.clicked.connect(self._search_prev)
        search_layout.addWidget(self.btn_search_prev)
        
        self.btn_search_next = QPushButton("↓")
        self.btn_search_next.setFixedSize(28, 28)
        self.btn_search_next.setToolTip("下一条匹配")
        self.btn_search_next.setStyleSheet("""
            QPushButton { background: #3A3A3A; color: #AAA; border: 1px solid #555; border-radius: 4px; }
            QPushButton:hover { background: #454545; color: #FFF; }
        """)
        self.btn_search_next.clicked.connect(self._search_next)
        search_layout.addWidget(self.btn_search_next)
        
        self.search_result_label = QLabel("")
        self.search_result_label.setStyleSheet("color: #888; font-size: 11px;")
        search_layout.addWidget(self.search_result_label)
        
        search_layout.addStretch()
        
        # 关闭搜索栏按钮
        btn_close_search = QPushButton("✕")
        btn_close_search.setFixedSize(24, 24)
        btn_close_search.setStyleSheet("""
            QPushButton { background: transparent; color: #888; border: none; font-size: 14px; }
            QPushButton:hover { color: #E74C3C; }
        """)
        btn_close_search.clicked.connect(self._close_search)
        search_layout.addWidget(btn_close_search)
        
        self.search_bar = search_bar
        self.search_bar.setVisible(False)  # 默认隐藏
        main_layout.addWidget(self.search_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)

        proj_header = QHBoxLayout()
        proj_header.addWidget(QLabel(" **Projects**"))
        btn_new_proj = QPushButton("＋ 新项目")
        btn_new_proj.setFixedHeight(28)
        btn_new_proj.setStyleSheet(
            "QPushButton { font-size: 12px; font-weight: bold; color: #E5E5E5; "
            "background: #3A3A3A; border: 1px solid #555; border-radius: 4px; min-width: 72px; }"
            "QPushButton:hover { background: #454545; }"
        )
        btn_new_proj.setToolTip("New Project (Ctrl+Shift+N)")
        btn_new_proj.clicked.connect(self._new_project)
        proj_header.addWidget(btn_new_proj)
        left_layout.addLayout(proj_header)

        self.project_list = QListWidget()
        self.project_list.setMaximumHeight(200)
        self.project_list.currentItemChanged.connect(self._on_project_selected)
        self.project_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.project_list.customContextMenuRequested.connect(self._project_context_menu)
        left_layout.addWidget(self.project_list)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        left_layout.addWidget(sep)

        conv_header = QHBoxLayout()
        conv_header.addWidget(QLabel(" **Conversations**"))
        btn_new_conv = QPushButton("＋ 新对话")
        btn_new_conv.setFixedHeight(28)
        btn_new_conv.setStyleSheet(
            "QPushButton { font-size: 12px; font-weight: bold; color: #E5E5E5; "
            "background: #3A3A3A; border: 1px solid #555; border-radius: 4px; min-width: 72px; }"
            "QPushButton:hover { background: #454545; }"
        )
        btn_new_conv.setToolTip("New Conversation (Ctrl+N)")
        btn_new_conv.clicked.connect(self._new_conversation)
        conv_header.addWidget(btn_new_conv)
        left_layout.addLayout(conv_header)

        self.conv_list = QListWidget()
        self.conv_list.currentItemChanged.connect(self._on_conv_selected)
        self.conv_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.conv_list.customContextMenuRequested.connect(self._conv_context_menu)
        left_layout.addWidget(self.conv_list)

        left_panel.setFixedWidth(SIDEBAR_WIDTH)
        splitter.addWidget(left_panel)

        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self.chat_view = QWebEngineView()
        center_layout.addWidget(self.chat_view, 1)

        # 获取当前主题颜色
        input_bg = "#252525"
        input_border = "#3A3A3A"
        try:
            import json
            from pathlib import Path
            theme_file = Path.home() / "ClaudeStation" / "theme_config.json"
            if theme_file.exists():
                with open(theme_file, "r", encoding="utf-8") as f:
                    theme_data = json.load(f)
                    if theme_data.get("mode") == "light":
                        input_bg = "#FFFFFF"
                        input_border = "#DDDDDD"
        except:
            pass
        
        input_frame = QFrame()
        input_frame.setStyleSheet(f"""
            QFrame {{ 
                background: {input_bg}; 
                border-top: 1px solid {input_border}; 
            }}
        """)
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(12, 8, 12, 8)

        attach_row = QHBoxLayout()
        self.attach_list_container = QWidget()
        self.attach_list_layout = QHBoxLayout(self.attach_list_container)
        self.attach_list_layout.setContentsMargins(0, 0, 0, 0)
        self.attach_list_layout.setSpacing(6)
        attach_row.addWidget(self.attach_list_container, 1)
        input_layout.addLayout(attach_row)

        input_row = QHBoxLayout()
        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText(
            "Type your message... (Ctrl+Enter to send). Use @#uid to reference a message (e.g. @#e9cfaca2)."
        )
        self.input_box.setMaximumHeight(120)
        self.input_box.setAcceptRichText(False)
        self.input_box.textChanged.connect(self._recommend_thinking_budget)
        input_row.addWidget(self.input_box, 1)

        btn_col = QVBoxLayout()
        self.btn_attach = QPushButton("📎")
        self.btn_attach.setFixedSize(36, 36)
        self.btn_attach.setToolTip("Attach files (images, PDF, etc.)")
        self.btn_attach.clicked.connect(self._attach_files)
        btn_col.addWidget(self.btn_attach)

        self.btn_send = QPushButton("Send")
        self.btn_send.setFixedSize(60, 36)
        self.btn_send.setStyleSheet("QPushButton { background: #D97706; color: white; border-radius: 6px; font-weight: bold; }")
        self.btn_send.clicked.connect(self._send_message)
        btn_col.addWidget(self.btn_send)
        input_row.addLayout(btn_col)

        input_layout.addLayout(input_row)
        center_layout.addWidget(input_frame)
        splitter.addWidget(center_panel)

        self.chat_view.setPage(ChatWebPage(self))
        # #region agent log
        self.chat_view.setHtml(get_chat_html_template(dark_mode=True))
        _dlog("main_window.py:254", "setHtml called", {"caller": "init"}, "H1")
        # #endregion

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        right_layout.addWidget(QLabel(" **System Prompt**"))
        self.system_prompt_edit = QPlainTextEdit()
        self.system_prompt_edit.setPlaceholderText("Enter custom instructions for this project...")
        self.system_prompt_edit.setMaximumHeight(150)
        right_layout.addWidget(self.system_prompt_edit)

        btn_save_prompt = QPushButton("Save Prompt")
        btn_save_prompt.clicked.connect(self._save_system_prompt)
        right_layout.addWidget(btn_save_prompt)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        right_layout.addWidget(sep2)

        doc_header = QHBoxLayout()
        doc_header.addWidget(QLabel(" **Documents**"))
        btn_upload = QPushButton("Upload")
        btn_upload.clicked.connect(self._upload_document)
        doc_header.addWidget(btn_upload)
        right_layout.addLayout(doc_header)

        self.doc_list = QListWidget()
        self.doc_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doc_list.customContextMenuRequested.connect(self._doc_context_menu)
        right_layout.addWidget(self.doc_list)

        self.doc_tokens_label = QLabel("Documents: 0 tokens")
        self.doc_tokens_label.setStyleSheet("color: #888; font-size: 11px;")
        right_layout.addWidget(self.doc_tokens_label)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        right_layout.addWidget(sep3)

        right_layout.addWidget(QLabel(" **Token Stats**"))
        self.stats_label = QLabel("No conversation selected")
        self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet("color: #666; font-size: 12px;")
        right_layout.addWidget(self.stats_label)

        # PRD v3: 4层缓存可视化仪表盘
        sep4 = QFrame()
        sep4.setFrameShape(QFrame.Shape.HLine)
        right_layout.addWidget(sep4)
        
        right_layout.addWidget(QLabel(" **4-Layer Cache**"))
        
        # Layer 1: System + Docs
        self.layer1_label = QLabel("L1: System+Docs -")
        self.layer1_label.setStyleSheet("color: #4CAF50; font-size: 11px;")
        right_layout.addWidget(self.layer1_label)
        
        # Layer 2: Rolling Summary
        self.layer2_label = QLabel("L2: Summary -")
        self.layer2_label.setStyleSheet("color: #2196F3; font-size: 11px;")
        right_layout.addWidget(self.layer2_label)
        
        # Layer 3: Recent Messages
        self.layer3_label = QLabel("L3: Recent -")
        self.layer3_label.setStyleSheet("color: #FF9800; font-size: 11px;")
        right_layout.addWidget(self.layer3_label)
        
        # Layer 4: Current Message
        self.layer4_label = QLabel("L4: Current -")
        self.layer4_label.setStyleSheet("color: #9C27B0; font-size: 11px;")
        right_layout.addWidget(self.layer4_label)
        
        # Total tokens
        self.total_tokens_label = QLabel("Total: 0 / 200K")
        self.total_tokens_label.setStyleSheet("color: #666; font-size: 11px; font-weight: bold;")
        right_layout.addWidget(self.total_tokens_label)

        right_layout.addStretch()

        right_panel.setFixedWidth(RIGHT_PANEL_WIDTH)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        main_layout.addWidget(splitter, 1)

        self.statusBar().showMessage("Ready")
        self.pending_attachments: list[dict] = []
        self._pending_history_messages: list | None = None

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self._send_message)
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self._new_conversation)
        QShortcut(QKeySequence("Ctrl+Shift+N"), self).activated.connect(self._new_project)
        QShortcut(QKeySequence("Ctrl+,"), self).activated.connect(self._open_settings)
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self.input_box.setFocus)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._cancel_streaming)
        # PRD v3 §8.6: 对话内搜索
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._toggle_search)
    
    def _setup_context_menu(self):
        """Disable default context menu."""
        self.chat_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

    # PRD v3 §8.6: 对话内搜索功能
    def _toggle_search(self):
        """Toggle search bar visibility (Ctrl+F)."""
        if self.search_bar.isVisible():
            self._close_search()
        else:
            self.search_bar.setVisible(True)
            self.search_box.setFocus()
            self.search_box.selectAll()

    def _close_search(self):
        """Close search bar and clear search results."""
        self.search_bar.setVisible(False)
        self.search_box.clear()
        self.search_result_label.setText("")
        self._search_matches = []
        self._current_match_index = 0
        # 清除搜索高亮
        self.chat_view.page().runJavaScript("clearSearch()")

    def _search_messages(self):
        """Search messages in current conversation."""
        query = self.search_box.text().strip().lower()
        
        if not query:
            self.search_result_label.setText("")
            self._search_matches = []
            self.chat_view.page().runJavaScript("clearSearch()")
            return
        
        if not self.current_conv:
            self.search_result_label.setText("请先选择一个对话")
            return
        
        # 获取当前对话的所有消息
        messages = self.conv_mgr.get_messages(self.current_conv.id)
        
        # 搜索匹配的消息
        self._search_matches = []
        for i, msg in enumerate(messages):
            if query in msg.content.lower():
                self._search_matches.append({
                    'index': i,
                    'uid': msg.id,
                    'role': msg.role,
                    'preview': msg.content[:100].replace('\n', ' ')
                })
        
        if not self._search_matches:
            self.search_result_label.setText(f"未找到匹配: {query}")
            self.chat_view.page().runJavaScript("clearSearch()")
            return
        
        # 显示结果数量
        self._current_match_index = 0
        self.search_result_label.setText(f"找到 {len(self._search_matches)} 条匹配")
        
        # 在 WebView 中高亮显示匹配
        self._highlight_search_results(query)

    def _highlight_search_results(self, query: str):
        """Highlight search matches in the chat view."""
        # 将所有匹配的消息UID传给JS
        uids = [m['uid'] for m in self._search_matches]
        escaped_query = query.replace("'", "\\'")
        escaped_uids = json.dumps(uids)
        js_code = f"highlightSearch('{escaped_query}', {escaped_uids}, {self._current_match_index})"
        self.chat_view.page().runJavaScript(js_code)

    def _search_next(self):
        """Go to next search match."""
        if not self._search_matches:
            return
        
        self._current_match_index = (self._current_match_index + 1) % len(self._search_matches)
        self.search_result_label.setText(f"匹配 {self._current_match_index + 1}/{len(self._search_matches)}")
        
        # 更新高亮
        query = self.search_box.text().strip().lower()
        if query:
            self._highlight_search_results(query)

    def _search_prev(self):
        """Go to previous search match."""
        if not self._search_matches:
            return
        
        self._current_match_index = (self._current_match_index - 1) % len(self._search_matches)
        self.search_result_label.setText(f"匹配 {self._current_match_index + 1}/{len(self._search_matches)}")
        
        # 更新高亮
        query = self.search_box.text().strip().lower()
        if query:
            self._highlight_search_results(query)

    def _init_client(self):
        default = self.key_manager.get_default_key()
        if default:
            _, key = default
            self.client.configure(key)
            self.statusBar().showMessage("API key loaded")
            log.info("Client initialized with default API key")
        else:
            self.statusBar().showMessage("⚠ No API key configured - open Settings")
            log.warning("No API key found")

    def _on_model_changed(self, index):
        """Handle model switch with cache cost warning."""
        if not self.current_project:
            return
        
        new_model = self.model_combo.currentData()
        new_model_info = MODELS.get(new_model)
        if not new_model_info:
            return
        
        docs = self.doc_processor.get_project_documents(self.current_project.id)
        doc_tokens = sum(d.get('token_count', 0) for d in docs)
        system_tokens = len(self.current_project.system_prompt) // 4
        total_cached = doc_tokens + system_tokens
        
        if total_cached == 0:
            total_cached = 500
        
        recent = db.execute("""
            SELECT cache_read_tokens, cache_creation_tokens 
            FROM api_call_log 
            WHERE project_id = ? AND model_id = ?
            ORDER BY created_at DESC LIMIT 5
        """, (self.current_project.id, new_model))
        
        hit_count = sum(1 for r in recent if r['cache_read_tokens'] > 0)
        
        write_cost = total_cached * new_model_info.input_price * 1.25 / 1_000_000
        read_cost = total_cached * new_model_info.input_price * 0.10 / 1_000_000
        
        if hit_count == 0 and len(recent) == 0:
            msg = (
                f"⚠️ 首次使用 {new_model_info.display_name} — "
                f"Cache冷启动成本约 ${write_cost:.4f} ({total_cached:,} tokens)"
            )
            self.statusBar().setStyleSheet("background: #FFF3CD; color: #856404; font-weight: bold;")
            QTimer.singleShot(5000, lambda: self.statusBar().setStyleSheet(""))
        elif hit_count < 2:
            msg = (
                f"ℹ️ 切换到 {new_model_info.display_name} — "
                f"Cache可能已过期，预期成本 ${write_cost:.4f}，命中后降至 ${read_cost:.4f}"
            )
        else:
            msg = f"✅ 切换到 {new_model_info.display_name} — Cache仍热，文档读取成本仅 ${read_cost:.4f}"
        
        self.statusBar().showMessage(msg, 8000)
        log.info(f"Model switched: {new_model}, cache status: {hit_count}/{len(recent)} hits")

    def _on_thinking_toggled(self, checked: bool):
        if checked:
            self._recommend_thinking_budget()
        else:
            self.thinking_recommend_label.setVisible(False)

    def _recommend_thinking_budget(self):
        """Recommend thinking budget based on input length."""
        if not self.thinking_check.isChecked():
            return
        
        text = self.input_box.toPlainText()
        length = len(text)
        
        if length < 200:
            recommended = 1024
            reason = "短问题，快速推理即可"
        elif length < 1000:
            recommended = 2048
            reason = "中等复杂度，标准分析"
        elif length < 3000:
            recommended = 4096
            reason = "较长内容，建议深度思考"
        else:
            recommended = 8192
            reason = "复杂长文本，需要充分推理"
        
        current = self.thinking_budget.currentData()
        if abs(current - recommended) >= 2048:
            self.thinking_recommend_label.setText(f"💡 建议: {recommended} — {reason}")
            self.thinking_recommend_label.setVisible(True)
        else:
            self.thinking_recommend_label.setVisible(False)

    def _refresh_projects(self):
        self.project_list.clear()
        projects = self.project_mgr.list_all()
        for p in projects:
            item = QListWidgetItem(p.name)
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            self.project_list.addItem(item)

        # 恢复最后选择的项目和对话
        state = _get_app_state()
        last_project_id = state.get("last_project_id")
        last_conversation_id = state.get("last_conversation_id")
        
        # 尝试选中最后项目
        if last_project_id:
            for i in range(self.project_list.count()):
                if self.project_list.item(i).data(Qt.ItemDataRole.UserRole) == last_project_id:
                    self.project_list.setCurrentRow(i)
                    break
            else:
                # 如果没找到，使用第一个项目
                if projects:
                    self.project_list.setCurrentRow(0)
        elif projects and not self.current_project:
            self.project_list.setCurrentRow(0)
        
        # 如果有最后对话ID且当前项目匹配，加载该对话
        if last_conversation_id and self.current_project:
            # 延迟执行，确保对话列表已加载
            QTimer.singleShot(100, lambda: self._restore_last_conversation(last_conversation_id))

    def _new_project(self):
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if ok and name.strip():
            model_id = self.model_combo.currentData()
            project = self.project_mgr.create(name.strip(), model=model_id)
            self._refresh_projects()
            for i in range(self.project_list.count()):
                item = self.project_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == project.id:
                    self.project_list.setCurrentRow(i)
                    break
            log.info("Created project: %s", name)

    def _on_project_selected(self, current, previous):
        if not current:
            return
        pid = current.data(Qt.ItemDataRole.UserRole)
        self.current_project = self.project_mgr.get(pid)
        if not self.current_project:
            return

        self.current_conv = None
        self.system_prompt_edit.setPlainText(self.current_project.system_prompt)
        self._refresh_conversations()
        self._refresh_documents()
        self._update_stats()
        self.statusBar().showMessage(f"Project: {self.current_project.name}")
        log.debug("Selected project: %s", self.current_project.name)
        
        # 保存最后选择的项目ID
        _set_app_state_value("last_project_id", self.current_project.id)

    def _project_context_menu(self, pos):
        item = self.project_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        rename = menu.addAction("Rename")
        delete = menu.addAction("Delete")
        action = menu.exec(self.project_list.mapToGlobal(pos))
        pid = item.data(Qt.ItemDataRole.UserRole)
        if action == rename:
            name, ok = QInputDialog.getText(self, "Rename", "New name:", text=item.text())
            if ok and name.strip():
                self.project_mgr.update(pid, name=name.strip())
                self._refresh_projects()
        elif action == delete:
            if QMessageBox.question(self, "Delete", f"Delete project '{item.text()}'?") == QMessageBox.StandardButton.Yes:
                self.project_mgr.delete(pid)
                self.current_project = None
                self._refresh_projects()

    def _restore_last_conversation(self, conversation_id: str):
        """Restore the last selected conversation by ID."""
        if not self.current_project:
            return
        # 查找并选中指定对话
        for i in range(self.conv_list.count()):
            item = self.conv_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == conversation_id:
                self.conv_list.setCurrentRow(i)
                log.debug("Restored last conversation: %s", conversation_id)
                return
        log.debug("Last conversation not found: %s", conversation_id)

    def _refresh_conversations(self):
        self.conv_list.clear()
        if not self.current_project:
            return
        convs = self.conv_mgr.list_conversations(self.current_project.id)
        for c in convs:
            item = QListWidgetItem(c.title)
            item.setData(Qt.ItemDataRole.UserRole, c.id)
            self.conv_list.addItem(item)

        if convs:
            self.conv_list.setCurrentRow(0)
        else:
            self._clear_chat()

    def _new_conversation(self):
        if not self.current_project:
            QMessageBox.warning(self, "Error", "Select a project first.")
            return
        conv = self.conv_mgr.create_conversation(self.current_project.id)
        self._refresh_conversations()
        for i in range(self.conv_list.count()):
            item = self.conv_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == conv.id:
                self.conv_list.setCurrentRow(i)
                break
        self.input_box.setFocus()

    def _on_conv_selected(self, current, previous):
        if not current:
            self.current_conv = None
            self._clear_chat()
            return
        cid = current.data(Qt.ItemDataRole.UserRole)
        self.current_conv = self.conv_mgr.get_conversation(cid)
        self._load_chat_history()
        self._update_stats()
        log.debug("Selected conversation: %s", self.current_conv.title if self.current_conv else "None")
        
        # 保存最后选择的对话ID
        if self.current_conv:
            _set_app_state_value("last_conversation_id", self.current_conv.id)
            if self.current_project:
                _set_app_state_value("last_project_id", self.current_project.id)

    def _conv_context_menu(self, pos):
        item = self.conv_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        rename = menu.addAction("Rename")
        export = menu.addAction("Export as Markdown")
        delete = menu.addAction("Delete")
        action = menu.exec(self.conv_list.mapToGlobal(pos))
        cid = item.data(Qt.ItemDataRole.UserRole)
        if action == rename:
            name, ok = QInputDialog.getText(self, "Rename", "New title:", text=item.text())
            if ok and name.strip():
                self.conv_mgr.rename_conversation(cid, name.strip())
                self._refresh_conversations()
        elif action == export:
            self._export_conversation(cid)
        elif action == delete:
            if QMessageBox.question(self, "Delete", "Delete this conversation?") == QMessageBox.StandardButton.Yes:
                self.conv_mgr.delete_conversation(cid)
                self.current_conv = None
                self._refresh_conversations()

    def _export_conversation(self, conv_id: str):
        conv = self.conv_mgr.get_conversation(conv_id)
        if not conv:
            return
        messages = self.conv_mgr.get_messages(conv_id)
        stats = self.conv_mgr.get_conversation_stats(conv_id)

        md = f"# {conv.title}\n\n"
        md += f"- Model: {conv.model_override or (self.current_project.default_model if self.current_project else 'N/A')}\n"
        md += f"- Messages: {stats['msg_count']}\n"
        md += f"- Total Cost: ${stats['total_cost']:.4f}\n\n---\n\n"

        for msg in messages:
            role = "**You**" if msg.role == "user" else "**Claude**"
            md += f"## {role}\n\n{msg.content}\n\n"
            if msg.cost_usd:
                md += f"*({msg.input_tokens} in / {msg.output_tokens} out, ${msg.cost_usd:.4f})*\n\n"
            md += "---\n\n"

        path, _ = QFileDialog.getSaveFileName(self, "Export", f"{conv.title}.md", "Markdown (*.md)")
        if path:
            Path(path).write_text(md, encoding="utf-8")
            self.statusBar().showMessage(f"Exported to {path}")

    def _refresh_documents(self):
        self.doc_list.clear()
        if not self.current_project:
            return
        docs = self.doc_processor.get_project_documents(self.current_project.id)
        total_tokens = 0
        for d in docs:
            tc = d.get("token_count", 0)
            total_tokens += tc
            item = QListWidgetItem(f"{d['filename']} ({tc:,} tokens)")
            item.setData(Qt.ItemDataRole.UserRole, d["id"])
            self.doc_list.addItem(item)
        self.doc_tokens_label.setText(f"Documents: {total_tokens:,} tokens total")

    def _upload_document(self):
        if not self.current_project:
            QMessageBox.warning(self, "Error", "Select a project first.")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Upload Documents", "",
            "All Supported (*.pdf *.docx *.txt *.md *.csv *.py *.js *.ts *.json *.xlsx *.xml *.yaml *.yml *.html *.css *.java *.c *.cpp *.go *.rs *.rb *.sql);;All Files (*)",
        )
        for path in paths:
            try:
                result = self.doc_processor.add_document(self.current_project.id, path)
                self.statusBar().showMessage(
                    f"Uploaded: {result['filename']} ({result['token_count']:,} tokens)"
                )
            except Exception as e:
                log.exception("Upload failed: %s", path)
                QMessageBox.warning(self, "Upload Error", f"Failed to process {Path(path).name}: {e}")
        self._refresh_documents()

    def _doc_context_menu(self, pos):
        item = self.doc_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        remove = menu.addAction("Remove")
        action = menu.exec(self.doc_list.mapToGlobal(pos))
        if action == remove:
            doc_id = item.data(Qt.ItemDataRole.UserRole)
            self.doc_processor.remove_document(doc_id)
            self._refresh_documents()

    def _clear_chat(self):
        self.chat_view.setHtml(get_chat_html_template(dark_mode=True))
        self.stats_label.setText("No conversation selected")

    def _load_chat_history(self):
        """Load and display all messages in current conversation."""
        # #region agent log
        self.chat_view.setHtml(get_chat_html_template(dark_mode=True))
        _dlog("main_window.py:689", "setHtml called", {"caller": "load_chat_history"}, "H1")
        # #endregion
        if not self.current_conv:
            return

        messages = self.conv_mgr.get_messages(self.current_conv.id)
        if not messages:
            return
        self._pending_history_messages = messages
        
        # 安全处理信号连接
        self._inject_chat_history_connected = True
        self.chat_view.page().loadFinished.connect(self._inject_chat_history)

    def _inject_chat_history(self, ok: bool):
        """Run after chat page load: inject message history (fixes addMessage not defined)."""
        if not self._pending_history_messages:
            return
        
        # 断开信号连接，避免重复触发
        if getattr(self, '_inject_chat_history_connected', False):
            try:
                self.chat_view.page().loadFinished.disconnect(self._inject_chat_history)
            except (TypeError, RuntimeError):
                pass
            self._inject_chat_history_connected = False
        
        messages = self._pending_history_messages
        self._pending_history_messages = None
        # #region agent log
        _dlog("main_window.py:_inject_chat_history", "runJS addMessage loop after loadFinished", {"msg_count": len(messages), "runId": "post-fix"}, "H1")
        # #endregion
        for msg in messages:
            html = render_markdown(msg.content)
            meta = ""
            if msg.role == "assistant" and msg.cost_usd:
                meta = f"{msg.input_tokens:,} in / {msg.output_tokens:,} out"
                if msg.cache_read_tokens:
                    meta += f" / {msg.cache_read_tokens:,} cached"
                meta += f" | ${msg.cost_usd:.4f}"
            escaped_html = escape_js_string(html)
            escaped_meta = escape_js_string(meta)
            uid = msg.id
            js_code = f"addMessage('{msg.role}', '{escaped_html}', '{escaped_meta}', '{uid}')"
            # #region agent log
            _dlog("main_window.py:718", "runJS addMessage", {"in_load_history": True, "after_load": True, "js_preview": js_code[:80]}, "H1")
            # #endregion
            self.chat_view.page().runJavaScript(js_code)

    def _update_stats(self):
        if not self.current_conv:
            self.stats_label.setText("No conversation selected")
            return
        
        stats = self.conv_mgr.get_conversation_stats(self.current_conv.id)
        
        cache_stats = db.execute("""
            SELECT 
                SUM(CASE WHEN cache_read_tokens > 0 THEN 1 ELSE 0 END) as hits,
                COUNT(*) as total,
                SUM(cache_read_tokens) as total_cache_read,
                SUM(input_tokens) as total_input
            FROM api_call_log 
            WHERE conversation_id = ?
            ORDER BY created_at DESC LIMIT 10
        """, (self.current_conv.id,))
        
        cache_text = ""
        compression_text = ""
        
        # 缓存统计
        if cache_stats and cache_stats[0]['total'] > 0:
            s = cache_stats[0]
            hit_rate = (s['hits'] / s['total']) * 100 if s['total'] > 0 else 0
            cache_savings = s['total_cache_read'] * 0.9 / 1_000_000
            
            cache_text = (
                f"\n---\n"
                f"Cache: {s['hits']}/{s['total']} ({hit_rate:.0f}%)\n"
                f"Saved: ~${cache_savings:.4f}"
            )
        
        # PRD v3: 压缩统计
        if self.current_conv:
            compression_stats = self.conv_mgr.get_compression_stats(self.current_conv.id)
            if compression_stats['has_summary']:
                compression_text = (
                    f"\n---\n"
                    f"摘要: {compression_stats['summary_tokens']:,} tok\n"
                    f"未压缩: {compression_stats['uncompressed_turns']} 轮"
                )
                if compression_stats['should_compress']:
                    compression_text += " ⚡"
        
        txt = (
            f"Messages: {stats['msg_count']}\n"
            f"Input: {stats['total_input']:,} tok\n"
            f"Output: {stats['total_output']:,} tok\n"
            f"Cost: ${stats['total_cost']:.4f}"
            f"{cache_text}"
            f"{compression_text}"
        )
        self.stats_label.setText(txt)
        
        # 更新 4 层缓存可视化
        self._update_cache_visualization()
    
    def _update_cache_visualization(self):
        """更新4层缓存可视化仪表盘"""
        if not self.current_conv:
            self.layer1_label.setText("L1: System+Docs -")
            self.layer2_label.setText("L2: Summary -")
            self.layer3_label.setText("L3: Recent -")
            self.layer4_label.setText("L4: Current -")
            self.total_tokens_label.setText("Total: 0 / 200K")
            return
        
        # 从 context_builder 获取当前层的 token 统计
        from core.context_builder import ContextBuilder
        cb = ContextBuilder()
        
        try:
            # 预估请求
            est = cb.estimate_request(
                project_id=self.current_project.id if self.current_project else "",
                conversation_id=self.current_conv.id,
                user_message="",
                system_prompt=self.current_project.system_prompt if self.current_project else "",
                model_id=self.current_conv.model_override or "claude-sonnet-4-5-20250929"
            )
            
            # 更新各层显示
            sys_tok = est.get("system_tokens", 0)
            sum_tok = est.get("summary_tokens", 0)
            hist_tok = est.get("history_tokens", 0)
            user_tok = est.get("user_tokens", 0)
            total = est.get("total_tokens", 0)
            
            self.layer1_label.setText(f"L1: System+Docs {sys_tok:,} tok")
            self.layer2_label.setText(f"L2: Summary {sum_tok:,} tok")
            self.layer3_label.setText(f"L3: Recent {hist_tok:,} tok")
            self.layer4_label.setText(f"L4: Current {user_tok:,} tok")
            self.total_tokens_label.setText(f"Total: {total:,} / 200K")
            
            # 根据缓存状态改变颜色
            if sum_tok >= 1024:
                self.layer2_label.setStyleSheet("color: #4CAF50; font-size: 11px;")  # 绿色 = 缓存
            else:
                self.layer2_label.setStyleSheet("color: #FF9800; font-size: 11px;")  # 橙色 = 未缓存
                
        except Exception as e:
            log.debug(f"Cache visualization update failed: {e}")

    def _send_message(self):
        if self.is_streaming:
            return
        text = self.input_box.toPlainText().strip()
        if not text:
            return
        if not self.current_project:
            QMessageBox.warning(self, "Error", "Select a project first.")
            return
        if not self.client.is_configured:
            QMessageBox.warning(self, "Error", "No API key configured. Open Settings.")
            return

        if not self.current_conv:
            self._new_conversation()
            if not self.current_conv:
                return

        messages = self.conv_mgr.get_messages(self.current_conv.id)
        if not messages:
            title = text[:50] + ("..." if len(text) > 50 else "")
            self.conv_mgr.rename_conversation(self.current_conv.id, title)
            self._refresh_conversations()

        attachments = self.pending_attachments.copy()
        self.conv_mgr.add_message(
            self.current_conv.id, "user", text,
            attachments=[{"type": a["type"], "filename": a.get("filename", "")} for a in attachments],
        )

        text_for_api = self._expand_uid_refs_in_message(text)

        user_html = render_markdown(text)
        escaped = user_html.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        # #region agent log
        _dlog("main_window.py:792", "runJS addMessage (send)", {"in_load_history": False, "escaped_len": len(escaped)}, "H2")
        # #endregion
        
        # 确保 HTML 已加载后再添加消息 (修复新对话首条消息不显示问题)
        js_code = f"""
            (function() {{
                if (typeof addMessage === 'function' && document.getElementById('chat')) {{
                    addMessage('user', '{escaped}', '');
                }} else {{
                    setTimeout(function() {{
                        addMessage('user', '{escaped}', '');
                    }}, 100);
                }}
            }})();
        """
        self.chat_view.page().runJavaScript(js_code)

        self.input_box.clear()
        self.pending_attachments.clear()

        model_id = self.model_combo.currentData()
        try:
            system_content, api_messages, est_tokens = self.context_builder.build(
                project_id=self.current_project.id,
                conversation_id=self.current_conv.id,
                user_message=text_for_api,
                system_prompt=self.current_project.system_prompt,
                model_id=model_id,
                user_attachments=attachments,
            )
        except Exception as e:
            log.exception("Failed to build context")
            # #region agent log
            err_s = str(e)
            _dlog("main_window.py:808", "runJS addError (context build)", {"exception_has_quote": "'" in err_s, "err_preview": err_s[:60]}, "H3")
            # #endregion
            escaped_err = escape_js_string(err_s)
            self.chat_view.page().runJavaScript(f"addError('Context build error: {escaped_err}')")
            return

        thinking_cfg = None
        if self.thinking_check.isChecked():
            budget = int(self.thinking_budget.currentText())
            thinking_cfg = {"type": "enabled", "budget_tokens": budget}

        self.is_streaming = True
        self.btn_send.setText("Stop")
        self.btn_send.setStyleSheet("QPushButton { background: #E74C3C; color: white; border-radius: 6px; font-weight: bold; }")
        self.btn_send.clicked.disconnect()
        self.btn_send.clicked.connect(self._cancel_streaming)
        self.statusBar().showMessage(f"Streaming... (~{est_tokens:,} input tokens)")
        self._accumulated_thinking = ""

        self.chat_view.page().runJavaScript("startStreaming()")

        self.worker = APIWorker(
            self.client, api_messages, system_content,
            model_id, 8192, thinking_cfg,
            project_id=self.current_project.id,
            conversation_id=self.current_conv.id,
        )
        self.worker.text_delta.connect(self._on_text_delta)
        self.worker.thinking_delta.connect(self._on_thinking_delta)
        self.worker.finished.connect(self._on_stream_finished)
        self.worker.error.connect(self._on_stream_error)
        self.worker.start()

    @Slot(str)
    def _on_text_delta(self, full_text: str):
        html = render_markdown(full_text)
        escaped = html.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        self.chat_view.page().runJavaScript(f"appendStreamText('{escaped}')")

    @Slot(str)
    def _on_thinking_delta(self, text: str):
        self._accumulated_thinking += text

    @Slot(str, str, object)
    def _on_stream_finished(self, full_text: str, thinking_text: str, usage):
        self.is_streaming = False
        self._reset_send_button()

        model_id = self.model_combo.currentData()
        cost = 0.0
        meta = ""
        msg_uid = ""

        if isinstance(usage, UsageInfo):
            cost = self.token_tracker.calculate_cost(model_id, usage)
            meta = f"{usage.input_tokens:,} in / {usage.output_tokens:,} out"
            if usage.cache_read_tokens:
                meta += f" / {usage.cache_read_tokens:,} cached"
            meta += f" | ${cost:.4f}"

        if thinking_text.strip():
            thinking_html = render_markdown(thinking_text)
            escaped_thinking = escape_js_string(thinking_html)
            self.chat_view.page().runJavaScript(f"addThinking('{escaped_thinking}')")

        final_html = render_markdown(full_text)
        escaped = escape_js_string(final_html)
        escaped_meta = escape_js_string(meta)
        escaped_raw = escape_js_string(full_text)  # 原始 Markdown

        if self.current_conv and full_text.strip():
            msg = self.conv_mgr.add_message(
                self.current_conv.id, "assistant", full_text,
                thinking_content=thinking_text,
                model_used=model_id,
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                cache_read_tokens=usage.cache_read_tokens if usage else 0,
                cache_creation_tokens=usage.cache_creation_tokens if usage else 0,
                cost_usd=cost,
            )
            msg_uid = msg.id
            js_code = f"finishStreaming('{escaped}', '{escaped_meta}', '{msg_uid}', '{escaped_raw}')"
            self.chat_view.page().runJavaScript(js_code)

        self._update_stats()
        self.statusBar().showMessage(f"Done | UID: {msg_uid[:8]}" if msg_uid else "Done")
        log.info("Response complete: %s", meta)
        
        # PRD v3: 触发后台压缩 (异步)
        self._trigger_compression()

    def _trigger_compression(self):
        """
        触发后台压缩 (PRD v3 核心功能)
        
        在用户收到回复后异步执行，不阻塞主流程
        """
        if not self.current_conv or not self.current_project:
            return
        
        compressor = ContextCompressor()
        
        # 检查是否需要压缩
        if not compressor.should_compress(self.current_conv.id):
            return
        
        # 显示压缩开始状态
        self.statusBar().showMessage("正在整理历史记忆... (Haiku)", 3000)
        log.info("Starting background compression for conversation %s", self.current_conv.id[:8])
        
        # 在后台线程执行压缩
        self.compression_worker = CompressionWorker(
            conversation_id=self.current_conv.id,
            project_name=self.current_project.name,
        )
        self.compression_worker.run()  # 同步执行（因为 Haiku 很快）
        
        result = self.compression_worker._result if hasattr(self.compression_worker, '_result') else None
        
        if result and result.success:
            saved = result.tokens_saved
            self.statusBar().showMessage(
                f"历史记忆已更新，节省 {saved:,} tokens" if saved > 0 else "历史记忆已更新",
                5000
            )
            log.info("Compression complete: saved %d tokens", saved)
        else:
            error_msg = result.error if result else "Unknown error"
            self.statusBar().setStyleSheet("background: #FFF3CD; color: #856404; font-weight: bold;")
            self.statusBar().showMessage(f"⚠ 压缩服务不可用，正在使用全量上下文", 8000)
            QTimer.singleShot(8000, lambda: self.statusBar().setStyleSheet(""))
            log.warning("Compression failed: %s", error_msg)
        
        self.compression_worker = None

    @Slot(str)
    def _on_stream_error(self, error_msg: str):
        self.is_streaming = False
        self._reset_send_button()
        escaped = escape_js_string(error_msg)
        # #region agent log
        _dlog("main_window.py:902", "runJS addError (stream)", {"error_has_quote": "'" in error_msg, "has_newline": "\n" in error_msg}, "H3")
        # #endregion
        self.chat_view.page().runJavaScript(f"addError('{escaped}')")
        self.statusBar().showMessage(f"Error: {error_msg}")
        log.error("Stream error: %s", error_msg)

    def _cancel_streaming(self):
        if self.worker and self.is_streaming:
            self.worker.cancel()
            self.statusBar().showMessage("Cancelled")

    def _reset_send_button(self):
        self.btn_send.setText("Send")
        self.btn_send.setStyleSheet("QPushButton { background: #D97706; color: white; border-radius: 6px; font-weight: bold; }")
        try:
            self.btn_send.clicked.disconnect()
        except RuntimeError:
            pass
        self.btn_send.clicked.connect(self._send_message)

    def _attach_files(self):
        all_supported = (
            "*.png *.jpg *.jpeg *.gif *.webp *.pdf *.txt *.md *.markdown "
            "*.doc *.docx *.xlsx *.xls *.csv *.json *.html *.rtf"
        )
        filter_str = (
            f"All supported ({all_supported});;"
            "Images (*.png *.jpg *.jpeg *.gif *.webp);;"
            "PDF (*.pdf);;"
            "Text / Markdown (*.txt *.md *.markdown);;"
            "Word (*.doc *.docx);;"
            "Excel (*.xlsx *.xls);;"
            "CSV (*.csv);;"
            "Other (*.json *.html *.rtf);;"
            "All Files (*)"
        )
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Attach Files", "", filter_str,
        )
        image_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp")
        image_media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                       ".gif": "image/gif", ".webp": "image/webp"}
        doc_media = {
            ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",
            ".markdown": "text/markdown", ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel", ".csv": "text/csv",
            ".json": "application/json", ".html": "text/html", ".rtf": "application/rtf",
        }
        for path in paths:
            try:
                data = Path(path).read_bytes()
            except OSError as e:
                QMessageBox.warning(self, "Attach Error", f"Cannot read file: {e}")
                continue
            b64 = base64.b64encode(data).decode()
            ext = Path(path).suffix.lower()
            name = Path(path).name
            if ext in image_exts:
                self.pending_attachments.append({
                    "type": "image",
                    "data": b64,
                    "media_type": image_media.get(ext, "image/png"),
                    "filename": name,
                })
            elif ext in doc_media:
                self.pending_attachments.append({
                    "type": "document",
                    "data": b64,
                    "media_type": doc_media[ext],
                    "filename": name,
                })
            else:
                self.statusBar().showMessage(f"Unsupported file type: {ext}", 3000)
        self._update_attachment_ui()

    def _expand_uid_refs_in_message(self, text: str) -> str:
        """Expand only @#uid references (explicit ref syntax) into message content for the LLM.
        Plain #hex in pasted text is NOT expanded, to avoid false matches."""
        if not self.current_conv or not text:
            return text
        # Only match explicit reference syntax: @#uid (8 hex or full UUID)
        refs = re.findall(
            r"@#([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})?)",
            text,
        )
        refs = list(dict.fromkeys(refs))
        if not refs:
            return text
        messages = self.conv_mgr.get_messages(self.current_conv.id)
        id_to_msg = {m.id: m for m in messages}
        parts = ["【以下为用户通过 @#uid 引用的消息原文，供参考】"]
        for ref in refs:
            msg = id_to_msg.get(ref)
            if not msg and len(ref) == 8:
                for mid, m in id_to_msg.items():
                    if mid.startswith(ref) or mid.replace("-", "").startswith(ref):
                        msg = m
                        break
            if msg:
                parts.append(f"【消息 @#{ref[:8]}】\n{msg.content}")
        if len(parts) <= 1:
            return text
        parts.append("【用户当前问题】")
        parts.append(text)
        return "\n\n".join(parts)

    def _clear_attachments(self):
        self.pending_attachments.clear()
        self._update_attachment_ui()

    def _remove_attachment(self, index: int):
        if 0 <= index < len(self.pending_attachments):
            self.pending_attachments.pop(index)
            self._update_attachment_ui()

    def _update_attachment_ui(self):
        while self.attach_list_layout.count():
            item = self.attach_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, att in enumerate(self.pending_attachments):
            name = att.get("filename", "?")
            chip = QFrame()
            chip.setStyleSheet("QFrame { background: #3A3A3A; border-radius: 4px; padding: 2px 6px; }")
            chip_layout = QHBoxLayout(chip)
            chip_layout.setContentsMargins(6, 2, 2, 2)
            chip_layout.setSpacing(4)
            lbl = QLabel(name)
            lbl.setStyleSheet("color: #CCC; font-size: 11px; max-width: 200px;")
            lbl.setToolTip(name)
            lbl.setWordWrap(False)
            chip_layout.addWidget(lbl)
            btn = QPushButton("\u00D7")
            btn.setFixedSize(22, 22)
            btn.setStyleSheet(
                "QPushButton { color: #AAA; font-size: 16px; font-weight: bold; "
                "background: transparent; border: 1px solid #555; border-radius: 4px; } "
                "QPushButton:hover { color: #E74C3C; border-color: #E74C3C; background: #3A2020; }"
            )
            btn.setToolTip("Remove this file")
            idx = i
            btn.clicked.connect(lambda checked=False, idx=idx: self._remove_attachment(idx))
            chip_layout.addWidget(btn)
            self.attach_list_layout.addWidget(chip)

    def _save_system_prompt(self):
        if not self.current_project:
            return
        prompt = self.system_prompt_edit.toPlainText()
        self.project_mgr.update(self.current_project.id, system_prompt=prompt)
        self.current_project.system_prompt = prompt
        self.statusBar().showMessage("System prompt saved")
        log.info("Saved system prompt for project %s", self.current_project.name)

    def _open_settings(self):
        dlg = SettingsDialog(self.client, self)
        dlg.settings_changed.connect(self._on_settings_changed)
        dlg.exec()

    def _on_settings_changed(self):
        # PRD v3 §8.5: 主题切换支持
        from utils.theme_manager import LIGHT_THEME, DARK_THEME
        import json
        from pathlib import Path
        
        # 重新加载主题
        try:
            theme_file = Path.home() / "ClaudeStation" / "theme_config.json"
            if theme_file.exists():
                with open(theme_file, "r", encoding="utf-8") as f:
                    theme_data = json.load(f)
                    theme_mode = theme_data.get("mode", "dark")
                    
                    # 获取 QApplication 实例
                    from PySide6.QtWidgets import QApplication
                    app = QApplication.instance()
                    
                    if theme_mode == "light":
                        app.setStyleSheet(LIGHT_THEME)
                    else:
                        app.setStyleSheet(DARK_THEME)
        except Exception as e:
            log.warning(f"Failed to apply theme: {e}")
        
        self._init_client()
        self.statusBar().showMessage("Settings updated")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        from data.database import db
        db.close()
        log.info("Application closed")
        event.accept()



