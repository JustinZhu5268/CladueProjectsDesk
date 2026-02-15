"""Main application window with three-panel layout."""
from __future__ import annotations
from utils.markdown_renderer import render_markdown, get_chat_html_template, escape_js_string
import os
import sys
import base64
import logging
from pathlib import Path
from functools import partial

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

from config import (
    APP_NAME, APP_VERSION, MODELS, DEFAULT_MODEL,
    SIDEBAR_WIDTH, RIGHT_PANEL_WIDTH, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
)
from core.project_manager import ProjectManager, Project
from core.conversation_manager import ConversationManager, Conversation, Message
from core.document_processor import DocumentProcessor
from core.context_builder import ContextBuilder
from core.token_tracker import TokenTracker, UsageInfo
from api.claude_client import ClaudeClient, StreamEvent
from utils.key_manager import KeyManager
from utils.markdown_renderer import render_markdown, get_chat_html_template
from ui.settings_dialog import SettingsDialog
from data.database import db

log = logging.getLogger(__name__)


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
        self.is_streaming = False
        self._accumulated_thinking = ""

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

        top_bar = QFrame()
        top_bar.setStyleSheet("""
            QFrame { 
                background: #252525; 
                border-bottom: 1px solid #3A3A3A; 
                padding: 4px; 
            }
            QLabel { color: #AAAAAA; font-size: 13px; }
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

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)

        proj_header = QHBoxLayout()
        proj_header.addWidget(QLabel(" **Projects**"))
        btn_new_proj = QPushButton("+")
        btn_new_proj.setFixedSize(28, 28)
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
        btn_new_conv = QPushButton("+")
        btn_new_conv.setFixedSize(28, 28)
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
        self.chat_view.setHtml(get_chat_html_template(dark_mode=True))
        center_layout.addWidget(self.chat_view, 1)

        input_frame = QFrame()
        input_frame.setStyleSheet("""
            QFrame { 
                background: #252525; 
                border-top: 1px solid #3A3A3A; 
            }
        """)
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(12, 8, 12, 8)

        self.token_label = QLabel("")
        self.token_label.setStyleSheet("color: #999; font-size: 11px;")
        input_layout.addWidget(self.token_label)

        input_row = QHBoxLayout()
        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText("Type your message... (Ctrl+Enter to send)")
        self.input_box.setMaximumHeight(120)
        self.input_box.setAcceptRichText(False)
        self.input_box.textChanged.connect(self._recommend_thinking_budget)
        input_row.addWidget(self.input_box, 1)

        btn_col = QVBoxLayout()
        self.btn_attach = QPushButton("📎")
        self.btn_attach.setFixedSize(36, 36)
        self.btn_attach.setToolTip("Attach image")
        self.btn_attach.clicked.connect(self._attach_image)
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

        right_layout.addStretch()

        right_panel.setFixedWidth(RIGHT_PANEL_WIDTH)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        main_layout.addWidget(splitter, 1)

        self.statusBar().showMessage("Ready")
        self.pending_attachments: list[dict] = []

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self._send_message)
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self._new_conversation)
        QShortcut(QKeySequence("Ctrl+Shift+N"), self).activated.connect(self._new_project)
        QShortcut(QKeySequence("Ctrl+,"), self).activated.connect(self._open_settings)
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self.input_box.setFocus)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._cancel_streaming)
    
    def _setup_context_menu(self):
        """Setup context menu for chat view to copy UID."""
        self.chat_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chat_view.customContextMenuRequested.connect(self._chat_context_menu)
    
    def _chat_context_menu(self, pos):
        """Show context menu in chat area."""
        js_code = f"""
            (function() {{
                var el = document.elementFromPoint({pos.x()}, {pos.y()});
                if (!el) return null;
                var msg = el.closest('.message');
                return msg ? msg.id : null;
            }})()
        """
        self.chat_view.page().runJavaScript(js_code, self._show_chat_menu_callback)
    
    def _show_chat_menu_callback(self, element_id):
        """Callback with element ID."""
        if not element_id or not element_id.startswith('msg-'):
            return
        
        uid = element_id.replace('msg-', '')
        menu = QMenu(self)
        
        copy_action = menu.addAction(f"复制UID: {uid[:8]}...")
        copy_action.triggered.connect(lambda: self._copy_uid_to_clipboard(uid))
        
        menu.exec(QCursor.pos())
    
    def _copy_uid_to_clipboard(self, uid: str):
        """Copy UID to system clipboard."""
        clipboard = QApplication.clipboard()
        clipboard.setText(uid)
        self.statusBar().showMessage(f"已复制UID: {uid}", 3000)

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

        if projects and not self.current_project:
            self.project_list.setCurrentRow(0)

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
        self.token_label.setText("")

    def _load_chat_history(self):
        """Load and display all messages in current conversation."""
        self.chat_view.setHtml(get_chat_html_template(dark_mode=True))
        if not self.current_conv:
            return

        messages = self.conv_mgr.get_messages(self.current_conv.id)
        for msg in messages:
            html = render_markdown(msg.content)
            meta = ""
            
            if msg.role == "assistant" and msg.cost_usd:
                meta = f"{msg.input_tokens:,} in / {msg.output_tokens:,} out"
                if msg.cache_read_tokens:
                    meta += f" / {msg.cache_read_tokens:,} cached"
                meta += f" | ${msg.cost_usd:.4f}"
            
            # 使用新的转义函数
            escaped_html = escape_js_string(html)
            escaped_meta = escape_js_string(meta)
            uid = msg.id
            
            js_code = f"addMessage('{msg.role}', '{escaped_html}', '{escaped_meta}', '{uid}')"
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
        if cache_stats and cache_stats[0]['total'] > 0:
            s = cache_stats[0]
            hit_rate = (s['hits'] / s['total']) * 100 if s['total'] > 0 else 0
            cache_savings = s['total_cache_read'] * 0.9 / 1_000_000
            
            cache_text = (
                f"\n---\n"
                f"Cache: {s['hits']}/{s['total']} ({hit_rate:.0f}%)\n"
                f"Saved: ~${cache_savings:.4f}"
            )
        
        txt = (
            f"Messages: {stats['msg_count']}\n"
            f"Input: {stats['total_input']:,} tok\n"
            f"Output: {stats['total_output']:,} tok\n"
            f"Cost: ${stats['total_cost']:.4f}"
            f"{cache_text}"
        )
        self.stats_label.setText(txt)

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

        user_html = render_markdown(text)
        escaped = user_html.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        self.chat_view.page().runJavaScript(f"addMessage('user', '{escaped}', '')")

        self.input_box.clear()
        self.pending_attachments.clear()

        model_id = self.model_combo.currentData()
        try:
            system_content, api_messages, est_tokens = self.context_builder.build(
                project_id=self.current_project.id,
                conversation_id=self.current_conv.id,
                user_message=text,
                system_prompt=self.current_project.system_prompt,
                model_id=model_id,
                user_attachments=attachments,
            )
        except Exception as e:
            log.exception("Failed to build context")
            self.chat_view.page().runJavaScript(f"addError('Context build error: {str(e)}')")
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

        if self.current_conv and full_text.strip():
            msg_id = self.conv_mgr.add_message(
                self.current_conv.id, "assistant", full_text,
                thinking_content=thinking_text,
                model_used=model_id,
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                cache_read_tokens=usage.cache_read_tokens if usage else 0,
                cache_creation_tokens=usage.cache_creation_tokens if usage else 0,
                cost_usd=cost,
            )
            msg_uid = str(msg_id)
            
            js_code = f"finishStreaming('{escaped}', '{escaped_meta}', '{msg_uid}')"
            self.chat_view.page().runJavaScript(js_code)

        self._update_stats()
        self.statusBar().showMessage(f"Done | UID: {msg_uid[:8]}" if msg_uid else "Done")
        log.info("Response complete: %s", meta)

    @Slot(str)
    def _on_stream_error(self, error_msg: str):
        self.is_streaming = False
        self._reset_send_button()
        escaped = error_msg.replace("\\", "\\\\").replace("'", "\\'")
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

    def _attach_image(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Attach Images", "",
            "Images (*.png *.jpg *.jpeg *.gif *.webp);;All Files (*)",
        )
        for path in paths:
            data = Path(path).read_bytes()
            b64 = base64.b64encode(data).decode()
            ext = Path(path).suffix.lower()
            media_map = {".png": "image/png", ".jpg": "image/jpeg",
                         ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
            self.pending_attachments.append({
                "type": "image",
                "data": b64,
                "media_type": media_map.get(ext, "image/png"),
                "filename": Path(path).name,
            })
        if self.pending_attachments:
            names = ", ".join(a.get("filename", "?") for a in self.pending_attachments)
            self.token_label.setText(f"📎 Attached: {names}")

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



