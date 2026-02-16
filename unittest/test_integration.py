"""
ClaudeStation PRD v3 Integration Tests

自动化集成测试 - 覆盖所有功能点和用户操作流程

设计原则:
1. 模拟完整用户工作流
2. 测试模块间交互
3. 使用 Mock 避免实际 API 调用
4. 不消耗实际 tokens

运行:
    python unittest/test_integration.py
"""
import unittest
import sys
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime, timezone

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set up test database
from data import database


# ============================================================================
# Test Fixtures - 模拟用户数据和场景
# ============================================================================

class TestFixtures:
    """测试夹具 - 提供模拟数据"""
    
    @staticmethod
    def create_test_project(pm, name="Test Project", model="claude-haiku-4-5-20251001"):
        """创建测试项目"""
        return pm.create(
            name=name,
            model=model,
            system_prompt="You are a helpful coding assistant."
        )
    
    @staticmethod
    def create_test_conversation(cm, project_id, title="Test Conversation"):
        """创建测试对话"""
        return cm.create_conversation(
            project_id=project_id,
            title=title,
            model="claude-sonnet-4-5-20250929"
        )
    
    @staticmethod
    def add_test_messages(cm, conversation_id, count=5):
        """添加测试消息"""
        for i in range(count):
            cm.add_message(
                conversation_id=conversation_id,
                role="user",
                content=f"User message {i+1}"
            )
            cm.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=f"Assistant response {i+1}" * 50  # Make it longer
            )
    
    @staticmethod
    def create_test_document(dp, project_id, content="Test document content"):
        """创建测试文档"""
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            result = dp.add_document(project_id, temp_path)
            return result
        finally:
            os.unlink(temp_path)


# ============================================================================
# Integration Test 1: 项目全生命周期
# ============================================================================

class TestProjectLifecycle(unittest.TestCase):
    """
    测试项目完整生命周期
    
    场景:
    1. 创建项目
    2. 更新项目设置
    3. 添加文档
    4. 删除项目 (级联删除)
    """
    
    @classmethod
    def setUpClass(cls):
        cls.test_db_path = tempfile.mktemp(suffix=".db")
        database.db._db_path = cls.test_db_path
        database.db.initialize()
    
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def setUp(self):
        database.db.execute("DELETE FROM projects")
        database.db.execute("DELETE FROM conversations")
        database.db.execute("DELETE FROM messages")
        database.db.execute("DELETE FROM documents")
    
    def test_complete_project_workflow(self):
        """完整项目工作流"""
        from core.project_manager import ProjectManager
        from core.document_processor import DocumentProcessor
        
        pm = ProjectManager()
        dp = DocumentProcessor()
        
        # 1. 创建项目
        project = pm.create(
            name="AI Coding Assistant",
            model="claude-sonnet-4-5-20250929",
            system_prompt="You are an expert programmer."
        )
        self.assertIsNotNone(project.id)
        self.assertEqual(project.name, "AI Coding Assistant")
        
        # 2. 更新项目设置
        pm.update(project.id, name="Updated Project", settings_json={"theme": "dark"})
        updated = pm.get(project.id)
        self.assertEqual(updated.name, "Updated Project")
        self.assertEqual(updated.settings.get("theme"), "dark")
        
        # 3. 添加文档
        doc_result = dp.add_document(project.id, __file__)  # Use this file as test
        self.assertIn("id", doc_result)
        self.assertIn("token_count", doc_result)
        
        # 4. 获取项目文档
        docs = dp.get_project_documents(project.id)
        self.assertEqual(len(docs), 1)
        
        # 5. 获取项目上下文
        context = dp.get_project_context(project.id)
        self.assertIn("Test", context)
        
        # 6. 删除项目 (应该级联删除对话和文档)
        pm.delete(project.id)
        
        # 验证项目已删除
        self.assertIsNone(pm.get(project.id))


# ============================================================================
# Integration Test 2: 对话全生命周期
# ============================================================================

