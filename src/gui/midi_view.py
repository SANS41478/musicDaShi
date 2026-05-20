"""MIDI track list view — displays tracks from a loaded MIDI file."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..midi_parser import MidiFileInfo


class MidiTrackView(QWidget):
    """Widget displaying MIDI file tracks in a tree/table view."""

    track_selected = Signal(int)  # track_index

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QLabel("MIDI 轨道")
        header.setFont(QFont(header.font().family(), 12, QFont.Bold))
        layout.addWidget(header)

        # Track tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["轨道", "音符数", "通道"])
        self.tree.setColumnWidth(0, 120)
        self.tree.setColumnWidth(1, 70)
        self.tree.setColumnWidth(2, 60)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree)

        # Info label
        self.info_label = QLabel("未加载 MIDI 文件")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #888; padding: 4px;")
        layout.addWidget(self.info_label)

        self._midi_info: MidiFileInfo | None = None

    def set_midi_info(self, midi_info: MidiFileInfo):
        """Populate the tree with MIDI track information."""
        self._midi_info = midi_info
        self.tree.clear()

        if not midi_info:
            self.info_label.setText("未加载 MIDI 文件")
            return

        for track in midi_info.tracks:
            item = QTreeWidgetItem([
                track.name,
                str(track.note_count),
                str(track.channel + 1),
            ])
            item.setData(0, Qt.UserRole, track.index)
            self.tree.addTopLevelItem(item)

        self.info_label.setText(
            f"文件: {midi_info.file_path.name}\n"
            f"时长: {midi_info.duration:.1f} 秒\n"
            f"总音符: {midi_info.note_count}\n"
            f"TPQ: {midi_info.ticks_per_beat}"
        )

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle track selection."""
        track_index = item.data(0, Qt.UserRole)
        if track_index is not None:
            self.track_selected.emit(track_index)
