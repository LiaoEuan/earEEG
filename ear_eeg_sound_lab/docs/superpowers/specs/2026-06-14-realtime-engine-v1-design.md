# Realtime EEG Analysis Engine V1 — Design Spec

**Date**: 2026-06-14
**Status**: Approved
**Scope**: 离线/模拟数据驱动的实时分析引擎第一版

## 目标

在 `ear_eeg_sound_lab` 中实现第一版 EEG 数据处理链路：

```
NPZ / LSL 实时流
  → 窗口切片
  → 预处理（counts→uV + demean + 带通 + 陷波）
  → 频段特征（FFT band power）
  → 信号质量评估
  → 专注度评分
  → 结构化输出
```

不做：UI、LLM 报告、推荐歌、深度学习、直接连接 ESP32 TCP。

## 双入口架构

### 实时主入口

```
真实设备(192.168.4.1:8888) / 模拟设备(127.0.0.1:8889)
  │ TCP
  ▼
upper_machine.lsl_proxy
  │ LSL streams: earEEG_EEG (16ch, 250Hz, float32 counts)
  ▼
integrations/lsl_reader.py → EEGChunk
  │
  ▼
integrations/lsl_buffer.py → EEGWindow
  │
  ▼
realtime_engine/pipeline.py → EngineOutput
```

### 离线辅助入口

```
recordings/*.npz
  │
  ▼
integrations/npz_loader.py → NPZSession
  │
  ▼
realtime_engine/windowing.py → Iterator[EEGWindow]
  │
  ▼
realtime_engine/pipeline.py → EngineOutput
```

### 关键约束

- `realtime_engine/` 不依赖 LSL、HTTP、UI
- `integrations/lsl_reader.py` 可依赖 pylsl
- 真实设备和模拟设备都通过 `lsl_proxy` 进入 LSL
- `EEGWindow` 统一进入 pipeline，两个入口产出相同结构
- preprocessing 条件转换单位：`unit=="counts"` 才转 uV
- `EEGWindow` 携带 `gain`/`vref` 防止重复转换
- 下游模块统一在 uV 域工作

## 文件结构

```
ear_eeg_sound_lab/
  src/
    integrations/
      __init__.py
      lsl_reader.py          # 主入口：连接 LSL，拉取 EEG chunks
      lsl_buffer.py          # 滚动缓存，LSL chunk → 连续数据 → 窗口
      npz_loader.py          # 离线入口：读取 NPZ 文件
      replay.py              # 可选：NPZ 按时间回放（本阶段不实现）
    realtime_engine/
      __init__.py
      schemas.py             # 所有 dataclass
      windowing.py           # NPZ 离线窗口切片
      preprocessing.py       # counts→uV(条件) + demean + 带通 + 陷波
      features.py            # FFT band power + ratios
      quality.py             # 信号质量
      focus.py               # 专注度启发式
      pipeline.py            # 串联
    storage/
      __init__.py
      session_summary.py     # 汇总
  tests/
    test_lsl_buffer.py
    test_npz_loader.py
    test_windowing.py
    test_preprocessing.py
    test_features.py
    test_quality.py
    test_focus.py
    test_pipeline.py
```

## 数据结构（schemas.py）

### EEGWindow

```python
@dataclass
class EEGWindow:
    """算法管线的统一输入单元。"""
    data: np.ndarray          # shape: (channels, samples), float64
    sample_rate: float        # Hz, e.g. 250.0
    start_sample: int         # 在原始数据中的起始样本索引
    start_time: float | None  # 秒, start_sample / sample_rate
    unit: str                 # "counts" or "uv"
    gain: float = 24.0        # ADS1299 gain, 用于 counts→uV
    vref: float = 4.5         # ADS1299 vref, 用于 counts→uV
```

### PreprocessedWindow

```python
@dataclass
class PreprocessedWindow:
    """预处理后的窗口，下游模块统一使用。"""
    raw: EEGWindow            # 原始窗口引用
    data: np.ndarray          # shape: (channels, samples), float64, 单位 uV
    unit: str = "uv"
    sample_rate: float = 250.0
    notes: list[str]          # 预处理过程中的警告/信息
```

