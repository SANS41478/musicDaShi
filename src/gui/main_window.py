"""Main application window for musicDaShi."""

import logging
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..engine import PerformanceEngine, RenderResult
from ..midi_parser import parse_midi, MidiFileInfo
from ..mixer import Mixer
from ..voice.base import VoiceProvider
from ..voice.sf2_provider import SF2Provider, FLUIDSYNTH_AVAILABLE
from ..voice.synth_provider import SynthProvider, Waveform, ADSR
from ..voice.user_sample_provider import UserSampleProvider

from .voice_panel import VoiceConfigPanel
from .midi_view import MidiTrackView
from .export_dialog import ExportDialog

logger = logging.getLogger(__name__)


class RenderWorker(QThread):
    """Background thread for rendering audio without blocking the UI."""

    progress = Signal(float)
    finished = Signal(object)  # RenderResult
    error = Signal(str)

    def __init__(self, engine: PerformanceEngine, midi_info: MidiFileInfo):
        super().__init__()
        self.engine = engine
        self.midi_info = midi_info

    def run(self):
        try:
            self.engine.set_progress_callback(lambda p: self.progress.emit(p))
            result = self.engine.render(self.midi_info)
            self.finished.emit(result)
        except Exception as e:
            logger.exception("Render failed")
            self.error.emit(str(e))


