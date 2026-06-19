"""Unit tests for Item model."""

import pytest
from datetime import datetime
from src.studyvault.models.item import Item
from src.studyvault.models.task import Task
from src.studyvault.models.memento import Memento

class TestItemRating:
    """Test rating functionality."""
    
    def test_rating_clamps_upper_bound(self):
        """Test rating clamped to max 5."""
        item = Item("Test", "Cat", "pdf")
        item.set_rating(10)
        
        assert item.rating == 5
    
    def test_rating_clamps_lower_bound(self):
        """Test rating clamped to min 0."""
        item = Item("Test", "Cat", "pdf")
        item.set_rating(-5)
        
        assert item.rating == 0
    
    def test_rating_allows_zero(self):
        """Test rating can be 0 (unrated)."""
        item = Item("Test", "Cat", "pdf")
        item.set_rating(0)
        
        assert item.rating == 0


class TestItemSerialization:
    """Test to_dict/from_dict for persistence."""
    
    def test_to_dict(self):
        """Test converting item to dictionary."""
        item = Item("Test Title", "Test Cat", "pdf")
        item.add_tag("tag1")
        item.set_rating(4)
        
        data = item.to_dict()
        
        assert data['title'] == "Test Title"
        assert data['category'] == "Test Cat"
        assert data['type'] == "pdf"
        assert data['rating'] == 4
        assert "tag1" in data['tags']
        assert 'id' in data
    
    def test_from_dict(self):
        """Test creating item from dictionary."""
        data = {
            'id': 'test-id-123',
            'title': 'Test',
            'category': 'Cat',
            'type': 'pdf',
            'tags': ['tag1', 'tag2'],
            'rating': 3,
        }
        
        item = Item.from_dict(data)
        
        assert item.id == 'test-id-123'
        assert item.title == 'Test'
        assert item.rating == 3
        assert len(item.tags) == 2
    
    def test_round_trip_serialization(self):
        """Test item -> dict -> item preserves data."""
        original = Item("Original", "Category", "video")
        original.add_tag("test")
        original.set_rating(5)
        
        data = original.to_dict()
        restored = Item.from_dict(data)
        
        assert restored.title == original.title
        assert restored.category == original.category
        assert restored.rating == original.rating
        assert restored.tags == original.tags

class TestTaskCreation:
    """Test Task initialization and validation."""
    
    def test_create_task_with_valid_data(self):
        """Test creating task with valid parameters."""
        deadline = datetime(2025, 12, 31, 23, 59)
        task = Task(item_id="item-123", priority=5, deadline=deadline, description="Study DSP")
        
        assert task.item_id == "item-123"
        assert task.priority == 5
        assert task.deadline == deadline
        assert task.description == "Study DSP"
    
    def test_create_task_validates_empty_item_id(self):
        """Test that empty item_id raises ValueError."""
        with pytest.raises(ValueError, match="item_id cannot be empty"):
            Task(item_id="", priority=5, deadline=datetime.now(), description="Test")
    
    def test_create_task_validates_negative_priority(self):
        """Test that negative priority raises ValueError."""
        with pytest.raises(ValueError, match="priority must be >= 1"):
            Task(item_id="item-123", priority=-1, deadline=datetime.now(), description="Test")
    
    def test_create_task_validates_empty_description(self):
        """Test that empty description raises ValueError."""
        with pytest.raises(ValueError, match="description cannot be empty"):
            Task(item_id="item-123", priority=5, deadline=datetime.now(), description="   ")


class TestTaskComparison:
    """Test Task sorting (Comparable implementation)."""
    
    def test_higher_priority_comes_first(self):
        """Test that higher priority task is 'less than' for max-heap."""
        task_high = Task("item-1", 10, datetime.now(), "Urgent")
        task_low = Task("item-2", 2, datetime.now(), "Not urgent")
        
        # Higher priority should be "less than" for max-heap behavior
        assert task_high < task_low
    
    def test_sorting_tasks_by_priority(self):
        """Test that sorting puts highest priority first."""
        tasks = [
            Task("item-1", 3, datetime.now(), "Low"),
            Task("item-2", 8, datetime.now(), "High"),
            Task("item-3", 5, datetime.now(), "Medium"),
        ]
        
        sorted_tasks = sorted(tasks)
        
        assert sorted_tasks[0].priority == 8  # Highest first
        assert sorted_tasks[1].priority == 5
        assert sorted_tasks[2].priority == 3
    
    def test_equal_priority_tasks(self):
        """Test equality comparison."""
        task1 = Task("item-1", 5, datetime.now(), "Task 1")
        task2 = Task("item-2", 5, datetime.now(), "Task 2")
        
        assert task1 == task2


