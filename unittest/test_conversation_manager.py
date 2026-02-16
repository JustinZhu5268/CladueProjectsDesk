"""
Unit tests for ConversationManager - Conversation and message management with compression support
"""
import unittest
import sys
import sqlite3
import tempfile
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.conversation_manager import ConversationManager, Conversation, Message


class TestConversationManager(unittest.TestCase):
    """测试 ConversationManager"""
    
    def setUp(self):
        """创建临时数据库"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db_path = Path(self.temp_db.name)
        self._setup_db()
        
    def tearDown(self):
        """清理"""
        try:
            os.unlink(self.db_path)
        except:
            pass
    
    def _setup_db(self):
        """设置测试数据库"""
        from data.database import Database
        
        # 临时替换数据库路径
        import data.database
        original_db_path = data.database.DB_PATH
        data.database.DB_PATH = self.db_path
        
        self.mgr = ConversationManager()
        
        # 恢复原始路径
        data.database.DB_PATH = original_db_path


class TestConversationModel(unittest.TestCase):
    """测试 Conversation 数据类"""
    
    def test_conversation_defaults(self):
        """测试默认值"""
        conv = Conversation(
            id="test-id",
            project_id="proj-id",
        )
        
        self.assertEqual(conv.title, "New Conversation")
        self.assertIsNone(conv.model_override)
        self.assertFalse(conv.is_archived)
        self.assertEqual(conv.rolling_summary, "")
        self.assertIsNone(conv.last_compressed_msg_id)
        self.assertEqual(conv.summary_token_count, 0)
        self.assertEqual(conv.compress_after_turns, 10)
    
    def test_conversation_with_compression(self):
        """测试带压缩字段"""
        conv = Conversation(
            id="test-id",
            project_id="proj-id",
            rolling_summary="Summary of conversation",
            last_compressed_msg_id="msg-100",
            summary_token_count=500,
            compress_after_turns=20,
        )
        
        self.assertEqual(conv.rolling_summary, "Summary of conversation")
        self.assertEqual(conv.last_compressed_msg_id, "msg-100")
        self.assertEqual(conv.summary_token_count, 500)
        self.assertEqual(conv.compress_after_turns, 20)


class TestMessageModel(unittest.TestCase):
    """测试 Message 数据类"""
    
    def test_message_defaults(self):
        """测试默认值"""
        msg = Message(
            id="msg-id",
            conversation_id="conv-id",
            role="user",
            content="Hello",
        )
        
        self.assertEqual(msg.thinking_content, "")
        self.assertEqual(msg.attachments, [])
        self.assertEqual(msg.model_used, "")
        self.assertEqual(msg.input_tokens, 0)
        self.assertEqual(msg.output_tokens, 0)
        self.assertEqual(msg.cache_read_tokens, 0)
        self.assertEqual(msg.cache_creation_tokens, 0)
        self.assertEqual(msg.cost_usd, 0.0)
    
    def test_message_with_cache(self):
        """测试带缓存信息"""
        msg = Message(
            id="msg-id",
            conversation_id="conv-id",
            role="assistant",
            content="Response",
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=80,
            cache_creation_tokens=20,
            cost_usd=0.002,
        )
        
        self.assertEqual(msg.input_tokens, 100)
        self.assertEqual(msg.output_tokens, 50)
        self.assertEqual(msg.cache_read_tokens, 80)
        self.assertEqual(msg.cache_creation_tokens, 20)
        self.assertAlmostEqual(msg.cost_usd, 0.002)


class TestConversationConversions(unittest.TestCase):
    """测试对话转换"""
    
    def test_row_to_conv_no_compression(self):
        """测试无压缩字段的转换"""
        from core.conversation_manager import ConversationManager
        
        mgr = ConversationManager()
        
        row = {
            "id": "conv-001",
            "project_id": "proj-001",
            "title": "Test Conv",
            "model_override": None,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "is_archived": 0,
            "rolling_summary": None,
            "last_compressed_msg_id": None,
            "summary_token_count": None,
            "compress_after_turns": None,
        }
        
        conv = mgr._row_to_conv(row)
        
        self.assertEqual(conv.id, "conv-001")
        self.assertEqual(conv.rolling_summary, "")
        self.assertEqual(conv.compress_after_turns, 10)  # 默认值
    
    def test_row_to_conv_with_compression(self):
        """测试带压缩字段的转换"""
        from core.conversation_manager import ConversationManager
        
        mgr = ConversationManager()
        
        row = {
            "id": "conv-001",
            "project_id": "proj-001",
            "title": "Test Conv",
            "model_override": "claude-sonnet-4-5-20250929",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "is_archived": 0,
            "rolling_summary": "This is a summary.",
            "last_compressed_msg_id": "msg-050",
            "summary_token_count": 200,
            "compress_after_turns": 15,
        }
        
        conv = mgr._row_to_conv(row)
        
        self.assertEqual(conv.model_override, "claude-sonnet-4-5-20250929")
        self.assertEqual(conv.rolling_summary, "This is a summary.")
        self.assertEqual(conv.last_compressed_msg_id, "msg-050")
        self.assertEqual(conv.summary_token_count, 200)
        self.assertEqual(conv.compress_after_turns, 15)
    
    def test_row_to_msg_basic(self):
        """测试消息转换"""
        from core.conversation_manager import ConversationManager
        
        mgr = ConversationManager()
        
        row = {
            "id": "msg-001",
            "conversation_id": "conv-001",
            "role": "user",
            "content": "Hello",
            "thinking_content": None,
            "attachments_json": "[]",
            "model_used": None,
            "input_tokens": 10,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cost_usd": 0.0,
            "created_at": "2026-01-01T00:00:00",
        }
        
        msg = mgr._row_to_msg(row)
        
        self.assertEqual(msg.id, "msg-001")
        self.assertEqual(msg.content, "Hello")
        self.assertEqual(msg.attachments, [])
    
    def test_row_to_msg_with_attachments(self):
        """测试带附件的消息"""
        from core.conversation_manager import ConversationManager
        
        mgr = ConversationManager()
        
        attachments = [{"type": "image", "filename": "test.png"}]
        
        row = {
            "id": "msg-001",
            "conversation_id": "conv-001",
            "role": "user",
            "content": "Check this",
            "thinking_content": None,
            "attachments_json": json.dumps(attachments),
            "model_used": None,
            "input_tokens": 10,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cost_usd": 0.0,
            "created_at": "2026-01-01T00:00:00",
        }
        
        msg = mgr._row_to_msg(row)
        
        self.assertEqual(len(msg.attachments), 1)
        self.assertEqual(msg.attachments[0]["type"], "image")


class TestCompressionMethods(unittest.TestCase):
    """测试压缩相关方法"""
    
    @patch("core.conversation_manager.db")
    def test_update_rolling_summary(self, mock_db):
        """测试更新滚动摘要"""
        from core.conversation_manager import ConversationManager
        
        # 重置 mock
        mock_db.execute = MagicMock()
        
        mgr = ConversationManager()
        mgr.update_rolling_summary(
            conversation_id="conv-001",
            summary="New summary",
            last_msg_id="msg-100",
            token_count=200,
        )
        
        # 验证调用
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0]
        
        self.assertIn("rolling_summary", call_args[0])
        self.assertIn("conv-001", call_args[1])
    
    @patch("core.conversation_manager.db")
    def test_reset_rolling_summary(self, mock_db):
        """测试重置滚动摘要"""
        from core.conversation_manager import ConversationManager
        
        mock_db.execute = MagicMock()
        
        mgr = ConversationManager()
        mgr.reset_rolling_summary("conv-001")
        
        # 验证调用
        mock_db.execute.assert_called_once()
    
    @patch("core.conversation_manager.db")
    def test_get_compression_stats_no_summary(self, mock_db):
        """测试无摘要时的压缩统计"""
        from core.conversation_manager import ConversationManager
        
        # 模拟返回无摘要的对话
        mock_conv = MagicMock()
        mock_conv.rolling_summary = ""
        mock_conv.last_compressed_msg_id = None
        mock_conv.summary_token_count = 0
        mock_conv.compress_after_turns = 10
        
        mock_db.execute_one.return_value = mock_conv
        
        # 模拟消息返回空列表
        mock_db.execute.return_value = []
        
        mgr = ConversationManager()
        mgr.get_conversation = MagicMock(return_value=mock_conv)
        mgr.get_messages = MagicMock(return_value=[])
        
        stats = mgr.get_compression_stats("conv-001")
        
        self.assertFalse(stats["has_summary"])
        self.assertEqual(stats["summary_tokens"], 0)
        self.assertEqual(stats["uncompressed_count"], 0)
        self.assertEqual(stats["uncompressed_turns"], 0)
        self.assertFalse(stats["should_compress"])
    
    @patch("core.conversation_manager.db")
    def test_get_compression_stats_with_summary(self, mock_db):
        """测试有摘要时的压缩统计"""
        from core.conversation_manager import ConversationManager
        
        mock_conv = MagicMock()
        mock_conv.rolling_summary = "x" * 500
        mock_conv.last_compressed_msg_id = "msg-050"
        mock_conv.summary_token_count = 500
        mock_conv.compress_after_turns = 10
        
        # 模拟 25 条消息 = 12+ 轮
        mock_messages = [MagicMock(id=f"msg-{i}") for i in range(25)]
        
        mgr = ConversationManager()
        mgr.get_conversation = MagicMock(return_value=mock_conv)
        mgr.get_messages = MagicMock(return_value=mock_messages)
        
        stats = mgr.get_compression_stats("conv-001")
        
        self.assertTrue(stats["has_summary"])
        self.assertEqual(stats["summary_tokens"], 500)
        self.assertEqual(stats["uncompressed_turns"], 12)  # 25 // 2
        self.assertTrue(stats["should_compress"])


class TestConversationEdgeCases(unittest.TestCase):
    """测试边界情况"""
    
    @patch("core.conversation_manager.db")
    def test_get_conversation_not_found(self, mock_db):
        """测试获取不存在的对话"""
        from core.conversation_manager import ConversationManager
        
        mock_db.execute_one.return_value = None
        
        mgr = ConversationManager()
        result = mgr.get_conversation("nonexistent")
        
        self.assertIsNone(result)
    
    @patch("core.conversation_manager.db")
    def test_get_messages_empty(self, mock_db):
        """测试获取空消息列表"""
        from core.conversation_manager import ConversationManager
        
        mock_db.execute.return_value = []
        
        mgr = ConversationManager()
        messages = mgr.get_messages("conv-001")
        
        self.assertEqual(len(messages), 0)
    
    @patch("core.conversation_manager.db")
    def test_get_messages_with_limit(self, mock_db):
        """测试带限制的消息获取"""
        from core.conversation_manager import ConversationManager
        
        # 模拟子查询结果
        mock_rows = [
            {"id": "msg-001", "conversation_id": "conv-001", "role": "user",
             "content": "Hello", "thinking_content": None, "attachments_json": "[]",
             "model_used": None, "input_tokens": 10, "output_tokens": 20,
             "cache_read_tokens": 0, "cache_creation_tokens": 0, "cost_usd": 0.0,
             "created_at": "2026-01-01T00:00:00"},
            {"id": "msg-002", "conversation_id": "conv-001", "role": "assistant",
             "content": "Hi there", "thinking_content": None, "attachments_json": "[]",
             "model_used": "claude-sonnet-4-5-20250929", "input_tokens": 20,
             "output_tokens": 15, "cache_read_tokens": 10, "cache_creation_tokens": 50,
             "cost_usd": 0.001, "created_at": "2026-01-01T00:00:01"},
        ]
        
        mock_db.execute.return_value = mock_rows
        
        mgr = ConversationManager()
        messages = mgr.get_messages("conv-001", limit=5)
        
        self.assertEqual(len(messages), 2)
    
    @patch("core.conversation_manager.db")
    def test_conversation_stats(self, mock_db):
        """测试对话统计"""
        from core.conversation_manager import ConversationManager
        
        mock_db.execute_one.return_value = {
            "msg_count": 10,
            "total_input": 1000,
            "total_output": 500,
            "total_cache_read": 800,
            "total_cache_create": 200,
            "total_cost": 0.05,
        }
        
        mgr = ConversationManager()
        stats = mgr.get_conversation_stats("conv-001")
        
        self.assertEqual(stats["msg_count"], 10)
        self.assertEqual(stats["total_input"], 1000)
        self.assertEqual(stats["total_cost"], 0.05)


class TestArchiveAndDelete(unittest.TestCase):
    """测试归档和删除"""
    
    @patch("core.conversation_manager.db")
    def test_archive_conversation(self, mock_db):
        """测试归档对话"""
        from core.conversation_manager import ConversationManager
        
        mock_db.execute = MagicMock()
        
        mgr = ConversationManager()
        mgr.archive_conversation("conv-001")
        
        # 验证调用
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0]
        self.assertIn("is_archived", call_args[0])
    
    @patch("core.conversation_manager.db")
    def test_delete_conversation(self, mock_db):
        """测试删除对话"""
        from core.conversation_manager import ConversationManager
        
        mock_db.execute = MagicMock()
        
        mgr = ConversationManager()
        mgr.delete_conversation("conv-001")
        
        # 验证调用
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0]
        self.assertIn("conv-001", call_args[1])


if __name__ == "__main__":
    unittest.main()
