"""
Main Controller - Core orchestrator for StudyVault application.

Handles all user interactions: CRUD operations, search, import, tasks, and media preview.
Connects services (library, search, import) to the UI (views/widgets).
Implements animations, dialogs, and error handling.
Supports optimized parallel file import for large datasets.
"""

from typing import Optional, List
from pathlib import Path
from datetime import datetime
import os
import platform
import subprocess
import logging

from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QLineEdit, QPushButton, QLabel,
    QMessageBox, QDialog, QDialogButtonBox, QGridLayout, QVBoxLayout,
    QHBoxLayout, QSlider, QFileDialog, QDateEdit, QWidget, QRadioButton
)

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QDate, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from studyvault.models.item import Item
from studyvault.models.task import Task
from studyvault.services.library_service import LibraryService
from studyvault.services.search_service import SearchService
from studyvault.services.import_service import ImportService
from studyvault.repositories.library_repository import LibraryData
from studyvault.utils.logger import get_logger

logger = get_logger(__name__)


class MainController:
    """
    Main application controller.
    
    Connects UI widgets to business logic services. Handles all user actions
    including CRUD operations, search, import, task management, and media preview.
    """
    
    def __init__(
        self,
        items_table: QTableWidget,
        search_field: QLineEdit,
        task_count_label: QLabel,
        add_button: QPushButton,
        edit_button: QPushButton,
        delete_button: QPushButton,
        undo_button: QPushButton,
        search_button: QPushButton,
        import_button: QPushButton,
        add_task_button: QPushButton,
        view_task_button: QPushButton,
        preview_button: QPushButton,
        clear_search_button: QPushButton
    ):
        """Initialize main controller with UI widgets."""
        self.items_table = items_table
        self.search_field = search_field
        self.task_count_label = task_count_label
        self.view = items_table.window()
        
        self.add_button = add_button
        self.edit_button = edit_button
        self.delete_button = delete_button
        self.undo_button = undo_button
        self.search_button = search_button
        self.clear_search_button = clear_search_button
        self.import_button = import_button
        self.add_task_button = add_task_button
        self.view_task_button = view_task_button
        self.preview_button = preview_button
        
        self.library_service = LibraryService()
        self.search_service = SearchService()
        self.import_service = ImportService()
        
        self.media_player: Optional[QMediaPlayer] = None
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("MainController initialized")
    
    def initialize(self) -> None:
        """Initialize controller - setup table, connect signals, load data."""
        self._setup_table()
        self._connect_signals()
        self._animate_fade_in(self.items_table, duration=800)
        
        if logger.isEnabledFor(logging.INFO):
            logger.info("MainController initialized and ready")
    
    def _setup_table(self) -> None:
        """Configure table columns and settings."""
        self.items_table.setColumnCount(5)
        self.items_table.setHorizontalHeaderLabels([
            "Title", "Category", "Type", "Rating", "Tags"
        ])
        
        self.items_table.setSortingEnabled(True)
        
        header = self.items_table.horizontalHeader()
        header.setStretchLastSection(True)
        self.items_table.setWordWrap(True)
        
        vertical_header = self.items_table.verticalHeader()
        vertical_header.setSectionResizeMode(vertical_header.ResizeMode.ResizeToContents)
        
        self.items_table.setColumnWidth(0, 200)
        self.items_table.setColumnWidth(1, 150)
        self.items_table.setColumnWidth(2, 100)
        self.items_table.setColumnWidth(3, 80)
    
    def _connect_signals(self) -> None:
        """Connect button clicks to handler methods."""
        self.add_button.clicked.connect(self.handle_add)
        self.edit_button.clicked.connect(self.handle_edit)
        self.delete_button.clicked.connect(self.handle_delete)
        self.undo_button.clicked.connect(self.handle_undo)
        self.search_button.clicked.connect(self.handle_search)
        self.clear_search_button.clicked.connect(self.handle_clear_search)
        self.import_button.clicked.connect(self.handle_import)
        self.add_task_button.clicked.connect(self.handle_add_task)
        self.view_task_button.clicked.connect(self.handle_view_next_task)
        self.preview_button.clicked.connect(self.handle_preview)
        self.search_field.returnPressed.connect(self.handle_search)
    
    def _show_message(self, title: str, message: str,
                  icon=QMessageBox.Icon.Information) -> None:
        """Show message dialog with proper formatting."""
        box = QMessageBox(self.view)
        box.setWindowTitle(title)
        box.setIcon(icon)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.setText(message)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setStyleSheet("""
            QLabel#qt_msgbox_label, QLabel#qt_msgbox_informativelabel {
                qproperty-wordWrap: true;
                min-width: 320px;
                max-width: 520px;
            }
        """)
        box.exec()
    
    # ===== CRUD Operations =====
    
    def handle_add(self) -> None:
        """Open dialog to add a new item."""
        dialog = self.AddItemDialog(self.view)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            item_data = dialog.get_item_data()
            if item_data:
                new_item = Item(
                    title=item_data["title"],
                    category=item_data["category"],
                    type=item_data["type"]
                )
                new_item.file_path = item_data.get("file_path")
                new_item.url = item_data.get("url")
                new_item.set_rating(item_data.get("rating", 0))
                
                for tag in item_data.get("tags", []):
                    new_item.add_tag(tag)
                
                self.library_service.add_item(new_item)
                self.search_service.build_index(self.library_service.get_items())
                
                self._refresh_table()
                self._animate_fade_in(self.items_table, duration=300, start_opacity=0.5)
                self._show_message("Success", f"Item '{new_item.title}' added successfully.")
    
    def handle_edit(self) -> None:
        """Handle Edit button click."""
        selected_item = self._get_selected_item()
        if not selected_item:
            self._show_message("No Selection", "Please select an item to edit.", QMessageBox.Icon.Warning)
            return
        
        dialog = QDialog(self.view)
        dialog.setWindowTitle("Edit Item")
        dialog.resize(600, 350)
        dialog.setMinimumSize(550, 320)
        dialog.showEvent = lambda event: self._animate_scale(dialog, duration=200)
        
        main_layout = QVBoxLayout()
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(25, 25, 25, 25)
        
        form_layout = QGridLayout()
        form_layout.setSpacing(15)
        form_layout.setColumnStretch(1, 1)
        
        title_label = QLabel("Title:")
        title_field = QLineEdit(selected_item.title)
        title_field.setMinimumHeight(35)
        form_layout.addWidget(title_label, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        form_layout.addWidget(title_field, 0, 1)
        
        category_label = QLabel("Category:")
        category_field = QLineEdit(selected_item.category)
        category_field.setMinimumHeight(35)
        form_layout.addWidget(category_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        form_layout.addWidget(category_field, 1, 1)
        
        tags_label = QLabel("Tags:")
        tags_field = QLineEdit(", ".join(selected_item.tags))
        tags_field.setMinimumHeight(35)
        tags_field.setPlaceholderText("Comma separated tags")
        form_layout.addWidget(tags_label, 2, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        form_layout.addWidget(tags_field, 2, 1)
        
        rating_label = QLabel("Rating:")
        rating_container = QWidget()
        rating_layout = QHBoxLayout(rating_container)
        rating_layout.setContentsMargins(0, 0, 0, 0)
        rating_layout.setSpacing(15)
        
        rating_slider = QSlider(Qt.Orientation.Horizontal)
        rating_slider.setMinimum(1)
        rating_slider.setMaximum(5)
        rating_slider.setValue(selected_item.rating)
        rating_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        rating_slider.setTickInterval(1)
        rating_slider.setMinimumWidth(200)
        
        rating_value_label = QLabel(self._format_rating(selected_item.rating))
        rating_value_label.setMinimumWidth(130)
        rating_value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        rating_slider.valueChanged.connect(
            lambda value: rating_value_label.setText(self._format_rating(value))
        )
        
        rating_layout.addWidget(rating_slider, stretch=1)
        rating_layout.addWidget(rating_value_label, stretch=0)
        form_layout.addWidget(rating_label, 3, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        form_layout.addWidget(rating_container, 3, 1)
        
        main_layout.addLayout(form_layout)
        main_layout.addStretch(1)
        
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        main_layout.addWidget(button_box)
        dialog.setLayout(main_layout)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            old_item = selected_item
            selected_item.title = title_field.text().strip()
            selected_item.category = category_field.text().strip()
            selected_item.set_rating(rating_slider.value())
            
            selected_item.tags.clear()
            for tag in tags_field.text().split(','):
                tag_clean = tag.strip()
                if tag_clean:
                    selected_item.add_tag(tag_clean)
            
            self.library_service.update_item(old_item, selected_item)
            self.search_service.build_index(self.library_service.get_items())
            self._refresh_table()
            
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"Item edited: {selected_item.title}")
            
            self._show_message("Success", "Item updated successfully!", QMessageBox.Icon.Information)
    
    def _format_rating(self, value: int) -> str:
        """Format rating value with stars."""
        stars = "★" * value + "☆" * (5 - value)
        return f"{stars} ({value}/5)"
    
    def handle_delete(self) -> None:
        """Handle Delete button click."""
        selected_items = self._get_selected_items()
        
        if not selected_items:
            self._show_message("No Selection", "Please select at least one item to delete.",
                               QMessageBox.Icon.Warning)
            return
        
        if len(selected_items) == 1:
            item_name = selected_items[0].title
            if not self._confirm_dialog("Confirm Delete", f"Are you sure you want to delete '{item_name}'?"):
                return
        else:
            if not self._confirm_dialog("Confirm Delete",
                                        f"Are you sure you want to delete {len(selected_items)} items?"):
                return
        
        for item in selected_items:
            self.library_service.delete_item(item)
        
        self.search_service.build_index(self.library_service.get_items())
        self._refresh_table()
        
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Deleted {len(selected_items)} item(s)")
        
        self._show_message("Success", f"Deleted {len(selected_items)} item(s) successfully.",
                           QMessageBox.Icon.Information)
    
    def _confirm_dialog(self, title: str, message: str) -> bool:
        """Custom confirmation dialog. Returns True if user clicks 'Yes'."""
        box = QMessageBox(self.view)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(QMessageBox.Icon.Question)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setStyleSheet("QLabel{ min-width: 250px; }")
        return box.exec() == QMessageBox.StandardButton.Yes
   
    def handle_undo(self) -> None:
        """Handle Undo button click."""
        if not self.library_service.can_undo():
            self._show_message("Nothing to Undo", "No actions to undo.", QMessageBox.Icon.Information)
            return
        
        self.library_service.undo()
        self.search_service.build_index(self.library_service.get_items())
        self._refresh_table()
        
        if logger.isEnabledFor(logging.INFO):
            logger.info("Undo completed")
        
        self._show_message("Undo", "Last action has been undone.", QMessageBox.Icon.Information)
    
    # ===== Search Operations =====
    
    def handle_search(self) -> None:
        """Handle Search button click or Enter key in search field."""
        query = self.search_field.text().strip()
        
        if not query:
            self._refresh_table()
            return
        
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Searching for: {query}")
        
        item_map = self.library_service._id_index
        result_ids = self.search_service.search(query, item_map)
        results = [item_map[item_id] for item_id in result_ids if item_id in item_map]
        
        self._refresh_table(results)
        self._animate_fade_in(self.items_table, duration=300, start_opacity=0.3)
        
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Search found {len(results)} results")
        
        self._show_message("Search Results", f"Found {len(results)} matching items", QMessageBox.Icon.Information)
    
    def handle_clear_search(self) -> None:
        """Reset search bar and reload the full item list."""
        self.search_field.clear()
        self._refresh_table()
        
        if logger.isEnabledFor(logging.INFO):
            logger.info("Search cleared, displaying all items.")
    
    # ===== Import Operations =====
    
    def handle_import(self) -> None:
        """Handle Import button click with parallel import optimization."""
        directory = Path(QFileDialog.getExistingDirectory(
            self.view,
            "Select Folder to Import",
            str(Path.home())
        ))
        
        if not directory:
            return
        
        dir_path = Path(directory)
        
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Importing from: {dir_path}")
        
        # ✅ USE PARALLEL (not optimized) - 1.5-2× faster, simpler
        imported_items = self.import_service.import_from_directory(
            dir_path,
            parallel=True,
            max_workers=4  # Optimal for most systems
        )
        
        # Bulk add items
        for item in imported_items:
            self.library_service.add_item(item)
        
        # Single index rebuild
        self.search_service.build_index(self.library_service.get_items())
        self._refresh_table()
        
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Import complete: {len(imported_items)} items")
        
        self._show_message(
            "Import Complete",
            f"Successfully imported {len(imported_items)} items from folder!",
            QMessageBox.Icon.Information
        )

    
    # ===== Task Operations =====
    
    def handle_add_task(self) -> None:
        """Handle Add Task button click."""
        selected_item = self._get_selected_item()
        if not selected_item:
            self._show_message("No Selection", "Please select an item to create a task for.", QMessageBox.Icon.Warning)
            return
        
        dialog = QDialog(self.view)
        dialog.setWindowTitle("Add Task")
        dialog.resize(700, 450)
        dialog.setMinimumSize(650, 400)
        dialog.showEvent = lambda event: self._animate_scale(dialog, duration=200)
        
        layout = QGridLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        desc_label = QLabel("Description:")
        desc_field = QLineEdit()
        desc_field.setMinimumHeight(35)
        desc_field.setPlaceholderText("Enter task description")
        layout.addWidget(desc_label, 0, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(desc_field, 0, 1)
        
        priority_label = QLabel("Priority:")
        priority_slider = QSlider(Qt.Orientation.Horizontal)
        priority_slider.setMinimum(1)
        priority_slider.setMaximum(10)
        priority_slider.setValue(5)
        priority_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        priority_slider.setTickInterval(1)
        
        priority_value_label = QLabel(f"Priority: {5}/10")
        priority_value_label.setMinimumWidth(100)
        priority_slider.valueChanged.connect(
            lambda value: priority_value_label.setText(f"Priority: {value}/10")
        )
        
        priority_layout = QHBoxLayout()
        priority_layout.addWidget(priority_slider, stretch=1)
        priority_layout.addWidget(priority_value_label)
        layout.addWidget(priority_label, 1, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(priority_layout, 1, 1)
        
        deadline_label = QLabel("Deadline:")
        deadline_picker = QDateEdit()
        deadline_picker.setDate(QDate.currentDate().addDays(7))
        deadline_picker.setCalendarPopup(True)
        deadline_picker.setMinimumHeight(35)
        layout.addWidget(deadline_label, 2, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(deadline_picker, 2, 1)
        
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box, 3, 0, 1, 2)
        layout.setRowStretch(3, 1)
        dialog.setLayout(layout)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            q_date = deadline_picker.date()
            deadline = datetime(q_date.year(), q_date.month(), q_date.day())
            
            task = Task(
                item_id=selected_item.id,
                priority=priority_slider.value(),
                deadline=deadline,
                description=desc_field.text()
            )
            
            self.library_service.add_task(task)
            self._update_task_count()
            
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"Task created: priority={task.priority}")
            
            self._show_message("Success", f"Task created with priority {task.priority}!", QMessageBox.Icon.Information)
    
    def handle_view_next_task(self) -> None:
        """Handle View Next Task button click."""
        next_task = self.library_service.get_next_task()
        
        if not next_task:
            self._show_message("No Tasks", "Task queue is empty!", QMessageBox.Icon.Information)
            return
        
        item = self.library_service.find_item_by_id(next_task.item_id)
        item_title = item.title if item else "Unknown Item"
        
        message = (
            f"Item: {item_title}\n"
            f"Priority: {next_task.priority}/10\n"
            f"Deadline: {next_task.deadline.date()}\n"
            f"Description: {next_task.description}"
        )
        
        self._show_message("Highest Priority Task", message, QMessageBox.Icon.Information)
        self._update_task_count()
        
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Retrieved next task: priority={next_task.priority}")
    
    def _update_task_count(self) -> None:
        """Update task count label."""
        count = len(self.library_service.get_all_tasks())
        self.task_count_label.setText(f"Tasks: {count}")
    
    # ===== Media Preview =====
    
    def handle_preview(self) -> None:
        """Handle Preview button click."""
        selected_items = self._get_selected_items()
        if not selected_items:
            self._show_message("No Selection", "Please select at least one item to preview.",
                               QMessageBox.Icon.Warning)
            return
        
        for item in selected_items:
            file_path = item.file_path
            if not file_path:
                self._show_message("No File", f"Item '{item.title}' has no associated file.",
                                   QMessageBox.Icon.Warning)
                continue
            
            path = Path(file_path)
            if not path.exists():
                self._show_message("File Not Found", f"File does not exist:\n{file_path}",
                                   QMessageBox.Icon.Critical)
                continue
            
            item_type = item.type
            
            if item_type in ["audio", "video"]:
                self._preview_media(path, item_type)
            else:
                self._open_in_system_viewer(path)
    
    def _open_in_system_viewer(self, path: Path) -> None:
        """Open file with the system's default application."""
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(str(path))
            elif system == "Darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
            
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"Opened in system viewer: {path}")
        
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Failed to open system viewer for {path}: {e}", exc_info=True)
            self._show_message("Preview Error", f"Could not open file:\n{str(e)}", QMessageBox.Icon.Critical)
    
    def _preview_media(self, file_path: Path, media_type: str) -> None:
        """Open media player for audio/video preview."""
        try:
            self.media_player = QMediaPlayer()
            audio_output = QAudioOutput()
            self.media_player.setAudioOutput(audio_output)
            
            dialog = QDialog(self.view)
            dialog.setWindowTitle(f"Media Preview: {file_path.name}")
            dialog.resize(640, 480)
            
            layout = QVBoxLayout()
            
            if media_type == "video":
                video_widget = QVideoWidget()
                self.media_player.setVideoOutput(video_widget)
                layout.addWidget(video_widget)
            else:
                audio_label = QLabel(f"🎵 Playing Audio: {file_path.name}")
                audio_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                audio_label.setStyleSheet("font-size: 16px;")
                layout.addWidget(audio_label)
            
            controls_layout = QHBoxLayout()
            play_btn = QPushButton("▶ Play")
            pause_btn = QPushButton("⏸ Pause")
            stop_btn = QPushButton("⏹ Stop")
            
            play_btn.clicked.connect(self.media_player.play)
            pause_btn.clicked.connect(self.media_player.pause)
            stop_btn.clicked.connect(lambda: [self.media_player.stop(), dialog.close()])
            
            controls_layout.addWidget(play_btn)
            controls_layout.addWidget(pause_btn)
            controls_layout.addWidget(stop_btn)
            layout.addLayout(controls_layout)
            dialog.setLayout(layout)
            
            self.media_player.setSource(QUrl.fromLocalFile(str(file_path)))
            self.media_player.play()
            dialog.finished.connect(lambda _: self.media_player.stop())
            dialog.exec()
            
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"Media preview opened: {file_path.name}")
        
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Media preview error: {e}", exc_info=True)
            self._show_message("Media Error", f"Error playing media file:\n{str(e)}", QMessageBox.Icon.Critical)
    
    # ===== Data Persistence =====
    
    def load_data(self, data: LibraryData) -> None:
        """Load library data from repository."""
        self.library_service.items.clear()
        self.library_service._id_index.clear()
        
        for item in data.items:
            self.library_service.add_item(item)
        
        self.search_service.build_index(self.library_service.get_items())
        self._refresh_table()
        
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Loaded {len(data.items)} items from repository")
    
    def get_data(self) -> LibraryData:
        """Get library data for saving to repository."""
        data = LibraryData()
        data.items = self.library_service.get_items().copy()
        data.tasks = self.library_service.get_all_tasks().copy()
        data.keyword_index = self.search_service.get_keyword_index()
        data.tag_frequency = self.search_service.get_tag_frequency()
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Prepared data for saving: {len(data.items)} items")
        
        return data
    
    # ===== UI Helper Methods =====
    
    def _refresh_table(self, items: Optional[List[Item]] = None) -> None:
        """Refresh table with items (optimized batch operation)."""
        if items is None:
            items = self.library_service.get_items()
        
        self.items_table.setSortingEnabled(False)
        self.items_table.setRowCount(len(items))
        
        for row, item in enumerate(items):
            title_item = QTableWidgetItem(item.title)
            title_item.setData(Qt.ItemDataRole.UserRole, item)
            self.items_table.setItem(row, 0, title_item)
            self.items_table.setItem(row, 1, QTableWidgetItem(item.category))
            self.items_table.setItem(row, 2, QTableWidgetItem(item.type))
            self.items_table.setItem(row, 3, QTableWidgetItem(str(item.rating)))
            self.items_table.setItem(row, 4, QTableWidgetItem(", ".join(item.tags)))
        
        self.items_table.setSortingEnabled(True)
    
    def _get_selected_item(self) -> Optional[Item]:
        """Get the currently selected item from table."""
        selected_rows = self.items_table.selectedItems()
        if not selected_rows:
            return None
        
        row = self.items_table.currentRow()
        title_item = self.items_table.item(row, 0)
        
        if title_item:
            return title_item.data(Qt.ItemDataRole.UserRole)
        
        return None
    
    def _get_selected_items(self) -> List[Item]:
        """Return all selected Item objects from the table."""
        selected_items = []
        rows = set(index.row() for index in self.items_table.selectedIndexes())
        if not rows:
            return []
        
        for row in rows:
            title_item = self.items_table.item(row, 0)
            if title_item:
                item = title_item.data(Qt.ItemDataRole.UserRole)
                if item:
                    selected_items.append(item)
        
        return selected_items
    
    # ===== Animations =====
    
    def _animate_fade_in(
        self,
        widget,
        duration: int = 800,
        start_opacity: float = 0.0
    ) -> None:
        """Fade-in animation for widget."""
        animation = QPropertyAnimation(widget, b"windowOpacity")
        animation.setDuration(duration)
        animation.setStartValue(start_opacity)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        animation.start()
    
    def _animate_scale(self, widget, duration: int = 200) -> None:
        """Scale animation for dialogs."""
        self._animate_fade_in(widget, duration=duration, start_opacity=0.8)
    
    # ===== Inner Class: AddItemDialog =====
    
    class AddItemDialog(QDialog):
        """Dialog to add a new library item."""
        
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Add New Item")
            self.setMinimumWidth(450)
            
            layout = QVBoxLayout(self)
            
            self.title_field = QLineEdit()
            self.title_field.setPlaceholderText("Enter title")
            layout.addWidget(QLabel("Title*"))
            layout.addWidget(self.title_field)
            
            self.category_field = QLineEdit()
            self.category_field.setPlaceholderText("Enter category (optional)")
            layout.addWidget(QLabel("Category"))
            layout.addWidget(self.category_field)
            
            layout.addWidget(QLabel("Type*"))
            self.type_group = QWidget()
            type_layout = QHBoxLayout(self.type_group)
            self.types = {
                "note": QRadioButton("Note"),
                "pdf": QRadioButton("PDF"),
                "docx": QRadioButton("DOCX"),
                "ppt": QRadioButton("PPT"),
                "audio": QRadioButton("Audio"),
                "video": QRadioButton("Video"),
                "url": QRadioButton("URL")
            }
            for t in self.types.values():
                type_layout.addWidget(t)
            self.types["note"].setChecked(True)
            layout.addWidget(self.type_group)
            
            self.file_field = QLineEdit()
            self.file_button = QPushButton("Browse")
            file_layout = QHBoxLayout()
            file_layout.addWidget(self.file_field)
            file_layout.addWidget(self.file_button)
            layout.addWidget(QLabel("File Path"))
            layout.addLayout(file_layout)
            self.file_button.clicked.connect(self.pick_file)
            
            self.url_field = QLineEdit()
            self.url_field.setPlaceholderText("Enter URL (if type is URL)")
            layout.addWidget(QLabel("URL"))
            layout.addWidget(self.url_field)
            
            self.tags_field = QLineEdit()
            self.tags_field.setPlaceholderText("e.g. math, algorithms, ai")
            layout.addWidget(QLabel("Tags (comma-separated)"))
            layout.addWidget(self.tags_field)
            
            layout.addWidget(QLabel("Rating (0 = Unrated)"))
            slider_layout = QHBoxLayout()
            self.rating_slider = QSlider(Qt.Orientation.Horizontal)
            self.rating_slider.setRange(0, 5)
            self.rating_slider.setValue(0)
            self.rating_label = QLabel("0")
            self.rating_slider.valueChanged.connect(
                lambda v: self.rating_label.setText(str(v))
            )
            slider_layout.addWidget(self.rating_slider)
            slider_layout.addWidget(self.rating_label)
            layout.addLayout(slider_layout)
            
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok |
                QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            
            for _, btn in self.types.items():
                btn.toggled.connect(self.update_field_states)
            
            self.update_field_states()
        
        def pick_file(self):
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File")
            if file_path:
                self.file_field.setText(file_path)
        
        def update_field_states(self):
            selected = self.get_selected_type()
            is_url_type = selected == "url"
            is_file_type = selected in {"pdf", "docx", "ppt", "audio", "video"}
            
            self.url_field.setEnabled(is_url_type)
            self.file_field.setEnabled(is_file_type)
            self.file_button.setEnabled(is_file_type)
            
            if is_url_type and self.file_field.text():
                self.file_field.clear()
            if is_file_type and self.url_field.text():
                self.url_field.clear()
        
        def get_selected_type(self) -> str:
            for type_key, btn in self.types.items():
                if btn.isChecked():
                    return type_key
            return "note"
        
        def get_item_data(self) -> Optional[dict]:
            title = self.title_field.text().strip()
            if not title:
                QMessageBox.warning(self, "Error", "Title is required.")
                return None
            
            data = {
                "title": title,
                "category": self.category_field.text().strip() or "Uncategorized",
                "type": self.get_selected_type(),
                "tags": [t.strip() for t in self.tags_field.text().split(",") if t.strip()],
                "rating": self.rating_slider.value()
            }
            
            if data["type"] == "url":
                url = self.url_field.text().strip()
                if not url:
                    QMessageBox.warning(self, "Error", "URL is required for URL type.")
                    return None
                data["url"] = url
            else:
                file = self.file_field.text().strip()
                if data["type"] in {"pdf", "docx", "ppt", "audio", "video"} and not file:
                    QMessageBox.warning(self, "Error", "File is required for this type.")
                    return None
                data["file_path"] = file if file else None
            
            return data