### BandPower

```python
@dataclass
class BandPower:
    """单通道的五频段功率。单位: uV²"""
    delta: float    # 1-4 Hz
    theta: float    # 4-8 Hz
    alpha: float    # 8-13 Hz
    beta: float     # 13-30 Hz
    gamma: float    # 30-45 Hz
```

### FeatureFrame

```python
@dataclass
class FeatureFrame:
    """频段特征输出。"""
    timestamp: float | None
    band_powers: dict[int, BandPower]    # channel_index → BandPower
    global_band_powers: BandPower        # 所有通道均值
    theta_beta_ratio: float              # global theta / global beta
    alpha_beta_ratio: float              # global alpha / global beta
    artifact_ratio: float                # 0.0-1.0
```

### SignalQuality

```python
@dataclass
class SignalQuality:
    """信号质量评估。"""
    score: float              # 0.0 - 1.0
    bad_channels: list[int]   # 问题通道索引
    warnings: list[str]       # 警告代码
```

### FocusEstimate

```python
@dataclass
class FocusEstimate:
    """专注度估计。"""
    score: int                # 0 - 100
    quality: float            # 0.0 - 1.0
    state: str                # "focused", "stable", "relaxed", "fatigued", "noisy"
    reasons: list[str]        # 原因代码列表
```

### EngineOutput

```python
@dataclass
class EngineOutput:
    """pipeline 单次输出。"""
    window: EEGWindow
    preprocessed: PreprocessedWindow
    features: FeatureFrame
    quality: SignalQuality
    focus: FocusEstimate
```

### EEGChunk（LSL 集成）

```python
@dataclass
class EEGChunk:
    """LSL 拉取的原始数据块。"""
    data: np.ndarray          # shape: (samples, channels), LSL 原始格式
    timestamps: np.ndarray    # shape: (samples,)
    sample_rate: float
    unit: str = "counts"
```

### NPZSession

```python
@dataclass
class NPZSession:
    """NPZ 文件加载结果。"""
    path: Path
    eeg: np.ndarray           # shape: (channels, samples), float32
    mic: np.ndarray | None    # shape: (samples,) or (samples, channels)
    stimuli: np.ndarray | None
    eeg_sample_rate: float
    mic_sample_rate: float | None
    metadata: dict
```

## 模块设计

### 1. npz_loader.py

读取 `recordings/*.npz`，纯 I/O，不做单位转换。

```python
def load_npz_session(path: str | Path) -> NPZSession:
    """
    读取 NPZ 文件，统一输出格式。

    Input: NPZ 文件路径
    Output: NPZSession
        - eeg: shape (channels, samples), float32, 单位 raw counts
        - mic: shape (samples,), float32 或 None
        - eeg_sample_rate: 默认 250.0
    """
```

行为：
- EEG 统一为 `(channels, samples)`，NPZ 已是此格式则保持
- MIC `(M, 1)` squeeze 为 `(M,)`
- 缺失字段返回 None，不崩溃
- 默认采样率 eeg=250, mic=16000

### 2. windowing.py

NPZ 离线窗口切片。

```python
def iter_eeg_windows(
    eeg: np.ndarray, sample_rate: float,
    window_seconds=2.0, step_seconds=0.5,
    unit="counts", gain=24.0, vref=4.5,
) -> Iterator[EEGWindow]:
    """
    把连续 EEG 切成固定窗口。

    Input: eeg shape (channels, samples)
    Output: Iterator[EEGWindow], 每个窗口 shape (channels, window_samples)
    """
```

行为：
- 2 秒窗口，0.5 秒步长
- 数据不足一个窗口时不输出
- `start_sample` 记录窗口起点
- `start_time = start_sample / sample_rate`

### 3. preprocessing.py

预处理：counts→uV（条件）+ demean + 带通 + 陷波。

