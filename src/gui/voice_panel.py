"""Voice configuration panel — assign voices to MIDI tracks."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class VoiceConfigPanel(QWidget):
    """Panel for configuring voice assignments and track settings."""

    voice_changed = Signal(int, str)          # track_index, voice_name
    track_settings_changed = Signal(int)       # track_index — emitted when volume/pan/transpose/mute/solo change
    add_sf2_requested = Signal()
    add_synth_requested = Signal()
    add_user_samples_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)

        # Header
        header = QLabel("音色配置")
        header.setFont(QFont(header.font().family(), 12, QFont.Bold))
        layout.addWidget(header)

        # Track info
        self.track_label = QLabel("请先在左侧选择一个轨道")
        self.track_label.setStyleSheet("color: #888;")
        layout.addWidget(self.track_label)

        # Voice assignment
        voice_group = QGroupBox("音色分配")
        voice_layout = QVBoxLayout(voice_group)

        voice_row = QHBoxLayout()
        voice_row.addWidget(QLabel("音色:"))
        self.voice_combo = QComboBox()
        self.voice_combo.setMinimumWidth(200)
        self.voice_combo.currentTextChanged.connect(self._on_voice_selected)
        voice_row.addWidget(self.voice_combo, 1)
        voice_layout.addLayout(voice_row)

        layout.addWidget(voice_group)

        # Track settings
        settings_group = QGroupBox("轨道设置")
        settings_layout = QVBoxLayout(settings_group)

        # Mute / Solo
        ms_row = QHBoxLayout()
        self.mute_check = QCheckBox("静音 (Mute)")
        self.mute_check.toggled.connect(lambda: self._emit_settings_changed())
        ms_row.addWidget(self.mute_check)
        self.solo_check = QCheckBox("独奏 (Solo)")
        self.solo_check.toggled.connect(lambda: self._emit_settings_changed())
        ms_row.addWidget(self.solo_check)
        ms_row.addStretch()
        settings_layout.addLayout(ms_row)

        # Volume
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("音量:"))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_label = QLabel("100%")
        self.volume_slider.valueChanged.connect(
            lambda v: (self.volume_label.setText(f"{v}%"), self._emit_settings_changed())
        )
        vol_row.addWidget(self.volume_slider)
        vol_row.addWidget(self.volume_label)
        settings_layout.addLayout(vol_row)

        # Pan
        pan_row = QHBoxLayout()
        pan_row.addWidget(QLabel("声像:"))
        self.pan_slider = QSlider(Qt.Horizontal)
        self.pan_slider.setRange(-100, 100)
        self.pan_slider.setValue(0)
        self.pan_label = QLabel("C")
        self.pan_slider.valueChanged.connect(
            lambda v: (self._update_pan_label(v), self._emit_settings_changed())
        )
        pan_row.addWidget(self.pan_slider)
        pan_row.addWidget(self.pan_label)
        settings_layout.addLayout(pan_row)

        # Transpose
        trans_row = QHBoxLayout()
        trans_row.addWidget(QLabel("移调:"))
        self.transpose_spin = QSpinBox()
        self.transpose_spin.setRange(-24, 24)
        self.transpose_spin.setValue(0)
        self.transpose_spin.setSuffix(" 半音")
        self.transpose_spin.valueChanged.connect(lambda v: self._emit_settings_changed())
        trans_row.addWidget(self.transpose_spin)
        trans_row.addStretch()
        settings_layout.addLayout(trans_row)

        layout.addWidget(settings_group)

        # Add voice buttons
        add_group = QGroupBox("添加音色")
        add_layout = QVBoxLayout(add_group)

        btn_sf2 = QPushButton("添加 SF2/SFZ 音色库...")
        btn_sf2.clicked.connect(self.add_sf2_requested.emit)
        add_layout.addWidget(btn_sf2)

        btn_synth = QPushButton("添加合成器音色...")
        btn_synth.clicked.connect(self.add_synth_requested.emit)
        add_layout.addWidget(btn_synth)

        btn_user = QPushButton("添加自定义采样...")
        btn_user.clicked.connect(self.add_user_samples_requested.emit)
        add_layout.addWidget(btn_user)

        layout.addWidget(add_group)

        layout.addStretch()

        self._current_track = -1
        self._suppress_signal = False

    def _update_pan_label(self, value: int):
        if value < -33:
            self.pan_label.setText(f"L{abs(value)}")
        elif value > 33:
            self.pan_label.setText(f"R{value}")
        else:
            self.pan_label.setText("C")

    def set_available_voices(self, voice_names: list[str]):
        """Update the voice dropdown with available voices."""
        self._suppress_signal = True
        current = self.voice_combo.currentText()
        self.voice_combo.clear()
        self.voice_combo.addItems(voice_names)
        if current in voice_names:
            self.voice_combo.setCurrentText(current)
        self._suppress_signal = False

    def set_current_track(self, track_index: int):
        """Update the panel for a newly selected track."""
        self._current_track = track_index
        self.track_label.setText(f"当前轨道: {track_index}")

    def set_current_voice(self, voice_name: str):
        """Set the displayed voice for the current track."""
        self._suppress_signal = True
        idx = self.voice_combo.findText(voice_name)
        if idx >= 0:
            self.voice_combo.setCurrentIndex(idx)
        self._suppress_signal = False

    def set_track_settings(self, volume: float = 1.0, pan: float = 0.0,
                           transpose: int = 0, mute: bool = False, solo: bool = False):
        """Update all track setting controls from external values."""
        self._suppress_signal = True
        self.volume_slider.setValue(int(volume * 100))
        self.pan_slider.setValue(int(pan * 100))
        self.transpose_spin.setValue(transpose)
        self.mute_check.setChecked(mute)
        self.solo_check.setChecked(solo)
        self._suppress_signal = False

    def get_track_settings(self) -> dict:
        """Get current track settings as a dictionary."""
        return {
            "volume": self.volume_slider.value() / 100.0,
            "pan": self.pan_slider.value() / 100.0,
            "transpose": self.transpose_spin.value(),
            "mute": self.mute_check.isChecked(),
            "solo": self.solo_check.isChecked(),
        }

    def _on_voice_selected(self, voice_name: str):
        """Handle voice selection change."""
        if self._suppress_signal or self._current_track < 0:
            return
        self.voice_changed.emit(self._current_track, voice_name)

    def _emit_settings_changed(self):
        """Emit track_settings_changed when any setting control changes."""
        if self._suppress_signal or self._current_track < 0:
            return
        self.track_settings_changed.emit(self._current_track)
