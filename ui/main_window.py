"""Main application window with three-panel layout."""
from __future__ import annotations

import os
import sys
import base64
import asyncio
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

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# API Worker Thread
# ═══════════════════════════════════════════════════════

class APIWorker(QThread):
    """Background thread for API calls."""
    text_delta = Signal(str)        # streaming text
    thinking_delta = Signal(str)    # streaming thinking
    finished = Signal(str, str, object)  # full_text, thinking_text, UsageInfo
    error = Signal(str)

    def __init__(self, client: ClaudeClient, messages: list, system: list,
                 model: str, max_tokens: int, thinking: dict | None = None):
        super().__init__()
        self.client = client
        self.messages = messages
        self.system = system
        self.model = model
        self.max_tokens = max_tokens
        self.thinking_cfg = thinking
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


# ═══════════════════════════════════════════════════════
# Main Window
# ═══════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    """Three-panel main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.resize(1300, 800)

        # Core managers
        self.project_mgr = ProjectManager()
        self.conv_mgr = ConversationManager()
        self.doc_processor = DocumentProcessor()
        self.context_builder = ContextBuilder()
        self.token_tracker = TokenTracker()
        self.key_manager = KeyManager()
        self.client = ClaudeClient()

        # State
        self.current_project: Project | None = None
        self.current_conv: Conversation | None = None
        self.worker: APIWorker | None = None
        self.is_streaming = False
        self._accumulated_thinking = ""

        self._build_ui()
        self._setup_shortcuts()
        self._init_client()
        self._refresh_projects()

        log.info("Main window initialized")

    # ── UI Construction ────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Top Bar ────────────────────────────
                # ── Top Bar ────────────────────────────
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
        # 在self.model_combo创建后添加：
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(280)

        # 确保MODELS已导入并检查
        if not MODELS:
            log.error("MODELS is empty!")
            self.model_combo.addItem("Error: No models", "none")
        else:
            for mid, minfo in MODELS.items():
                display_text = f"{minfo.display_name} ${minfo.input_price}/${minfo.output_price}"
                self.model_combo.addItem(display_text, mid)
                log.debug(f"Added model: {display_text}")

        # 显式设置当前索引
        idx = self.model_combo.findData(DEFAULT_MODEL)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        else:
            self.model_combo.setCurrentIndex(0)
            
        for mid, minfo in MODELS.items():
            self.model_combo.addItem(
                f"{minfo.display_name}  ${minfo.input_price}/${minfo.output_price}",
                mid,
            )
        # Default to Sonnet 4.5
        idx = list(MODELS.keys()).index(DEFAULT_MODEL) if DEFAULT_MODEL in MODELS else 0
        self.model_combo.setCurrentIndex(idx)
        top_layout.addWidget(self.model_combo)

        top_layout.addSpacing(20)

        self.thinking_check = QCheckBox("Extended Thinking")
        top_layout.addWidget(self.thinking_check)

        top_layout.addWidget(QLabel("Budget:"))
        self.thinking_budget = QComboBox()
        self.thinking_budget.addItems(["1024", "2048", "4096", "8192", "16384"])
        self.thinking_budget.setCurrentIndex(2)
        self.thinking_budget.setEnabled(False)
        self.thinking_check.toggled.connect(self.thinking_budget.setEnabled)
        top_layout.addWidget(self.thinking_budget)

        top_layout.addStretch()

        btn_settings = QPushButton("Settings")
        btn_settings.clicked.connect(self._open_settings)
        top_layout.addWidget(btn_settings)

        main_layout.addWidget(top_bar)

        # ── Three Panels ───────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # LEFT: Sidebar
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)

        # Projects section
        proj_header = QHBoxLayout()
        proj_header.addWidget(QLabel("<b>Projects</b>"))
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

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        left_layout.addWidget(sep)

        # Conversations section
        conv_header = QHBoxLayout()
        conv_header.addWidget(QLabel("<b>Conversations</b>"))
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

        # CENTER: Chat
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self.chat_view = QWebEngineView()
        self.chat_view.setHtml(get_chat_html_template())
        center_layout.addWidget(self.chat_view, 1)

        # Input area
                # Input area
        input_frame = QFrame()
        input_frame.setStyleSheet("""
            QFrame { 
                background: #252525; 
                border-top: 1px solid #3A3A3A; 
            }
        """)
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(12, 8, 12, 8)

        # Token estimate
        self.token_label = QLabel("")
        self.token_label.setStyleSheet("color: #999; font-size: 11px;")
        input_layout.addWidget(self.token_label)

        input_row = QHBoxLayout()
        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText("Type your message... (Ctrl+Enter to send)")
        self.input_box.setMaximumHeight(120)
        self.input_box.setAcceptRichText(False)
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

        # RIGHT: Project Details Panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        right_layout.addWidget(QLabel("<b>System Prompt</b>"))
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

        # Documents
        doc_header = QHBoxLayout()
        doc_header.addWidget(QLabel("<b>Documents</b>"))
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

        # Stats
        right_layout.addWidget(QLabel("<b>Token Stats</b>"))
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

        # ── Status Bar ─────────────────────────
        self.statusBar().showMessage("Ready")

        # ── Pending attachments ────────────────
        self.pending_attachments: list[dict] = []

    def _setup_shortcuts(self):
        """Configure keyboard shortcuts."""
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self._send_message)
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self._new_conversation)
        QShortcut(QKeySequence("Ctrl+Shift+N"), self).activated.connect(self._new_project)
        QShortcut(QKeySequence("Ctrl+,"), self).activated.connect(self._open_settings)
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self.input_box.setFocus)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._cancel_streaming)

    # ── Initialization ─────────────────────────────────

    def _init_client(self):
        """Initialize API client with stored key."""
        default = self.key_manager.get_default_key()
        if default:
            _, key = default
            self.client.configure(key)
            self.statusBar().showMessage("API key loaded")
            log.info("Client initialized with default API key")
        else:
            self.statusBar().showMessage("⚠ No API key configured - open Settings")
            log.warning("No API key found")

    # ── Project Management ─────────────────────────────

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
            # Select the new project
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

    # ── Conversation Management ────────────────────────

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
        """Export a conversation as markdown."""
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

    # ── Document Management ────────────────────────────

    def _refresh_documents(self):
        self.doc_list.clear()
        if not self.current_project:
            return
        docs = self.doc_processor.get_project_documents(self.current_project.id)
        total_tokens = 0
        for d in docs:
            tc = d.get("token_count", 0)
            total_tokens += tc
            item = QListWidgetItem(f"{d['filename']}  ({tc:,} tokens)")
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

    # ── Chat Display ───────────────────────────────────

    def _clear_chat(self):
        self.chat_view.setHtml(get_chat_html_template())
        self.stats_label.setText("No conversation selected")
        self.token_label.setText("")

    def _load_chat_history(self):
        """Load and display all messages in current conversation."""
        # 强制使用暗黑模式模板
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
                meta += f" | {self.token_tracker.format_cost(msg.cost_usd)}"

            escaped_html = html.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
            escaped_meta = meta.replace("'", "\\'")
            self.chat_view.page().runJavaScript(
                f"addMessage('{msg.role}', '{escaped_html}', '{escaped_meta}')"
            )

    def _update_stats(self):
        """Update the stats panel."""
        if not self.current_conv:
            self.stats_label.setText("No conversation selected")
            return
        stats = self.conv_mgr.get_conversation_stats(self.current_conv.id)
        txt = (
            f"Messages: {stats['msg_count']}\n"
            f"Input tokens: {stats['total_input']:,}\n"
            f"Output tokens: {stats['total_output']:,}\n"
            f"Cache reads: {stats['total_cache_read']:,}\n"
            f"Total cost: {self.token_tracker.format_cost(stats['total_cost'])}"
        )
        self.stats_label.setText(txt)

    # ── Message Sending ────────────────────────────────

    def _send_message(self):
        """Send user message and start streaming response."""
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

        # Auto-create conversation if needed
        if not self.current_conv:
            self._new_conversation()
            if not self.current_conv:
                return

        # Auto-title from first message
        messages = self.conv_mgr.get_messages(self.current_conv.id)
        if not messages:
            title = text[:50] + ("..." if len(text) > 50 else "")
            self.conv_mgr.rename_conversation(self.current_conv.id, title)
            self._refresh_conversations()

        # Save user message
        attachments = self.pending_attachments.copy()
        self.conv_mgr.add_message(
            self.current_conv.id, "user", text,
            attachments=[{"type": a["type"], "filename": a.get("filename", "")} for a in attachments],
        )

        # Display user message
        user_html = render_markdown(text)
        escaped = user_html.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        self.chat_view.page().runJavaScript(f"addMessage('user', '{escaped}', '')")

        self.input_box.clear()
        self.pending_attachments.clear()

        # Build API request
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

        # Thinking config
        thinking_cfg = None
        if self.thinking_check.isChecked():
            budget = int(self.thinking_budget.currentText())
            thinking_cfg = {"type": "enabled", "budget_tokens": budget}

        # Start streaming
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
        )
        self.worker.text_delta.connect(self._on_text_delta)
        self.worker.thinking_delta.connect(self._on_thinking_delta)
        self.worker.finished.connect(self._on_stream_finished)
        self.worker.error.connect(self._on_stream_error)
        self.worker.start()

    @Slot(str)
    def _on_text_delta(self, full_text: str):
        """Handle streaming text update."""
        html = render_markdown(full_text)
        escaped = html.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        self.chat_view.page().runJavaScript(f"appendStreamText('{escaped}')")

    @Slot(str)
    def _on_thinking_delta(self, text: str):
        """Handle streaming thinking update."""
        self._accumulated_thinking += text

    @Slot(str, str, object)
    def _on_stream_finished(self, full_text: str, thinking_text: str, usage):
        """Handle stream completion."""
        self.is_streaming = False
        self._reset_send_button()

        model_id = self.model_combo.currentData()
        cost = 0.0
        meta = ""

        if isinstance(usage, UsageInfo):
            cost = self.token_tracker.calculate_cost(model_id, usage)
            meta = f"{usage.input_tokens:,} in / {usage.output_tokens:,} out"
            if usage.cache_read_tokens:
                meta += f" / {usage.cache_read_tokens:,} cached"
            meta += f" | {self.token_tracker.format_cost(cost)}"

        # Show thinking if any
        if thinking_text.strip():
            thinking_html = render_markdown(thinking_text)
            escaped_thinking = thinking_html.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
            self.chat_view.page().runJavaScript(f"addThinking('{escaped_thinking}')")

        # Finalize streaming message
        final_html = render_markdown(full_text)
        escaped = final_html.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        escaped_meta = meta.replace("'", "\\'")
        self.chat_view.page().runJavaScript(f"finishStreaming('{escaped}', '{escaped_meta}')")

        # Save assistant message
        if self.current_conv and full_text.strip():
            self.conv_mgr.add_message(
                self.current_conv.id, "assistant", full_text,
                thinking_content=thinking_text,
                model_used=model_id,
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                cache_read_tokens=usage.cache_read_tokens if usage else 0,
                cache_creation_tokens=usage.cache_creation_tokens if usage else 0,
                cost_usd=cost,
            )

        self._update_stats()
        self.statusBar().showMessage(f"Done | {meta}" if meta else "Done")
        log.info("Response complete: %s", meta)

    @Slot(str)
    def _on_stream_error(self, error_msg: str):
        """Handle streaming error."""
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

    # ── Attachments ────────────────────────────────────

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

    # ── System Prompt ──────────────────────────────────

    def _save_system_prompt(self):
        if not self.current_project:
            return
        prompt = self.system_prompt_edit.toPlainText()
        self.project_mgr.update(self.current_project.id, system_prompt=prompt)
        self.current_project.system_prompt = prompt
        self.statusBar().showMessage("System prompt saved")
        log.info("Saved system prompt for project %s", self.current_project.name)

    # ── Settings ───────────────────────────────────────

    def _open_settings(self):
        dlg = SettingsDialog(self.client, self)
        dlg.settings_changed.connect(self._on_settings_changed)
        dlg.exec()

    def _on_settings_changed(self):
        self._init_client()
        self.statusBar().showMessage("Settings updated")

    # ── Cleanup ────────────────────────────────────────

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        from data.database import db
        db.close()
        log.info("Application closed")
        event.accept()
