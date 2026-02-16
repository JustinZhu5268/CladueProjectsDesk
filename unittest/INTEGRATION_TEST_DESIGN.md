# ClaudeStation PRD v3 集成测试设计文档

## 概述

本文档描述 ClaudeStation PRD v3 功能的集成测试设计，涵盖所有功能点、用户操作流程和测试覆盖情况。

## 测试运行

```bash
# 运行所有测试（包括单元测试和集成测试）
python unittest/run_tests.py

# 运行集成测试
python unittest/test_integration.py
```

## 测试统计

| 类别 | 测试数量 |
|------|----------|
| 单元测试 | 170 |
| 集成测试 | 16 |
| **总计** | **186** |

---

## 一、集成测试覆盖的功能模块

### 1. 项目全生命周期 (TestProjectLifecycle)

**测试场景：**
- 创建项目
- 更新项目设置
- 添加文档
- 获取项目文档
- 获取项目上下文
- 删除项目（级联删除）

**测试用例：**
```python
def test_complete_project_workflow(self):
    """完整项目工作流"""
    # 1. 创建项目
    project = pm.create(name="AI Coding Assistant", ...)
    # 2. 更新项目设置
    pm.update(project.id, name="Updated Project", ...)
    # 3. 添加文档
    doc_result = dp.add_document(project.id, file_path)
    # 4. 获取项目文档
    docs = dp.get_project_documents(project.id)
    # 5. 获取项目上下文
    context = dp.get_project_context(project.id)
    # 6. 删除项目
    pm.delete(project.id)
```

### 2. 对话全生命周期 (TestConversationLifecycle)

**测试场景：**
- 创建对话
- 添加用户消息
- 添加助手消息
- 获取对话历史
- 更新对话标题
- 删除对话

**测试用例：**
```python
def test_complete_conversation_workflow(self):
    """完整对话工作流"""
    # 1. 创建项目
    project = pm.create("Test Project")
    # 2. 创建对话
    conv = cm.create_conversation(project_id, "Coding Help")
    # 3. 添加消息
    msg1 = cm.add_message(conv.id, "user", "How do I reverse...")
    msg2 = cm.add_message(conv.id, "assistant", "You can use...")
    # 4. 获取消息
    messages = cm.get_messages(conv.id)
    # 5. 更新对话
    cm.rename_conversation(conv.id, "Updated Title")
    # 6. 删除对话
    cm.delete_conversation(conv.id)
```

### 3. 四层上下文构建 (TestContextBuilderFlow)

**测试场景：**
- Layer 1: System Prompt + Documents (缓存)
- Layer 2: Rolling Summary (条件性缓存)
- Layer 3: Recent Messages (未缓存)
- Layer 4: Current User Message

**测试用例：**
```python
def test_four_layer_context_building(self):
    """测试四层上下文构建"""
    # Setup: 创建项目 + 文档
    project = pm.create("Test", system_prompt="You are...")
    dp.add_document(project.id, "test.txt")
    
    # Setup: 创建对话 + 15轮消息
    conv = cm.create_conversation(project.id, "Test")
    for i in range(15):
        cm.add_message(conv.id, "user", f"Question {i}")
        cm.add_message(conv.id, "assistant", f"Answer {i}")
    
    # 测试: 构建上下文
    system_content, messages, tokens = cb.build(
        project_id=project.id,
        conversation_id=conv.id,
        user_message="How to use list?",
        system_prompt="You are...",
        model_id="claude-sonnet-4-5-20250929"
    )
    
    # 验证 Layer 1 有 cache_control
    self.assertIn("cache_control", system_content[0])
```

### 4. Token 追踪与成本计算 (TestTokenTrackingFlow)

**测试场景：**
- 正常请求成本计算
- 缓存命中节省计算
- 不同缓存 TTL (5m vs 1h) 对比

**测试用例：**
```python
def test_cost_calculation_with_cache(self):
    """测试缓存成本计算"""
    tracker = TokenTracker(cache_ttl="5m")
    usage = UsageInfo(
        input_tokens=5000,
        output_tokens=500,
        cache_creation_tokens=50000,
        cache_read_tokens=45000,
    )
    cost = tracker.calculate_cost("claude-sonnet-4-5-20250929", usage)
    
    # 验证: cache_write = 50000 * 3/1M * 1.25
    # 验证: cache_read = 45000 * 3/1M * 0.1
    expected = 0.015 + 0.0075 + 0.1875 + 0.0135
    self.assertAlmostEqual(cost, expected, places=4)
```

### 5. 对话压缩流程 (TestCompressionFlow)

**测试场景：**
- 对话轮数达到阈值触发压缩
- should_compress 正确判断

**测试用例：**
```python
def test_compression_trigger_and_execution(self):
    """测试压缩触发"""
    # 添加 12 轮对话 (默认阈值 10)
    for i in range(12):
        cm.add_message(conv.id, "user", f"Q{i}")
        cm.add_message(conv.id, "assistant", f"A{i}")
    
    # 验证应该触发压缩
    should_compress = compressor.should_compress(conv.id)
    self.assertTrue(should_compress)
```

### 6. API 客户端 (TestAPIClientFlow)