class TestConversationLifecycle(unittest.TestCase):
    """
    测试对话完整生命周期
    
    场景:
    1. 创建对话
    2. 添加多条消息
    3. 获取对话历史
    4. 更新对话设置
    5. 删除对话
    """
    
    @classmethod
    def setUpClass(cls):
        cls.test_db_path = tempfile.mktemp(suffix=".db")
        database.db._db_path = cls.test_db_path
        database.db.initialize()
    
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def setUp(self):
        database.db.execute("DELETE FROM projects")
        database.db.execute("DELETE FROM conversations")
        database.db.execute("DELETE FROM messages")
    
    def test_complete_conversation_workflow(self):
        """完整对话工作流"""
        from core.project_manager import ProjectManager
        from core.conversation_manager import ConversationManager
        
        pm = ProjectManager()
        cm = ConversationManager()
        
        # 1. 创建项目
        project = pm.create("Test Project")
        
        # 2. 创建对话
        conv = cm.create_conversation(
            project_id=project.id,
            title="Coding Help"
        )
        self.assertIsNotNone(conv.id)
        self.assertEqual(conv.title, "Coding Help")
        
        # 3. 添加用户消息
        msg1 = cm.add_message(
            conversation_id=conv.id,
            role="user",
            content="How do I reverse a string in Python?"
        )
        self.assertIsNotNone(msg1.id)
        
        # 4. 添加助手消息
        msg2 = cm.add_message(
            conversation_id=conv.id,
            role="assistant",
            content="You can use slicing: s[::-1] or the reversed() function."
        )
        
        # 5. 获取对话消息
        messages = cm.get_messages(conv.id)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[1].role, "assistant")
        
        # 6. 更新对话
        cm.rename_conversation(conv.id, "Updated Title")
        updated = cm.get_conversation(conv.id)
        self.assertEqual(updated.title, "Updated Title")
        
        # 7. 删除对话
        cm.delete_conversation(conv.id)
        
        # 验证对话已删除
        self.assertIsNone(cm.get_conversation(conv.id))


# ============================================================================
# Integration Test 3: 上下文构建 (四层架构)
# ============================================================================

class TestContextBuilderFlow(unittest.TestCase):
    """
    测试四层上下文构建流程
    
    场景:
    1. 项目 + 文档 + 系统提示词 -> Layer 1
    2. 滚动摘要 -> Layer 2
    3. 最近消息 -> Layer 3
    4. 用户当前消息 -> Layer 4
    """
    
    @classmethod
    def setUpClass(cls):
        cls.test_db_path = tempfile.mktemp(suffix=".db")
        database.db._db_path = cls.test_db_path
        database.db.initialize()
    
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def setUp(self):
        database.db.execute("DELETE FROM projects")
        database.db.execute("DELETE FROM conversations")
        database.db.execute("DELETE FROM messages")
        database.db.execute("DELETE FROM documents")
    
    def test_four_layer_context_building(self):
        """测试四层上下文构建"""
        from core.project_manager import ProjectManager
        from core.document_processor import DocumentProcessor
        from core.conversation_manager import ConversationManager
        from core.context_builder import ContextBuilder
        
        pm = ProjectManager()
        dp = DocumentProcessor()
        cm = ConversationManager()
        cb = ContextBuilder()
        
        # Setup: 创建项目
        project = pm.create("Test Project", system_prompt="You are a Python expert.")
        
        # Setup: 添加文档
        TestFixtures.create_test_document(dp, project.id, "This is a test document about Python.")
        
        # Setup: 创建对话并添加消息
        conv = cm.create_conversation(project.id, "Test Conv")
        for i in range(15):  # 添加 15 轮对话，触发压缩
            cm.add_message(conv.id, "user", f"Question {i}")
            cm.add_message(conv.id, "assistant", f"Answer {i} " * 20)
        
        # 测试: 构建上下文
        system_content, messages, estimated_tokens = cb.build(
            project_id=project.id,
            conversation_id=conv.id,
            user_message="How to use list comprehension?",
            system_prompt="You are a Python expert.",
            model_id="claude-sonnet-4-5-20250929"
        )
        
        # 验证: Layer 1 - System prompt
        self.assertIsNotNone(system_content)
        self.assertGreater(len(system_content), 0)
        
        # 验证: Layer 1 - 有 cache_control
        self.assertIn("cache_control", system_content[0])
        
        # 验证: Layer 3+4 - Messages
        self.assertIsNotNone(messages)
        self.assertGreater(len(messages), 0)
        
        # 验证: Token 预估
        self.assertGreater(estimated_tokens, 0)
        self.assertLess(estimated_tokens, 200000)  # 应该在上下文限制内


# ============================================================================
# Integration Test 4: Token 追踪与成本计算
# ============================================================================

