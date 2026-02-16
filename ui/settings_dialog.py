"""Settings dialog for API keys, proxy, and preferences."""
from __future__ import annotations

import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QComboBox, QListWidget,
    QListWidgetItem, QMessageBox, QGroupBox, QFormLayout,
    QCheckBox,
)
from PySide6.QtCore import Qt, Signal

from config import MODELS, DEFAULT_MODEL, CACHE_TTL_DEFAULT, CACHE_TTL_1H
from utils.key_manager import KeyManager
from api.claude_client import ClaudeClient

log = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Application settings dialog."""

    settings_changed = Signal()

    def __init__(self, client: ClaudeClient, parent=None):
        super().__init__(parent)
        self.client = client
        self.key_manager = KeyManager()
        self.setWindowTitle("Settings")
        self.setMinimumWidth(550)
        self.setMinimumHeight(450)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # ── API Keys Tab ───────────────────────
        api_tab = QWidget()
        api_layout = QVBoxLayout(api_tab)

        # Key list
        api_layout.addWidget(QLabel("API Key Profiles:"))
        self.key_list = QListWidget()
        api_layout.addWidget(self.key_list)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Add Key")
        self.btn_add.clicked.connect(self._add_key)
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.clicked.connect(self._remove_key)
        self.btn_default = QPushButton("Set Default")
        self.btn_default.clicked.connect(self._set_default)
        self.btn_test = QPushButton("Test Connection")
        self.btn_test.clicked.connect(self._test_connection)
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_remove)
        btn_row.addWidget(self.btn_default)
        btn_row.addWidget(self.btn_test)
        api_layout.addLayout(btn_row)

        # Add key form
        add_group = QGroupBox("Add New Key")
        add_form = QFormLayout(add_group)
        self.key_label_input = QLineEdit()
        self.key_label_input.setPlaceholderText("e.g., Personal, Work")
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("sk-ant-...")
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        add_form.addRow("Label:", self.key_label_input)
        add_form.addRow("API Key:", self.key_input)
        api_layout.addWidget(add_group)

        tabs.addTab(api_tab, "API Keys")

        # ── Proxy Tab ──────────────────────────
        proxy_tab = QWidget()
        proxy_layout = QVBoxLayout(proxy_tab)

        self.proxy_enabled = QCheckBox("Enable Proxy")
        proxy_layout.addWidget(self.proxy_enabled)

        proxy_form = QFormLayout()
        self.proxy_type = QComboBox()
        self.proxy_type.addItems(["http", "https", "socks5"])
        self.proxy_host = QLineEdit()
        self.proxy_host.setPlaceholderText("127.0.0.1")
        self.proxy_port = QLineEdit()
        self.proxy_port.setPlaceholderText("7890")
        self.proxy_user = QLineEdit()
        self.proxy_user.setPlaceholderText("(optional)")
        self.proxy_pass = QLineEdit()
        self.proxy_pass.setPlaceholderText("(optional)")
        self.proxy_pass.setEchoMode(QLineEdit.EchoMode.Password)

        proxy_form.addRow("Type:", self.proxy_type)
        proxy_form.addRow("Host:", self.proxy_host)
        proxy_form.addRow("Port:", self.proxy_port)
        proxy_form.addRow("Username:", self.proxy_user)
        proxy_form.addRow("Password:", self.proxy_pass)
        proxy_layout.addLayout(proxy_form)

        tabs.addTab(proxy_tab, "Proxy")

        # ── General Tab ────────────────────────
        gen_tab = QWidget()
        gen_layout = QVBoxLayout(gen_tab)
        gen_form = QFormLayout()

        # PRD v3 §8.5: 主题选择
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("暗色 (Dark)", "dark")
        self.theme_combo.addItem("亮色 (Light)", "light")
        gen_form.addRow("主题 Theme:", self.theme_combo)

        self.default_model = QComboBox()
        for mid, minfo in MODELS.items():
            self.default_model.addItem(
                f"{minfo.display_name}  (${minfo.input_price}/${minfo.output_price})", mid
            )
        gen_form.addRow("Default Model:", self.default_model)
        gen_layout.addLayout(gen_form)
        gen_layout.addStretch()
        tabs.addTab(gen_tab, "General")

        # ── Token Strategy Tab (PRD v3) ────────────────────
        token_tab = QWidget()
        token_layout = QVBoxLayout(token_tab)
        
        # Cache TTL 设置
        cache_group = QGroupBox("Cache TTL (缓存有效期)")
        cache_form = QFormLayout(cache_group)
        
        self.cache_ttl = QComboBox()
        self.cache_ttl.addItem("5 分钟 (默认) - 更便宜，适合持续对话", "5m")
        self.cache_ttl.addItem("1 小时 - 适合偶尔中断的工作节奏", "1h")
        
        cache_desc = QLabel(
            "• 5分钟：持续对话时成本更低\n"
            "• 1小时：经常超过5分钟空闲时更划算"
        )
        cache_desc.setStyleSheet("color: #666; font-size: 11px;")
        
        cache_form.addRow("缓存有效期:", self.cache_ttl)
        cache_form.addRow("", cache_desc)
        token_layout.addWidget(cache_group)
        
        # 压缩模式设置
        compress_group = QGroupBox("Compression Mode (压缩模式)")
        compress_form = QFormLayout(compress_group)
        
        self.compress_mode = QComboBox()
        self.compress_mode.addItem("标准模式 (默认) - N=10, K=5", "standard")
        self.compress_mode.addItem("保守模式 - N=20, K=5", "conservative")
        
        compress_desc = QLabel(
            "• 标准模式：平衡成本与上下文质量\n"
            "• 保守模式：保留更多完整上下文，适合代码调试"
        )
        compress_desc.setStyleSheet("color: #666; font-size: 11px;")
        
        compress_form.addRow("压缩策略:", self.compress_mode)
        compress_form.addRow("", compress_desc)
        token_layout.addWidget(compress_group)
        
        # 成本预估说明
        cost_info = QLabel(
            "💡 Token 优化原理：\n"
            "• 缓存命中时，系统提示只付 10% 价格\n"
            "• 对话摘要作为第二个缓存断点，再省 90%\n"
            "• 增量压缩只处理最老的 K 轮，成本可预测"
        )
        cost_info.setStyleSheet("color: #888; font-size: 11px; padding: 10px;")
        token_layout.addWidget(cost_info)
        
        # PRD v3 §8.4: 重置摘要按钮
        reset_group = QGroupBox("重置对话摘要 (Reset Summary)")
        reset_layout = QVBoxLayout(reset_group)
        
        reset_desc = QLabel(
            "清除当前对话的累积摘要，强制下一次请求发送全量历史。\n"
            "适用于摘要出现错误信息、需要重新开始对话上下文的场景。"
        )
        reset_desc.setStyleSheet("color: #666; font-size: 11px;")
        reset_layout.addWidget(reset_desc)
        
        self.btn_reset_summary = QPushButton("清除当前对话摘要")
        self.btn_reset_summary.setStyleSheet("""
            QPushButton {
                background: #E74C3C;
                color: white;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #C0392B;
            }
        """)
        self.btn_reset_summary.clicked.connect(self._reset_summary)
        reset_layout.addWidget(self.btn_reset_summary)
        
        token_layout.addWidget(reset_group)
        
        token_layout.addStretch()
        tabs.addTab(token_tab, "Token 策略")

        layout.addWidget(tabs)

        # Bottom buttons
        bottom = QHBoxLayout()
        bottom.addStretch()
        btn_save = QPushButton("Save")
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_save)
        bottom.addWidget(btn_cancel)
        layout.addLayout(bottom)

    def _load(self):
        """Load existing settings."""
        self._refresh_key_list()
        
        # PRD v3 §8.5: 加载主题设置
        try:
            import json
            from pathlib import Path
            theme_file = Path.home() / "ClaudeStation" / "theme_config.json"
            if theme_file.exists():
                with open(theme_file, "r", encoding="utf-8") as f:
                    theme_data = json.load(f)
                    theme_mode = theme_data.get("mode", "dark")
                    idx = self.theme_combo.findData(theme_mode)
                    if idx >= 0:
                        self.theme_combo.setCurrentIndex(idx)
        except Exception:
            pass

    def _refresh_key_list(self):
        self.key_list.clear()
        keys = self.key_manager.list_keys()
        for k in keys:
            label = k["label"]
            if k["is_default"]:
                label += " [DEFAULT]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, k["id"])
            self.key_list.addItem(item)

    def _add_key(self):
        label = self.key_label_input.text().strip()
        key = self.key_input.text().strip()
        if not label or not key:
            QMessageBox.warning(self, "Error", "Please enter both a label and API key.")
            return
        if not key.startswith("sk-"):
            QMessageBox.warning(self, "Error", "API key should start with 'sk-'.")
            return
        self.key_manager.add_key(label, key)
        self.key_label_input.clear()
        self.key_input.clear()
        self._refresh_key_list()
        log.info("Added API key profile: %s", label)

    def _remove_key(self):
        item = self.key_list.currentItem()
        if not item:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        self.key_manager.delete_key(pid)
        self._refresh_key_list()

    def _set_default(self):
        item = self.key_list.currentItem()
        if not item:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        self.key_manager.set_default(pid)
        self._refresh_key_list()

    def _test_connection(self):
        """Test API connection with current/default key."""
        default = self.key_manager.get_default_key()
        if not default:
            QMessageBox.warning(self, "Error", "No API key configured.")
            return
        _, key = default
        proxy = self.get_proxy_url()
        self.client.configure(key, proxy)
        ok, msg = self.client.test_connection()
        if ok:
            QMessageBox.information(self, "Success", msg)
        else:
            QMessageBox.warning(self, "Connection Failed", msg)

    def get_proxy_url(self) -> str:
        """Build proxy URL from current settings."""
        if not self.proxy_enabled.isChecked():
            return ""
        ptype = self.proxy_type.currentText()
        host = self.proxy_host.text().strip()
        port = self.proxy_port.text().strip()
        if not host or not port:
            return ""
        user = self.proxy_user.text().strip()
        pw = self.proxy_pass.text().strip()
        if user and pw:
            return f"{ptype}://{user}:{pw}@{host}:{port}"
        return f"{ptype}://{host}:{port}"

    def _reset_summary(self):
        """Reset the rolling summary for the current conversation (PRD v3 §8.4)."""
        from core.conversation_manager import ConversationManager
        from data.database import db
        
        # 获取当前对话ID
        from ui.main_window import _get_app_state
        state = _get_app_state()
        conversation_id = state.get("last_conversation_id")
        
        if not conversation_id:
            QMessageBox.warning(
                self, 
                "无法重置", 
                "请先选择一个对话，然后再尝试重置摘要。"
            )
            return
        
        # 确认对话框
        reply = QMessageBox.question(
            self,
            "确认重置摘要",
            "确定要清除当前对话的累积摘要吗？\n\n"
            "这将强制下一次请求发送全量历史上下文。\n"
            "适用于摘要出现错误、需要重新开始对话上下文的场景。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        try:
            # 重置摘要
            db.execute("""
                UPDATE conversations 
                SET rolling_summary = NULL, 
                    last_compressed_msg_id = NULL, 
                    summary_token_count = NULL
                WHERE id = ?
            """, (conversation_id,))
            
            QMessageBox.information(
                self,
                "重置成功",
                "对话摘要已清除。\n\n"
                "下一次对话请求将发送全量历史上下文。"
            )
            log.info("Reset rolling summary for conversation %s", conversation_id[:8])
        except Exception as e:
            QMessageBox.warning(self, "重置失败", f"无法重置摘要: {e}")
            log.error("Failed to reset summary: %s", e)

    def _save(self):
        # PRD v3 §8.5: 保存主题设置
        theme_mode = self.theme_combo.currentData()
        try:
            import json
            from pathlib import Path
            theme_file = Path.home() / "ClaudeStation" / "theme_config.json"
            theme_file.parent.mkdir(parents=True, exist_ok=True)
            with open(theme_file, "w", encoding="utf-8") as f:
                json.dump({"mode": theme_mode}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"Failed to save theme config: {e}")
        
        self.settings_changed.emit()
        self.accept()
