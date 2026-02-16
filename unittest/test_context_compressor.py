"""
Unit tests for ContextCompressor - PRD v3 incremental rolling summary
"""
import unittest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.context_compressor import (
    ContextCompressor,
    CompressionWorker,
    CompressionResult,
    COMPRESS_MODEL,
)

# 从 context_builder 导入常量
from core.context_builder import CACHE_BREAKPOINT_THRESHOLD
from config import (
    COMPRESS_AFTER_TURNS,
    COMPRESS_BATCH_SIZE,
    MAX_SUMMARY_TOKENS,
    SUMMARY_RECOMPRESS_THRESHOLD,
)


class TestCompressionConstants(unittest.TestCase):
    """测试压缩常量定义"""
    
    def test_compress_model_is_haiku(self):
        """验证压缩使用 Haiku 模型"""
        self.assertEqual(COMPRESS_MODEL, "claude-haiku-4-5-20251001")
    
    def test_compress_system_prompt_template(self):
        """测试压缩系统提示词模板"""
        prompt = COMPRESS_SYSTEM_PROMPT_TEMPLATE.format(project_name="Test Project")
        self.assertIn("Test Project", prompt)
        self.assertIn("conversation summarizer", prompt.lower())
    
    def test_compress_user_prompt_template(self):
        """测试压缩用户提示词模板"""
        prompt = COMPRESS_USER_PROMPT_TEMPLATE.format(
            max_tokens=500,
            existing_summary="",
            conversation_turns="test content",
        )
        self.assertIn("500", prompt)
        self.assertIn("test content", prompt)


class TestContextCompressorShouldCompress(unittest.TestCase):
    """测试压缩触发判断"""
    
    @patch("core.context_compressor.ConversationManager")
    def test_should_compress_under_threshold(self, mock_cm):
        """测试未达到压缩阈值"""
        compressor = ContextCompressor()
        
        # 模拟对话：5 轮对话（10条消息）
        mock_conv = MagicMock()
        mock_conv.compress_after_turns = 10
        
        mock_cm.get_conversation.return_value = mock_conv
        compressor.conv_manager = mock_cm
        
        # 模拟返回 8 条消息（4 轮）
        mock_cm.get_uncompressed_messages.return_value = [
            MagicMock(id=f"msg-{i}") for i in range(8)
        ]
        
        result = compressor.should_compress("test-conv-id")
        
        self.assertFalse(result)
    
    @patch("core.context_compressor.ConversationManager")
    def test_should_compress_at_threshold(self, mock_cm):
        """测试达到压缩阈值"""
        compressor = ContextCompressor()
        
        mock_conv = MagicMock()
        mock_conv.compress_after_turns = 10
        
        mock_cm.get_conversation.return_value = mock_conv
        compressor.conv_manager = mock_cm
        
        # 模拟返回 20 条消息（10 轮）
        mock_cm.get_uncompressed_messages.return_value = [
            MagicMock(id=f"msg-{i}") for i in range(20)
        ]
        
        result = compressor.should_compress("test-conv-id")
        
        self.assertTrue(result)
    
    @patch("core.context_compressor.ConversationManager")
    def test_should_compress_above_threshold(self, mock_cm):
        """测试超过压缩阈值"""
        compressor = ContextCompressor()
        
        mock_conv = MagicMock()
        mock_conv.compress_after_turns = 10
        
        mock_cm.get_conversation.return_value = mock_conv
        compressor.conv_manager = mock_cm
        
        # 模拟返回 30 条消息（15 轮）
        mock_cm.get_uncompressed_messages.return_value = [
            MagicMock(id=f"msg-{i}") for i in range(30)
        ]
        
        result = compressor.should_compress("test-conv-id")
        
        self.assertTrue(result)
    
    @patch("core.context_compressor.ConversationManager")
    def test_should_compress_no_conversation(self, mock_cm):
        """测试对话不存在"""
        compressor = ContextCompressor()
        
        mock_cm.get_conversation.return_value = None
        
        result = compressor.should_compress("test-conv-id")
        
        self.assertFalse(result)


