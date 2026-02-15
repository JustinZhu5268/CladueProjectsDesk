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

from config import MODELS, DEFAULT_MODEL
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

        self.default_model = QComboBox()
        for mid, minfo in MODELS.items():
            self.default_model.addItem(
                f"{minfo.display_name}  (${minfo.input_price}/${minfo.output_price})", mid
            )
        gen_form.addRow("Default Model:", self.default_model)
        gen_layout.addLayout(gen_form)
        gen_layout.addStretch()
        tabs.addTab(gen_tab, "General")

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

    def _save(self):
        self.settings_changed.emit()
        self.accept()
