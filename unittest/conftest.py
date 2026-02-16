"""
共享的测试 fixtures 和工具函数
"""
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 添加项目根目录到 path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def temp_dir():
    """创建临时目录用于测试"""
    temp_path = tempfile.mkdtemp()
    yield Path(temp_path)
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def mock_db(temp_dir):
    """创建模拟的数据库"""
    from unittest.mock import MagicMock
    
    # 创建一个内存数据库用于测试
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    
    mock_db = MagicMock()
    mock_db._conn = conn
    
    # Mock execute 方法
    def mock_execute(sql, params=()):
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    
    def mock_execute_one(sql, params=()):
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchone()
    
    mock_db.execute = mock_execute
    mock_db.execute_one = mock_execute_one
    
    return mock_db


@pytest.fixture
def sample_project():
    """示例项目数据"""
    return {
        "id": "test-project-001",
        "name": "Test Project",
        "system_prompt": "You are a helpful coding assistant.",
        "default_model": "claude-sonnet-4-5-20250929",
        "settings": {
            "cache_ttl": "5m",
            "compress_after_turns": 10,
        }
    }


@pytest.fixture
def sample_conversation():
    """示例对话数据"""
    return {
        "id": "test-conv-001",
        "project_id": "test-project-001",
        "title": "Test Conversation",
        "model_override": None,
        "is_archived": False,
        "rolling_summary": "",
        "last_compressed_msg_id": None,
        "summary_token_count": 0,
        "compress_after_turns": 10,
    }


@pytest.fixture
def sample_messages():
    """示例消息列表"""
    return [
        {
            "id": "msg-001",
            "conversation_id": "test-conv-001",
            "role": "user",
            "content": "Hello, can you help me write a Python function?",
        },
        {
            "id": "msg-002", 
            "conversation_id": "test-conv-001",
            "role": "assistant",
            "content": "Of course! I'd be happy to help you write a Python function. What kind of function do you need?",
        },
        {
            "id": "msg-003",
            "conversation_id": "test-conv-001",
            "role": "user",
            "content": "I need a function to calculate factorial.",
        },
        {
            "id": "msg-004",
            "conversation_id": "test-conv-001",
            "role": "assistant",
            "content": "Here's a Python function to calculate factorial:\n\n```python\ndef factorial(n):\n    if n < 0:\n        raise ValueError(\"Factorial is not defined for negative numbers\")\n    if n == 0 or n == 1:\n        return 1\n    return n * factorial(n - 1)\n```",
        },
    ]


@pytest.fixture
def sample_documents():
    """示例文档数据"""
    return [
        {
            "id": "doc-001",
            "filename": "readme.md",
            "extracted_text": "# Project Readme\n\nThis is a test project.",
            "token_count": 20,
        },
        {
            "id": "doc-002",
            "filename": "requirements.txt",
            "extracted_text": "pytest>=7.0.0\nanthropic>=0.40.0",
            "token_count": 10,
        },
    ]


def create_mock_message(**kwargs):
    """创建模拟的消息对象"""
    from dataclasses import dataclass
    from core.conversation_manager import Message
    
    defaults = {
        "id": "mock-msg-001",
        "conversation_id": "test-conv-001",
        "role": "user",
        "content": "Test message content",
        "thinking_content": "",
        "attachments": [],
        "model_used": "",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "cost_usd": 0.0,
        "created_at": "2026-01-01T00:00:00",
    }
    defaults.update(kwargs)
    
    return Message(**defaults)


def create_mock_conversation(**kwargs):
    """创建模拟的对话对象"""
    from dataclasses import dataclass
    from core.conversation_manager import Conversation
    
    defaults = {
        "id": "mock-conv-001",
        "project_id": "test-project-001",
        "title": "Test Conversation",
        "model_override": None,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "is_archived": False,
        "rolling_summary": "",
        "last_compressed_msg_id": None,
        "summary_token_count": 0,
        "compress_after_turns": 10,
    }
    defaults.update(kwargs)
    
    return Conversation(**defaults)