```python
def preprocess_window(
    window: EEGWindow,
    notch_freq: float = 50.0,
    notch_q: float = 30.0,
    bandpass_low: float = 1.0,
    bandpass_high: float = 45.0,
    bandpass_order: int = 4,
) -> PreprocessedWindow:
    """
    预处理单个 EEG 窗口。

    Input: EEGWindow, unit 可能是 "counts" 或 "uv"
    Output: PreprocessedWindow, unit 固定为 "uv"

    流程:
    1. 条件转换单位 (counts→uV)
    2. NaN/Inf 清理
    3. 每通道去均值
    4. 陷波滤波 (可配置 50/60Hz)
    5. 带通滤波 (1-45Hz, 4阶 Butterworth)
    """
```

counts→uV 公式：
```python
scale = vref / gain / ((1 << 23) - 1) * 1e6  # µV per count
```

滤波注意事项：
- `filtfilt` 零相位滤波
- 短窗口 padlen 不能超过数据长度，否则降级为只做 demean
- 依赖 scipy: `scipy.signal.butter`, `scipy.signal.iirnotch`, `scipy.signal.filtfilt`

### 4. features.py

FFT 频段特征提取。

```python
BANDS = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta":  (13.0, 30.0),
    "gamma": (30.0, 45.0),
}

def compute_band_power(
    data: np.ndarray,       # shape: (channels, samples)
    sample_rate: float,
    low_hz: float,
    high_hz: float,
) -> np.ndarray:            # shape: (channels,)
    """单频段平均功率 (Hann 窗 + FFT)。"""

def extract_features(window: PreprocessedWindow) -> FeatureFrame:
    """提取全部频段特征 + ratios + artifact_ratio。"""
```

实现：
- Hann 窗 → rfft → 功率谱 → 频段平均
- 全局频段 = 所有通道均值
- `theta_beta_ratio = theta / max(beta, 1e-12)`
- `alpha_beta_ratio = alpha / max(beta, 1e-12)`
- `artifact_ratio = gamma_power / total_power`（gamma 30-45Hz 占总功率的比例，反映肌电等高频伪迹）

### 5. quality.py

信号质量评估。

```python
@dataclass
class QualityThresholds:
    min_std: float = 1e-6           # flatline
    max_abs_uv: float = 100000.0    # high amplitude
    max_ptp_uv: float = 200000.0    # high ptp
    noisy_std: float = 500.0        # noisy

def estimate_signal_quality(
    window: PreprocessedWindow,
    thresholds: QualityThresholds | None = None,
) -> SignalQuality:
    """评估窗口信号质量。"""
```

检测规则：
- flatline: `std(ch) < min_std`
- high amplitude: `max(abs(ch)) > max_abs_uv`
- high ptp: `ptp(ch) > max_ptp_uv`
- noisy: `std(ch) > noisy_std`

质量分数：
```python
artifact_penalty = min(len(bad_channels) * 0.15, 0.6)
score = clamp(1.0 - artifact_penalty, 0.0, 1.0)
```

### 6. focus.py

专注度启发式（扩展版）。

```python
def estimate_focus(features: FeatureFrame, quality: SignalQuality) -> FocusEstimate:
    """根据特征和质量估计专注度。"""
```

算法：
1. 质量门控：`quality < 0.4` → state="noisy", score≤40
2. 基础分 50
3. theta/beta ratio: <1.5 加 15, <2.0 加 10, >3.0 减 8, >4.0 减 15
4. alpha/beta ratio: >3.0 减 10, >2.0 减 5
5. beta 存在性: 加 5
6. artifact 惩罚: `artifact_ratio > 0.3` 时减 `int(artifact_ratio * 20)` 分
7. 质量加权: `base *= quality.score`
8. clamp 到 [0, 100]
9. 状态: ≥70 focused, ≥45 stable, ≥30 relaxed, <30 fatigued

### 7. pipeline.py

串联所有模块。

```python
def process_window(window: EEGWindow) -> EngineOutput:
    """处理单个窗口。"""

def process_eeg_array(
    eeg: np.ndarray, sample_rate: float,
    window_seconds=2.0, step_seconds=0.5,
    unit="counts", gain=24.0, vref=4.5,
) -> list[EngineOutput]:
    """离线入口：处理整个 EEG 数组。"""
```

