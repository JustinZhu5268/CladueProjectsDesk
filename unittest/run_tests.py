#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ClaudeStation PRD v3 Unit Tests Runner

Usage:
    python run_tests.py              # Run all tests
    python run_tests.py test_config # Run specific test module
"""
import sys
import unittest
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def discover_tests():
    """Discover all tests in the unittest directory"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    test_dir = PROJECT_ROOT / "unittest"
    
    # Load all test modules
    test_files = [
        "test_config",
        "test_token_tracker", 
        "test_context_compressor",
        "test_context_builder",
        "test_database",
        "test_conversation_manager",
        # New test files (PRD v3 features)
        "test_project_manager",
        "test_document_processor",
        "test_markdown_renderer",
        "test_claude_client",
    ]
    
    # Change to test directory to allow imports
    import os
    old_cwd = os.getcwd()
    os.chdir(test_dir)
    
    try:
        for module in test_files:
            try:
                suite.addTests(loader.loadTestsFromName(module))
                print(f"[OK] Loaded {module}")
            except Exception as e:
                print(f"[FAIL] Failed to load {module}: {e}")
    finally:
        os.chdir(old_cwd)
    
    return suite


def main():
    """Main entry point"""
    print("=" * 60)
    print("ClaudeStation PRD v3 Unit Tests")
    print("=" * 60)
    print()
    
    # Discover and run tests
    suite = discover_tests()
    
    print()
    print("Running tests...")
    print("-" * 60)
    
    # Run with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print()
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    # Return exit code
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
