"""Integration Test Runner for ClaudeStation PRD v3"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if __name__ == "__main__":
    import unittest
    # Discover and run integration tests
    loader = unittest.TestLoader()
    suite = loader.discover("unittest", pattern="test_integration.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
