"""
Unit tests for Database - Schema migrations and initialization
"""
import unittest
import sys
import sqlite3
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data.database import Database, SCHEMA_VERSION


class TestDatabaseSchema(unittest.TestCase):
    """测试数据库 Schema"""
    
    def setUp(self):
        """每个测试前创建临时数据库"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db = Database(Path(self.temp_db.name))
        
    def tearDown(self):
        """每个测试后清理"""
        try:
            self.db.close()
            os.unlink(self.temp_db.name)
        except:
            pass
    
    def test_schema_version(self):
        """测试 Schema 版本"""
        self.assertEqual(SCHEMA_VERSION, 3)
    
    def test_initialize_schema(self):
        """测试 Schema 初始化"""
        self.db.initialize()
        
        # 验证版本表
        row = self.db.execute_one("SELECT version FROM schema_version")
        self.assertEqual(row["version"], 3)
        
        # 验证表存在
        tables = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = [t["name"] for t in tables]
        
        self.assertIn("schema_version", table_names)
        self.assertIn("projects", table_names)
        self.assertIn("conversations", table_names)
        self.assertIn("messages", table_names)
        self.assertIn("documents", table_names)
        self.assertIn("api_keys", table_names)
        self.assertIn("api_call_log", table_names)
    
    def test_conversations_table_columns(self):
        """测试 conversations 表字段"""
        self.db.initialize()
        
        # 获取表结构
        rows = self.db.execute("PRAGMA table_info(conversations)")
        columns = {r["name"] for r in rows}
        
        # 验证必需字段
        required = {"id", "project_id", "title", "model_override", 
                   "created_at", "updated_at", "is_archived",
                   "rolling_summary", "last_compressed_msg_id", 
                   "summary_token_count", "compress_after_turns"}
        
        for col in required:
            self.assertIn(col, columns, f"Column {col} missing")
    
    def test_projects_table_columns(self):
        """测试 projects 表字段"""
        self.db.initialize()
        
        rows = self.db.execute("PRAGMA table_info(projects)")
        columns = {r["name"] for r in rows}
        
        required = {"id", "name", "system_prompt", "default_model",
                   "api_key_id", "created_at", "updated_at", "settings_json"}
        
        for col in required:
            self.assertIn(col, columns)
    
    def test_messages_table_columns(self):
        """测试 messages 表字段"""
        self.db.initialize()
        
        rows = self.db.execute("PRAGMA table_info(messages)")
        columns = {r["name"] for r in rows}
        
        required = {"id", "conversation_id", "role", "content",
                   "thinking_content", "attachments_json", "model_used",
                   "input_tokens", "output_tokens", "cache_read_tokens",
                   "cache_creation_tokens", "cost_usd", "created_at"}
        
        for col in required:
            self.assertIn(col, columns)


class TestDatabaseMigration(unittest.TestCase):
    """测试数据库迁移"""
    
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db = Database(Path(self.temp_db.name))
        
    def tearDown(self):
        try:
            self.db.close()
            os.unlink(self.temp_db.name)
        except:
            pass
    
    def test_migration_from_v1_to_v3(self):
        """测试从 v1 迁移到 v3"""
        # 创建 v1 风格的表（不含压缩字段）
        conn = self.db._get_connection()
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER);
            INSERT INTO schema_version (version) VALUES (1);
            
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                system_prompt TEXT DEFAULT '',
                default_model TEXT NOT NULL DEFAULT 'claude-haiku-4-5-20251001',
                api_key_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                settings_json TEXT DEFAULT '{}'
            );
            
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New Conversation',
                model_override TEXT,
                created_at TEXT,
                updated_at TEXT,
                is_archived INTEGER NOT NULL DEFAULT 0
            );
            
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                thinking_content TEXT,
                attachments_json TEXT DEFAULT '[]',
                model_used TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cache_read_tokens INTEGER DEFAULT 0,
                cache_creation_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                created_at TEXT
            );
        """)
        conn.commit()
        
        # 运行迁移
        self.db.initialize()
        
        # 验证迁移后的版本
        row = self.db.execute_one("SELECT version FROM schema_version")
        self.assertEqual(row["version"], 3)
        
        # 验证新字段已添加
        rows = self.db.execute("PRAGMA table_info(conversations)")
        columns = {r["name"] for r in rows}
        
        self.assertIn("rolling_summary", columns)
        self.assertIn("last_compressed_msg_id", columns)
        self.assertIn("summary_token_count", columns)
        self.assertIn("compress_after_turns", columns)
    
    def test_migration_from_v2_to_v3(self):
        """测试从 v2 迁移到 v3"""
        # 创建 v2 风格的表
        conn = self.db._get_connection()
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER);
            INSERT INTO schema_version (version) VALUES (2);
            
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                system_prompt TEXT DEFAULT '',
                default_model TEXT NOT NULL DEFAULT 'claude-haiku-4-5-20251001',
                api_key_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                settings_json TEXT DEFAULT '{}'
            );
            
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New Conversation',
                model_override TEXT,
                created_at TEXT,
                updated_at TEXT,
                is_archived INTEGER NOT NULL DEFAULT 0
            );
            
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                thinking_content TEXT,
                attachments_json TEXT DEFAULT '[]',
                model_used TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cache_read_tokens INTEGER DEFAULT 0,
                cache_creation_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                created_at TEXT
            );
            
            CREATE TABLE api_call_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT,
                conversation_id TEXT,
                model_id TEXT,
                cache_read_tokens INTEGER DEFAULT 0,
                cache_creation_tokens INTEGER DEFAULT 0,
                input_tokens INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        
        # 运行迁移
        self.db.initialize()
        
        # 验证版本
        row = self.db.execute_one("SELECT version FROM schema_version")
        self.assertEqual(row["version"], 3)
        
        # 验证压缩字段
        rows = self.db.execute("PRAGMA table_info(conversations)")
        columns = {r["name"] for r in rows}
        
        self.assertIn("rolling_summary", columns)
        self.assertIn("summary_token_count", columns)