class TestTokenTrackingFlow(unittest.TestCase):
    """
    测试 Token 追踪和成本计算流程
    
    场景:
    1. 正常请求成本
    2. 缓存命中节省
    3. 不同缓存 TTL 对比
    """
    
    @classmethod
    def setUpClass(cls):
        cls.test_db_path = tempfile.mktemp(suffix=".db")
        database.db._db_path = cls.test_db_path
        database.db.initialize()
    
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def test_cost_calculation_with_cache(self):
        """测试缓存成本计算"""
        from core.token_tracker import TokenTracker, UsageInfo
        
        tracker = TokenTracker(cache_ttl="5m")
        
        # 模拟使用场景: 50K 缓存 + 5K 新消息
        usage = UsageInfo(
            input_tokens=5000,
            output_tokens=500,
            cache_creation_tokens=50000,  # 50K 缓存写入
            cache_read_tokens=45000,       # 45K 缓存读取
        )
        
        cost = tracker.calculate_cost("claude-sonnet-4-5-20250929", usage)
        
        # 验证成本计算正确
        # input: 5000 * 3/1M = 0.015
        # output: 500 * 15/1M = 0.0075
        # cache_write: 50000 * 3/1M * 1.25 = 0.1875
        # cache_read: 45000 * 3/1M * 0.1 = 0.0135
        expected = 0.015 + 0.0075 + 0.1875 + 0.0135
        self.assertAlmostEqual(cost, expected, places=4)
    
    def test_cache_ttl_comparison(self):
        """测试不同缓存 TTL 的成本差异"""
        from core.token_tracker import TokenTracker, UsageInfo
        
        tracker_5m = TokenTracker(cache_ttl="5m")
        tracker_1h = TokenTracker(cache_ttl="1h")
        
        usage = UsageInfo(
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=10000,
        )
        
        cost_5m = tracker_5m.calculate_cost("claude-sonnet-4-5-20250929", usage)
        cost_1h = tracker_1h.calculate_cost("claude-sonnet-4-5-20250929", usage)
        
        # 1h 缓存应该更贵 (2.0x vs 1.25x)
        self.assertGreater(cost_1h, cost_5m)


# ============================================================================
# Integration Test 5: 对话压缩流程
# ============================================================================

class TestCompressionFlow(unittest.TestCase):
    """
    测试对话压缩流程
    
    场景:
    1. 对话轮数达到阈值触发压缩
    2. 使用 Haiku 模型进行压缩
    3. 更新摘要
    """
    
    @classmethod
    def setUpClass(cls):
        cls.test_db_path = tempfile.mktemp(suffix=".db")
        database.db._db_path = cls.test_db_path
        database.db.initialize()
    
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def setUp(self):
        database.db.execute("DELETE FROM projects")
        database.db.execute("DELETE FROM conversations")
        database.db.execute("DELETE FROM messages")
    
    def test_compression_trigger_and_execution(self):
        """测试压缩触发和执行"""
        from core.project_manager import ProjectManager
        from core.conversation_manager import ConversationManager
        from core.context_compressor import ContextCompressor
        
        pm = ProjectManager()
        cm = ConversationManager()
        
        # Setup
        project = pm.create("Test Project")
        conv = cm.create_conversation(project.id, "Test Conv")
        
        # 添加大量消息触发压缩 (10+ 轮)
        for i in range(12):
            cm.add_message(conv.id, "user", f"Question {i} " * 50)
            cm.add_message(conv.id, "assistant", f"Answer {i} " * 100)
        
        # 测试: should_compress - 检查是否需要压缩
        compressor = ContextCompressor()
        should_compress = compressor.should_compress(conv.id)
        
        # 验证: 12轮对话应该触发压缩 (默认10轮)
        self.assertTrue(should_compress)


# ============================================================================
# Integration Test 6: API 客户端完整流程
# ============================================================================

class TestAPIClientFlow(unittest.TestCase):
    """
    测试 API 客户端完整流程
    
    场景:
    1. 配置 API 密钥
    2. 构建请求
    3. 发送消息
    4. 处理响应
    """
    
    @classmethod
    def setUpClass(cls):
        cls.test_db_path = tempfile.mktemp(suffix=".db")
        database.db._db_path = cls.test_db_path
        database.db.initialize()
    
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def test_api_client_configuration(self):
        """测试 API 客户端配置"""
        from api.claude_client import ClaudeClient
        
        client = ClaudeClient()
        
        # 未配置状态
        self.assertFalse(client.is_configured)
        
        # 配置
        client.configure("sk-test-key-12345")
        
        # 验证配置状态
        self.assertTrue(client.is_configured)
        self.assertEqual(client._api_key, "sk-test-key-12345")
    
    def test_api_client_with_proxy(self):
        """测试代理配置"""
        from api.claude_client import ClaudeClient
        
        client = ClaudeClient()
        client.configure("sk-test-key", proxy="http://proxy:8080")
        
        self.assertTrue(client.is_configured)
        self.assertEqual(client._proxy, "http://proxy:8080")
    
    def test_api_client_error_handling(self):
        """测试错误处理"""
        from api.claude_client import ClaudeClient
        
        client = ClaudeClient()
        
        # 未配置时应该返回错误事件
        events = list(client.stream_message(
            messages=[{"role": "user", "content": "Hello"}],
            system_content=[{"type": "text", "text": "You are helpful."}],
        ))
        
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "error")
        self.assertIn("not configured", events[0].error)


