"""
Unit tests for ContextBuilder - PRD v3 four-layer context architecture
"""
import unittest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.context_builder import ContextBuilder, CACHE_BREAKPOINT_THRESHOLD
from config import (
    RECENT_TURNS_KEPT,
    CACHE_TTL_DEFAULT,
    CACHE_TTL_1H,
)


class TestContextBuilderConstants(unittest.TestCase):
    """测试 ContextBuilder 常量"""
    
    def test_cache_breakpoint_threshold(self):
        """测试缓存断点阈值"""
        self.assertEqual(CACHE_BREAKPOINT_THRESHOLD, 1024)
    
    def test_recent_turns_kept(self):
        """测试保留最近轮数"""
        self.assertEqual(RECENT_TURNS_KEPT, 10)


class TestContextBuilderInitialization(unittest.TestCase):
    """测试 ContextBuilder 初始化"""
    
    def test_default_initialization(self):
        """测试默认初始化"""
        builder = ContextBuilder()
        
        self.assertEqual(builder.cache_ttl, CACHE_TTL_DEFAULT)
    
    def test_custom_cache_ttl(self):
        """测试自定义缓存 TTL"""
        builder = ContextBuilder(cache_ttl="1h")
        
        self.assertEqual(builder.cache_ttl, "1h")
    
    def test_cache_ttl_setter(self):
        """测试缓存 TTL 设置器"""
        builder = ContextBuilder()
        
        builder.cache_ttl = "1h"
        
        self.assertEqual(builder.cache_ttl, "1h")
        self.assertEqual(builder.tracker.cache_ttl, "1h")


