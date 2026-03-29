"""
Import Service - Handles recursive directory import and file processing.

Scans directories for supported files and creates Item objects with metadata.
Maintains processed paths to prevent duplicates across multiple imports.
Supports parallel file scanning for large directory trees.
"""

from pathlib import Path
from typing import List, Set
import logging

from studyvault.models.item import Item
import studyvault.utils.file_util as FileUtil
from studyvault.utils.logger import get_logger

logger = get_logger(__name__)


class ImportService:
    """
    Service for importing files from directories into the library.
    
    Recursively scans directories for supported file types and creates Item objects.
    Supports parallel scanning for optimal performance on large datasets.
    """
    
    LOG_BATCH_SIZE = 100
    
    def __init__(self):
        """Initialize import service with empty processed paths set."""
        self.processed_paths: Set[str] = set()
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("ImportService initialized")
    
    def import_from_directory(
        self, 
        directory: Path, 
        parallel: bool = False,
        max_workers: int = 4
    ) -> List[Item]:
        """
        Import all supported files from a directory recursively.
        
        Args:
            directory: Path object of directory to scan
            parallel: Use parallel scanning (1.5-2× faster for large nested trees)
            max_workers: Number of threads for parallel scan (default: 4)
        
        Returns:
            List of imported Item objects
        """
        imported_items: List[Item] = []
        
        # Validate directory
        if not directory.exists():
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Directory does not exist: {directory}")
            return imported_items
        
        if not directory.is_dir():
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Path is not a directory: {directory}")
            return imported_items
        
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Starting import from: {directory} (parallel={parallel})")
        
        # Scan for files (parallel or sequential)
        if parallel:
            files = FileUtil.scan_directory_parallel(
                directory, 
                self.processed_paths,
                max_workers=max_workers
            )
        else:
            files = FileUtil.scan_directory(directory, self.processed_paths)
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Found {len(files)} files to import")
        
        # Batch counters for logging
        success_count = 0
        error_count = 0
        
        # Create Item for each file
        for file_path in files:
            try:
                file_type = FileUtil.determine_type(file_path)
                
                title = file_path.stem if file_path.stem else file_path.name
                if not title:
                    title = "Untitled"
                
                category = self._derive_category(file_path, file_type)
                
                item = Item(
                    title=title,
                    category=category,
                    type=file_type
                )
                
                item.file_path = str(file_path)
                
                imported_items.append(item)
                success_count += 1
                
                if success_count % self.LOG_BATCH_SIZE == 0:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Imported {success_count} items so far...")
            
            except Exception as e:
                error_count += 1
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(f"Failed to import {file_path}: {e}", exc_info=True)
                continue
        
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Import complete: {success_count} items imported, "
                f"{error_count} errors"
            )
        
        return imported_items
    
    def _derive_category(self, file_path: Path, file_type: str) -> str:
        """Derive category from file location or type."""
        parent_name = file_path.parent.name
        
        ignore_dirs = {'Desktop', 'Downloads', 'Documents', 'Users', 'home'}
        if parent_name and parent_name not in ignore_dirs:
            return parent_name.capitalize()
        
        type_category_map = {
            'pdf': 'Documents',
            'docx': 'Documents',
            'ppt': 'Presentations',
            'video': 'Videos',
            'audio': 'Audio',
            'note': 'Notes',
        }
        
        return type_category_map.get(file_type, 'Imported')
    
    def get_processed_paths(self) -> Set[str]:
        """Get set of already-processed file paths."""
        return self.processed_paths
    
    def clear_processed_paths(self) -> None:
        """Clear the processed paths cache."""
        count = len(self.processed_paths)
        self.processed_paths.clear()
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Cleared {count} processed paths")
    
    def get_import_stats(self) -> dict:
        """Get statistics about import operations."""
        return {
            'total_processed': len(self.processed_paths),
            'supported_extensions': FileUtil.get_supported_extensions_list(),
        }