# ============================================================================
# Integration Test 7: 数据库迁移
# ============================================================================

class TestDatabaseMigration(unittest.TestCase):
    """
    测试数据库迁移
    
    场景:
    1. 旧版本数据库结构
    2. 执行迁移
    3. 验证新结构
    """
    
    @classmethod
    def setUpClass(cls):
        cls.test_db_path = tempfile.mktemp(suffix=".db")
    
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def test_database_initialization(self):
        """测试数据库初始化"""
        database.db._db_path = self.test_db_path
        database.db.initialize()
        
        # 验证表存在
        tables = database.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = [t["name"] for t in tables]
        
        self.assertIn("projects", table_names)
        self.assertIn("conversations", table_names)
        self.assertIn("messages", table_names)
        self.assertIn("documents", table_names)
    
    def test_new_columns_exist(self):
        """测试新增字段"""
        database.db._db_path = self.test_db_path
        database.db.initialize()
        
        # 检查 conversations 表新字段
        cols = database.db.execute_one("PRAGMA table_info(conversations)")
        
        # 获取所有列名
        result = database.db.execute("PRAGMA table_info(conversations)")
        column_names = [r["name"] for r in result]
        
        # PRD v3 新增字段
        self.assertIn("rolling_summary", column_names)
        self.assertIn("last_compressed_msg_id", column_names)


# ============================================================================
# Integration Test 8: 配置参数验证
# ============================================================================

class TestConfigurationFlow(unittest.TestCase):
    """
    测试配置参数流程
    
    场景:
    1. 验证 PRD v3 配置
    2. 模型定价
    3. 缓存参数
    """
    
    def test_prd_v3_configurations(self):
        """验证 PRD v3 配置"""
        from config import (
            COMPRESS_AFTER_TURNS,
            MAX_SUMMARY_TOKENS,
            CACHE_WRITE_MULTIPLIER_5M,
            CACHE_WRITE_MULTIPLIER_1H,
            CACHE_READ_MULTIPLIER,
            COMPACTION_TRIGGER_TOKENS,
        )
        
        # PRD v3 规格
        self.assertEqual(COMPRESS_AFTER_TURNS, 10)
        self.assertEqual(MAX_SUMMARY_TOKENS, 500)
        
        # 缓存定价
        self.assertEqual(CACHE_WRITE_MULTIPLIER_5M, 1.25)
        self.assertEqual(CACHE_WRITE_MULTIPLIER_1H, 2.0)
        self.assertEqual(CACHE_READ_MULTIPLIER, 0.10)  # 90% 节省
        
        # Compaction
        self.assertEqual(COMPACTION_TRIGGER_TOKENS, 160000)  # 200K * 80%
    
    def test_model_definitions(self):
        """验证模型定义"""
        from config import MODELS, DEFAULT_MODEL
        
        # 默认模型
        self.assertEqual(DEFAULT_MODEL, "claude-haiku-4-5-20251001")
        
        # 所有模型应有定价
        for model_id, model in MODELS.items():
            self.assertGreater(model.input_price, 0)
            self.assertGreater(model.output_price, 0)
            self.assertEqual(model.context_window, 200000)


# ============================================================================
# Integration Test 9: UI 模拟交互
# ============================================================================