### 8. lsl_reader.py

LSL 实时读取。

```python
class LSLStreamReader:
    def __init__(self, stream_name="earEEG_EEG", stream_type="EEG",
                 expected_channels=16, unit="counts"): ...
    def connect(self, timeout=5.0) -> None: ...
    def pull_chunk(self, max_samples=128, timeout=0.0) -> EEGChunk | None: ...
```

行为：
- 找不到 LSL stream 时给出清晰错误
- `pull_chunk()` 没数据返回 None
- 不做滤波，不做专注度
- 保证 shape 和 timestamp 正确

### 9. lsl_buffer.py

滚动缓存，LSL chunk → EEGWindow。

```python
class EEGRollingBuffer:
    def __init__(self, channels, sample_rate, capacity_seconds=30.0, unit="counts"): ...
    def append_chunk(self, chunk: EEGChunk) -> None: ...
    def has_window(self, window_seconds=2.0) -> bool: ...
    def latest_window(self, window_seconds=2.0) -> EEGWindow: ...
    def pop_next_window(self, window_seconds=2.0, step_seconds=0.5) -> EEGWindow | None: ...
```

内部保存 `(channels, samples)` 格式。

### 10. session_summary.py

汇总 EngineOutput 列表。

```python
def summarize_engine_outputs(outputs: list[EngineOutput]) -> dict:
    """
    返回汇总统计。

    badWindowRatio = count(quality.score < 0.4) / total_windows
    """

输出：
```json
{
    "windowCount": 120,
    "meanFocus": 63.5,
    "minFocus": 20,
    "maxFocus": 92,
    "meanQuality": 0.78,
    "badWindowRatio": 0.12,
    "stateCounts": {
        "focused": 34,
        "stable": 70,
        "noisy": 16
    },
    "warnings": []
}
```

## 依赖

```
numpy        — 全局
scipy        — preprocessing (滤波)
pylsl        — lsl_reader
dataclasses  — schemas (标准库)
unittest     — tests (标准库)
```

## 测试策略

测试优先覆盖纯算法模块，不强依赖真实 LSL。

| 测试文件 | 覆盖模块 | 关键用例 |
|----------|----------|----------|
| test_npz_loader.py | npz_loader | 读取真实 NPZ, eeg.ndim==2, 缺失字段不崩 |
| test_windowing.py | windowing | 250Hz/1000点 → 正确窗口数, shape 正确 |
| test_preprocessing.py | preprocessing | DC 偏置去除, NaN 清理, counts→uV, 滤波 |
| test_features.py | features | 10Hz→alpha 最大, 20Hz→beta 最大, 除零稳定 |
| test_quality.py | quality | 全零低质量, 正弦波高质量, score 范围 |
| test_focus.py | focus | 质量低→score 低, beta 占优→分数高, 范围正确 |
| test_pipeline.py | pipeline | 10s 模拟 EEG → 多个 EngineOutput, 无 NaN |
| test_lsl_buffer.py | lsl_buffer | chunk 累积, 窗口输出, 容量限制 |

测试命令：
```powershell
python -m unittest discover -s ear_eeg_sound_lab\tests -p "test_*.py"
```

## 验收标准

1. 可以读取已有 NPZ
2. 可以把 EEG 分成 2 秒窗口
3. 每个窗口输出: band powers, theta/beta ratio, signal quality, focus score, reasons
4. 所有测试通过
5. 不破坏现有 earEEG/, upper_machine/, simulated_device/
6. 代码注释说明清楚单位和 shape

## 目标调用示例

```python
from ear_eeg_sound_lab.src.integrations.npz_loader import load_npz_session
from ear_eeg_sound_lab.src.realtime_engine.pipeline import process_eeg_array
from ear_eeg_sound_lab.src.storage.session_summary import summarize_engine_outputs

session = load_npz_session("recordings/20260606_113353.npz")
outputs = process_eeg_array(
    session.eeg,
    sample_rate=session.eeg_sample_rate,
    unit="counts",
)
summary = summarize_engine_outputs(outputs)
print(summary)
```
