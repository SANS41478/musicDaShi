"""Export dialog — configure WAV export settings."""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
)


class ExportDialog(QDialog):
    """Dialog for configuring audio export settings."""

    def __init__(self, parent=None, duration: float = 0.0):
        super().__init__(parent)
        self.setWindowTitle("导出 WAV")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        # Info
        info_label = QLabel(f"渲染时长: {duration:.1f} 秒")
        layout.addWidget(info_label)

        # Effects
        fx_group = QGroupBox("效果")
        fx_form = QFormLayout(fx_group)

        self.reverb_check = QCheckBox("启用混响")
        self.reverb_check.setChecked(False)
        self.reverb_check.setToolTip("添加 Schroeder 混响效果")
        self.reverb_check.toggled.connect(self._on_reverb_toggled)
        fx_form.addRow(self.reverb_check)

        self.wet_spin = QDoubleSpinBox()
        self.wet_spin.setRange(0.0, 1.0)
        self.wet_spin.setValue(0.3)
        self.wet_spin.setSingleStep(0.05)
        self.wet_spin.setDecimals(2)
        self.wet_spin.setSuffix("")
        self.wet_spin.setToolTip("混响强度 (0-1)")
        self.wet_spin.setEnabled(False)
        fx_form.addRow("混响强度:", self.wet_spin)

        self.room_spin = QDoubleSpinBox()
        self.room_spin.setRange(0.0, 1.0)
        self.room_spin.setValue(0.5)
        self.room_spin.setSingleStep(0.05)
        self.room_spin.setDecimals(2)
        self.room_spin.setToolTip("房间大小 (0-1)")
        self.room_spin.setEnabled(False)
        fx_form.addRow("房间大小:", self.room_spin)

        self.damp_spin = QDoubleSpinBox()
        self.damp_spin.setRange(0.0, 1.0)
        self.damp_spin.setValue(0.5)
        self.damp_spin.setSingleStep(0.05)
        self.damp_spin.setDecimals(2)
        self.damp_spin.setToolTip("高频衰减 (0-1)")
        self.damp_spin.setEnabled(False)
        fx_form.addRow("阻尼:", self.damp_spin)

        layout.addWidget(fx_group)

        # Settings
        settings_group = QGroupBox("导出设置")
        form = QFormLayout(settings_group)

        self.normalize_check = QCheckBox("自动归一化")
        self.normalize_check.setChecked(True)
        self.normalize_check.setToolTip("自动调整音量避免削波失真")
        form.addRow(self.normalize_check)

        self.fade_in_spin = QDoubleSpinBox()
        self.fade_in_spin.setRange(0.0, 5.0)
        self.fade_in_spin.setValue(0.02)
        self.fade_in_spin.setSingleStep(0.01)
        self.fade_in_spin.setSuffix(" 秒")
        self.fade_in_spin.setDecimals(2)
        form.addRow("淡入:", self.fade_in_spin)

        self.fade_out_spin = QDoubleSpinBox()
        self.fade_out_spin.setRange(0.0, 10.0)
        self.fade_out_spin.setValue(0.5)
        self.fade_out_spin.setSingleStep(0.1)
        self.fade_out_spin.setSuffix(" 秒")
        self.fade_out_spin.setDecimals(2)
        form.addRow("淡出:", self.fade_out_spin)

        layout.addWidget(settings_group)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_reverb_toggled(self, enabled: bool):
        self.wet_spin.setEnabled(enabled)
        self.room_spin.setEnabled(enabled)
        self.damp_spin.setEnabled(enabled)

    def get_settings(self) -> dict:
        """Get the export settings as a dictionary."""
        return {
            "normalize": self.normalize_check.isChecked(),
            "fade_in": self.fade_in_spin.value(),
            "fade_out": self.fade_out_spin.value(),
            "reverb": self.reverb_check.isChecked(),
            "reverb_wet": self.wet_spin.value(),
            "reverb_room": self.room_spin.value(),
            "reverb_damping": self.damp_spin.value(),
            "default_name": "output.wav",
        }