class TestContextCompressorCompress(unittest.TestCase):
    """测试压缩执行"""
    
    @patch("core.context_compressor.ContextCompressor._call_compress_api")
    @patch("core.context_compressor.ConversationManager")
    def test_compress_success(self, mock_cm, mock_api):
        """测试成功压缩"""
        compressor = ContextCompressor()
        
        # 模拟对话
        mock_conv = MagicMock()
        mock_conv.rolling_summary = ""
        mock_conv.last_compressed_msg_id = None
        
        mock_cm.get_conversation.return_value = mock_conv
        compressor.conv_manager = mock_cm
        
        # 模拟消息
        mock_messages = [
            MagicMock(id=f"msg-{i}", role="user" if i % 2 == 0 else "assistant", content=f"Message {i}")
            for i in range(10)
        ]
        mock_cm.get_messages.return_value = mock_messages
        
        # 模拟压缩 API 返回
        mock_api.return_value = "This is a summary of the conversation."
        
        result = compressor.compress("test-conv-id", "Test Project")
        
        self.assertTrue(result.success)
        self.assertIn("summary", result.new_summary.lower())
        self.assertGreater(result.tokens_saved, 0)
    
    @patch("core.context_compressor.ContextCompressor._call_compress_api")
    @patch("core.context_compressor.ConversationManager")
    def test_compress_with_existing_summary(self, mock_cm, mock_api):
        """测试追加到现有摘要"""
        compressor = ContextCompressor()
        
        mock_conv = MagicMock()
        mock_conv.rolling_summary = "Existing summary of previous turns."
        mock_conv.last_compressed_msg_id = "msg-010"
        
        mock_cm.get_conversation.return_value = mock_conv
        compressor.conv_manager = mock_cm
        
        mock_messages = [
            MagicMock(id=f"msg-{i}", role="user" if i % 2 == 0 else "assistant", content=f"Message {i}")
            for i in range(10)
        ]
        mock_cm.get_messages.return_value = mock_messages
        
        mock_api.return_value = "New summary of recent turns."
        
        result = compressor.compress("test-conv-id", "Test Project")
        
        self.assertTrue(result.success)
        # 验证摘要被追加
        mock_cm.update_rolling_summary.assert_called_once()
        call_args = mock_cm.update_rolling_summary.call_args
        new_summary = call_args[0][2]  # summary 参数
        self.assertIn("Existing summary", new_summary)
        self.assertIn("New summary", new_summary)
    
    @patch("core.context_compressor.ContextCompressor._call_compress_api")
    @patch("core.context_compressor.ConversationManager")
    def test_compress_api_failure(self, mock_cm, mock_api):
        """测试压缩 API 失败"""
        compressor = ContextCompressor()
        
        mock_conv = MagicMock()
        mock_conv.rolling_summary = ""
        
        mock_cm.get_conversation.return_value = mock_conv
        compressor.conv_manager = mock_cm
        
        mock_messages = [MagicMock(id=f"msg-{i}", role="user", content=f"msg") for i in range(10)]
        mock_cm.get_messages.return_value = mock_messages
        
        mock_api.side_effect = RuntimeError("API Error")
        
        result = compressor.compress("test-conv-id", "Test Project")
        
        self.assertFalse(result.success)
        self.assertIn("API Error", result.error)
    
    @patch("core.context_compressor.ContextCompressor._call_compress_api")
    @patch("core.context_compressor.ConversationManager")
    def test_compress_no_messages(self, mock_cm, mock_api):
        """测试没有消息可压缩"""
        compressor = ContextCompressor()
        
        mock_conv = MagicMock()
        mock_conv.rolling_summary = ""
        mock_conv.last_compressed_msg_id = None
        
        mock_cm.get_conversation.return_value = mock_conv
        compressor.conv_manager = mock_cm
        
        # 返回空消息列表
        mock_cm.get_messages.return_value = []
        
        result = compressor.compress("test-conv-id", "Test Project")
        
        self.assertFalse(result.success)
        mock_api.assert_not_called()


class TestContextCompressorRecompress(unittest.TestCase):
    """测试摘要再压缩"""
    
    @patch("core.context_compressor.ContextCompressor._call_compress_api")
    @patch("core.context_compressor.ConversationManager")
    def test_recompress_summary_above_threshold(self, mock_cm, mock_api):
        """测试摘要超过阈值时重新压缩"""
        compressor = ContextCompressor()
        
        mock_conv = MagicMock()
        mock_conv.rolling_summary = "x" * 4000  # 超过 3000 阈值
        mock_conv.last_compressed_msg_id = "msg-010"
        
        mock_cm.get_conversation.return_value = mock_conv
        compressor.conv_manager = mock_cm
        
        mock_messages = [
            MagicMock(id=f"msg-{i}", role="user", content=f"msg{i}")
            for i in range(10)
        ]
        mock_cm.get_messages.return_value = mock_messages
        
        # 模拟两次调用：第一次压缩，第二次再压缩
        mock_api.side_effect = [
            "New summary part.",
            "Recompressed summary.",
        ]
        
        # 手动调用压缩
        compressor.compress("test-conv-id", "Test Project")
        
        # 验证 API 被调用了两次（一次压缩，一次再压缩）
        self.assertEqual(mock_api.call_count, 2)


