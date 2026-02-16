"""
Unit tests for ProjectManager - PRD v3 project CRUD operations

BASIC TESTS: Core functionality tests
FULL TESTS: Edge cases, error handling, integration tests
"""
import unittest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import shutil

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set up test database before importing modules
from data import database


class TestProjectManagerBasic(unittest.TestCase):
    """Basic tests for ProjectManager - Core CRUD operations"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test database"""
        cls.test_db_path = tempfile.mktemp(suffix=".db")
        database.db._db_path = cls.test_db_path
        database.db.initialize()
    
    @classmethod
    def tearDownClass(cls):
        """Clean up test database"""
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def setUp(self):
        """Clean database before each test"""
        database.db.execute("DELETE FROM projects")
        database.db.execute("DELETE FROM conversations")
        database.db.execute("DELETE FROM messages")
    
    def test_create_project(self):
        """Test basic project creation"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        project = pm.create("Test Project", model="claude-sonnet-4-5-20250929")
        
        self.assertIsNotNone(project.id)
        self.assertEqual(project.name, "Test Project")
        self.assertEqual(project.default_model, "claude-sonnet-4-5-20250929")
        self.assertIsNotNone(project.created_at)
    
    def test_get_project(self):
        """Test retrieving a project by ID"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        created = pm.create("Test Project")
        
        retrieved = pm.get(created.id)
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, created.id)
        self.assertEqual(retrieved.name, "Test Project")
    
    def test_get_nonexistent_project(self):
        """Test retrieving a project that doesn't exist"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        result = pm.get("nonexistent-id-12345")
        
        self.assertIsNone(result)
    
    def test_list_all_projects(self):
        """Test listing all projects"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        pm.create("Project 1")
        pm.create("Project 2")
        pm.create("Project 3")
        
        projects = pm.list_all()
        
        self.assertEqual(len(projects), 3)
        # Should be ordered by updated_at DESC
        self.assertEqual(projects[0].name, "Project 3")
    
    def test_update_project_name(self):
        """Test updating project name"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        project = pm.create("Original Name")
        
        pm.update(project.id, name="Updated Name")
        
        updated = pm.get(project.id)
        self.assertEqual(updated.name, "Updated Name")
    
    def test_update_system_prompt(self):
        """Test updating project system prompt"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        project = pm.create("Test Project")
        
        pm.update(project.id, system_prompt="You are a helpful assistant.")
        
        updated = pm.get(project.id)
        self.assertEqual(updated.system_prompt, "You are a helpful assistant.")
    
    def test_delete_project(self):
        """Test deleting a project"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        project = pm.create("To Delete")
        
        pm.delete(project.id)
        
        result = pm.get(project.id)
        self.assertIsNone(result)


class TestProjectManagerFull(unittest.TestCase):
    """Full tests for ProjectManager - Edge cases and advanced features"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test database"""
        cls.test_db_path = tempfile.mktemp(suffix=".db")
        database.db._db_path = cls.test_db_path
        database.db.initialize()
    
    @classmethod
    def tearDownClass(cls):
        """Clean up test database"""
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
    
    def setUp(self):
        """Clean database before each test"""
        database.db.execute("DELETE FROM projects")
        database.db.execute("DELETE FROM conversations")
        database.db.execute("DELETE FROM messages")
    
    def test_create_with_system_prompt(self):
        """Test creating project with system prompt"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        project = pm.create(
            "AI Project", 
            system_prompt="You are a coding assistant.",
            model="claude-opus-4-6"
        )
        
        self.assertEqual(project.system_prompt, "You are a coding assistant.")
        self.assertEqual(project.default_model, "claude-opus-4-6")
    
    def test_update_multiple_fields(self):
        """Test updating multiple fields at once"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        project = pm.create("Original")
        
        pm.update(project.id, 
                  name="New Name",
                  system_prompt="New prompt",
                  default_model="claude-opus-4-6")
        
        updated = pm.get(project.id)
        self.assertEqual(updated.name, "New Name")
        self.assertEqual(updated.system_prompt, "New prompt")
        self.assertEqual(updated.default_model, "claude-opus-4-6")
    
    def test_update_with_dict_settings(self):
        """Test updating settings as dict"""
        from core.project_manager import ProjectManager
        import json
        
        pm = ProjectManager()
        project = pm.create("Test Project")
        
        settings = {"cache_ttl": "1h", "compress_after_turns": 20}
        pm.update(project.id, settings_json=settings)
        
        updated = pm.get(project.id)
        self.assertEqual(updated.settings.get("cache_ttl"), "1h")
        self.assertEqual(updated.settings.get("compress_after_turns"), 20)
    
    def test_update_invalid_field_ignored(self):
        """Test that invalid fields are ignored"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        project = pm.create("Test Project")
        
        # This should not raise an error, but should be ignored
        pm.update(project.id, invalid_field="value", another_invalid=123)
        
        # Project should remain unchanged
        updated = pm.get(project.id)
        self.assertEqual(updated.name, "Test Project")
    
    def test_delete_nonexistent_project(self):
        """Test deleting a project that doesn't exist"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        # Should not raise an error
        pm.delete("nonexistent-id")
    
    def test_project_timestamps(self):
        """Test that timestamps are properly set"""
        from core.project_manager import ProjectManager
        import time
        
        pm = ProjectManager()
        before = time.time()
        project = pm.create("Timestamp Test")
        after = time.time()
        
        self.assertIsNotNone(project.created_at)
        self.assertIsNotNone(project.updated_at)
        
        # Wait a bit and update
        time.sleep(0.01)
        pm.update(project.id, name="Updated")
        
        updated = pm.get(project.id)
        self.assertGreater(updated.updated_at, project.updated_at)
    
    def test_list_empty(self):
        """Test listing projects when none exist"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        projects = pm.list_all()
        
        self.assertEqual(len(projects), 0)
    
    def test_many_projects_ordering(self):
        """Test that projects are properly ordered"""
        from core.project_manager import ProjectManager
        
        pm = ProjectManager()
        
        # Create projects in order
        for i in range(10):
            pm.create(f"Project {i}")
            import time
            time.sleep(0.001)  # Small delay to ensure different timestamps
        
        projects = pm.list_all()
        
        # Should be in reverse chronological order (newest first)
        names = [p.name for p in projects]
        
        # Check that it's sorted in descending order
        self.assertEqual(names, sorted(names, reverse=True))


class TestProjectModel(unittest.TestCase):
    """Test Project dataclass"""
    
    def test_project_defaults(self):
        """Test Project model default values"""
        from core.project_manager import Project
        
        p = Project(id="test-id", name="Test")
        
        self.assertEqual(p.id, "test-id")
        self.assertEqual(p.name, "Test")
        self.assertEqual(p.system_prompt, "")
        self.assertEqual(p.default_model, "claude-haiku-4-5-20251001")
        self.assertEqual(p.settings, {})


if __name__ == "__main__":
    unittest.main()
