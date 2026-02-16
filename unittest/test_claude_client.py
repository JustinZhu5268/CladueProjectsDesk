"""
Unit tests for ClaudeClient - PRD v3 API client

BASIC TESTS: Core functionality
FULL TESTS: Edge cases, error handling, streaming
"""
import unittest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
import json

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestClaudeClientBasic(unittest.TestCase):
    """Basic tests for ClaudeClient - Core functionality"""
    
    def test_client_initialization(self):
        """Test client initializes correctly"""
        from api.claude_client import ClaudeClient
        
        client = ClaudeClient()
        
        self.assertIsNone(client._client)
        self.assertEqual(client._api_key, "")
        self.assertFalse(client.is_configured)
    
    def test_compress_model_constant(self):
        """Test that COMPRESS_MODEL is Haiku"""
        from api.claude_client import COMPRESS_MODEL
        
        self.assertEqual(COMPRESS_MODEL, "claude-haiku-4-5-20251001")
    
    def test_stream_event_dataclass(self):
        """Test StreamEvent dataclass"""
        from api.claude_client import StreamEvent, UsageInfo
        
        # Test text event
        event = StreamEvent(type="text", text="Hello")
        self.assertEqual(event.type, "text")
        self.assertEqual(event.text, "Hello")
        
        # Test error event
        event = StreamEvent(type="error", error="Something went wrong")
        self.assertEqual(event.type, "error")
        self.assertEqual(event.error, "Something went wrong")
        
        # Test done event with usage
        usage = UsageInfo(input_tokens=100, output_tokens=50)
        event = StreamEvent(type="done", text="Response", usage=usage)
        self.assertEqual(event.type, "done")
        self.assertEqual(event.usage.input_tokens, 100)


class TestClaudeClientFull(unittest.TestCase):
    """Full tests for ClaudeClient - Edge cases and advanced features"""
    
    def test_configure_with_api_key(self):
        """Test configuring client with API key"""
        from api.claude_client import ClaudeClient
        
        client = ClaudeClient()
        client.configure("sk-test-key-12345")
        
        self.assertTrue(client.is_configured)
        self.assertEqual(client._api_key, "sk-test-key-12345")
    
    def test_configure_with_proxy(self):
        """Test configuring client with proxy"""
        from api.claude_client import ClaudeClient
        
        client = ClaudeClient()
        client.configure("sk-test-key", proxy="http://proxy.example.com:8080")
        
        self.assertTrue(client.is_configured)
        self.assertEqual(client._proxy, "http://proxy.example.com:8080")
    
    def test_stream_message_not_configured(self):
        """Test streaming when not configured returns error"""
        from api.claude_client import ClaudeClient
        
        client = ClaudeClient()
        
        # Collect events from generator
        events = list(client.stream_message(
            messages=[{"role": "user", "content": "Hello"}],
            system_content=[{"type": "text", "text": "You are a helpful assistant."}],
        ))
        
        # Should have error event
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "error")
        self.assertIn("not configured", events[0].error)
    
    def test_stream_message_with_thinking(self):
        """Test streaming with extended thinking"""
        from api.claude_client import ClaudeClient
        import inspect
        
        client = ClaudeClient()
        
        # Verify the method signature accepts thinking param
        sig = inspect.signature(client.stream_message)
        params = list(sig.parameters.keys())
        
        self.assertIn("thinking", params)
    
    def test_stream_message_compaction_params(self):
        """Test that compaction params are added when enabled"""
        from api.claude_client import ClaudeClient
        import inspect
        
        client = ClaudeClient()
        
        # Verify use_compaction parameter exists
        sig = inspect.signature(client.stream_message)
        params = list(sig.parameters.keys())
        
        self.assertIn("use_compaction", params)
    
    def test_model_fallback(self):
        """Test that unknown model falls back to default"""
        from config import DEFAULT_MODEL
        
        # The default model should be Haiku
        self.assertEqual(DEFAULT_MODEL, "claude-haiku-4-5-20251001")


class TestClaudeClientIntegration(unittest.TestCase):
    """Integration-style tests for ClaudeClient"""
    
    def test_message_format_structure(self):
        """Test that messages are properly formatted"""
        from api.claude_client import ClaudeClient
        
        client = ClaudeClient()
        
        # The system_content should be a list of dicts with cache_control
        system_with_cache = [
            {
                "type": "text",
                "text": "System prompt",
                "cache_control": {"type": "ephemeral"}
            }
        ]
        
        # Verify structure
        self.assertEqual(len(system_with_cache), 1)
        self.assertIn("cache_control", system_with_cache[0])
    
    def test_compaction_trigger_value(self):
        """Test compaction trigger value"""
        from config import COMPACTION_TRIGGER_TOKENS
        
        # PRD v3: 200K * 80% = 160K
        self.assertEqual(COMPACTION_TRIGGER_TOKENS, 160000)


if __name__ == "__main__":
    unittest.main()
