# earEEG

ESP32-S3 EEG 耳机工程项目，包含固件、上位机和声音-EEG 闭环应用。

## 项目结构

```
earEEG/
├── earEEG/                  # ESP32-S3 固件 (C / ESP-IDF / PlatformIO)
├── upper_machine/           # PC 上位机 (Python / LSL / 浏览器查看器)
├── ear_eeg_sound_lab/       # 声音-EEG 闭环应用
│   ├── src/
│   │   ├── integrations/    # LSL 读取、NPZ 加载、滚动缓存
│   │   ├── realtime_engine/ # 预处理、频段特征、信号质量、专注度、管线
│   │   └── storage/         # 会话汇总
│   └── tests/               # 单元测试
└── recordings/              # 实验数据 (.npz)
```

## 数据流

```
真实设备 / 模拟设备
  → upper_machine.lsl_proxy (TCP → LSL)
  → ear_eeg_sound_lab (窗口 → 预处理 → 频段特征 → 信号质量 → 专注度)
  → 结构化输出
```

## 快速开始

### 安装依赖

```powershell
cd ear_eeg_sound_lab
pip install -e .
```

### 运行测试

```powershell
python -m unittest discover -s ear_eeg_sound_lab/tests -p "test_*.py"
```

### 离线分析 NPZ

```python
from ear_eeg_sound_lab.src.integrations.npz_loader import load_npz_session
from ear_eeg_sound_lab.src.realtime_engine.pipeline import process_eeg_array
from ear_eeg_sound_lab.src.storage.session_summary import summarize_engine_outputs

session = load_npz_session("recordings/20260606_113353.npz")
outputs = process_eeg_array(session.eeg, sample_rate=session.eeg_sample_rate, unit="counts")
summary = summarize_engine_outputs(outputs)
print(summary)
```

### 实时 LSL

```python
from ear_eeg_sound_lab.src.integrations.lsl_reader import LSLStreamReader
from ear_eeg_sound_lab.src.integrations.lsl_buffer import EEGRollingBuffer
from ear_eeg_sound_lab.src.realtime_engine.pipeline import process_window

reader = LSLStreamReader()
reader.connect()
buffer = EEGRollingBuffer(channels=16, sample_rate=250.0)

while True:
    chunk = reader.pull_chunk()
    if chunk:
        buffer.append_chunk(chunk)
        window = buffer.pop_next_window()
        if window:
            result = process_window(window)
            print(f"Focus: {result.focus.score}, State: {result.focus.state}")
```

## 技术栈

- **固件:** C / ESP-IDF / PlatformIO
- **上位机:** Python 3.14+ / pylsl / numpy
- **算法:** numpy / scipy (FFT band power, Butterworth 滤波)
- **协议:** 自定义 TCP 二进制协议 (OpenBCI 兼容)

## 许可

未指定。