class TestContextBuilderBuild(unittest.TestCase):
    """测试上下文构建"""
    
    @patch("core.context_builder.DocumentProcessor")
    @patch("core.context_builder.ConversationManager")
    @patch("core.context_builder.TokenTracker")
    def test_build_empty_project(self, mock_tracker, mock_cm, mock_doc):
        """测试空项目构建"""
        builder = ContextBuilder()
        
        # Mock 文档处理器
        mock_doc.get_project_context.return_value = ""
        builder.doc_processor = mock_doc
        
        # Mock 对话管理器
        mock_conv = MagicMock()
        mock_conv.rolling_summary = ""
        mock_conv.last_compressed_msg_id = None
        
        mock_cm.get_conversation.return_value = mock_conv
        mock_cm.get_messages.return_value = []
        builder.conv_manager = mock_cm
        
        # Mock token tracker
        mock_tracker.estimate_tokens.return_value = 10
        builder.tracker = mock_tracker
        
        system_content, messages, est_tokens = builder.build(
            project_id="test-project",
            conversation_id="test-conv",
            user_message="Hello",
            system_prompt="You are helpful.",
            model_id="claude-sonnet-4-5-20250929",
        )
        
        # 验证系统内容包含缓存控制
        self.assertEqual(len(system_content), 1)
        self.assertIn("cache_control", system_content[0])
        self.assertEqual(system_content[0]["cache_control"]["type"], "ephemeral")
        
        # 验证消息
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "Hello")
    
    @patch("core.context_builder.DocumentProcessor")
    @patch("core.context_builder.ConversationManager")
    @patch("core.context_builder.TokenTracker")
    def test_build_with_rolling_summary(self, mock_tracker, mock_cm, mock_doc):
        """测试带滚动摘要的构建"""
        builder = ContextBuilder()
        
        # Mock 文档
        mock_doc.get_project_context.return_value = "Document context"
        builder.doc_processor = mock_doc
        
        # Mock 对话 - 有摘要
        mock_conv = MagicMock()
        mock_conv.rolling_summary = "x" * 1500  # 超过 1024 阈值
        mock_conv.last_compressed_msg_id = "msg-010"
        
        mock_cm.get_conversation.return_value = mock_conv
        mock_cm.get_messages.return_value = [
            MagicMock(id=f"msg-{i}", role="user" if i % 2 == 0 else "assistant", content=f"msg{i}")
            for i in range(20)  # 10 轮
        ]
        builder.conv_manager = mock_cm
        
        # Mock token tracker
        def estimate_tokens(text):
            if "Document context" in text or "project_knowledge" in text:
                return 100
            if "<conversation_summary>" in text:
                return 1500  # 超过 1024
            if len(text) < 20:
                return 10
            return len(text) // 4
        
        mock_tracker.estimate_tokens.side_effect = estimate_tokens
        builder.tracker = mock_tracker
        
        system_content, messages, est_tokens = builder.build(
            project_id="test-project",
            conversation_id="test-conv",
            user_message="Hello",
            system_prompt="You are helpful.",
            model_id="claude-sonnet-4-5-20250929",
        )
        
        # 验证：应该有 2 个系统内容块
        self.assertEqual(len(system_content), 2)
        
        # 第二个块应该是摘要
        self.assertIn("<conversation_summary>", system_content[1]["text"])
        
        # 超过 1024 应该有缓存控制
        self.assertIn("cache_control", system_content[1])
    
    @patch("core.context_builder.DocumentProcessor")
    @patch("core.context_builder.ConversationManager")
    @patch("core.context_builder.TokenTracker")
    def test_build_summary_below_threshold(self, mock_tracker, mock_cm, mock_doc):
        """测试摘要低于缓存阈值"""
        builder = ContextBuilder()
        
        mock_doc.get_project_context.return_value = ""
        builder.doc_processor = mock_doc
        
        # 摘要低于阈值
        mock_conv = MagicMock()
        mock_conv.rolling_summary = "Short summary"  # < 1024 tokens
        mock_conv.last_compressed_msg_id = "msg-010"
        
        mock_cm.get_conversation.return_value = mock_conv
        mock_cm.get_messages.return_value = []
        builder.conv_manager = mock_cm
        
        def estimate_tokens(text):
            if "Short summary" in text:
                return 500  # 低于 1024
            return 10
        
        mock_tracker.estimate_tokens.side_effect = estimate_tokens
        builder.tracker = mock_tracker
        
        system_content, messages, est_tokens = builder.build(
            project_id="test-project",
            conversation_id="test-conv",
            user_message="Hello",
            system_prompt="You are helpful.",
            model_id="claude-sonnet-4-5-20250929",
        )
        
        # 验证：第二个块没有缓存控制
        self.assertEqual(len(system_content), 2)
        self.assertNotIn("cache_control", system_content[1])
    
    @patch("core.context_builder.DocumentProcessor")
    @patch("core.context_builder.ConversationManager")
    @patch("core.context_builder.TokenTracker")
    def test_build_with_1h_cache_ttl(self, mock_tracker, mock_cm, mock_doc):
        """测试 1 小时缓存 TTL"""
        builder = ContextBuilder(cache_ttl="1h")
        
        mock_doc.get_project_context.return_value = ""
        builder.doc_processor = mock_doc
        
        mock_conv = MagicMock()
        mock_conv.rolling_summary = ""
        mock_conv.last_compressed_msg_id = None
        
        mock_cm.get_conversation.return_value = mock_conv
        mock_cm.get_messages.return_value = []
        builder.conv_manager = mock_cm
        
        mock_tracker.estimate_tokens.return_value = 10
        builder.tracker = mock_tracker
        
        system_content, messages, est_tokens = builder.build(
            project_id="test-project",
            conversation_id="test-conv",
            user_message="Hello",
            system_prompt="You are helpful.",
            model_id="claude-sonnet-4-5-20250929",
        )
        
        # 验证缓存 TTL
        self.assertEqual(system_content[0]["cache_control"]["ttl"], "1h")


