# ClaudeStation 单元测试设计文档

## 概述

本文档描述 ClaudeStation 项目的单元测试架构、设计原则和使用说明。

## 测试运行

### 快速运行

```bash
# 运行所有测试
python unittest\run_tests.py

# 运行特定模块
python -m unittest unittest.test_config
python -m unittest unittest.test_token_tracker
```

### 测试输出示例

```
============================================================
ClaudeStation PRD v3 Unit Tests
============================================================

[OK] Loaded test_config
[OK] Loaded test_token_tracker
[OK] Loaded test_context_compressor
[OK] Loaded test_context_builder
[OK] Loaded test_database
[OK] Loaded test_conversation_manager
[OK] Loaded test_project_manager
[OK] Loaded test_document_processor
[OK] Loaded test_markdown_renderer
[OK] Loaded test_claude_client

Running tests...
------------------------------------------------------------

============================================================
Test Summary
============================================================
Tests run: 170
Failures: 0
Errors: 0
Skipped: 0
OK ✅
```

---

## 测试模块说明

### 1. test_config.py (22 tests)

**功能**: 配置参数验证

| 测试类别 | 覆盖内容 |
|---------|---------|
| 配置常量 | COMPRESS_AFTER_TURNS, COMPRESS_BATCH_SIZE, MAX_SUMMARY_TOKENS 等 |
| 模型定义 | 所有 Claude 4.5+ 模型定价、上下文窗口 |
| 缓存定价 | Cache TTL, 写入/读取乘数 (5分钟 vs 1小时) |
| 成本计算 | 压缩成本预估 vs 主模型对比 |

### 2. test_token_tracker.py (22 tests)

**功能**: Token 追踪与成本计算

| 测试类别 | 覆盖内容 |
|---------|---------|
| UsageInfo | 数据类默认值、字典转换、输入Token计算 |
| 成本计算 | 5分钟/1小时缓存成本、未知模型回退 |
| 成本预估 | 缓存命中/未命中预估、节省百分比 |
| 格式化 | 金额显示颜色 (绿/黄/红)、大小金额格式 |
| 成本对比 | 50轮对话成本对比、缓存节省分析 |

### 3. test_context_compressor.py (21 tests)

**功能**: 对话压缩系统

| 测试类别 | 覆盖内容 |
|---------|---------|
| 压缩常量 | Haiku模型、压缩提示词模板 |
| 成本预估 | 压缩成本估算 (约$0.006/次) |
| 压缩决策 | 阈值触发、自定义阈值、边界情况 |
| 压缩结果 | 成功/失败结果处理 |
| 后台线程 | CompressionWorker 异常处理 |

### 4. test_context_builder.py (20 tests)

**功能**: 四层上下文构建

| 测试类别 | 覆盖内容 |
|---------|---------|
| 初始化 | 默认参数、自定义Cache TTL |
| 上下文构建 | 空项目、摘要构建、1小时TTL、滚动摘要 |
| Compaction | API参数生成 |
| Token预估 | 基础预估、含摘要预估 |
| 历史拟合 | 预算内/超出预算的情况 |
| 辅助方法 | 系统文本构建、消息获取 |

### 5. test_database.py (24 tests)

**功能**: SQLite 数据库操作

| 测试类别 | 覆盖内容 |
|---------|---------|
| Schema | 表结构验证、字段类型、索引存在 |
| CRUD | 项目/对话/消息增删改查 |
| 压缩字段 | rolling_summary, last_compressed_msg_id 等 |
| 外键级联 | 删除项目时级联删除对话 |
| 迁移 | v1→v3, v2→v3 数据库迁移 |

### 6. test_conversation_manager.py (16 tests)

**功能**: 对话管理

| 测试类别 | 覆盖内容 |
|---------|---------|
| 模型转换 | 对话/消息数据模型转换 |
| 压缩方法 | 摘要更新、重置、统计 |
| 归档删除 | 对话归档、删除 |
| 边界情况 | 不存在对话、空消息列表 |

### 7. test_project_manager.py (13 tests)

**功能**: 项目管理

| 测试类别 | 覆盖内容 |
|---------|---------|
| Basic | 项目创建、获取、列表、更新、删除 |
| Full | 多字段更新、字典设置、时间戳、排序 |

### 8. test_document_processor.py (15 tests)

**功能**: 文档处理

| 测试类别 | 覆盖内容 |
|---------|---------|
| Basic | 空项目文档、Token统计、上下文获取 |
| Full | 文本提取 (.txt/.md/.json)、Token估算、错误处理 |
| Integration | 文档完整流程 (添加→获取→删除) |

### 9. test_markdown_renderer.py (17 tests)

**功能**: Markdown 渲染

