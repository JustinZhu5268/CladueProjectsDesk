"""
Unit tests for DocumentProcessor - PRD v3 document text extraction

BASIC TESTS: Core functionality tests  
FULL TESTS: Edge cases, error handling, various file formats
"""
import unittest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import tempfile
import shutil

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set up test database before importing modules
from data import database


class TestDocumentProcessorBasic(unittest.TestCase):
    """Basic tests for DocumentProcessor - Core functionality"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test database"""
        cls.test_db_path = tempfile.mktemp(suffix=".db")
        database.db._db_path = cls.test_db_path
        database.db.initialize()
        
        # Create temp docs directory
        cls.test_docs_dir = tempfile.mkdtemp()
    
    @classmethod
    def tearDownClass(cls):
        """Clean up test database and temp files"""
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)
        if os.path.exists(cls.test_docs_dir):
            shutil.rmtree(cls.test_docs_dir)
    
    def setUp(self):
        """Clean database before each test"""
        database.db.execute("DELETE FROM documents")
        database.db.execute("DELETE FROM projects")
    
    @patch('core.document_processor.DOCS_DIR', new_callable=lambda: Path(tempfile.gettempdir()) / 'test_docs')
    def test_get_project_documents_empty(self, mock_docs_dir):
        """Test getting documents when none exist"""
        from core.document_processor import DocumentProcessor
        
        processor = DocumentProcessor()
        
        # Create a mock project
        project_id = "test-project-123"
        
        docs = processor.get_project_documents(project_id)
        
        self.assertEqual(len(docs), 0)
    
    @patch('core.document_processor.DOCS_DIR', new_callable=lambda: Path(tempfile.gettempdir()) / 'test_docs')
    def test_get_total_tokens_empty(self, mock_docs_dir):
        """Test total tokens when no documents"""
        from core.document_processor import DocumentProcessor
        
        processor = DocumentProcessor()
        
        total = processor.get_total_tokens("nonexistent-project")
        
        self.assertEqual(total, 0)
    
    @patch('core.document_processor.DOCS_DIR', new_callable=lambda: Path(tempfile.gettempdir()) / 'test_docs')
    def test_get_project_context_empty(self, mock_docs_dir):
        """Test getting context when no documents"""
        from core.document_processor import DocumentProcessor
        
        processor = DocumentProcessor()
        
        context = processor.get_project_context("nonexistent-project")
        
        self.assertEqual(context, "")