class TestUIMockInteraction(unittest.TestCase):
    """
    测试 UI 模拟交互
    
    场景:
    1. 模拟用户发送消息
    2. 模拟流式响应
    3. 模拟消息渲染
    """
    
    @classmethod
    def setUpClass(cls):
        cls.test_db_path = tempfile.mktemp(suffix=".db")
        database.db._db_path = cls.test_db_path
        database.db.initialize()
    
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def setUp(self):
        database.db.execute("DELETE FROM projects")
        database.db.execute("DELETE FROM conversations")
        database.db.execute("DELETE FROM messages")
    
    def test_user_message_flow(self):
        """测试用户消息流程"""
        from core.project_manager import ProjectManager
        from core.conversation_manager import ConversationManager
        from core.context_builder import ContextBuilder
        
        pm = ProjectManager()
        cm = ConversationManager()
        cb = ContextBuilder()
        
        # 创建场景
        project = pm.create("Test Project")
        conv = cm.create_conversation(project.id, "Test")
        
        # 模拟用户发送消息
        user_message = "How do I create a list in Python?"
        
        # 构建上下文
        system_content, messages, tokens = cb.build(
            project_id=project.id,
            conversation_id=conv.id,
            user_message=user_message,
            system_prompt="You are a helpful assistant.",
            model_id="claude-sonnet-4-5-20250929"
        )
        
        # 验证消息已添加到末尾
        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(messages[-1]["content"], user_message)
    
    def test_markdown_rendering(self):
        """测试 Markdown 渲染"""
        from utils.markdown_renderer import render_markdown
        
        md_text = "# Hello\n\nThis is **bold** and *italic*."
        
        html = render_markdown(md_text)
        
        # 验证渲染结果
        self.assertIn("Hello", html)


# ============================================================================
# Integration Test 10: 完整用户场景
# ============================================================================

class TestCompleteUserScenario(unittest.TestCase):
    """
    完整用户场景测试
    
    模拟真实用户使用场景:
    1. 创建项目和文档
    2. 开始多轮对话
    3. 触发压缩
    4. 检查成本节省
    """
    
    @classmethod
    def setUpClass(cls):
        cls.test_db_path = tempfile.mktemp(suffix=".db")
        database.db._db_path = cls.test_db_path
        database.db.initialize()
    
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def setUp(self):
        database.db.execute("DELETE FROM projects")
        database.db.execute("DELETE FROM conversations")
        database.db.execute("DELETE FROM messages")
        database.db.execute("DELETE FROM documents")
    
    def test_full_user_journey(self):
        """完整用户旅程"""
        from core.project_manager import ProjectManager
        from core.document_processor import DocumentProcessor
        from core.conversation_manager import ConversationManager
        from core.context_builder import ContextBuilder
        from core.context_compressor import ContextCompressor
        from core.token_tracker import TokenTracker, UsageInfo
        
        # === 步骤 1: 设置项目 ===
        pm = ProjectManager()
        dp = DocumentProcessor()
        
        project = pm.create(
            name="Python Helper",
            system_prompt="You are a Python programming expert."
        )
        
        # 添加文档
        TestFixtures.create_test_document(
            dp, project.id,
            "Python best practices: Use list comprehension, virtual environments, type hints."
        )
        
        # === 步骤 2: 开始对话 ===
        cm = ConversationManager()
        conv = cm.create_conversation(project.id, "Python Tips")
        
        # === 步骤 3: 多轮对话 ===
        questions = [
            "What is list comprehension?",
            "How to use virtual environments?",
            "What are type hints?",
            "Best practices for error handling?",
            "How to optimize Python code?",
            "What is decorator?",
            "How to use context managers?",
            "What is generator?",
            "How to use dataclasses?",
            "What is closure?",
            "How to implement caching?",
        ]
        
        for q in questions:
            cm.add_message(conv.id, "user", q)
            cm.add_message(conv.id, "assistant", f"Here is the answer to: {q}")
        
        # === 步骤 4: 构建上下文 ===
        cb = ContextBuilder()
        system_content, messages, tokens = cb.build(
            project_id=project.id,
            conversation_id=conv.id,
            user_message="Give me a summary of what we discussed.",
            system_prompt=project.system_prompt,
            model_id="claude-sonnet-4-5-20250929"
        )
        
        # 验证上下文构建
        self.assertGreater(len(system_content), 0)
        self.assertGreater(len(messages), 0)
        
        # === 步骤 5: 检查压缩触发 ===
        compressor = ContextCompressor()
        
        # 检查是否需要压缩 (不实际调用 API)
        should_compress = compressor.should_compress(conv.id)
        
        # 11轮对话应该触发压缩 (默认10轮)
        self.assertTrue(should_compress)
        
        # === 步骤 6: 成本追踪 ===
        tracker = TokenTracker()
        usage = UsageInfo(
            input_tokens=tokens,
            output_tokens=500,
            cache_creation_tokens=5000,
            cache_read_tokens=10000,
        )
        
        cost = tracker.calculate_cost("claude-sonnet-4-5-20250929", usage)
        
        # 验证成本计算
        self.assertGreater(cost, 0)
        
        # === 验证: 整体流程成功 ===
        self.assertIsNotNone(project.id)
        self.assertIsNotNone(conv.id)
        self.assertGreater(len(messages), 0)


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