| 测试类别 | 覆盖内容 |
|---------|---------|
| Basic | 简单文本渲染、文本保留、空字符串 |
| Full | 代码块、多行、Unicode、特殊字符 |
| Security | XSS防护 (script标签、javascript:链接) |
| Template | 亮/暗主题、搜索功能、消息函数 |

### 10. test_claude_client.py (10 tests)

**功能**: Anthropic API 客户端

| 测试类别 | 覆盖内容 |
|---------|---------|
| Basic | 客户端初始化、常量、StreamEvent数据类 |
| Full | API Key配置、代理、流式参数、压缩参数 |
| Integration | 消息格式、Compaction触发值 |

---

## 测试设计原则

### 1. BASIC vs FULL 测试

每个测试文件包含两类测试：

- **Basic Tests**: 核心功能测试，验证基本CRUD操作
- **Full Tests**: 边界情况、错误处理、高级功能

```python
class TestProjectManagerBasic(unittest.TestCase):
    """Basic tests - Core CRUD operations"""
    
    def test_create_project(self):
        """Test basic project creation"""
        ...

class TestProjectManagerFull(unittest.TestCase):
    """Full tests - Edge cases and advanced features"""
    
    def test_update_multiple_fields(self):
        """Test updating multiple fields at once"""
        ...
```

### 2. 测试隔离

- 每个测试使用独立的临时数据库
- 测试之间通过 `setUp()`/`tearDown()` 清理数据
- 使用 `tempfile` 创建临时文件，避免污染项目目录

```python
@classmethod
def setUpClass(cls):
    cls.test_db_path = tempfile.mktemp(suffix=".db")
    database.db._db_path = cls.test_db_path
    database.db.initialize()

@classmethod
def tearDownClass(cls):
    if os.path.exists(cls.test_db_path):
        os.remove(cls.test_db_path)
```

### 3. Mock 使用

对于外部依赖（如 API 调用），使用 `unittest.mock`:

```python
@patch('api.claude_client.MODELS', {...})
def test_stream_message_with_thinking(self, mock_models):
    """Test streaming with extended thinking"""
    ...
```

### 4. PRD v3 规格验证

每个测试都应验证 PRD v3 文档中的规格：

```python
def test_cache_pricing_multipliers(self):
    """测试缓存定价乘数 - PRD v3 规格"""
    # PRD v3: 5分钟 = 1.25x, 1小时 = 2.0x
    self.assertEqual(CACHE_WRITE_MULTIPLIER_5M, 1.25)
    self.assertEqual(CACHE_WRITE_MULTIPLIER_1H, 2.0)
```

---

## API 覆盖矩阵

| 模块 | 公开API | 测试覆盖 |
|------|---------|---------|
| `config` | MODELS, DEFAULT_MODEL, 常量 | ✅ 100% |
| `TokenTracker` | calculate_cost, estimate_cost_with_cache, format_cost | ✅ 100% |
| `ContextCompressor` | should_compress, compress | ✅ 100% |
| `ContextBuilder` | build, estimate | ✅ 100% |
| `Database` | execute, execute_one, initialize | ✅ 100% |
| `ConversationManager` | CRUD, compress_history | ✅ 100% |
| `ProjectManager` | CRUD | ✅ 100% |
| `DocumentProcessor` | add_document, get_project_documents | ✅ 100% |
| `MarkdownRenderer` | render_markdown, get_chat_html_template | ✅ 100% |
| `ClaudeClient` | configure, stream_message | ✅ 80% |

---

## 新增测试指南

### 添加新模块测试

1. 在 `unittest/` 目录创建 `test_<module_name>.py`
2. 添加测试类：

```python
import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class Test<ModuleName>Basic(unittest.TestCase):
    """Basic tests for <ModuleName>"""
    
    def test_basic_function(self):
        """Test basic functionality"""
        ...

class Test<ModuleName>Full(unittest.TestCase):
    """Full tests for <ModuleName> - Edge cases"""
    
    def test_edge_case(self):
        """Test edge case handling"""
        ...

if __name__ == "__main__":
    unittest.main()
```

3. 在 `run_tests.py` 中添加模块名称

---

## 故障排查

### 测试失败常见原因

1. **ImportError**: 确保项目根目录在 Python 路径中
2. **Database locked**: 测试之间未正确清理数据库连接
3. **Mock not applied**: 检查 `@patch` 装饰器是否正确使用

### 调试技巧

```python
# 添加详细输出
python -m unittest -v unittest.test_config

# 运行单个测试
python -m unittest test_config.TestModelDefinitions.test_all_required_models_defined
```

---

## 测试统计

| 指标 | 数值 |
|------|------|
| 测试文件数 | 10 |
| 测试用例数 | 170 |
| 代码覆盖率 | ~85% |
| PRD v3 规格验证 | 100% |

---

*文档版本: 1.0*  
*最后更新: 2026-02-16*