class TestDocumentProcessorFull(unittest.TestCase):
    """Full tests for DocumentProcessor - Edge cases and advanced features"""
    
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
        database.db.execute("DELETE FROM documents")
        database.db.execute("DELETE FROM projects")
    
    def test_extract_text_file_plain(self):
        """Test extracting plain text file"""
        from core.document_processor import DocumentProcessor
        
        processor = DocumentProcessor()
        
        # Create temp text file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Hello world\nThis is a test document.")
            temp_path = f.name
        
        try:
            result = processor._extract_text_file(Path(temp_path))
            self.assertIn("Hello world", result)
            self.assertIn("test document", result)
        finally:
            os.unlink(temp_path)
    
    def test_extract_text_file_markdown(self):
        """Test extracting markdown file"""
        from core.document_processor import DocumentProcessor
        
        processor = DocumentProcessor()
        
        # Create temp markdown file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("# Title\n\nThis is **bold** and *italic*.")
            temp_path = f.name
        
        try:
            result = processor._extract_text_file(Path(temp_path))
            self.assertIn("Title", result)
            self.assertIn("bold", result)
        finally:
            os.unlink(temp_path)
    
    def test_extract_text_file_json(self):
        """Test extracting JSON file"""
        from core.document_processor import DocumentProcessor
        
        processor = DocumentProcessor()
        
        # Create temp JSON file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{"name": "test", "value": 123}')
            temp_path = f.name
        
        try:
            result = processor._extract_text_file(Path(temp_path))
            self.assertIn("test", result)
            self.assertIn("123", result)
        finally:
            os.unlink(temp_path)
    
    def test_estimate_tokens_simple(self):
        """Test token estimation for simple text"""
        from core.document_processor import DocumentProcessor
        
        processor = DocumentProcessor()
        
        # 100 characters / 4 = 25 tokens (fallback), or tiktoken may give different result
        text = "a" * 100
        tokens = processor._estimate_tokens(text)
        
        # tiktoken 或 fallback 都应该在合理范围内
        self.assertGreaterEqual(tokens, 10)
        self.assertLessEqual(tokens, 35)
    
    def test_estimate_tokens_chinese(self):
        """Test token estimation for Chinese text (chars, not words)"""
        from core.document_processor import DocumentProcessor
        
        processor = DocumentProcessor()
        
        # Chinese characters: each is roughly 1-2 tokens
        # Using /4 as fallback should work
        text = "你好世界" * 25  # 100 characters
        tokens = processor._estimate_tokens(text)
        
        # tiktoken 或 fallback 都应该在合理范围内
        self.assertGreaterEqual(tokens, 10)
        self.assertLessEqual(tokens, 150)
    
    def test_estimate_tokens_code(self):
        """Test token estimation for code"""
        from core.document_processor import DocumentProcessor
        
        processor = DocumentProcessor()
        
        # Code with many characters
        code = "function test() {\n" * 50  # ~650 chars
        tokens = processor._estimate_tokens(code)
        
        # Should be roughly chars/4
        self.assertGreater(tokens, 100)
    
    def test_extract_text_unsupported_extension(self):
        """Test extracting unsupported file type falls back to text"""
        from core.document_processor import DocumentProcessor
        
        processor = DocumentProcessor()
        
        # Create temp file with unknown extension
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xyz', delete=False) as f:
            f.write("Unknown file type content")
            temp_path = f.name
        
        try:
            # Should fall back to text extraction
            result = processor._extract_text(Path(temp_path), ".xyz")
            self.assertIn("Unknown file type content", result)
        finally:
            os.unlink(temp_path)
    
    def test_text_extensions_list(self):
        """Test that TEXT_EXTENSIONS contains common types"""
        from core.document_processor import TEXT_EXTENSIONS
        
        # Check some common extensions
        self.assertIn(".py", TEXT_EXTENSIONS)
        self.assertIn(".js", TEXT_EXTENSIONS)
        self.assertIn(".txt", TEXT_EXTENSIONS)
        self.assertIn(".md", TEXT_EXTENSIONS)
        self.assertIn(".json", TEXT_EXTENSIONS)
        self.assertIn(".html", TEXT_EXTENSIONS)
        self.assertIn(".sql", TEXT_EXTENSIONS)
    
    def test_extract_error_handling(self):
        """Test error handling in text extraction"""
        from core.document_processor import DocumentProcessor
        
        processor = DocumentProcessor()
        
        # Nonexistent file should return error message (as per the actual implementation)
        result = processor._extract_text(Path("/nonexistent/file.txt"), ".txt")
        
        # The actual implementation returns an error message when extraction fails
        self.assertTrue(len(result) > 0)


class TestDocumentProcessorIntegration(unittest.TestCase):
    """Integration tests for document processor with database"""
    
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
        database.db.execute("DELETE FROM documents")
        database.db.execute("DELETE FROM projects")
    
    def test_document_roundtrip(self):
        """Test adding and retrieving a document"""
        from core.document_processor import DocumentProcessor
        from core.project_manager import ProjectManager
        
        # Create project
        pm = ProjectManager()
        project = pm.create("Test Project")
        
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content for document processing.")
            temp_path = f.name
        
        try:
            processor = DocumentProcessor()
            
            # Add document
            result = processor.add_document(project.id, temp_path)
            
            self.assertIn("id", result)
            self.assertIn("token_count", result)
            self.assertEqual(result["filename"], os.path.basename(temp_path))
            
            # Get project documents
            docs = processor.get_project_documents(project.id)
            self.assertEqual(len(docs), 1)
            self.assertIn("Test content", docs[0]["extracted_text"])
            
            # Get total tokens
            total = processor.get_total_tokens(project.id)
            self.assertGreater(total, 0)
            
            # Get project context
            context = processor.get_project_context(project.id)
            self.assertIn("Test content", context)
            
        finally:
            os.unlink(temp_path)
    
    def test_remove_document(self):
        """Test removing a document"""
        from core.document_processor import DocumentProcessor
        from core.project_manager import ProjectManager
        
        # Create project
        pm = ProjectManager()
        project = pm.create("Test Project")
        
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Content to be removed")
            temp_path = f.name
        
        try:
            processor = DocumentProcessor()
            
            # Add document
            result = processor.add_document(project.id, temp_path)
            doc_id = result["id"]
            
            # Verify added
            docs = processor.get_project_documents(project.id)
            self.assertEqual(len(docs), 1)
            
            # Remove document
            processor.remove_document(doc_id)
            
            # Verify removed
            docs = processor.get_project_documents(project.id)
            self.assertEqual(len(docs), 0)
            
        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    unittest.main()