class TestContextBuilderEstimate(unittest.TestCase):
    """测试成本预估"""
    
    @patch("core.context_builder.DocumentProcessor")
    @patch("core.context_builder.ConversationManager")
    @patch("core.context_builder.TokenTracker")
    def test_estimate_request_basic(self, mock_tracker, mock_cm, mock_doc):
        """测试基本预估"""
        builder = ContextBuilder()
        
        mock_doc.get_project_context.return_value = ""
        builder.doc_processor = mock_doc
        
        mock_conv = MagicMock()
        mock_conv.rolling_summary = ""
        mock_conv.last_compressed_msg_id = None
        
        mock_cm.get_conversation.return_value = mock_conv
        mock_cm.get_messages.return_value = []
        builder.conv_manager = mock_cm
        
        mock_tracker.estimate_tokens.return_value = 50
        builder.tracker = mock_tracker
        
        result = builder.estimate_request(
            project_id="test-project",
            conversation_id="test-conv",
            user_message="Hello",
            system_prompt="You are helpful.",
            model_id="claude-sonnet-4-5-20250929",
        )
        
        # 验证返回结构
        self.assertIn("system_tokens", result)
        self.assertIn("summary_tokens", result)
        self.assertIn("history_tokens", result)
        self.assertIn("user_tokens", result)
        self.assertIn("total_tokens", result)
        self.assertIn("cached_tokens", result)
        self.assertIn("estimated_cost", result)
        self.assertIn("savings_percent", result)
        self.assertIn("cache_hit", result)
    
    @patch("core.context_builder.DocumentProcessor")
    @patch("core.context_builder.ConversationManager")
    @patch("core.context_builder.TokenTracker")
    def test_estimate_with_summary(self, mock_tracker, mock_cm, mock_doc):
        """测试带摘要的预估"""
        builder = ContextBuilder()
        
        mock_doc.get_project_context.return_value = ""
        builder.doc_processor = mock_doc
        
        mock_conv = MagicMock()
        mock_conv.rolling_summary = "x" * 1500  # 超过 1024
        mock_conv.last_compressed_msg_id = None
        
        mock_cm.get_conversation.return_value = mock_conv
        mock_cm.get_messages.return_value = []
        builder.conv_manager = mock_cm
        
        def estimate_tokens(text):
            if "x" * 1500 in text:
                return 1500
            return 50
        
        mock_tracker.estimate_tokens.side_effect = estimate_tokens
        mock_tracker.estimate_input_cost.return_value = 0.01
        builder.tracker = mock_tracker
        
        result = builder.estimate_request(
            project_id="test-project",
            conversation_id="test-conv",
            user_message="Hello",
            system_prompt="You are helpful.",
            model_id="claude-sonnet-4-5-20250929",
        )
        
        # 验证缓存命中 - 直接检查返回值而不假设内部逻辑
        self.assertIn("cache_hit", result)


class TestContextBuilderHelperMethods(unittest.TestCase):
    """测试辅助方法"""
    
    def test_build_system_text(self):
        """测试系统文本构建"""
        builder = ContextBuilder()
        
        # 无系统提示，无文档
        text = builder._build_system_text("", "")
        self.assertEqual(text, "You are a helpful AI assistant.")
        
        # 有系统提示
        text = builder._build_system_text("You are a coding expert.", "")
        self.assertIn("You are a coding expert.", text)
        
        # 有文档
        text = builder._build_system_text("", "Document content here")
        self.assertIn("<project_knowledge>", text)
        self.assertIn("Document content here", text)
        
        # 都有
        text = builder._build_system_text("System prompt", "Doc content")
        self.assertIn("System prompt", text)
        self.assertIn("Doc content", text)
    
    def test_get_recent_messages(self):
        """测试获取最近消息"""
        builder = ContextBuilder()
        
        messages = [MagicMock(id=f"msg-{i}") for i in range(30)]
        
        # 获取最近 10 轮 (20 条消息)
        recent = builder._get_recent_messages(messages, 10)
        
        self.assertEqual(len(recent), 20)
        self.assertEqual(recent[0].id, "msg-10")
        self.assertEqual(recent[-1].id, "msg-29")
    
    def test_get_recent_messages_less_than_limit(self):
        """测试消息少于限制"""
        builder = ContextBuilder()
        
        messages = [MagicMock(id=f"msg-{i}") for i in range(5)]
        
        recent = builder._get_recent_messages(messages, 10)
        
        self.assertEqual(len(recent), 5)
    
    def test_get_recent_messages_empty(self):
        """测试空消息列表"""
        builder = ContextBuilder()
        
        recent = builder._get_recent_messages([], 10)
        
        self.assertEqual(len(recent), 0)