class TestDatabaseCRUD(unittest.TestCase):
    """测试数据库 CRUD 操作"""
    
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db = Database(Path(self.temp_db.name))
        self.db.initialize()
        
    def tearDown(self):
        try:
            self.db.close()
            os.unlink(self.temp_db.name)
        except:
            pass
    
    def test_insert_and_select_project(self):
        """测试插入和查询项目"""
        import uuid
        
        pid = str(uuid.uuid4())
        now = "2026-01-01T00:00:00"
        
        self.db.execute(
            """INSERT INTO projects (id, name, system_prompt, default_model, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (pid, "Test Project", "You are helpful.", "claude-sonnet-4-5-20250929", now, now)
        )
        
        row = self.db.execute_one("SELECT * FROM projects WHERE id = ?", (pid,))
        
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Test Project")
        self.assertEqual(row["system_prompt"], "You are helpful.")
    
    def test_insert_conversation_with_compression_fields(self):
        """测试插入带压缩字段的对话"""
        import uuid
        
        pid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        now = "2026-01-01T00:00:00"
        
        # 先创建项目
        self.db.execute(
            """INSERT INTO projects (id, name, default_model, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (pid, "Test Project", "claude-sonnet-4-5-20250929", now, now)
        )
        
        # 创建对话（带压缩字段）
        self.db.execute(
            """INSERT INTO conversations 
               (id, project_id, title, model_override, created_at, updated_at, 
                rolling_summary, summary_token_count, compress_after_turns)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cid, pid, "Test Conv", None, now, now, "", 0, 10)
        )
        
        row = self.db.execute_one("SELECT * FROM conversations WHERE id = ?", (cid,))
        
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "Test Conv")
        self.assertEqual(row["rolling_summary"], "")
        self.assertEqual(row["summary_token_count"], 0)
        self.assertEqual(row["compress_after_turns"], 10)
    
    def test_update_rolling_summary(self):
        """测试更新滚动摘要"""
        import uuid
        
        pid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        now = "2026-01-01T00:00:00"
        
        # 创建项目
        self.db.execute(
            """INSERT INTO projects (id, name, default_model, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (pid, "Test Project", "claude-sonnet-4-5-20250929", now, now)
        )
        
        # 创建对话
        self.db.execute(
            """INSERT INTO conversations 
               (id, project_id, title, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (cid, pid, "Test Conv", now, now)
        )
        
        # 更新摘要
        new_summary = "This is a summary of the conversation."
        new_now = "2026-01-02T00:00:00"
        
        self.db.execute(
            """UPDATE conversations 
               SET rolling_summary = ?, last_compressed_msg_id = ?, 
                   summary_token_count = ?, updated_at = ?
               WHERE id = ?""",
            (new_summary, "msg-100", 50, new_now, cid)
        )
        
        # 验证更新
        row = self.db.execute_one("SELECT * FROM conversations WHERE id = ?", (cid,))
        
        self.assertEqual(row["rolling_summary"], new_summary)
        self.assertEqual(row["last_compressed_msg_id"], "msg-100")
        self.assertEqual(row["summary_token_count"], 50)


class TestDatabaseIndexes(unittest.TestCase):
    """测试数据库索引"""
    
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db = Database(Path(self.temp_db.name))
        self.db.initialize()
        
    def tearDown(self):
        try:
            self.db.close()
            os.unlink(self.temp_db.name)
        except:
            pass
    
    def test_indexes_exist(self):
        """测试索引存在"""
        indexes = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        index_names = [i["name"] for i in indexes if i["name"]]
        
        # 验证关键索引
        self.assertTrue(any("documents_project" in n for n in index_names))
        self.assertTrue(any("conversations_project" in n for n in index_names))
        self.assertTrue(any("messages_conversation" in n for n in index_names))
        self.assertTrue(any("messages_created" in n for n in index_names))
        self.assertTrue(any("api_log_project" in n for n in index_names))
        self.assertTrue(any("api_log_conversation" in n for n in index_names))


class TestDatabaseEdgeCases(unittest.TestCase):
    """测试边界情况"""
    
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db = Database(Path(self.temp_db.name))
        self.db.initialize()
        
    def tearDown(self):
        try:
            self.db.close()
            os.unlink(self.temp_db.name)
        except:
            pass
    
    def test_empty_database(self):
        """测试空数据库"""
        # 查询空表
        rows = self.db.execute("SELECT * FROM projects")
        self.assertEqual(len(rows), 0)
        
        rows = self.db.execute("SELECT * FROM conversations")
        self.assertEqual(len(rows), 0)
    
    def test_execute_with_params(self):
        """测试带参数查询"""
        import uuid
        
        pid = str(uuid.uuid4())
        now = "2026-01-01T00:00:00"
        
        # 插入
        self.db.execute(
            "INSERT INTO projects (id, name, default_model, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (pid, "Test", "claude-sonnet-4-5-20250929", now, now)
        )
        
        # 查询不存在的记录
        row = self.db.execute_one("SELECT * FROM projects WHERE id = ?", ("nonexistent",))
        self.assertIsNone(row)
    
    def test_foreign_key_cascade(self):
        """测试级联删除"""
        import uuid
        
        pid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        now = "2026-01-01T00:00:00"
        
        # 创建项目
        self.db.execute(
            "INSERT INTO projects (id, name, default_model, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (pid, "Test", "claude-sonnet-4-5-20250929", now, now)
        )
        
        # 创建对话
        self.db.execute(
            "INSERT INTO conversations (id, project_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (cid, pid, "Test Conv", now, now)
        )
        
        # 创建消息
        self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (mid, cid, "user", "Hello", now)
        )
        
        # 删除项目
        self.db.execute("DELETE FROM projects WHERE id = ?", (pid,))
        
        # 验证对话和消息已被级联删除
        conv = self.db.execute_one("SELECT * FROM conversations WHERE id = ?", (cid,))
        self.assertIsNone(conv)
        
        msg = self.db.execute_one("SELECT * FROM messages WHERE id = ?", (mid,))
        self.assertIsNone(msg)


if __name__ == "__main__":
    unittest.main()