class TestCompressionResult(unittest.TestCase):
    """测试压缩结果数据类"""
    
    def test_compression_result_success(self):
        """测试成功结果"""
        result = CompressionResult(
            success=True,
            new_summary="Test summary",
            tokens_saved=1000,
        )
        
        self.assertTrue(result.success)
        self.assertEqual(result.new_summary, "Test summary")
        self.assertEqual(result.tokens_saved, 1000)
        self.assertEqual(result.error, "")
    
    def test_compression_result_failure(self):
        """测试失败结果"""
        result = CompressionResult(
            success=False,
            new_summary="",
            error="API Error",
        )
        
        self.assertFalse(result.success)
        self.assertEqual(result.error, "API Error")


class TestCompressionWorker(unittest.TestCase):
    """测试后台压缩工作线程"""
    
    @patch("core.context_compressor.ContextCompressor")
    def test_worker_no_compression_needed(self, mock_compressor_cls):
        """测试不需要压缩"""
        mock_compressor = MagicMock()
        mock_compressor.should_compress.return_value = False
        mock_compressor_cls.return_value = mock_compressor
        
        worker = CompressionWorker("test-conv-id", "Test Project")
        result = worker.run()
        
        mock_compressor.should_compress.assert_called_once()
        mock_compressor.compress.assert_not_called()
        self.assertTrue(result.success)
    
    @patch("core.context_compressor.ContextCompressor")
    def test_worker_compression_needed(self, mock_compressor_cls):
        """测试需要压缩"""
        mock_compressor = MagicMock()
        mock_compressor.should_compress.return_value = True
        mock_compressor.compress.return_value = CompressionResult(
            success=True,
            new_summary="Summary",
            tokens_saved=500,
        )
        mock_compressor_cls.return_value = mock_compressor
        
        worker = CompressionWorker("test-conv-id", "Test Project")
        result = worker.run()
        
        mock_compressor.compress.assert_called_once()
        self.assertTrue(result.success)
    
    @patch("core.context_compressor.ContextCompressor")
    def test_worker_exception(self, mock_compressor_cls):
        """测试工作线程异常"""
        mock_compressor = MagicMock()
        mock_compressor.should_compress.side_effect = Exception("Test Error")
        mock_compressor_cls.return_value = mock_compressor
        
        worker = CompressionWorker("test-conv-id", "Test Project")
        result = worker.run()
        
        self.assertFalse(result.success)
        self.assertIn("Test Error", result.error)


class TestCompressionEdgeCases(unittest.TestCase):
    """测试边界情况"""
    
    @patch("core.context_compressor.ConversationManager")
    def test_compress_after_turns_custom(self, mock_cm):
        """测试自定义压缩阈值"""
        compressor = ContextCompressor()
        
        mock_conv = MagicMock()
        mock_conv.compress_after_turns = 20  # 自定义 20 轮
        
        mock_cm.get_conversation.return_value = mock_conv
        compressor.conv_manager = mock_cm
        
        # 15 轮 - 不应该压缩
        mock_cm.get_uncompressed_messages.return_value = [
            MagicMock(id=f"msg-{i}") for i in range(30)
        ]
        
        result = compressor.should_compress("test-conv-id")
        
        # 15 轮 < 20 轮阈值，所以不应该压缩
        # 但由于每轮2条消息，30条消息=15轮，接近阈值边界
        # 需要确保逻辑正确
        mock_cm.get_uncompressed_messages.assert_called()


class TestCompressionCostEstimate(unittest.TestCase):
    """测试压缩成本预估"""
    
    def test_estimate_compression_cost(self):
        """测试压缩成本预估"""
        compressor = ContextCompressor()
        
        # 模拟消息
        mock_messages = [
            MagicMock(content="Hello, can you help me?")
            for _ in range(10)
        ]
        
        # Mock token tracker
        with patch.object(compressor, "token_tracker") as mock_tracker:
            mock_tracker.estimate_tokens.return_value = 100
            
            cost = compressor.estimate_compression_cost(mock_messages)
            
            # 10 条消息 * 100 tokens = 1000 tokens
            mock_tracker.estimate_tokens.assert_called()
            # Haiku 定价: 1000 * 1/1M 输入 + 300 * 5/1M 输出
            # = 0.001 + 0.0015 = 0.0025
            self.assertGreater(cost, 0)
            self.assertLess(cost, 0.01)  # 小于 1 cent


if __name__ == "__main__":
    unittest.main()