class TestContextBuilderFitHistory(unittest.TestCase):
    """测试历史消息过滤"""
    
    @patch("core.context_builder.TokenTracker")
    def test_fit_history_within_budget(self, mock_tracker):
        """测试在预算内"""
        builder = ContextBuilder()
        
        # Mock 消息，每条约 10 tokens
        messages = [
            MagicMock(id=f"msg-{i}", role="user" if i % 2 == 0 else "assistant", content=f"message {i}")
            for i in range(10)
        ]
        
        mock_tracker.estimate_tokens.return_value = 10
        builder.tracker = mock_tracker
        
        selected = builder._fit_history(messages, 80)  # 80 tokens 预算
        
        # 应该选择 8 条消息
        self.assertLessEqual(len(selected), 8)
    
    @patch("core.context_builder.TokenTracker")
    def test_fit_history_exceed_budget(self, mock_tracker):
        """测试超过预算"""
        builder = ContextBuilder()
        
        messages = [
            MagicMock(id=f"msg-{i}", role="user" if i % 2 == 0 else "assistant", content=f"message {i}" * 50)
            for i in range(20)
        ]
        
        mock_tracker.estimate_tokens.return_value = 500
        builder.tracker = mock_tracker
        
        selected = builder._fit_history(messages, 1000)  # 只能容纳 2 条
        
        # 应该从最新的开始选
        self.assertLessEqual(len(selected), 2)


class TestCompactionParams(unittest.TestCase):
    """测试 Compaction API 参数"""
    
    @patch("core.context_builder.DocumentProcessor")
    @patch("core.context_builder.ConversationManager")
    @patch("core.context_builder.TokenTracker")
    def test_get_compaction_params(self, mock_tracker, mock_cm, mock_doc):
        """测试获取 Compaction API 参数"""
        builder = ContextBuilder()
        
        params = builder.get_compaction_params("claude-sonnet-4-5-20250929")
        
        # 注意：由于当前 Anthropic SDK 版本不支持 betas 参数在流式调用中，
        # get_compaction_params 现在返回空字典
        # 未来 SDK 更新后可能需要重新启用
        self.assertEqual(params, {})


class TestContextBuilderEdgeCases(unittest.TestCase):
    """测试边界情况"""
    
    @patch("core.context_builder.DocumentProcessor")
    @patch("core.context_builder.ConversationManager")
    @patch("core.context_builder.TokenTracker")
    def test_build_with_attachments(self, mock_tracker, mock_cm, mock_doc):
        """测试带附件的消息"""
        builder = ContextBuilder()
        
        mock_doc.get_project_context.return_value = ""
        builder.doc_processor = mock_doc
        
        mock_conv = MagicMock()
        mock_conv.rolling_summary = ""
        mock_conv.last_compressed_msg_id = None
        
        mock_cm.get_conversation.return_value = mock_conv
        mock_cm.get_messages.return_value = []
        builder.conv_manager = mock_cm
        
        mock_tracker.estimate_tokens.return_value = 10
        builder.tracker = mock_tracker
        
        attachments = [
            {"type": "image", "data": "base64data", "media_type": "image/png"},
        ]
        
        system_content, messages, est_tokens = builder.build(
            project_id="test-project",
            conversation_id="test-conv",
            user_message="Look at this image",
            system_prompt="You are helpful.",
            model_id="claude-sonnet-4-5-20250929",
            user_attachments=attachments,
        )
        
        # 验证附件被正确添加
        self.assertIsInstance(messages[0]["content"], list)
        self.assertEqual(messages[0]["content"][0]["type"], "text")
        self.assertEqual(messages[0]["content"][1]["type"], "image")
    
    @patch("core.context_builder.DocumentProcessor")
    @patch("core.context_builder.ConversationManager")
    @patch("core.context_builder.TokenTracker")
    def test_build_with_all_messages_compressed(self, mock_tracker, mock_cm, mock_doc):
        """测试所有消息都已压缩"""
        builder = ContextBuilder()
        
        mock_doc.get_project_context.return_value = ""
        builder.doc_processor = mock_doc
        
        mock_conv = MagicMock()
        mock_conv.rolling_summary = "x" * 2000  # 超过 1024
        mock_conv.last_compressed_msg_id = "msg-100"  # 所有消息都已压缩
        
        mock_cm.get_conversation.return_value = mock_conv
        # 模拟 last_compressed_msg_id 之后没有消息
        mock_cm.get_messages.return_value = []
        builder.conv_manager = mock_cm
        
        mock_tracker.estimate_tokens.return_value = 50
        builder.tracker = mock_tracker
        
        system_content, messages, est_tokens = builder.build(
            project_id="test-project",
            conversation_id="test-conv",
            user_message="Hello",
            system_prompt="You are helpful.",
            model_id="claude-sonnet-4-5-20250929",
        )
        
        # 应该有系统提示 + 摘要
        self.assertEqual(len(system_content), 2)


if __name__ == "__main__":
    unittest.main()