class TestTaskSerialization:
    """Test to_dict/from_dict for persistence."""
    
    def test_to_dict(self):
        """Test converting task to dictionary."""
        deadline = datetime(2025, 12, 31, 23, 59)
        task = Task("item-123", 7, deadline, "Complete assignment")
        
        data = task.to_dict()
        
        assert data['item_id'] == "item-123"
        assert data['priority'] == 7
        assert data['description'] == "Complete assignment"
        assert '2025-12-31' in data['deadline']
    
    def test_from_dict(self):
        """Test creating task from dictionary."""
        data = {
            'item_id': 'item-456',
            'priority': 9,
            'deadline': '2025-11-30T12:00:00',
            'description': 'Review notes',
        }
        
        task = Task.from_dict(data)
        
        assert task.item_id == 'item-456'
        assert task.priority == 9
        assert task.description == 'Review notes'
    
    def test_round_trip_serialization(self):
        """Test task -> dict -> task preserves data."""
        original = Task("item-789", 6, datetime(2025, 10, 15, 10, 30), "Study graphs")
        
        data = original.to_dict()
        restored = Task.from_dict(data)
        
        assert restored.item_id == original.item_id
        assert restored.priority == original.priority
        assert restored.description == original.description

class TestMementoCreation:
    """Test Memento initialization and deep copy."""
    
    def test_create_memento_with_item(self):
        """Test creating memento saves item snapshot."""
        item = Item("Original Title", "Category", "pdf")
        item.add_tag("test-tag")
        item.set_rating(4)
        
        memento = Memento(item, "EDIT")
        
        assert memento.saved_item.title == "Original Title"
        assert memento.saved_item.rating == 4
        assert "test-tag" in memento.saved_item.tags
        assert memento.operation_type == "EDIT"
    
    def test_memento_creates_deep_copy(self):
        """Test that memento creates independent copy of item."""
        item = Item("Original", "Category", "pdf")
        item.add_tag("original-tag")
        
        memento = Memento(item, "DELETE")
        
        # Modify original item
        item.title = "Modified"
        item.add_tag("new-tag")
        item.set_rating(5)
        
        # Memento should still have original values
        assert memento.saved_item.title == "Original"
        assert "original-tag" in memento.saved_item.tags
        assert "new-tag" not in memento.saved_item.tags
        assert memento.saved_item.rating == 0
    
    def test_memento_has_timestamp(self):
        """Test that memento records creation time."""
        item = Item("Test", "Cat", "pdf")
        memento = Memento(item, "EDIT")
        
        assert isinstance(memento.timestamp, datetime)
        assert (datetime.now() - memento.timestamp).total_seconds() < 1


class TestMementoOperationTypes:
    """Test operation type validation."""
    
    def test_memento_with_delete_operation(self):
        """Test memento with DELETE operation."""
        item = Item("Test", "Cat", "pdf")
        memento = Memento(item, "DELETE")
        
        assert memento.operation_type == "DELETE"
    
    def test_memento_with_edit_operation(self):
        """Test memento with EDIT operation."""
        item = Item("Test", "Cat", "pdf")
        memento = Memento(item, "EDIT")
        
        assert memento.operation_type == "EDIT"


class TestMementoSerialization:
    """Test to_dict/from_dict for persistence."""
    
    def test_memento_to_dict(self):
        """Test converting memento to dictionary."""
        item = Item("Test Item", "Category", "video")
        item.add_tag("tag1")
        memento = Memento(item, "EDIT")
        
        data = memento.to_dict()
        
        assert data['operation_type'] == "EDIT"
        assert 'saved_item' in data
        assert data['saved_item']['title'] == "Test Item"
        assert 'timestamp' in data
    
    def test_memento_from_dict(self):
        """Test creating memento from dictionary."""
        data = {
            'saved_item': {
                'id': 'item-123',
                'title': 'Saved',
                'category': 'Cat',
                'type': 'pdf',
                'tags': ['tag1'],
                'rating': 3,
                'created_at': datetime.now().isoformat(),
                'media_url': None,
                'file_path': None,
            },
            'operation_type': 'DELETE',
            'timestamp': '2025-10-29T01:00:00',
        }
        
        memento = Memento.from_dict(data)
        
        assert memento.operation_type == 'DELETE'
        assert memento.saved_item.title == 'Saved'
        assert memento.saved_item.rating == 3
    
    def test_memento_round_trip_serialization(self):
        """Test memento -> dict -> memento preserves data."""
        item = Item("Original", "Category", "audio")
        item.add_tag("music")
        item.set_rating(5)
        
        original_memento = Memento(item, "EDIT")
        
        data = original_memento.to_dict()
        restored_memento = Memento.from_dict(data)
        
        assert restored_memento.operation_type == original_memento.operation_type
        assert restored_memento.saved_item.title == original_memento.saved_item.title
        assert restored_memento.saved_item.rating == original_memento.saved_item.rating
        assert restored_memento.saved_item.tags == original_memento.saved_item.tags