class PlaybackThread(QThread):
    """Thread for real-time audio playback via sounddevice."""

    finished = Signal()

    def __init__(self, audio: np.ndarray, sample_rate: int):
        super().__init__()
        self.audio = audio
        self.sample_rate = sample_rate
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            import sounddevice as sd

            # Resample if needed to match device rate
            device_rate = sd.query_devices(kind="output")["default_samplerate"]

            audio = self.audio
            if self.sample_rate != device_rate:
                from scipy import signal
                ratio = device_rate / self.sample_rate
                if audio.ndim == 2:
                    audio = np.column_stack([
                        signal.resample(audio[:, 0], int(len(audio) * ratio)),
                        signal.resample(audio[:, 1], int(len(audio) * ratio)),
                    ])
                else:
                    audio = signal.resample(audio, int(len(audio) * ratio))

            # Stream in chunks to allow stopping
            chunk_size = 1024
            stream = sd.OutputStream(
                samplerate=device_rate,
                channels=audio.shape[1] if audio.ndim == 2 else 1,
                dtype=np.float32,
            )
            stream.start()

            pos = 0
            while pos < len(audio) and not self._stop:
                end = min(pos + chunk_size, len(audio))
                chunk = audio[pos:end]
                if chunk.ndim == 1:
                    chunk = chunk.reshape(-1, 1)
                stream.write(chunk)
                pos = end

            stream.stop()
            stream.close()
        except ImportError:
            logger.warning("sounddevice not available — playback skipped")
        except Exception as e:
            logger.error("Playback error: %s", e)
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    """Main window for the musicDaShi desktop application."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("musicDaShi — 自动演奏引擎")
        self.resize(1000, 650)

        # Core components
        self.engine = PerformanceEngine(sample_rate=44100)
        self.mixer = Mixer(sample_rate=44100)
        self._midi_info: MidiFileInfo | None = None
        self._render_result: RenderResult | None = None
        self._render_worker: RenderWorker | None = None
        self._playback_thread: PlaybackThread | None = None
        self._voice_providers: dict[str, VoiceProvider] = {}

        # Default synth voice
        default_synth = SynthProvider(
            waveform=Waveform.SINE,
            adsr=ADSR(attack=0.01, decay=0.2, sustain=0.6, release=0.4),
            harmonics=3,
            name="默认钢琴 (合成)",
        )
        self._voice_providers["default_synth"] = default_synth
        self.engine.set_default_voice(default_synth)

        self._setup_ui()
        self._setup_menu()

    def _setup_ui(self):
        """Build the main UI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Splitter: track list | voice config
        splitter = QSplitter(Qt.Horizontal)

        # Left: Track list
        self.track_view = MidiTrackView()
        self.track_view.track_selected.connect(self._on_track_selected)
        splitter.addWidget(self.track_view)

        # Right: Voice config panel
        self.voice_panel = VoiceConfigPanel()
        self.voice_panel.voice_changed.connect(self._on_voice_changed)
        self.voice_panel.add_sf2_requested.connect(self._on_add_sf2)
        self.voice_panel.add_synth_requested.connect(self._on_add_synth)
        self.voice_panel.add_user_samples_requested.connect(self._on_add_user_samples)
        splitter.addWidget(self.voice_panel)

        splitter.setSizes([300, 650])
        main_layout.addWidget(splitter)

        # Bottom: Transport controls
        transport_layout = QHBoxLayout()

        self.btn_open = QPushButton("打开 MIDI")
        self.btn_open.clicked.connect(self._on_open_midi)
        transport_layout.addWidget(self.btn_open)

        self.btn_render = QPushButton("渲染")
        self.btn_render.setEnabled(False)
        self.btn_render.clicked.connect(self._on_render)
        transport_layout.addWidget(self.btn_render)

        self.btn_play = QPushButton("播放")
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(self._on_play)
        transport_layout.addWidget(self.btn_play)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        transport_layout.addWidget(self.btn_stop)

        self.btn_export = QPushButton("导出 WAV")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._on_export)
        transport_layout.addWidget(self.btn_export)

        transport_layout.addStretch()

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(250)
        transport_layout.addWidget(self.progress_bar)

        self.label_status = QLabel("请打开一个 MIDI 文件开始")
        transport_layout.addWidget(self.label_status)

        main_layout.addLayout(transport_layout)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪 — 请打开 MIDI 文件")

    def _setup_menu(self):
        """Set up the menu bar."""
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("文件(&F)")
        open_action = QAction("打开 MIDI(&O)...", self)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self._on_open_midi)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        export_action = QAction("导出 WAV(&E)...", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self._on_export)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        quit_action = QAction("退出(&Q)", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Voice menu
        voice_menu = menu_bar.addMenu("音色(&V)")
        add_sf2 = QAction("添加 SF2/SFZ 音色库...", self)
        add_sf2.triggered.connect(self._on_add_sf2)
        voice_menu.addAction(add_sf2)
        add_synth = QAction("添加合成器音色...", self)
        add_synth.triggered.connect(self._on_add_synth)
        voice_menu.addAction(add_synth)
        add_user = QAction("添加自定义采样...", self)
        add_user.triggered.connect(self._on_add_user_samples)
        voice_menu.addAction(add_user)

        # Help menu
        help_menu = menu_bar.addMenu("帮助(&H)")
        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    # ── Event handlers ────────────────────────────────────────────

    def _on_open_midi(self):
        """Open a MIDI file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "打开 MIDI 文件",
            "",
            "MIDI 文件 (*.mid *.midi);;所有文件 (*.*)",
        )
        if not file_path:
            return

        try:
            self._midi_info = parse_midi(file_path)
            self.status_bar.showMessage(f"已加载: {Path(file_path).name} — {self._midi_info.note_count} 个音符, {self._midi_info.track_count} 个轨道")

            # Update track view
            self.track_view.set_midi_info(self._midi_info)

            # Update voice panel with current voice configs
            voice_names = list(self._voice_providers.keys())
            self.voice_panel.set_available_voices(voice_names)

            # Enable render button
            self.btn_render.setEnabled(True)
            self.btn_play.setEnabled(False)
            self.btn_export.setEnabled(False)
            self.label_status.setText(f"{self._midi_info.note_count} 个音符 | {self._midi_info.track_count} 个轨道 | {self._midi_info.duration:.1f}秒")

        except Exception as e:
            logger.exception("Failed to open MIDI")
            QMessageBox.critical(self, "错误", f"无法打开 MIDI 文件:\n{e}")

    def _on_track_selected(self, track_index: int):
        """Handle track selection in the track view."""
        self.voice_panel.set_current_track(track_index)
        # Show current voice assignment for this track
        config = self.engine._track_configs.get(track_index)
        if config:
            self.voice_panel.set_current_voice(config.voice.name)

    def _on_voice_changed(self, track_index: int, voice_name: str):
        """Handle voice assignment change for a track."""
        voice = self._voice_providers.get(voice_name)
        if voice:
            self.engine.set_voice_for_track(track_index, voice)
            self.status_bar.showMessage(f"轨道 {track_index} → {voice_name}")
            # Need to re-render
            if self._render_result:
                self.btn_render.setText("重新渲染")
            self.btn_play.setEnabled(False)

    def _on_add_sf2(self):
        """Add an SF2/SFZ soundfont."""
        if not FLUIDSYNTH_AVAILABLE:
            QMessageBox.warning(
                self,
                "FluidSynth 不可用",
                "SF2/SFZ 支持需要安装 FluidSynth。\n\n"
                "请先安装 FluidSynth C 库，然后:\n"
                "pip install pyfluidsynth",
            )
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 SoundFont 文件",
            "",
            "SoundFont 文件 (*.sf2 *.sfz);;所有文件 (*.*)",
        )
        if not file_path:
            return

        try:
            sf2 = SF2Provider(file_path)
            name = sf2.name
            # Ensure unique name
            base = name
            counter = 1
            while name in self._voice_providers:
                name = f"{base} ({counter})"
                counter += 1
            sf2.name = name
            self._voice_providers[name] = sf2
            self.voice_panel.set_available_voices(list(self._voice_providers.keys()))
            self.status_bar.showMessage(f"已加载: {name}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法加载 SoundFont:\n{e}")

    def _on_add_synth(self):
        """Add a new synth voice with custom settings."""
        from PySide6.QtWidgets import QDialog, QFormLayout, QComboBox, QDialogButtonBox, QDoubleSpinBox

        dialog = QDialog(self)
        dialog.setWindowTitle("添加合成器音色")
        layout = QFormLayout(dialog)

        wave_combo = QComboBox()
        for w in Waveform:
            wave_combo.addItem(w.value, w)
        wave_combo.setCurrentText(Waveform.SINE.value)
        layout.addRow("波形:", wave_combo)

        attack_spin = QDoubleSpinBox()
        attack_spin.setRange(0.001, 2.0)
        attack_spin.setValue(0.01)
        attack_spin.setSingleStep(0.01)
        attack_spin.setDecimals(3)
        layout.addRow("Attack (秒):", attack_spin)

        decay_spin = QDoubleSpinBox()
        decay_spin.setRange(0.001, 2.0)
        decay_spin.setValue(0.2)
        decay_spin.setSingleStep(0.01)
        decay_spin.setDecimals(3)
        layout.addRow("Decay (秒):", decay_spin)

        sustain_spin = QDoubleSpinBox()
        sustain_spin.setRange(0.0, 1.0)
        sustain_spin.setValue(0.6)
        sustain_spin.setSingleStep(0.05)
        layout.addRow("Sustain (0-1):", sustain_spin)

        release_spin = QDoubleSpinBox()
        release_spin.setRange(0.01, 3.0)
        release_spin.setValue(0.4)
        release_spin.setSingleStep(0.05)
        layout.addRow("Release (秒):", release_spin)

        harm_spin = QDoubleSpinBox()
        harm_spin.setRange(0, 10)
        harm_spin.setValue(3)
        harm_spin.setDecimals(0)
        layout.addRow("泛音数:", harm_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        synth = SynthProvider(
            waveform=wave_combo.currentData(),
            adsr=ADSR(
                attack=attack_spin.value(),
                decay=decay_spin.value(),
                sustain=sustain_spin.value(),
                release=release_spin.value(),
            ),
            harmonics=int(harm_spin.value()),
            name=f"Synth-{wave_combo.currentText()}",
        )

        name = synth.name
        base = name
        counter = 1
        while name in self._voice_providers:
            name = f"{base} ({counter})"
            counter += 1
        synth.name = name
        self._voice_providers[name] = synth
        self.voice_panel.set_available_voices(list(self._voice_providers.keys()))
        self.status_bar.showMessage(f"已添加: {name}")

    def _on_add_user_samples(self):
        """Add user custom samples."""
        folder = QFileDialog.getExistingDirectory(self, "选择采样文件夹")
        if not folder:
            return

        try:
            usp = UserSampleProvider(name="自定义采样")
            folder_path = Path(folder)
            wav_files = sorted(folder_path.glob("*.wav"))

            if not wav_files:
                QMessageBox.warning(self, "无采样文件", "所选文件夹中没有找到 .wav 文件。")
                return

            # Auto-map: assume files are named with MIDI note numbers
            # e.g., "60.wav" = middle C, "C4.wav", or just assign sequentially
            note_map = {
                "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
                "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
                "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
            }

            for i, wav_path in enumerate(wav_files):
                # Try to extract note from filename
                stem = wav_path.stem.upper()

                midi_note = None
                # Try pure number
                try:
                    midi_note = int(stem)
                except ValueError:
                    pass

                # Try note name like "C4", "F#3"
                if midi_note is None and len(stem) >= 2:
                    for note_name, semitone in note_map.items():
                        if stem.startswith(note_name):
                            octave_str = stem[len(note_name):]
                            try:
                                octave = int(octave_str)
                                midi_note = (octave + 1) * 12 + semitone
                            except ValueError:
                                pass
                            break

                # Fallback: assign starting from middle C
                if midi_note is None:
                    midi_note = 60 + i

                usp.add_sample(
                    file_path=wav_path,
                    root_note=midi_note,
                    note_lo=max(0, midi_note - 2),
                    note_hi=min(127, midi_note + 2),
                )

            usp.load_samples()

            name = usp.name
            base = name
            counter = 1
            while name in self._voice_providers:
                name = f"{base} ({counter})"
                counter += 1
            usp.name = name
            self._voice_providers[name] = usp
            self.voice_panel.set_available_voices(list(self._voice_providers.keys()))
            self.status_bar.showMessage(f"已加载 {usp.sample_count} 个自定义采样 → {name}")
        except Exception as e:
            logger.exception("Failed to load user samples")
            QMessageBox.critical(self, "错误", f"无法加载自定义采样:\n{e}")

    def _on_render(self):
        """Render the MIDI with current voice settings."""
        if not self._midi_info:
            return

        self.btn_render.setEnabled(False)
        self.btn_play.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.label_status.setText("渲染中...")

        self._render_worker = RenderWorker(self.engine, self._midi_info)
        self._render_worker.progress.connect(self._on_render_progress)
        self._render_worker.finished.connect(self._on_render_finished)
        self._render_worker.error.connect(self._on_render_error)
        self._render_worker.start()

    def _on_render_progress(self, progress: float):
        """Update render progress bar."""
        self.progress_bar.setValue(int(progress * 100))

    def _on_render_finished(self, result: RenderResult):
        """Handle render completion."""
        self._render_result = result
        self.btn_render.setEnabled(True)
        self.btn_render.setText("重新渲染")
        self.btn_play.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.label_status.setText(
            f"渲染完成 — {result.note_count} 音符 | {result.duration:.1f}秒 | 用时 {result.render_time:.1f}秒"
        )
        self.status_bar.showMessage("渲染完成 — 可以播放或导出")

    def _on_render_error(self, error: str):
        """Handle render error."""
        self.btn_render.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.label_status.setText("渲染失败")
        QMessageBox.critical(self, "渲染错误", error)

    def _on_play(self):
        """Play the rendered audio."""
        if self._render_result is None:
            return

        self.btn_play.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.label_status.setText("播放中...")

        self._playback_thread = PlaybackThread(
            self._render_result.audio, self._render_result.sample_rate
        )
        self._playback_thread.finished.connect(self._on_playback_finished)
        self._playback_thread.start()

    def _on_stop(self):
        """Stop playback."""
        if self._playback_thread and self._playback_thread.isRunning():
            self._playback_thread.stop()
        self.btn_play.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.label_status.setText("已停止")

    def _on_playback_finished(self):
        """Handle playback completion."""
        self.btn_play.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if self._render_result:
            self.label_status.setText(
                f"渲染完成 — {self._render_result.note_count} 音符 | {self._render_result.duration:.1f}秒"
            )

    def _on_export(self):
        """Export rendered audio to WAV."""
        if self._render_result is None:
            return

        dialog = ExportDialog(self, self._render_result.duration)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        settings = dialog.get_settings()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 WAV",
            settings.get("default_name", "output.wav"),
            "WAV 文件 (*.wav);;所有文件 (*.*)",
        )
        if not file_path:
            return

        try:
            self.mixer.export_wav(
                self._render_result.audio,
                file_path,
                normalize=settings["normalize"],
                fade_in=settings["fade_in"],
                fade_out=settings["fade_out"],
            )
            self.status_bar.showMessage(f"已导出: {Path(file_path).name}")
        except Exception as e:
            QMessageBox.critical(self, "导出错误", str(e))

    def _on_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "关于 musicDaShi",
            "<h2>musicDaShi — 自动演奏引擎</h2>"
            "<p>将 MIDI 乐谱 + 乐器采样自动合成为音频。</p>"
            "<p>支持三种音色来源:</p>"
            "<ul>"
            "<li>SF2/SFZ 标准采样库 (FluidSynth)</li>"
            "<li>波形合成器</li>"
            "<li>用户自定义 WAV 采样</li>"
            "</ul>"
            "<p><b>技术栈:</b> Python + PySide6 + FluidSynth + numpy</p>",
        )
