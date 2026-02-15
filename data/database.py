"""SQLite database layer with schema management and migrations."""
from __future__ import annotations

import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Generator

from config import DB_PATH

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2  # 版本升级

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    key_ref TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    system_prompt TEXT DEFAULT '',
    default_model TEXT NOT NULL DEFAULT 'claude-sonnet-4-5-20250929',
    api_key_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    settings_json TEXT DEFAULT '{}',
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    extracted_text TEXT DEFAULT '',
    token_count INTEGER DEFAULT 0,
    file_type TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT 'New Conversation',
    model_override TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_archived INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL DEFAULT '',
    thinking_content TEXT,
    attachments_json TEXT DEFAULT '[]',
    model_used TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

-- 新增：API调用日志表（用于统计cache命中率）
CREATE TABLE IF NOT EXISTS api_call_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT,
    conversation_id TEXT,
    model_id TEXT,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);
CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_api_log_project ON api_call_log(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_log_conversation ON api_call_log(conversation_id, created_at DESC);
"""

class Database:
    """SQLite database manager with connection pooling."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        log.info("Database path: %s", self.db_path)

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=10.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            log.debug("Database connection established")
        return self._conn

    @contextmanager
    def cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """Get a database cursor within a transaction."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            log.exception("Database transaction failed, rolled back")
            raise

    def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute SQL and return all rows."""
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def execute_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        """Execute SQL and return one row or None."""
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def execute_insert(self, sql: str, params: tuple = ()) -> str | None:
        """Execute an INSERT and return lastrowid."""
        with self.cursor() as cur:
            cur.execute(sql, params)
            return str(cur.lastrowid) if cur.lastrowid else None

    def execute_many(self, sql: str, params_list: list[tuple]) -> int:
        """Execute SQL for multiple parameter sets."""
        with self.cursor() as cur:
            cur.executemany(sql, params_list)
            return cur.rowcount

    def initialize(self) -> None:
        """Create tables and run migrations."""
        log.info("Initializing database schema (version %d)", SCHEMA_VERSION)
        conn = self._get_connection()
        conn.executescript(SCHEMA_SQL)

        row = self.execute_one("SELECT version FROM schema_version LIMIT 1")
        if row is None:
            self.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            log.info("Schema version set to %d", SCHEMA_VERSION)
        else:
            current = row["version"]
            if current < SCHEMA_VERSION:
                self._migrate(current, SCHEMA_VERSION)
                self.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
                log.info("Schema migrated from %d to %d", current, SCHEMA_VERSION)
            else:
                log.info("Schema version: %d", current)

    def _migrate(self, from_ver: int, to_ver: int) -> None:
        """Run schema migrations between versions."""
        log.info("Migrating schema from v%d to v%d", from_ver, to_ver)
        
        if from_ver < 2:
            # 添加api_call_log表
            self.execute("""
                CREATE TABLE IF NOT EXISTS api_call_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT,
                    conversation_id TEXT,
                    model_id TEXT,
                    cache_read_tokens INTEGER DEFAULT 0,
                    cache_creation_tokens INTEGER DEFAULT 0,
                    input_tokens INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.execute("CREATE INDEX IF NOT EXISTS idx_api_log_project ON api_call_log(project_id, created_at DESC)")
            self.execute("CREATE INDEX IF NOT EXISTS idx_api_log_conversation ON api_call_log(conversation_id, created_at DESC)")
            log.info("Migration to v2: Added api_call_log table")

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            log.debug("Database connection closed")

# Singleton
db = Database()