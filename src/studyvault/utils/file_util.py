"""
File Utility Module - Recursive directory scanning and file type detection.

Provides utilities for scanning directories recursively, detecting supported file types,
and preventing duplicate processing. Uses DFS traversal with deduplication via set.
Supports parallel scanning for large directory trees.
"""

from pathlib import Path
from typing import List, Set
from concurrent.futures import ThreadPoolExecutor
from threading import Thread, Lock
from queue import Queue, Empty
import logging
import stat as stat_module
import sys

try:
    import win32file
    import win32con
    _WIN32_AVAILABLE = sys.platform == 'win32'
except ImportError:
    _WIN32_AVAILABLE = False

from studyvault.utils.logger import get_logger

logger = get_logger(__name__)


class FileUtil:
    """
    Static utility class for file operations.
    
    Supports recursive directory scanning with deduplication for file types:
    - Text files: .txt, .md
    - Documents: .pdf, .docx, .pptx
    - Audio: .mp3
    - Video: .mp4
    """
    
    SUPPORTED_EXTENSIONS = {'.txt', '.md', '.pdf', '.mp3', '.mp4', '.docx', '.pptx'}
    
    TYPE_MAPPING = {
        '.txt': 'note',
        '.md': 'note',
        '.pdf': 'pdf',
        '.mp3': 'audio',
        '.mp4': 'video',
        '.docx': 'docx',
        '.pptx': 'ppt',
    }
    
    @staticmethod
    def scan_directory(directory: Path, processed_paths: Set[str]) -> List[Path]:
        """
        Recursively scan directory for supported files (DFS traversal).
        
        Optimized: Check extension first, resolve only if needed
        
        Args:
            directory: Path object of directory to scan
            processed_paths: Set of already-processed absolute paths (mutated in-place)
        
        Returns:
            List of Path objects for found files
        """
        found_files: List[Path] = []
        
        if directory is None or not directory.exists():
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Directory does not exist: {directory}")
            return found_files
        
        if not directory.is_dir():
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Path is not a directory: {directory}")
            return found_files
        
        try:
            for item in directory.iterdir():
                try:
                    if item.is_dir():
                        found_files.extend(
                            FileUtil.scan_directory(item, processed_paths)
                        )
                    elif item.is_file():
                        ext = item.suffix.lower() if item.suffix else ""
                        
                        if ext not in FileUtil.SUPPORTED_EXTENSIONS:
                            continue
                        
                        path_str = str(item.resolve())
                        
                        if path_str in processed_paths:
                            continue
                        
                        found_files.append(item)
                        processed_paths.add(path_str)
                        
                        if len(found_files) % 100 == 0:
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(f"Found {len(found_files)} files so far...")
                
                except PermissionError:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(f"Permission denied: {item}")
                    continue
        
        except PermissionError:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Cannot access directory: {directory}")
        
        return found_files
    
    @staticmethod
    def scan_directory_parallel(
        directory: Path, 
        processed_paths: Set[str],
        max_workers: int = 4
    ) -> List[Path]:
        """
        Parallel directory scanning using threads (2-4× faster for large trees).
        
        Scans top-level subdirectories in parallel, then aggregates results.
        Best for: Large nested directory structures (10K+ files, 50+ subdirs).
        
        Args:
            directory: Root directory to scan
            processed_paths: Set of already-processed paths (mutated in-place)
            max_workers: Number of threads (default: 4, typically optimal)
        
        Returns:
            List of Path objects for found files
        """
        found_files: List[Path] = []
        
        if directory is None or not directory.exists() or not directory.is_dir():
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Invalid directory: {directory}")
            return found_files
        
        try:
            # Get top-level items
            items = list(directory.iterdir())
            subdirs = [item for item in items if item.is_dir()]
            files = [item for item in items if item.is_file()]
            
            # Process files in current directory (single-threaded, fast)
            for item in files:
                try:
                    ext = item.suffix.lower() if item.suffix else ""
                    
                    if ext not in FileUtil.SUPPORTED_EXTENSIONS:
                        continue
                    
                    path_str = str(item.resolve())
                    
                    if path_str not in processed_paths:
                        found_files.append(item)
                        processed_paths.add(path_str)
                
                except PermissionError:
                    continue
            
            # Parallel scan subdirectories (I/O-bound, benefits from threads)
            if subdirs:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Each subdir gets its own thread
                    futures = [
                        executor.submit(FileUtil.scan_directory, subdir, processed_paths)
                        for subdir in subdirs
                    ]
                    
                    # Collect results
                    for future in futures:
                        try:
                            found_files.extend(future.result())
                        except Exception as e:
                            if logger.isEnabledFor(logging.ERROR):
                                logger.error(f"Error in parallel scan: {e}")
        
        except PermissionError:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Cannot access directory: {directory}")
        
        return found_files
    
    @staticmethod
    def scan_directory_async(
        directory: Path,
        processed_paths: Set[str],
        max_workers: int = 4
    ) -> List[Path]:
        """
        Master-worker directory scanning using thread queue for full-tree parallelism.
        
        Uses sentinel-based exit: no timeout overhead, workers block cleanly until
        explicitly signaled to exit after all work is complete.
        
        Args:
            directory: Root directory to scan
            processed_paths: Set of already-processed paths (protected by lock)
            max_workers: Number of worker threads (default: 4)
        
        Returns:
            List of Path objects for all found files
        """
        found_files: List[Path] = []
        
        if directory is None or not directory.exists() or not directory.is_dir():
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Invalid directory: {directory}")
            return found_files
        
        work_queue: Queue = Queue()
        lock = Lock()
        sentinel = object()  # Unique sentinel to signal worker exit
        
        def worker():
            """Worker thread: pop dirs from queue, scan, enqueue subdirs, collect files."""
            while True:
                dir_path = work_queue.get()  # Block until item available (no timeout)
                
                if dir_path is sentinel:  # Exit signal
                    break
                
                try:
                    # Check if already processed (thread-safe)
                    with lock:
                        dir_str = str(dir_path)
                        if dir_str in processed_paths:
                            work_queue.task_done()
                            continue
                        processed_paths.add(dir_str)
                    
                    # Scan directory using Win32 API (Windows) or pathlib fallback
                    if _WIN32_AVAILABLE:
                        pattern = str(dir_path / "*")
                        try:
                            for find_data in win32file.FindFilesIterator(pattern):
                                name = find_data[8]  # cFileName
                                if name in ('.', '..'):
                                    continue
                                attrs = find_data[0]  # dwFileAttributes (free, no syscall)
                                full_path = dir_path / name
                                if attrs & win32con.FILE_ATTRIBUTE_DIRECTORY:
                                    work_queue.put(full_path)
                                else:
                                    ext = full_path.suffix.lower()
                                    if ext not in FileUtil.SUPPORTED_EXTENSIONS:
                                        continue
                                    path_str = str(full_path)
                                    with lock:
                                        if path_str not in processed_paths:
                                            found_files.append(full_path)
                                            processed_paths.add(path_str)
                        except Exception:
                            pass
                    else:
                        for item in dir_path.iterdir():
                            try:
                                if item.is_file():
                                    ext = item.suffix.lower() if item.suffix else ""
                                    if ext not in FileUtil.SUPPORTED_EXTENSIONS:
                                        continue
                                    path_str = str(item.resolve())
                                    with lock:
                                        if path_str not in processed_paths:
                                            found_files.append(item)
                                            processed_paths.add(path_str)
                                elif item.is_dir():
                                    work_queue.put(item)
                            except (PermissionError, OSError):
                                continue
                    
                    if len(found_files) % 100 == 0 and len(found_files) > 0:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(f"Found {len(found_files)} files so far...")
                
                except PermissionError:
                    pass
                finally:
                    work_queue.task_done()
        
        try:
            # Enqueue root directory
            work_queue.put(directory)
            
            # Create and start worker threads
            threads = []
            for _ in range(max_workers):
                t = Thread(target=worker, daemon=False)
                t.start()
                threads.append(t)
            
            # Wait for all work to complete (all .task_done() calls matched)
            work_queue.join()
            
            # Signal workers to exit (send sentinel for each worker)
            for _ in range(max_workers):
                work_queue.put(sentinel)
            
            # Wait for all threads to finish
            for t in threads:
                t.join()
        
        except PermissionError:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Cannot access directory: {directory}")
        
        return found_files
    
    @staticmethod
    def get_file_extension(file_path: Path) -> str:
        """Get file extension in lowercase (includes dot)."""
        return file_path.suffix.lower() if file_path.suffix else ""
    
    @staticmethod
    def determine_type(file_path: Path) -> str:
        """Determine item type based on file extension."""
        ext = file_path.suffix.lower() if file_path.suffix else ""
        return FileUtil.TYPE_MAPPING.get(ext, 'unknown')
    
    @staticmethod
    def is_supported_file(file_path: Path) -> bool:
        """Check if file extension is supported."""
        ext = file_path.suffix.lower() if file_path.suffix else ""
        return ext in FileUtil.SUPPORTED_EXTENSIONS
    
    @staticmethod
    def get_file_stats(file_path: Path) -> dict:
        """Get file metadata (size, modified time, etc.)."""
        try:
            stat_info = file_path.stat()
            return {
                'size_bytes': stat_info.st_size,
                'modified_time': stat_info.st_mtime,
                'is_readable': stat_module.S_ISREG(stat_info.st_mode),
            }
        except OSError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Cannot get stats for {file_path}: {e}")
            return {
                'size_bytes': 0,
                'modified_time': 0,
                'is_readable': False,
            }
    
    @staticmethod
    def get_supported_extensions_list() -> List[str]:
        """Get supported extensions as list."""
        return sorted(FileUtil.SUPPORTED_EXTENSIONS)