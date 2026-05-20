# musicDaShi — 自动演奏引擎

## 项目概述

一个桌面应用，用户提供 MIDI 乐谱 + 乐器采样（标准库/合成器/自定义），自动渲染成音频。

### 核心理念

MIDI 本身就是完美的"量化乐谱"——它将音乐拆解为：
- Note Number（哪个音）
- Velocity（多大声）
- Tick/Delta Time（什么时候弹、弹多久）
- Control Change（踏板、滑音等）

演奏 = MIDI Event Stream × Voice Provider（音色源）→ 混音 → WAV

---

## 架构设计

```
┌────────────────────────────────────────────────────┐
│                    GUI (PySide6)                    │
│  MIDI导入 │ 音色管理 │ 播放/停止 │ 导出           │
└──────────────────────┬─────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────┐
│                  Performance Engine                 │
│  MIDI Parser ──► Timeline Builder ──► Renderer     │
└──────────────────────┬─────────────────────────────┘
                       │ per-note-event
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │SF2/SFZ   │ │ Synth    │ │ User     │
    │Provider  │ │ Provider │ │ Sample   │
    │(FluidSyn│ │ (numpy)  │ │ Provider │
    └────┬─────┘ └────┬─────┘ └────┬─────┘
         │            │            │
         └────────────┼────────────┘
                      ▼
               ┌──────────────┐
               │    Mixer      │
               │  numpy sum +  │
               │  normalize   │
               └──────┬───────┘
                      ▼
                 WAV / 实时播放
```

---

## 模块划分

### 1. MIDI Parser (`midi_parser.py`)
- 输入: .mid 文件路径
- 输出: `List[NoteEvent]`，每个事件包含 track, note, velocity, start_time(秒), duration(秒)
- 依赖: `mido`
- 处理: tempo 变化、拍号、将 tick 转为绝对时间

### 2. Voice Providers (`voice/`)
- 抽象基类 `VoiceProvider`: `render(note, velocity, duration, sample_rate) -> np.ndarray`
- `SF2Provider`: 封装 FluidSynth，加载 .sf2/.sfz
- `SynthProvider`: numpy 波形合成（sine/square/saw/triangle + ADSR 包络）
- `UserSampleProvider`: 用户提供 WAV + 手工指定键位/力度映射

### 3. Performance Engine (`engine.py`)
- 接收 MIDI event list + VoiceProvider 字典（每轨可选不同音色）
- 构建时间线，按 note 逐个调用 voice.render()
- 将渲染结果放置到时间线正确位置
- 处理复音（polyphony）

### 4. Mixer (`mixer.py`)
- 将所有时间线片段叠加混合
- 归一化防爆音
- 可加简单混响（可选）
- 输出完整 numpy array

### 5. GUI (`gui/`)
- MainWindow: 整体布局
- MIDI Track View: 显示轨道信息
- Voice Panel: 管理音色配置（添加/切换 SF2/SFZ/Synth/UserSample）
- Transport: 播放/停止/导出
- Export Dialog: 选择输出格式和参数

---

## 技术决策

| 项目 | 选择 | 理由 |
|-----|------|------|
| 语言 | Python 3.10+ | 音频库生态最成熟 |
| GUI | PySide6 | Qt 的 Python 绑定，跨平台，组件丰富 |
| MIDI 解析 | mido | 纯 Python，API 简洁 |
| SF2/SFZ 引擎 | pyfluidsynth | FluidSynth 支持 SF2+SFZ，质量高 |
| 合成器 | numpy 手写 | 简单波形合成不需要额外依赖 |
| 音频 I/O | soundfile + numpy | 读写 WAV，数组操作 |
| 实时播放 | sounddevice | 轻量，跨平台 |

---

## 目录结构

```
musicDaShi/
├── README.md
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── midi_parser.py
│   ├── voice/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── sf2_provider.py
│   │   ├── synth_provider.py
│   │   └── user_sample_provider.py
│   ├── engine.py
│   ├── mixer.py
│   └── gui/
│       ├── __init__.py
│       ├── main_window.py
│       ├── midi_view.py
│       ├── voice_panel.py
│       └── export_dialog.py
├── samples/          # 用户自定义采样存放
└── output/           # 渲染输出的 WAV/MP3
```

---

## 开发流水线

1. ✅ 架构规划
2. ✅ 项目骨架 + 依赖
3. ✅ MIDI Parser
4. ✅ Voice Provider 体系
5. ✅ Engine + Mixer
6. ✅ GUI
7. ✅ 集成测试
