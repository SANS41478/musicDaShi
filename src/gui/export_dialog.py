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
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        # Info
        info_label = QLabel(f"渲染时长: {duration:.1f} 秒")
        layout.addWidget(info_label)

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

    def get_settings(self) -> dict:
        """Get the export settings as a dictionary."""
        return {
            "normalize": self.normalize_check.isChecked(),
            "fade_in": self.fade_in_spin.value(),
            "fade_out": self.fade_out_spin.value(),
            "default_name": "output.wav",
        }