**测试场景：**
- 配置 API 密钥
- 代理配置
- 错误处理

**测试用例：**
```python
def test_api_client_configuration(self):
    client = ClaudeClient()
    client.configure("sk-test-key-12345")
    self.assertTrue(client.is_configured)

def test_api_client_error_handling(self):
    client = ClaudeClient()
    events = list(client.stream_message(...))
    self.assertEqual(events[0].type, "error")
```

### 7. 数据库 (TestDatabaseMigration)

**测试场景：**
- 表结构初始化
- 新增字段验证

**测试用例：**
```python
def test_database_initialization(self):
    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    self.assertIn("projects", table_names)
    self.assertIn("conversations", table_names)

def test_new_columns_exist(self):
    result = db.execute("PRAGMA table_info(conversations)")
    columns = [r["name"] for r in result]
    self.assertIn("rolling_summary", columns)
    self.assertIn("last_compressed_msg_id", columns)
```

### 8. 配置参数验证 (TestConfigurationFlow)

**测试场景：**
- PRD v3 配置参数
- 模型定价
- 缓存参数

**测试用例：**
```python
def test_prd_v3_configurations(self):
    self.assertEqual(COMPRESS_AFTER_TURNS, 10)
    self.assertEqual(MAX_SUMMARY_TOKENS, 500)
    self.assertEqual(CACHE_WRITE_MULTIPLIER_5M, 1.25)
    self.assertEqual(CACHE_READ_MULTIPLIER, 0.10)
```

### 9. UI 模拟交互 (TestUIMockInteraction)

**测试场景：**
- 用户消息流程
- Markdown 渲染

**测试用例：**
```python
def test_user_message_flow(self):
    system_content, messages, tokens = cb.build(...)
    self.assertEqual(messages[-1]["role"], "user")
    self.assertEqual(messages[-1]["content"], user_message)
```

### 10. 完整用户场景 (TestCompleteUserScenario)

**测试场景：**
- 完整用户旅程：项目 → 对话 → 上下文 → 压缩 → 成本

---

## 二、功能覆盖矩阵

| 功能模块 | 单元测试 | 集成测试 | API 覆盖 |
|----------|----------|----------|----------|
| 项目管理 | ✓ | ✓ | create, update, delete, get |
| 对话管理 | ✓ | ✓ | create, add_message, get_messages |
| 文档处理 | ✓ | ✓ | add_document, get_project_context |
| 上下文构建 | ✓ | ✓ | build, estimate_request |
| Token 追踪 | ✓ | ✓ | calculate_cost, estimate_tokens |
| 对话压缩 | ✓ | ✓ | compress, should_compress |
| API 客户端 | ✓ | ✓ | configure, stream_message |
| Markdown 渲染 | ✓ | ✓ | render_markdown, get_chat_html_template |
| 数据库 | ✓ | ✓ | execute, initialize |

---

## 三、API 覆盖详情

### 核心 API

| 类 | 方法 | 测试覆盖 |
|----|------|----------|
| ProjectManager | create | ✓ |
| ProjectManager | update | ✓ |
| ProjectManager | delete | ✓ |
| ProjectManager | get | ✓ |
| ConversationManager | create_conversation | ✓ |
| ConversationManager | add_message | ✓ |
| ConversationManager | get_messages | ✓ |
| ConversationManager | rename_conversation | ✓ |
| ConversationManager | delete_conversation | ✓ |
| DocumentProcessor | add_document | ✓ |
| DocumentProcessor | get_project_context | ✓ |
| ContextBuilder | build | ✓ |
| TokenTracker | calculate_cost | ✓ |
| TokenTracker | estimate_tokens | ✓ |
| ContextCompressor | should_compress | ✓ |
| ClaudeClient | configure | ✓ |
| ClaudeClient | stream_message | ✓ |

---

## 四、测试设计原则

### 1. Mock 策略
- 不调用实际 Anthropic API
- 使用临时数据库隔离测试
- Mock 第三方依赖

### 2. 隔离性
- 每个测试使用独立数据库
- 测试间无依赖
- 可并行运行

### 3. 覆盖率
- 基本功能路径
- 边界条件
- 错误处理

### 4. 可维护性
- 清晰的测试名称
- 完整的文档字符串
- 常用的 TestFixtures

---

## 五、边界情况覆盖

| 边界情况 | 测试用例 |
|----------|----------|
| 空项目 | test_project_workflow |
| 无消息对话 | test_conversation_workflow |
| 大量消息 (15+轮) | test_four_layer_context_building |
| 压缩阈值 (10轮) | test_compression_trigger |
| 空 Token | test_cost_calculation |
| 缓存 TTL 切换 | test_cache_ttl_comparison |

---

## 六、不消耗 Tokens 的设计

集成测试设计为**不消耗实际 API tokens**：

1. **Mock API 调用** - 所有对 Claude API 的调用都被 mock
2. **本地计算** - Token 计算使用本地估算
3. **临时数据库** - 使用临时 SQLite 数据库
4. **无网络请求** - 测试完全离线运行

---

## 七、运行结果

```
Test Summary
============
Tests run: 186
Failures: 0
Errors: 0
Skipped: 0
OK ✅
```

所有测试通过，无失败！
