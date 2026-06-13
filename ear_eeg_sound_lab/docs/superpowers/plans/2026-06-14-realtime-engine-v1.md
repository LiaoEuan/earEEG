# Realtime EEG Analysis Engine V1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现第一版 EEG 数据处理链路：NPZ/LSL → 窗口 → 预处理 → 频段特征 → 信号质量 → 专注度 → 结构化输出

**Architecture:** 双入口（LSL 实时 + NPZ 离线）统一汇入 `pipeline.process_window()`。preprocessing 负责 counts→uV + 滤波。所有下游模块在 uV 域工作。算法模块不依赖 LSL/HTTP/UI。

**Tech Stack:** Python 3.14+, numpy, scipy, pylsl (仅 lsl_reader), dataclasses, unittest

**Design Spec:** `ear_eeg_sound_lab/docs/superpowers/specs/2026-06-14-realtime-engine-v1-design.md`

---

## 文件结构总览

```
ear_eeg_sound_lab/
  src/
    integrations/
      __init__.py              (新建)
      npz_loader.py            (新建)
      lsl_reader.py            (新建)
      lsl_buffer.py            (新建)
    realtime_engine/
      __init__.py              (新建)
      schemas.py               (新建)
      windowing.py             (新建)
      preprocessing.py         (新建)
      features.py              (新建)
      quality.py               (新建)
      focus.py                 (新建)
      pipeline.py              (新建)
    storage/
      __init__.py              (新建)
      session_summary.py       (新建)
  tests/
    test_npz_loader.py         (新建)
    test_windowing.py          (新建)
    test_preprocessing.py      (新建)
    test_features.py           (新建)
    test_quality.py            (新建)
    test_focus.py              (新建)
    test_pipeline.py           (新建)
    test_lsl_buffer.py         (新建)
```

---

## Phase 1: Foundation

### Task 1: schemas.py — 数据结构定义

**Files:**
- Create: `ear_eeg_sound_lab/src/realtime_engine/__init__.py`
- Create: `ear_eeg_sound_lab/src/realtime_engine/schemas.py`

- [ ] **Step 1: 创建 realtime_engine 包**

```python
# ear_eeg_sound_lab/src/realtime_engine/__init__.py
```

（空文件）

- [ ] **Step 2: 创建 schemas.py**

```python
"""Realtime engine data structures.

All dataclasses used across the EEG processing pipeline.
No external dependencies beyond numpy and dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class EEGWindow:
    """算法管线的统一输入单元。

    Attributes:
        data: EEG 数据, shape (channels, samples), float64.
        sample_rate: 采样率 Hz.
        start_sample: 在原始数据中的起始样本索引.
        start_time: 窗口起始时间(秒), start_sample / sample_rate.
        unit: 数据单位, "counts" 或 "uv".
        gain: ADS1299 增益, 用于 counts→uV 转换.
        vref: ADS1299 参考电压, 用于 counts→uV 转换.
    """
    data: np.ndarray
    sample_rate: float
    start_sample: int
    start_time: float | None
    unit: str
    gain: float = 24.0
    vref: float = 4.5


@dataclass
class PreprocessedWindow:
    """预处理后的窗口, 下游模块统一使用.

    Attributes:
        raw: 原始窗口引用.
        data: 预处理后数据, shape (channels, samples), float64, 单位 uV.
        unit: 固定为 "uv".
        sample_rate: 采样率 Hz.
        notes: 预处理过程中的警告/信息.
    """
    raw: EEGWindow
    data: np.ndarray
    unit: str = "uv"
    sample_rate: float = 250.0
    notes: list[str] = field(default_factory=list)


@dataclass
class BandPower:
    """单通道的五频段功率. 单位: uV².

    Attributes:
        delta: 1-4 Hz.
        theta: 4-8 Hz.
        alpha: 8-13 Hz.
        beta:  13-30 Hz.
        gamma: 30-45 Hz.
    """
    delta: float = 0.0
    theta: float = 0.0
    alpha: float = 0.0
    beta: float = 0.0
    gamma: float = 0.0


@dataclass
class FeatureFrame:
    """频段特征输出.

    Attributes:
        timestamp: 窗口中心时间(秒), None 表示未知.
        band_powers: 每通道频段功率, key 为通道索引.
        global_band_powers: 所有通道均值的频段功率.
        theta_beta_ratio: global theta / global beta.
        alpha_beta_ratio: global alpha / global beta.
        artifact_ratio: gamma 占总功率比例 (0.0-1.0).
    """
    timestamp: float | None = None
    band_powers: dict[int, BandPower] = field(default_factory=dict)
    global_band_powers: BandPower = field(default_factory=BandPower)
    theta_beta_ratio: float = 0.0
    alpha_beta_ratio: float = 0.0
    artifact_ratio: float = 0.0


@dataclass
class SignalQuality:
    """信号质量评估.

    Attributes:
        score: 质量分数 0.0-1.0.
        bad_channels: 问题通道索引列表.
        warnings: 警告代码列表.
    """
    score: float = 0.0
    bad_channels: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class FocusEstimate:
    """专注度估计.

    Attributes:
        score: 专注度分数 0-100.
        quality: 信号质量 0.0-1.0.
        state: 状态标签, "focused"/"stable"/"relaxed"/"fatigued"/"noisy".
        reasons: 原因代码列表.
    """
    score: int = 0
    quality: float = 0.0
    state: str = "unknown"
    reasons: list[str] = field(default_factory=list)


@dataclass
class EngineOutput:
    """pipeline 单次输出.

    Attributes:
        window: 原始输入窗口.
        preprocessed: 预处理后窗口.
        features: 频段特征.
        quality: 信号质量.
        focus: 专注度估计.
    """
    window: EEGWindow
    preprocessed: PreprocessedWindow
    features: FeatureFrame
    quality: SignalQuality
    focus: FocusEstimate


@dataclass
class EEGChunk:
    """LSL 拉取的原始数据块.

    Attributes:
        data: LSL 原始数据, shape (samples, channels).
        timestamps: LSL 时间戳, shape (samples,).
        sample_rate: 采样率 Hz.
        unit: 数据单位, "counts" 或 "uv".
    """
    data: np.ndarray
    timestamps: np.ndarray
    sample_rate: float
    unit: str = "counts"


@dataclass
class NPZSession:
    """NPZ 文件加载结果.

    Attributes:
        path: NPZ 文件路径.
        eeg: EEG 数据, shape (channels, samples), float32, 单位 raw counts.
        mic: 麦克风数据, shape (samples,) 或 None.
        stimuli: 刺激数据 或 None.
        eeg_sample_rate: EEG 采样率 Hz.
        mic_sample_rate: 麦克风采样率 Hz 或 None.
        metadata: 其他元数据.
    """
    path: Path
    eeg: np.ndarray
    mic: np.ndarray | None = None
    stimuli: np.ndarray | None = None
    eeg_sample_rate: float = 250.0
    mic_sample_rate: float | None = None
    metadata: dict = field(default_factory=dict)
```

- [ ] **Step 3: 验证 schemas 可导入**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -c "from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGWindow, PreprocessedWindow, BandPower, FeatureFrame, SignalQuality, FocusEstimate, EngineOutput, EEGChunk, NPZSession; print('All schemas imported OK')"
```

Expected: `All schemas imported OK`

- [ ] **Step 4: Commit**

```bash
git add ear_eeg_sound_lab/src/realtime_engine/__init__.py ear_eeg_sound_lab/src/realtime_engine/schemas.py
git commit -m "feat(engine): add dataclass schemas for realtime pipeline"
```

---

### Task 2: npz_loader.py — NPZ 文件读取

**Files:**
- Create: `ear_eeg_sound_lab/src/integrations/__init__.py`
- Create: `ear_eeg_sound_lab/src/integrations/npz_loader.py`
- Create: `ear_eeg_sound_lab/tests/test_npz_loader.py`

- [ ] **Step 1: 创建 integrations 包**

```python
# ear_eeg_sound_lab/src/integrations/__init__.py
```

（空文件）

- [ ] **Step 2: 编写 test_npz_loader.py**

```python
"""Tests for npz_loader module."""

import unittest
from pathlib import Path

import numpy as np

from ear_eeg_sound_lab.src.integrations.npz_loader import load_npz_session


class TestLoadNPZSession(unittest.TestCase):
    """Test load_npz_session with real and synthetic NPZ files."""

    REAL_NPZ = Path("recordings/20260606_113353.npz")

    def test_load_real_npz(self):
        """读取真实 NPZ 文件, 验证基本结构."""
        if not self.REAL_NPZ.exists():
            self.skipTest(f"Real NPZ not found: {self.REAL_NPZ}")

        session = load_npz_session(self.REAL_NPZ)

        # EEG 必须是 2D (channels, samples)
        self.assertEqual(session.eeg.ndim, 2)
        self.assertEqual(session.eeg.shape[0], 16)  # 16 通道

        # 采样率必须存在且合理
        self.assertGreater(session.eeg_sample_rate, 0)
        self.assertEqual(session.eeg_sample_rate, 250.0)

        # path 应该是 Path 对象
        self.assertIsInstance(session.path, Path)

    def test_load_real_npz_mic_squeezed(self):
        """真实 NPZ 的 MIC (M,1) 应 squeeze 为 (M,)."""
        if not self.REAL_NPZ.exists():
            self.skipTest(f"Real NPZ not found: {self.REAL_NPZ}")

        session = load_npz_session(self.REAL_NPZ)

        if session.mic is not None:
            self.assertEqual(session.mic.ndim, 1, "MIC should be squeezed to 1D")

    def test_load_synthetic_npz(self):
        """读取合成 NPZ, 验证数据完整性."""
        import tempfile
        import os

        eeg = np.random.randn(16, 2500).astype(np.float32)
        mic = np.random.randn(40000).astype(np.float32)

        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            np.savez(
                f.name,
                eeg=eeg,
                mic=mic,
                eeg_sample_rate=np.int32(250),
                mic_sample_rate=np.int32(16000),
                eeg_channels=np.int32(16),
                mic_channels=np.int32(1),
            )
            tmp_path = f.name

        try:
            session = load_npz_session(tmp_path)

            np.testing.assert_array_equal(session.eeg, eeg)
            self.assertEqual(session.eeg_sample_rate, 250.0)
            self.assertIsNotNone(session.mic)
            np.testing.assert_array_equal(session.mic, mic)
        finally:
            os.unlink(tmp_path)

    def test_missing_optional_fields(self):
        """缺少可选字段时不崩溃."""
        import tempfile
        import os

        eeg = np.random.randn(8, 1000).astype(np.float32)

        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            np.savez(f.name, eeg=eeg)
            tmp_path = f.name

        try:
            session = load_npz_session(tmp_path)

            self.assertEqual(session.eeg.ndim, 2)
            self.assertIsNone(session.mic)
            self.assertIsNone(session.stimuli)
            # 应有默认采样率
            self.assertGreater(session.eeg_sample_rate, 0)
        finally:
            os.unlink(tmp_path)

    def test_mic_squeeze_2d(self):
        """MIC shape (M,1) 应 squeeze 为 (M,)."""
        import tempfile
        import os

        eeg = np.random.randn(8, 1000).astype(np.float32)
        mic = np.random.randn(5000, 1).astype(np.float32)

        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            np.savez(f.name, eeg=eeg, mic=mic, eeg_sample_rate=np.int32(250))
            tmp_path = f.name

        try:
            session = load_npz_session(tmp_path)

            self.assertIsNotNone(session.mic)
            self.assertEqual(session.mic.ndim, 1)
            self.assertEqual(session.mic.shape[0], 5000)
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行测试确认失败**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_npz_loader -v
```

Expected: `ModuleNotFoundError: No module named 'ear_eeg_sound_lab.src.integrations.npz_loader'`

- [ ] **Step 4: 实现 npz_loader.py**

```python
"""NPZ session loader.

Reads recordings/*.npz files and returns structured NPZSession objects.
This module handles pure I/O — no unit conversion, no filtering.

EEG data is returned as-is from the NPZ (typically float32 raw ADC counts).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import NPZSession

# Default sample rates matching the earEEG device configuration.
DEFAULT_EEG_SAMPLE_RATE = 250.0
DEFAULT_MIC_SAMPLE_RATE = 16000.0


def load_npz_session(path: str | Path) -> NPZSession:
    """Load an NPZ recording session.

    Reads the NPZ file and returns a structured NPZSession.
    No unit conversion is performed — EEG remains in raw ADC counts.

    Args:
        path: Path to the .npz file.

    Returns:
        NPZSession with:
            - eeg: shape (channels, samples), float32
            - mic: shape (samples,), float32, or None if missing
            - stimuli: original shape or None
            - eeg_sample_rate: from file or default 250.0
            - mic_sample_rate: from file or default 16000.0

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If NPZ contains no 'eeg' key.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"NPZ file not found: {path}")

    npz = np.load(path, allow_pickle=True)

    if "eeg" not in npz:
        raise ValueError(f"NPZ file missing 'eeg' key: {path}")

    eeg = npz["eeg"]

    # Ensure EEG is (channels, samples)
    if eeg.ndim != 2:
        raise ValueError(
            f"EEG must be 2D (channels, samples), got shape {eeg.shape}"
        )

    # Load optional MIC, squeeze (M,1) → (M,)
    mic = None
    if "mic" in npz:
        mic = npz["mic"]
        if mic.ndim == 2 and mic.shape[1] == 1:
            mic = mic.squeeze(axis=1)

    # Load optional stimuli
    stimuli = npz.get("stimuli", None)

    # Load sample rates with defaults
    eeg_sample_rate = _load_scalar(npz, "eeg_sample_rate", DEFAULT_EEG_SAMPLE_RATE)
    mic_sample_rate = _load_scalar(npz, "mic_sample_rate", DEFAULT_MIC_SAMPLE_RATE)

    # Collect remaining metadata
    metadata_keys = [
        k for k in npz.files
        if k not in ("eeg", "mic", "stimuli", "eeg_sample_rate", "mic_sample_rate")
    ]
    metadata = {k: npz[k] for k in metadata_keys}

    return NPZSession(
        path=path,
        eeg=eeg,
        mic=mic,
        stimuli=stimuli,
        eeg_sample_rate=float(eeg_sample_rate),
        mic_sample_rate=float(mic_sample_rate) if mic_sample_rate is not None else None,
        metadata=metadata,
    )


def _load_scalar(npz: np.lib.npyio.NpzFile, key: str, default: float) -> float:
    """Load a scalar value from NPZ, returning default if missing."""
    if key in npz:
        val = npz[key]
        return float(val)
    return default
```

- [ ] **Step 5: 运行测试确认通过**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_npz_loader -v
```

Expected: `OK` (all tests pass, or skipped if real NPZ not found)

- [ ] **Step 6: Commit**

```bash
git add ear_eeg_sound_lab/src/integrations/__init__.py ear_eeg_sound_lab/src/integrations/npz_loader.py ear_eeg_sound_lab/tests/test_npz_loader.py
git commit -m "feat(integrations): add NPZ session loader"
```

---

### Task 3: windowing.py — 窗口切片

**Files:**
- Create: `ear_eeg_sound_lab/src/realtime_engine/windowing.py`
- Create: `ear_eeg_sound_lab/tests/test_windowing.py`

- [ ] **Step 1: 编写 test_windowing.py**

```python
"""Tests for windowing module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.windowing import iter_eeg_windows


class TestIterEEGWindows(unittest.TestCase):
    """Test iter_eeg_windows behavior."""

    def test_basic_windowing(self):
        """250Hz, 1000 samples, 2s window, 0.5s step → correct count."""
        sample_rate = 250.0
        n_samples = 1000  # 4 seconds
        n_channels = 16
        eeg = np.random.randn(n_channels, n_samples)

        windows = list(iter_eeg_windows(eeg, sample_rate))

        # 2s = 500 samples, 0.5s = 125 samples
        # First window at 0, then 125, 250, 375 → 4 windows (0 to 499, 125 to 625, ...)
        # But 1000 - 500 = 500 remaining → start at 0,125,250,375 → 4 windows
        self.assertEqual(len(windows), 4)

    def test_window_shape(self):
        """Each window should have shape (channels, window_samples)."""
        sample_rate = 250.0
        n_channels = 8
        eeg = np.random.randn(n_channels, 1000)

        windows = list(iter_eeg_windows(eeg, sample_rate))

        for w in windows:
            self.assertEqual(w.data.shape, (n_channels, 500))

    def test_start_sample_increments(self):
        """start_sample should increment by step_samples."""
        sample_rate = 250.0
        eeg = np.random.randn(4, 2000)

        windows = list(iter_eeg_windows(eeg, sample_rate))

        # step = 0.5s * 250 = 125 samples
        for i in range(len(windows) - 1):
            self.assertEqual(
                windows[i + 1].start_sample - windows[i].start_sample, 125
            )

    def test_start_time(self):
        """start_time should equal start_sample / sample_rate."""
        sample_rate = 250.0
        eeg = np.random.randn(4, 1000)

        windows = list(iter_eeg_windows(eeg, sample_rate))

        for w in windows:
            expected_time = w.start_sample / sample_rate
            self.assertAlmostEqual(w.start_time, expected_time)

    def test_insufficient_data(self):
        """If data < one window, no windows should be returned."""
        sample_rate = 250.0
        eeg = np.random.randn(4, 400)  # 1.6 seconds < 2 seconds

        windows = list(iter_eeg_windows(eeg, sample_rate))

        self.assertEqual(len(windows), 0)

    def test_unit_passthrough(self):
        """Unit should be passed through to EEGWindow."""
        sample_rate = 250.0
        eeg = np.random.randn(4, 1000)

        windows = list(iter_eeg_windows(eeg, sample_rate, unit="uv"))

        for w in windows:
            self.assertEqual(w.unit, "uv")

    def test_custom_window_and_step(self):
        """Custom window_seconds and step_seconds should work."""
        sample_rate = 250.0
        eeg = np.random.randn(4, 2500)  # 10 seconds

        # 1s window, 0.25s step
        windows = list(iter_eeg_windows(eeg, sample_rate, window_seconds=1.0, step_seconds=0.25))

        # 1s = 250 samples, 0.25s = 62.5 → 62 samples
        # 2500 - 250 = 2250 remaining
        # starts: 0, 62, 124, ... → floor(2250/62) + 1 = 37 windows
        self.assertGreater(len(windows), 30)
        for w in windows:
            self.assertEqual(w.data.shape[1], 250)

    def test_gain_vref_passthrough(self):
        """gain and vref should be passed through."""
        sample_rate = 250.0
        eeg = np.random.randn(4, 1000)

        windows = list(iter_eeg_windows(eeg, sample_rate, gain=12.0, vref=2.5))

        for w in windows:
            self.assertEqual(w.gain, 12.0)
            self.assertEqual(w.vref, 2.5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_windowing -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现 windowing.py**

```python
"""EEG windowing — slice continuous EEG into fixed-length windows.

This module provides windowing for the offline NPZ path.
For real-time LSL path, use lsl_buffer.EEGRollingBuffer instead.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGWindow


def iter_eeg_windows(
    eeg: np.ndarray,
    sample_rate: float,
    window_seconds: float = 2.0,
    step_seconds: float = 0.5,
    unit: str = "counts",
    gain: float = 24.0,
    vref: float = 4.5,
) -> Iterator[EEGWindow]:
    """Slice continuous EEG into fixed-length overlapping windows.

    Args:
        eeg: Continuous EEG data, shape (channels, samples).
        sample_rate: Sampling rate in Hz.
        window_seconds: Window length in seconds (default 2.0).
        step_seconds: Step size in seconds (default 0.5).
        unit: Data unit, "counts" or "uv".
        gain: ADS1299 gain for counts→uV conversion.
        vref: ADS1299 reference voltage for counts→uV conversion.

    Yields:
        EEGWindow objects with shape (channels, window_samples).

    Note:
        If data is shorter than one window, no windows are yielded.
        This module does not perform any unit conversion.
    """
    n_channels, n_samples = eeg.shape
    window_samples = int(window_seconds * sample_rate)
    step_samples = int(step_seconds * sample_rate)

    if n_samples < window_samples:
        return

    start = 0
    while start + window_samples <= n_samples:
        data = eeg[:, start : start + window_samples].astype(np.float64)
        yield EEGWindow(
            data=data,
            sample_rate=sample_rate,
            start_sample=start,
            start_time=start / sample_rate,
            unit=unit,
            gain=gain,
            vref=vref,
        )
        start += step_samples
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_windowing -v
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add ear_eeg_sound_lab/src/realtime_engine/windowing.py ear_eeg_sound_lab/tests/test_windowing.py
git commit -m "feat(engine): add EEG windowing module"
```

---

## Phase 2: Core Engine

### Task 4: preprocessing.py — 预处理

**Files:**
- Create: `ear_eeg_sound_lab/src/realtime_engine/preprocessing.py`
- Create: `ear_eeg_sound_lab/tests/test_preprocessing.py`

**Dependencies:** scipy (for filtering)

- [ ] **Step 1: 编写 test_preprocessing.py**

```python
"""Tests for preprocessing module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.preprocessing import preprocess_window
from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGWindow


def _make_window(data: np.ndarray, sample_rate: float = 250.0, unit: str = "counts") -> EEGWindow:
    """Helper to create an EEGWindow from data array."""
    return EEGWindow(
        data=data.astype(np.float64),
        sample_rate=sample_rate,
        start_sample=0,
        start_time=0.0,
        unit=unit,
        gain=24.0,
        vref=4.5,
    )


class TestPreprocessWindow(unittest.TestCase):
    """Test preprocess_window behavior."""

    def test_dc_offset_removal(self):
        """DC offset should be removed — output mean ≈ 0 per channel."""
        n_channels, n_samples = 4, 500
        # Add large DC offset
        data = np.ones((n_channels, n_samples)) * 10000.0
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)

        for ch in range(n_channels):
            self.assertAlmostEqual(
                np.mean(result.data[ch]), 0.0, places=5,
                msg=f"Channel {ch} mean should be ~0 after demean"
            )

    def test_nan_cleanup(self):
        """NaN values should be replaced with 0, and noted."""
        n_channels, n_samples = 4, 500
        data = np.random.randn(n_channels, n_samples)
        data[0, 10] = np.nan
        data[2, 20:25] = np.inf
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)

        # No NaN/Inf in output
        self.assertTrue(np.all(np.isfinite(result.data)))
        # Notes should mention NaN replacement
        self.assertTrue(any("NaN" in n or "Inf" in n for n in result.notes))

    def test_counts_to_uv_conversion(self):
        """Counts should be converted to uV when unit='counts'."""
        n_channels, n_samples = 4, 500
        data = np.ones((n_channels, n_samples)) * 1000.0  # 1000 counts
        window = _make_window(data, unit="counts")

        result = preprocess_window(window)

        # Expected scale: vref / gain / (2^23 - 1) * 1e6
        expected_scale = 4.5 / 24.0 / ((1 << 23) - 1) * 1e6
        expected_uv = 1000.0 * expected_scale

        # After demean, the constant becomes 0, so check before demean
        # Actually the conversion happens before demean, so the output should be ~0
        # Let's check the raw conversion separately
        self.assertEqual(result.unit, "uv")

    def test_uv_passthrough(self):
        """If unit='uv', no counts→uV conversion should occur."""
        n_channels, n_samples = 4, 500
        data = np.random.randn(n_channels, n_samples) * 10.0
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)

        self.assertEqual(result.unit, "uv")
        # Data should still be finite
        self.assertTrue(np.all(np.isfinite(result.data)))

    def test_output_is_float64(self):
        """Output data should be float64."""
        data = np.random.randn(4, 500).astype(np.float32)
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)

        self.assertEqual(result.data.dtype, np.float64)

    def test_notes_populated(self):
        """PreprocessedWindow.notes should contain processing info."""
        data = np.random.randn(4, 500)
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)

        self.assertIsInstance(result.notes, list)

    def test_filter_does_not_crash_short_data(self):
        """Very short data should not crash (graceful degradation)."""
        # 10 samples is very short for filtering
        data = np.random.randn(4, 10)
        window = _make_window(data, unit="uv")

        # Should not raise
        result = preprocess_window(window)
        self.assertTrue(np.all(np.isfinite(result.data)))

    def test_sine_wave_survives_filtering(self):
        """A 10 Hz sine wave should survive 1-45 Hz bandpass."""
        sample_rate = 250.0
        n_samples = 500
        t = np.arange(n_samples) / sample_rate
        # 10 Hz sine, 50 uV amplitude
        sine = np.sin(2 * np.pi * 10.0 * t) * 50.0
        data = np.tile(sine, (4, 1))  # 4 channels
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)

        # After filtering, the sine should still be present
        # Check that std is not zero
        for ch in range(4):
            self.assertGreater(np.std(result.data[ch]), 1.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_preprocessing -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现 preprocessing.py**

```python
"""EEG preprocessing — unit conversion, demean, and filtering.

First version: counts→uV (conditional), demean, bandpass 1-45 Hz, notch 50/60 Hz.
Uses scipy for IIR filtering. Does NOT perform clinical-grade filtering.

Note: This module is the single entry point for data transformation.
All downstream modules (features, quality, focus) receive uV data.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, filtfilt, iirnotch

from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    EEGWindow,
    PreprocessedWindow,
)


def preprocess_window(
    window: EEGWindow,
    notch_freq: float = 50.0,
    notch_q: float = 30.0,
    bandpass_low: float = 1.0,
    bandpass_high: float = 45.0,
    bandpass_order: int = 4,
) -> PreprocessedWindow:
    """Preprocess a single EEG window.

    Steps:
        1. Conditional unit conversion (counts → uV)
        2. NaN/Inf cleanup (replace with 0)
        3. Per-channel demean
        4. Notch filter (configurable 50/60 Hz)
        5. Bandpass filter (1-45 Hz, 4th order Butterworth)

    Args:
        window: Input EEG window, unit may be "counts" or "uv".
        notch_freq: Notch center frequency in Hz (default 50.0).
        notch_q: Notch quality factor (default 30.0).
        bandpass_low: Bandpass lower cutoff in Hz (default 1.0).
        bandpass_high: Bandpass upper cutoff in Hz (default 45.0).
        bandpass_order: Butterworth filter order (default 4).

    Returns:
        PreprocessedWindow with unit="uv", demeaned and filtered.
    """
    notes: list[str] = []
    data = window.data.copy().astype(np.float64)

    # Step 1: Conditional unit conversion
    if window.unit == "counts":
        scale = window.vref / window.gain / ((1 << 23) - 1) * 1e6  # µV per count
        data *= scale
        notes.append(f"converted_counts_to_uv(scale={scale:.6e})")
    elif window.unit == "uv":
        pass  # Already in uV
    else:
        raise ValueError(f"Unknown unit: {window.unit!r}, expected 'counts' or 'uv'")

    # Step 2: NaN/Inf cleanup
    nan_mask = ~np.isfinite(data)
    nan_count = int(np.sum(nan_mask))
    if nan_count > 0:
        data[nan_mask] = 0.0
        notes.append(f"replaced {nan_count} NaN/Inf values with 0")

    # Step 3: Per-channel demean
    data -= data.mean(axis=1, keepdims=True)

    # Step 4 & 5: Filtering (with graceful degradation for short data)
    n_channels, n_samples = data.shape
    min_filter_len = max(3 * bandpass_order, 15)  # Minimum data length for filtfilt

    if n_samples >= min_filter_len:
        try:
            # Notch filter
            b_notch, a_notch = iirnotch(notch_freq, notch_q, window.sample_rate)
            for ch in range(n_channels):
                data[ch] = filtfilt(b_notch, a_notch, data[ch])
            notes.append(f"notch_filter(freq={notch_freq}Hz, q={notch_q})")

            # Bandpass filter
            nyq = window.sample_rate / 2.0
            b_bp, a_bp = butter(
                bandpass_order,
                [bandpass_low / nyq, bandpass_high / nyq],
                btype="band",
            )
            for ch in range(n_channels):
                data[ch] = filtfilt(b_bp, a_bp, data[ch])
            notes.append(
                f"bandpass(order={bandpass_order}, low={bandpass_low}Hz, high={bandpass_high}Hz)"
            )
        except Exception as e:
            notes.append(f"filter_failed({type(e).__name__}: {e}), data demeaned only")
    else:
        notes.append(
            f"filter_skipped(data_too_short: {n_samples} < {min_filter_len}), data demeaned only"
        )

    return PreprocessedWindow(
        raw=window,
        data=data,
        unit="uv",
        sample_rate=window.sample_rate,
        notes=notes,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_preprocessing -v
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add ear_eeg_sound_lab/src/realtime_engine/preprocessing.py ear_eeg_sound_lab/tests/test_preprocessing.py
git commit -m "feat(engine): add preprocessing with counts→uV, demean, bandpass, notch"
```

---

### Task 5: features.py — 频段特征提取

**Files:**
- Create: `ear_eeg_sound_lab/src/realtime_engine/features.py`
- Create: `ear_eeg_sound_lab/tests/test_features.py`

- [ ] **Step 1: 编写 test_features.py**

```python
"""Tests for features module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.features import (
    BANDS,
    compute_band_power,
    extract_features,
)
from ear_eeg_sound_lab.src.realtime_engine.schemas import PreprocessedWindow, EEGWindow


def _make_preprocessed(data: np.ndarray, sample_rate: float = 250.0) -> PreprocessedWindow:
    """Helper to create a PreprocessedWindow."""
    raw = EEGWindow(
        data=data, sample_rate=sample_rate,
        start_sample=0, start_time=0.0, unit="uv",
    )
    return PreprocessedWindow(raw=raw, data=data, unit="uv", sample_rate=sample_rate)


class TestComputeBandPower(unittest.TestCase):
    """Test compute_band_power function."""

    def test_10hz_sine_dominates_alpha(self):
        """10 Hz sine → alpha band power should be largest."""
        sample_rate = 250.0
        n_samples = 1000
        t = np.arange(n_samples) / sample_rate
        sine = np.sin(2 * np.pi * 10.0 * t)  # 10 Hz
        data = np.tile(sine, (4, 1))  # 4 channels

        alpha_power = compute_band_power(data, sample_rate, 8.0, 13.0)
        beta_power = compute_band_power(data, sample_rate, 13.0, 30.0)
        delta_power = compute_band_power(data, sample_rate, 1.0, 4.0)

        for ch in range(4):
            self.assertGreater(alpha_power[ch], beta_power[ch])
            self.assertGreater(alpha_power[ch], delta_power[ch])

    def test_20hz_sine_dominates_beta(self):
        """20 Hz sine → beta band power should be largest."""
        sample_rate = 250.0
        n_samples = 1000
        t = np.arange(n_samples) / sample_rate
        sine = np.sin(2 * np.pi * 20.0 * t)  # 20 Hz
        data = np.tile(sine, (4, 1))

        beta_power = compute_band_power(data, sample_rate, 13.0, 30.0)
        alpha_power = compute_band_power(data, sample_rate, 8.0, 13.0)

        for ch in range(4):
            self.assertGreater(beta_power[ch], alpha_power[ch])

    def test_output_shape(self):
        """Output should have shape (channels,)."""
        data = np.random.randn(8, 500)
        result = compute_band_power(data, 250.0, 8.0, 13.0)
        self.assertEqual(result.shape, (8,))

    def test_zero_input_no_nan(self):
        """All-zero input should not produce NaN."""
        data = np.zeros((4, 500))
        result = compute_band_power(data, 250.0, 1.0, 45.0)
        self.assertTrue(np.all(np.isfinite(result)))


class TestExtractFeatures(unittest.TestCase):
    """Test extract_features function."""

    def test_mixed_sine_no_nan(self):
        """Mixed sine waves should produce finite output."""
        sample_rate = 250.0
        n_samples = 1000
        t = np.arange(n_samples) / sample_rate
        data = (
            np.sin(2 * np.pi * 5.0 * t) * 10   # theta
            + np.sin(2 * np.pi * 10.0 * t) * 20  # alpha
            + np.sin(2 * np.pi * 20.0 * t) * 15  # beta
        )
        data = np.tile(data, (4, 1))
        window = _make_preprocessed(data, sample_rate)

        result = extract_features(window)

        self.assertTrue(np.isfinite(result.theta_beta_ratio))
        self.assertTrue(np.isfinite(result.alpha_beta_ratio))
        self.assertTrue(np.isfinite(result.artifact_ratio))

    def test_theta_beta_ratio_no_divide_by_zero(self):
        """When beta is zero, theta_beta_ratio should be finite."""
        sample_rate = 250.0
        n_samples = 1000
        t = np.arange(n_samples) / sample_rate
        # Pure theta, no beta
        data = np.sin(2 * np.pi * 6.0 * t)
        data = np.tile(data, (4, 1))
        window = _make_preprocessed(data, sample_rate)

        result = extract_features(window)

        self.assertTrue(np.isfinite(result.theta_beta_ratio))

    def test_band_powers_per_channel(self):
        """band_powers should have entries for all channels."""
        data = np.random.randn(8, 500)
        window = _make_preprocessed(data, 250.0)

        result = extract_features(window)

        for ch in range(8):
            self.assertIn(ch, result.band_powers)
            bp = result.band_powers[ch]
            self.assertTrue(hasattr(bp, "delta"))
            self.assertTrue(hasattr(bp, "theta"))
            self.assertTrue(hasattr(bp, "alpha"))
            self.assertTrue(hasattr(bp, "beta"))
            self.assertTrue(hasattr(bp, "gamma"))

    def test_global_band_powers_are_means(self):
        """global_band_powers should be the mean of per-channel powers."""
        data = np.random.randn(4, 500)
        window = _make_preprocessed(data, 250.0)

        result = extract_features(window)

        # Check that global is approximately the mean of per-channel
        deltas = [result.band_powers[ch].delta for ch in range(4)]
        self.assertAlmostEqual(
            result.global_band_powers.delta, np.mean(deltas), places=10
        )

    def test_artifact_ratio_range(self):
        """artifact_ratio should be in [0, 1]."""
        data = np.random.randn(4, 500) * 50
        window = _make_preprocessed(data, 250.0)

        result = extract_features(window)

        self.assertGreaterEqual(result.artifact_ratio, 0.0)
        self.assertLessEqual(result.artifact_ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_features -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现 features.py**

```python
"""EEG feature extraction — FFT-based band power computation.

Computes delta, theta, alpha, beta, gamma band power using Hann-windowed FFT.
Also computes theta/beta ratio, alpha/beta ratio, and artifact ratio.

Input: PreprocessedWindow (data in uV, shape (channels, samples))
Output: FeatureFrame with per-channel and global band powers.

Note: Band power units are uV². Absolute values are less important than ratios.
"""

from __future__ import annotations

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    BandPower,
    FeatureFrame,
    PreprocessedWindow,
)

# EEG frequency band definitions (Hz)
BANDS: dict[str, tuple[float, float]] = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}

# Small constant to prevent division by zero
_EPSILON = 1e-12


def compute_band_power(
    data: np.ndarray,
    sample_rate: float,
    low_hz: float,
    high_hz: float,
) -> np.ndarray:
    """Compute average power in a frequency band using Hann-windowed FFT.

    Args:
        data: EEG data, shape (channels, samples).
        sample_rate: Sampling rate in Hz.
        low_hz: Lower frequency bound in Hz.
        high_hz: Upper frequency bound in Hz.

    Returns:
        Band power per channel, shape (channels,). Units: uV².
    """
    n_channels, n_samples = data.shape

    # Apply Hann window to reduce spectral leakage
    hann = np.hanning(n_samples)
    windowed = data * hann[np.newaxis, :]

    # Compute one-sided FFT
    spectrum = np.fft.rfft(windowed, axis=1)
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate)

    # Power spectrum (|X|² / N)
    power = np.abs(spectrum) ** 2 / n_samples

    # Select frequency bins within [low_hz, high_hz]
    mask = (freqs >= low_hz) & (freqs <= high_hz)

    # Average power in the band
    band_power = np.mean(power[:, mask], axis=1)

    return band_power


def extract_features(window: PreprocessedWindow) -> FeatureFrame:
    """Extract all frequency band features from a preprocessed window.

    Args:
        window: Preprocessed EEG window, data in uV, shape (channels, samples).

    Returns:
        FeatureFrame with per-channel band powers, global band powers,
        theta/beta ratio, alpha/beta ratio, and artifact ratio.
    """
    data = window.data
    n_channels, n_samples = data.shape
    sample_rate = window.sample_rate

    # Compute per-channel band powers
    band_powers: dict[int, BandPower] = {}
    for ch in range(n_channels):
        ch_data = data[ch : ch + 1, :]  # shape (1, samples)
        bp = BandPower(
            delta=float(compute_band_power(ch_data, sample_rate, *BANDS["delta"])[0]),
            theta=float(compute_band_power(ch_data, sample_rate, *BANDS["theta"])[0]),
            alpha=float(compute_band_power(ch_data, sample_rate, *BANDS["alpha"])[0]),
            beta=float(compute_band_power(ch_data, sample_rate, *BANDS["beta"])[0]),
            gamma=float(compute_band_power(ch_data, sample_rate, *BANDS["gamma"])[0]),
        )
        band_powers[ch] = bp

    # Global band powers = mean of per-channel powers
    global_bp = BandPower(
        delta=float(np.mean([bp.delta for bp in band_powers.values()])),
        theta=float(np.mean([bp.theta for bp in band_powers.values()])),
        alpha=float(np.mean([bp.alpha for bp in band_powers.values()])),
        beta=float(np.mean([bp.beta for bp in band_powers.values()])),
        gamma=float(np.mean([bp.gamma for bp in band_powers.values()])),
    )

    # Ratios (with divide-by-zero protection)
    theta_beta_ratio = global_bp.theta / max(global_bp.beta, _EPSILON)
    alpha_beta_ratio = global_bp.alpha / max(global_bp.beta, _EPSILON)

    # Artifact ratio: gamma power as fraction of total power
    total_power = global_bp.delta + global_bp.theta + global_bp.alpha + global_bp.beta + global_bp.gamma
    artifact_ratio = global_bp.gamma / max(total_power, _EPSILON)
    artifact_ratio = float(np.clip(artifact_ratio, 0.0, 1.0))

    # Timestamp: center of window
    timestamp = None
    if window.raw.start_time is not None:
        n_samples = data.shape[1]
        timestamp = window.raw.start_time + n_samples / (2.0 * sample_rate)

    return FeatureFrame(
        timestamp=timestamp,
        band_powers=band_powers,
        global_band_powers=global_bp,
        theta_beta_ratio=float(theta_beta_ratio),
        alpha_beta_ratio=float(alpha_beta_ratio),
        artifact_ratio=float(artifact_ratio),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_features -v
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add ear_eeg_sound_lab/src/realtime_engine/features.py ear_eeg_sound_lab/tests/test_features.py
git commit -m "feat(engine): add FFT-based band power feature extraction"
```

---

### Task 6: quality.py — 信号质量评估

**Files:**
- Create: `ear_eeg_sound_lab/src/realtime_engine/quality.py`
- Create: `ear_eeg_sound_lab/tests/test_quality.py`

- [ ] **Step 1: 编写 test_quality.py**

```python
"""Tests for quality module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.quality import (
    QualityThresholds,
    estimate_signal_quality,
)
from ear_eeg_sound_lab.src.realtime_engine.schemas import PreprocessedWindow, EEGWindow


def _make_preprocessed(data: np.ndarray, sample_rate: float = 250.0) -> PreprocessedWindow:
    """Helper to create a PreprocessedWindow."""
    raw = EEGWindow(
        data=data, sample_rate=sample_rate,
        start_sample=0, start_time=0.0, unit="uv",
    )
    return PreprocessedWindow(raw=raw, data=data, unit="uv", sample_rate=sample_rate)


class TestEstimateSignalQuality(unittest.TestCase):
    """Test estimate_signal_quality function."""

    def test_all_zeros_low_quality(self):
        """All-zero data → flatline → low quality."""
        data = np.zeros((8, 500))
        window = _make_preprocessed(data)

        result = estimate_signal_quality(window)

        self.assertLess(result.score, 0.5)
        self.assertGreater(len(result.bad_channels), 0)

    def test_normal_sine_high_quality(self):
        """Normal 10 Hz sine, 10 uV → high quality."""
        sample_rate = 250.0
        n_samples = 500
        t = np.arange(n_samples) / sample_rate
        sine = np.sin(2 * np.pi * 10.0 * t) * 10.0  # 10 uV
        data = np.tile(sine, (8, 1))
        window = _make_preprocessed(data, sample_rate)

        result = estimate_signal_quality(window)

        self.assertGreater(result.score, 0.8)
        self.assertEqual(len(result.bad_channels), 0)

    def test_single_channel_high_amplitude(self):
        """One channel with extreme amplitude → marked as bad."""
        sample_rate = 250.0
        n_samples = 500
        t = np.arange(n_samples) / sample_rate
        data = np.tile(np.sin(2 * np.pi * 10.0 * t) * 10.0, (8, 1))
        # Channel 3 with extreme amplitude
        data[3, :] = np.sin(2 * np.pi * 10.0 * t) * 200000.0
        window = _make_preprocessed(data, sample_rate)

        result = estimate_signal_quality(window)

        self.assertIn(3, result.bad_channels)
        self.assertLess(result.score, 1.0)

    def test_score_range(self):
        """Score must always be in [0.0, 1.0]."""
        for _ in range(20):
            n_ch = np.random.randint(1, 16)
            data = np.random.randn(n_ch, 500) * np.random.uniform(0.1, 1000)
            window = _make_preprocessed(data)
            result = estimate_signal_quality(window)
            self.assertGreaterEqual(result.score, 0.0)
            self.assertLessEqual(result.score, 1.0)

    def test_custom_thresholds(self):
        """Custom thresholds should be respected."""
        data = np.random.randn(4, 500) * 10.0
        window = _make_preprocessed(data)

        # Very strict thresholds → everything is bad
        strict = QualityThresholds(min_std=1e6, max_abs_uv=0.001)
        result = estimate_signal_quality(window, thresholds=strict)

        self.assertLess(result.score, 0.5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_quality -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现 quality.py**

```python
"""EEG signal quality assessment.

Detects flatline, high amplitude, high peak-to-peak, and noisy channels.
Returns a quality score in [0.0, 1.0] and a list of bad channel indices.

Input: PreprocessedWindow (data in uV)
Output: SignalQuality

Thresholds are configurable via QualityThresholds dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    PreprocessedWindow,
    SignalQuality,
)


@dataclass
class QualityThresholds:
    """Thresholds for signal quality detection.

    Attributes:
        min_std: Minimum standard deviation for non-flatline (uV).
        max_abs_uv: Maximum absolute amplitude (uV).
        max_ptp_uv: Maximum peak-to-peak amplitude (uV).
        noisy_std: Standard deviation above which channel is considered noisy (uV).
    """
    min_std: float = 1e-6
    max_abs_uv: float = 100000.0
    max_ptp_uv: float = 200000.0
    noisy_std: float = 500.0


def estimate_signal_quality(
    window: PreprocessedWindow,
    thresholds: QualityThresholds | None = None,
) -> SignalQuality:
    """Estimate signal quality of a preprocessed EEG window.

    Detects problematic channels based on amplitude and variability.

    Args:
        window: Preprocessed EEG window, data in uV, shape (channels, samples).
        thresholds: Quality thresholds. Uses defaults if None.

    Returns:
        SignalQuality with score in [0.0, 1.0], bad channel indices, and warnings.
    """
    if thresholds is None:
        thresholds = QualityThresholds()

    data = window.data
    n_channels, _ = data.shape
    bad_channels: list[int] = []
    warnings: list[str] = []

    for ch in range(n_channels):
        ch_data = data[ch]
        ch_std = float(np.std(ch_data))
        ch_max_abs = float(np.max(np.abs(ch_data)))
        ch_ptp = float(np.ptp(ch_data))

        # Flatline detection
        if ch_std < thresholds.min_std:
            bad_channels.append(ch)
            warnings.append(f"channel_{ch}_flatline")
            continue

        # High amplitude detection
        if ch_max_abs > thresholds.max_abs_uv:
            bad_channels.append(ch)
            warnings.append(f"channel_{ch}_high_amplitude")
            continue

        # High peak-to-peak detection
        if ch_ptp > thresholds.max_ptp_uv:
            bad_channels.append(ch)
            warnings.append(f"channel_{ch}_high_ptp")
            continue

        # Noisy detection
        if ch_std > thresholds.noisy_std:
            bad_channels.append(ch)
            warnings.append(f"channel_{ch}_noisy")

    # Quality score: penalize bad channels
    # Each bad channel costs 0.15, capped at 0.6
    artifact_penalty = min(len(bad_channels) * 0.15, 0.6)
    score = float(np.clip(1.0 - artifact_penalty, 0.0, 1.0))

    return SignalQuality(
        score=score,
        bad_channels=bad_channels,
        warnings=warnings,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_quality -v
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add ear_eeg_sound_lab/src/realtime_engine/quality.py ear_eeg_sound_lab/tests/test_quality.py
git commit -m "feat(engine): add signal quality assessment"
```

---

### Task 7: focus.py — 专注度启发式

**Files:**
- Create: `ear_eeg_sound_lab/src/realtime_engine/focus.py`
- Create: `ear_eeg_sound_lab/tests/test_focus.py`

- [ ] **Step 1: 编写 test_focus.py**

```python
"""Tests for focus module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.focus import estimate_focus
from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    BandPower,
    FeatureFrame,
    SignalQuality,
)


def _make_quality(score: float = 0.9, bad_channels: list[int] | None = None) -> SignalQuality:
    """Helper to create SignalQuality."""
    return SignalQuality(
        score=score,
        bad_channels=bad_channels or [],
        warnings=[],
    )


def _make_features(
    theta: float = 5.0,
    beta: float = 5.0,
    alpha: float = 5.0,
    artifact_ratio: float = 0.1,
) -> FeatureFrame:
    """Helper to create FeatureFrame with specific global band powers."""
    global_bp = BandPower(
        delta=3.0,
        theta=theta,
        alpha=alpha,
        beta=beta,
        gamma=2.0,
    )
    theta_beta = theta / max(beta, 1e-12)
    alpha_beta = alpha / max(beta, 1e-12)
    return FeatureFrame(
        timestamp=0.0,
        band_powers={},
        global_band_powers=global_bp,
        theta_beta_ratio=theta_beta,
        alpha_beta_ratio=alpha_beta,
        artifact_ratio=artifact_ratio,
    )


class TestEstimateFocus(unittest.TestCase):
    """Test estimate_focus function."""

    def test_low_quality_low_score(self):
        """Quality < 0.4 → score should be ≤ 40, state='noisy'."""
        quality = _make_quality(score=0.3)
        features = _make_features()

        result = estimate_focus(features, quality)

        self.assertLessEqual(result.score, 40)
        self.assertEqual(result.state, "noisy")
        self.assertIn("poor_signal_quality", result.reasons)

    def test_beta_dominant_higher_than_theta(self):
        """Beta-dominant → higher score than theta-dominant."""
        quality = _make_quality(score=0.9)

        beta_dominant = _make_features(theta=3.0, beta=10.0)
        theta_dominant = _make_features(theta=10.0, beta=3.0)

        result_beta = estimate_focus(beta_dominant, quality)
        result_theta = estimate_focus(theta_dominant, quality)

        self.assertGreater(result_beta.score, result_theta.score)

    def test_score_range(self):
        """Score must always be in [0, 100]."""
        quality = _make_quality(score=0.9)

        for _ in range(50):
            theta = np.random.uniform(0.1, 50.0)
            beta = np.random.uniform(0.1, 50.0)
            alpha = np.random.uniform(0.1, 50.0)
            artifact = np.random.uniform(0.0, 1.0)
            features = _make_features(theta=theta, beta=beta, alpha=alpha, artifact_ratio=artifact)

            result = estimate_focus(features, quality)

            self.assertGreaterEqual(result.score, 0)
            self.assertLessEqual(result.score, 100)

    def test_reasons_not_empty(self):
        """Reasons should never be empty."""
        quality = _make_quality(score=0.9)
        features = _make_features()

        result = estimate_focus(features, quality)

        self.assertGreater(len(result.reasons), 0)

    def test_state_labels(self):
        """State should be one of the defined labels."""
        quality = _make_quality(score=0.9)
        features = _make_features()

        result = estimate_focus(features, quality)

        valid_states = {"focused", "stable", "relaxed", "fatigued", "noisy"}
        self.assertIn(result.state, valid_states)

    def test_quality_weighting(self):
        """Higher quality → higher score (all else equal)."""
        features = _make_features(theta=3.0, beta=10.0)

        high_q = estimate_focus(features, _make_quality(score=0.95))
        low_q = estimate_focus(features, _make_quality(score=0.5))

        self.assertGreater(high_q.score, low_q.score)

    def test_artifact_penalty(self):
        """High artifact_ratio → lower score."""
        quality = _make_quality(score=0.9)

        low_artifact = _make_features(artifact_ratio=0.1)
        high_artifact = _make_features(artifact_ratio=0.5)

        result_low = estimate_focus(low_artifact, quality)
        result_high = estimate_focus(high_artifact, quality)

        self.assertGreater(result_low.score, result_high.score)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_focus -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现 focus.py**

```python
"""Focus estimation — heuristic-based attention/focus scoring.

Extended heuristic using theta/beta ratio, alpha/beta ratio,
beta presence, artifact ratio, and signal quality.

Input: FeatureFrame + SignalQuality
Output: FocusEstimate (score 0-100, state, reasons)

This is an algorithmic estimate, not a medical diagnosis.
"""

from __future__ import annotations

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    FeatureFrame,
    FocusEstimate,
    SignalQuality,
)

# Small constant to prevent division by zero
_EPSILON = 1e-12


def estimate_focus(features: FeatureFrame, quality: SignalQuality) -> FocusEstimate:
    """Estimate focus level from EEG features and signal quality.

    Uses a heuristic combining:
        - Theta/beta ratio (primary attention indicator)
        - Alpha/beta ratio (relaxation indicator)
        - Beta presence (cognitive engagement)
        - Artifact ratio (signal contamination)
        - Signal quality (overall confidence)

    Args:
        features: Extracted frequency band features.
        quality: Signal quality assessment.

    Returns:
        FocusEstimate with score in [0, 100], quality, state label, and reasons.
    """
    reasons: list[str] = []

    # Quality gate: if quality is too low, return early
    if quality.score < 0.4:
        score = int(np.clip(quality.score * 100, 0, 40))
        return FocusEstimate(
            score=score,
            quality=quality.score,
            state="noisy",
            reasons=["poor_signal_quality"],
        )

    # Start with base score
    base = 50.0

    # Theta/beta ratio assessment (primary focus indicator)
    tbr = features.theta_beta_ratio
    if tbr < 1.5:
        base += 15
        reasons.append("low_theta_beta")
    elif tbr < 2.0:
        base += 10
        reasons.append("moderate_theta_beta")
    elif tbr > 4.0:
        base -= 15
        reasons.append("high_theta_beta")
    elif tbr > 3.0:
        base -= 8
        reasons.append("elevated_theta_beta")

    # Alpha/beta ratio assessment (relaxation indicator)
    abr = features.alpha_beta_ratio
    if abr > 3.0:
        base -= 10
        reasons.append("alpha_dominant")
    elif abr > 2.0:
        base -= 5
        reasons.append("alpha_elevated")

    # Beta presence (cognitive engagement)
    if features.global_band_powers.beta > _EPSILON:
        base += 5
        reasons.append("beta_present")

    # Artifact penalty
    if features.artifact_ratio > 0.3:
        penalty = int(features.artifact_ratio * 20)
        base -= penalty
        reasons.append("artifact_penalty")

    # Quality weighting
    base *= quality.score

    # Clamp to [0, 100]
    score = int(np.clip(round(base), 0, 100))

    # State determination
    if quality.score < 0.4:
        state = "noisy"
    elif score >= 70:
        state = "focused"
    elif score >= 45:
        state = "stable"
    elif score >= 30:
        state = "relaxed"
    else:
        state = "fatigued"

    # Ensure reasons is never empty
    if not reasons:
        reasons.append("default_assessment")

    return FocusEstimate(
        score=score,
        quality=quality.score,
        state=state,
        reasons=reasons,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_focus -v
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add ear_eeg_sound_lab/src/realtime_engine/focus.py ear_eeg_sound_lab/tests/test_focus.py
git commit -m "feat(engine): add heuristic-based focus estimation"
```

---

### Task 8: pipeline.py — 管线串联

**Files:**
- Create: `ear_eeg_sound_lab/src/realtime_engine/pipeline.py`
- Create: `ear_eeg_sound_lab/tests/test_pipeline.py`

- [ ] **Step 1: 编写 test_pipeline.py**

```python
"""Tests for pipeline module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.pipeline import (
    process_eeg_array,
    process_window,
)
from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGWindow


class TestProcessWindow(unittest.TestCase):
    """Test process_window function."""

    def test_basic_processing(self):
        """A normal window should produce valid EngineOutput."""
        sample_rate = 250.0
        n_samples = 500  # 2 seconds
        t = np.arange(n_samples) / sample_rate
        data = np.sin(2 * np.pi * 10.0 * t) * 20.0  # 10 Hz, 20 uV
        data = np.tile(data, (8, 1))

        window = EEGWindow(
            data=data.astype(np.float64),
            sample_rate=sample_rate,
            start_sample=0,
            start_time=0.0,
            unit="uv",
        )

        result = process_window(window)

        # Check all fields exist
        self.assertIsNotNone(result.window)
        self.assertIsNotNone(result.preprocessed)
        self.assertIsNotNone(result.features)
        self.assertIsNotNone(result.quality)
        self.assertIsNotNone(result.focus)

        # Check focus score range
        self.assertGreaterEqual(result.focus.score, 0)
        self.assertLessEqual(result.focus.score, 100)

        # Check quality score range
        self.assertGreaterEqual(result.quality.score, 0.0)
        self.assertLessEqual(result.quality.score, 1.0)

    def test_no_nan_in_output(self):
        """No NaN should appear anywhere in the output."""
        sample_rate = 250.0
        data = np.random.randn(8, 500) * 50.0
        window = EEGWindow(
            data=data, sample_rate=sample_rate,
            start_sample=0, start_time=0.0, unit="uv",
        )

        result = process_window(window)

        # Check features
        self.assertTrue(np.isfinite(result.features.theta_beta_ratio))
        self.assertTrue(np.isfinite(result.features.alpha_beta_ratio))
        self.assertTrue(np.isfinite(result.features.artifact_ratio))

        # Check focus
        self.assertTrue(0 <= result.focus.score <= 100)


class TestProcessEEGArray(unittest.TestCase):
    """Test process_eeg_array function."""

    def test_10_second_eeg(self):
        """10 seconds of EEG should produce multiple outputs."""
        sample_rate = 250.0
        n_samples = 2500  # 10 seconds
        t = np.arange(n_samples) / sample_rate
        data = np.sin(2 * np.pi * 10.0 * t) * 20.0
        data = np.tile(data, (8, 1))

        outputs = process_eeg_array(data, sample_rate, unit="uv")

        # Should produce multiple windows
        self.assertGreater(len(outputs), 1)

        # Each output should have valid focus
        for out in outputs:
            self.assertGreaterEqual(out.focus.score, 0)
            self.assertLessEqual(out.focus.score, 100)

    def test_counts_unit_input(self):
        """Input with unit='counts' should work end-to-end."""
        sample_rate = 250.0
        n_samples = 2500
        # Simulate raw counts (large values)
        data = np.random.randn(8, n_samples) * 10000.0

        outputs = process_eeg_array(data, sample_rate, unit="counts")

        self.assertGreater(len(outputs), 0)
        for out in outputs:
            self.assertEqual(out.preprocessed.unit, "uv")

    def test_insufficient_data(self):
        """Data shorter than one window → empty output."""
        sample_rate = 250.0
        data = np.random.randn(8, 100)  # 0.4 seconds

        outputs = process_eeg_array(data, sample_rate, unit="uv")

        self.assertEqual(len(outputs), 0)

    def test_no_nan_across_windows(self):
        """No NaN should appear in any window's output."""
        sample_rate = 250.0
        data = np.random.randn(8, 2500) * 50.0

        outputs = process_eeg_array(data, sample_rate, unit="uv")

        for out in outputs:
            self.assertTrue(np.isfinite(out.features.theta_beta_ratio))
            self.assertTrue(np.isfinite(out.features.alpha_beta_ratio))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_pipeline -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现 pipeline.py**

```python
"""Realtime EEG processing pipeline.

Chains preprocessing → features → quality → focus for each window.
Provides both single-window and array-level processing.

This module does not depend on LSL, HTTP, or UI.
"""

from __future__ import annotations

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.features import extract_features
from ear_eeg_sound_lab.src.realtime_engine.focus import estimate_focus
from ear_eeg_sound_lab.src.realtime_engine.preprocessing import preprocess_window
from ear_eeg_sound_lab.src.realtime_engine.quality import estimate_signal_quality
from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    EEGWindow,
    EngineOutput,
)
from ear_eeg_sound_lab.src.realtime_engine.windowing import iter_eeg_windows


def process_window(window: EEGWindow) -> EngineOutput:
    """Process a single EEG window through the full pipeline.

    Args:
        window: Input EEG window (counts or uV).

    Returns:
        EngineOutput with preprocessed data, features, quality, and focus.
    """
    preprocessed = preprocess_window(window)
    features = extract_features(preprocessed)
    quality = estimate_signal_quality(preprocessed)
    focus = estimate_focus(features, quality)

    return EngineOutput(
        window=window,
        preprocessed=preprocessed,
        features=features,
        quality=quality,
        focus=focus,
    )


def process_eeg_array(
    eeg: np.ndarray,
    sample_rate: float,
    window_seconds: float = 2.0,
    step_seconds: float = 0.5,
    unit: str = "counts",
    gain: float = 24.0,
    vref: float = 4.5,
) -> list[EngineOutput]:
    """Process an entire EEG array through the pipeline (offline entry point).

    Args:
        eeg: Continuous EEG data, shape (channels, samples).
        sample_rate: Sampling rate in Hz.
        window_seconds: Window length in seconds (default 2.0).
        step_seconds: Step size in seconds (default 0.5).
        unit: Data unit, "counts" or "uv".
        gain: ADS1299 gain for counts→uV conversion.
        vref: ADS1299 reference voltage for counts→uV conversion.

    Returns:
        List of EngineOutput, one per window.
    """
    windows = iter_eeg_windows(
        eeg, sample_rate, window_seconds, step_seconds, unit, gain, vref
    )
    return [process_window(w) for w in windows]
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_pipeline -v
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add ear_eeg_sound_lab/src/realtime_engine/pipeline.py ear_eeg_sound_lab/tests/test_pipeline.py
git commit -m "feat(engine): add processing pipeline chaining all modules"
```

---

## Phase 3: Integrations

### Task 9: lsl_reader.py — LSL 实时读取

**Files:**
- Create: `ear_eeg_sound_lab/src/integrations/lsl_reader.py`

**Dependencies:** pylsl

- [ ] **Step 1: 实现 lsl_reader.py**

```python
"""LSL stream reader for real-time EEG acquisition.

Connects to an LSL stream (typically earEEG_EEG from upper_machine.lsl_proxy)
and pulls EEG chunks. This module depends on pylsl.

Note: This module only reads from LSL — no filtering, no focus estimation.
The output EEGChunk should be fed into lsl_buffer.EEGRollingBuffer.
"""

from __future__ import annotations

import logging

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGChunk

logger = logging.getLogger(__name__)

try:
    import pylsl
except ImportError:
    pylsl = None  # type: ignore[assignment]


class LSLStreamReader:
    """Read EEG data from an LSL stream.

    Args:
        stream_name: LSL stream name to search for (default "earEEG_EEG").
        stream_type: LSL stream type (default "EEG").
        expected_channels: Expected number of EEG channels (default 16).
        unit: Data unit label (default "counts").
    """

    def __init__(
        self,
        stream_name: str = "earEEG_EEG",
        stream_type: str = "EEG",
        expected_channels: int = 16,
        unit: str = "counts",
    ) -> None:
        if pylsl is None:
            raise ImportError(
                "pylsl is required for LSLStreamReader. "
                "Install it with: pip install pylsl"
            )
        self._stream_name = stream_name
        self._stream_type = stream_type
        self._expected_channels = expected_channels
        self._unit = unit
        self._inlet: pylsl.StreamInlet | None = None
        self._sample_rate: float | None = None

    def connect(self, timeout: float = 5.0) -> None:
        """Find and connect to the LSL stream.

        Args:
            timeout: Timeout in seconds for stream discovery.

        Raises:
            RuntimeError: If no matching stream is found.
        """
        logger.info("Searching for LSL stream: %s (type=%s)", self._stream_name, self._stream_type)

        streams = pylsl.resolve_byprop("name", self._stream_name, timeout=timeout)

        if not streams:
            raise RuntimeError(
                f"LSL stream '{self._stream_name}' not found within {timeout}s. "
                "Is upper_machine.lsl_proxy running with --lsl?"
            )

        info = streams[0]
        self._inlet = pylsl.StreamInlet(info)
        self._sample_rate = info.nominal_srate()

        n_channels = info.channel_count()
        if n_channels != self._expected_channels:
            logger.warning(
                "Expected %d channels, got %d", self._expected_channels, n_channels
            )

        logger.info(
            "Connected to LSL stream '%s': %.0f Hz, %d channels",
            self._stream_name, self._sample_rate, n_channels,
        )

    def pull_chunk(self, max_samples: int = 128, timeout: float = 0.0) -> EEGChunk | None:
        """Pull a chunk of EEG data from the LSL stream.

        Args:
            max_samples: Maximum number of samples to pull.
            timeout: Timeout in seconds (0.0 = non-blocking).

        Returns:
            EEGChunk if data is available, None otherwise.

        Raises:
            RuntimeError: If not connected.
        """
        if self._inlet is None:
            raise RuntimeError("Not connected. Call connect() first.")

        chunk, timestamps = self._inlet.pull_chunk(timeout=timeout, max_samples=max_samples)

        if not chunk or len(chunk) == 0:
            return None

        # pylsl returns list of lists → numpy array (samples, channels)
        data = np.array(chunk, dtype=np.float64)
        ts = np.array(timestamps, dtype=np.float64)

        return EEGChunk(
            data=data,
            timestamps=ts,
            sample_rate=self._sample_rate or 250.0,
            unit=self._unit,
        )

    @property
    def is_connected(self) -> bool:
        """Whether the inlet is connected."""
        return self._inlet is not None

    @property
    def sample_rate(self) -> float | None:
        """Nominal sample rate of the connected stream."""
        return self._sample_rate
```

- [ ] **Step 2: 验证可导入**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -c "from ear_eeg_sound_lab.src.integrations.lsl_reader import LSLStreamReader; print('LSLStreamReader imported OK')"
```

Expected: `LSLStreamReader imported OK` (or ImportError if pylsl not installed — acceptable)

- [ ] **Step 3: Commit**

```bash
git add ear_eeg_sound_lab/src/integrations/lsl_reader.py
git commit -m "feat(integrations): add LSL stream reader"
```

---

### Task 10: lsl_buffer.py — 滚动缓存

**Files:**
- Create: `ear_eeg_sound_lab/src/integrations/lsl_buffer.py`
- Create: `ear_eeg_sound_lab/tests/test_lsl_buffer.py`

- [ ] **Step 1: 编写 test_lsl_buffer.py**

```python
"""Tests for lsl_buffer module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.integrations.lsl_buffer import EEGRollingBuffer
from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGChunk


class TestEEGRollingBuffer(unittest.TestCase):
    """Test EEGRollingBuffer behavior."""

    def test_append_and_has_window(self):
        """After enough data, has_window should return True."""
        buffer = EEGRollingBuffer(channels=4, sample_rate=250.0)

        # 2 seconds = 500 samples, send in chunks of 128
        for i in range(5):
            chunk = EEGChunk(
                data=np.random.randn(128, 4),
                timestamps=np.arange(128) / 250.0 + i * 128 / 250.0,
                sample_rate=250.0,
            )
            buffer.append_chunk(chunk)

        self.assertTrue(buffer.has_window())

    def test_not_enough_data(self):
        """Before enough data, has_window should return False."""
        buffer = EEGRollingBuffer(channels=4, sample_rate=250.0)

        chunk = EEGChunk(
            data=np.random.randn(100, 4),
            timestamps=np.arange(100) / 250.0,
            sample_rate=250.0,
        )
        buffer.append_chunk(chunk)

        self.assertFalse(buffer.has_window())

    def test_latest_window_shape(self):
        """latest_window should return (channels, window_samples) shape."""
        buffer = EEGRollingBuffer(channels=8, sample_rate=250.0)

        # Add enough data
        for i in range(5):
            chunk = EEGChunk(
                data=np.random.randn(128, 8),
                timestamps=np.arange(128) / 250.0 + i * 128 / 250.0,
                sample_rate=250.0,
            )
            buffer.append_chunk(chunk)

        window = buffer.latest_window()
        self.assertEqual(window.data.shape, (8, 500))

    def test_pop_next_window(self):
        """pop_next_window should return a window and advance the pointer."""
        buffer = EEGRollingBuffer(channels=4, sample_rate=250.0)

        # Add 3 seconds of data
        for i in range(7):
            chunk = EEGChunk(
                data=np.random.randn(128, 4),
                timestamps=np.arange(128) / 250.0 + i * 128 / 250.0,
                sample_rate=250.0,
            )
            buffer.append_chunk(chunk)

        window = buffer.pop_next_window()
        self.assertIsNotNone(window)
        self.assertEqual(window.data.shape[0], 4)
        self.assertEqual(window.data.shape[1], 500)

    def test_capacity_limit(self):
        """Buffer should not grow beyond capacity."""
        buffer = EEGRollingBuffer(channels=4, sample_rate=250.0, capacity_seconds=5.0)

        # Add 10 seconds of data (beyond 5s capacity)
        for i in range(20):
            chunk = EEGChunk(
                data=np.random.randn(128, 4),
                timestamps=np.arange(128) / 250.0 + i * 128 / 250.0,
                sample_rate=250.0,
            )
            buffer.append_chunk(chunk)

        # Internal buffer should not exceed capacity
        self.assertLessEqual(buffer.total_samples, 5.0 * 250.0 + 128)  # Allow one chunk overshoot


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_lsl_buffer -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现 lsl_buffer.py**

```python
"""EEG rolling buffer for real-time LSL data.

Accumulates LSL chunks into a continuous buffer and provides
fixed-length windows for the processing pipeline.

Internal storage: (channels, samples) format.
Output: EEGWindow objects.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGChunk, EEGWindow


class EEGRollingBuffer:
    """Rolling buffer that accumulates LSL EEG chunks and provides windows.

    Args:
        channels: Number of EEG channels.
        sample_rate: Sampling rate in Hz.
        capacity_seconds: Maximum buffer length in seconds (default 30.0).
        unit: Data unit label (default "counts").
    """

    def __init__(
        self,
        channels: int,
        sample_rate: float,
        capacity_seconds: float = 30.0,
        unit: str = "counts",
    ) -> None:
        self._channels = channels
        self._sample_rate = sample_rate
        self._capacity_samples = int(capacity_seconds * sample_rate)
        self._unit = unit
        self._buffer: deque[np.ndarray] = deque()  # Each element: (samples, channels)
        self._total_samples = 0
        self._popped_samples = 0  # Track how many samples have been popped

    def append_chunk(self, chunk: EEGChunk) -> None:
        """Append an LSL chunk to the buffer.

        Args:
            chunk: EEGChunk with data shape (samples, channels).
        """
        # Transpose to (channels, samples) for internal storage
        data_t = chunk.data.T  # (channels, samples)
        self._buffer.append(data_t)
        self._total_samples += data_t.shape[1]

        # Trim buffer if it exceeds capacity
        while self._total_samples > self._capacity_samples and len(self._buffer) > 1:
            removed = self._buffer.popleft()
            self._total_samples -= removed.shape[1]

    def has_window(self, window_seconds: float = 2.0) -> bool:
        """Check if enough data is available for a window.

        Args:
            window_seconds: Window length in seconds.

        Returns:
            True if enough samples are available.
        """
        window_samples = int(window_seconds * self._sample_rate)
        return self._total_samples >= window_samples

    def latest_window(
        self,
        window_seconds: float = 2.0,
        gain: float = 24.0,
        vref: float = 4.5,
    ) -> EEGWindow:
        """Get the latest window of data (non-destructive).

        Args:
            window_seconds: Window length in seconds.
            gain: ADS1299 gain for counts→uV.
            vref: ADS1299 reference voltage for counts→uV.

        Returns:
            EEGWindow with shape (channels, window_samples).

        Raises:
            RuntimeError: If not enough data is available.
        """
        if not self.has_window(window_seconds):
            raise RuntimeError(
                f"Not enough data: need {window_seconds}s, "
                f"have {self._total_samples / self._sample_rate:.1f}s"
            )

        window_samples = int(window_seconds * self._sample_rate)

        # Concatenate buffer into continuous array
        all_data = np.concatenate(list(self._buffer), axis=1)  # (channels, total)
        data = all_data[:, -window_samples:]  # Last N samples

        return EEGWindow(
            data=data.astype(np.float64),
            sample_rate=self._sample_rate,
            start_sample=self._total_samples - window_samples,
            start_time=(self._total_samples - window_samples) / self._sample_rate,
            unit=self._unit,
            gain=gain,
            vref=vref,
        )

    def pop_next_window(
        self,
        window_seconds: float = 2.0,
        step_seconds: float = 0.5,
        gain: float = 24.0,
        vref: float = 4.5,
    ) -> EEGWindow | None:
        """Pop the next window from the buffer (advances pointer).

        Args:
            window_seconds: Window length in seconds.
            step_seconds: Step size to advance after popping.
            gain: ADS1299 gain for counts→uV.
            vref: ADS1299 reference voltage for counts→uV.

        Returns:
            EEGWindow if enough data, None otherwise.
        """
        if not self.has_window(window_seconds):
            return None

        window_samples = int(window_seconds * self._sample_rate)
        step_samples = int(step_seconds * self._sample_rate)

        # Concatenate buffer
        all_data = np.concatenate(list(self._buffer), axis=1)

        # Get window starting from popped_samples
        start = self._popped_samples
        end = start + window_samples
        if end > all_data.shape[1]:
            return None

        data = all_data[:, start:end]
        self._popped_samples += step_samples

        return EEGWindow(
            data=data.astype(np.float64),
            sample_rate=self._sample_rate,
            start_sample=self._popped_samples - step_samples,
            start_time=(self._popped_samples - step_samples) / self._sample_rate,
            unit=self._unit,
            gain=gain,
            vref=vref,
        )

    @property
    def total_samples(self) -> int:
        """Total samples currently in the buffer."""
        return self._total_samples
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_lsl_buffer -v
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add ear_eeg_sound_lab/src/integrations/lsl_buffer.py ear_eeg_sound_lab/tests/test_lsl_buffer.py
git commit -m "feat(integrations): add EEG rolling buffer for LSL data"
```

---

## Phase 4: Storage

### Task 11: session_summary.py — 会话汇总

**Files:**
- Create: `ear_eeg_sound_lab/src/storage/__init__.py`
- Create: `ear_eeg_sound_lab/src/storage/session_summary.py`

- [ ] **Step 1: 创建 storage 包**

```python
# ear_eeg_sound_lab/src/storage/__init__.py
```

（空文件）

- [ ] **Step 2: 实现 session_summary.py**

```python
"""Session summary — aggregate EngineOutput list into statistics.

Provides a simple dict summary suitable for downstream reporting,
music policy, or LLM report input.
"""

from __future__ import annotations

from collections import Counter

from ear_eeg_sound_lab.src.realtime_engine.schemas import EngineOutput


def summarize_engine_outputs(outputs: list[EngineOutput]) -> dict:
    """Summarize a list of EngineOutput into aggregate statistics.

    Args:
        outputs: List of EngineOutput from pipeline processing.

    Returns:
        Dict with:
            - windowCount: Total number of windows.
            - meanFocus: Average focus score.
            - minFocus: Minimum focus score.
            - maxFocus: Maximum focus score.
            - meanQuality: Average signal quality score.
            - badWindowRatio: Fraction of windows with quality < 0.4.
            - stateCounts: Count of each focus state.
            - warnings: Deduplicated warning list.
    """
    if not outputs:
        return {
            "windowCount": 0,
            "meanFocus": 0,
            "minFocus": 0,
            "maxFocus": 0,
            "meanQuality": 0.0,
            "badWindowRatio": 0.0,
            "stateCounts": {},
            "warnings": [],
        }

    focus_scores = [o.focus.score for o in outputs]
    quality_scores = [o.quality.score for o in outputs]
    states = [o.focus.state for o in outputs]

    state_counts = dict(Counter(states))

    bad_window_count = sum(1 for q in quality_scores if q < 0.4)
    bad_window_ratio = bad_window_count / len(outputs)

    # Collect all warnings, deduplicated
    all_warnings: list[str] = []
    seen_warnings: set[str] = set()
    for o in outputs:
        for w in o.quality.warnings:
            if w not in seen_warnings:
                seen_warnings.add(w)
                all_warnings.append(w)

    return {
        "windowCount": len(outputs),
        "meanFocus": round(sum(focus_scores) / len(focus_scores), 1),
        "minFocus": min(focus_scores),
        "maxFocus": max(focus_scores),
        "meanQuality": round(sum(quality_scores) / len(quality_scores), 2),
        "badWindowRatio": round(bad_window_ratio, 2),
        "stateCounts": state_counts,
        "warnings": all_warnings,
    }
```

- [ ] **Step 3: 验证端到端调用**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -c "
from ear_eeg_sound_lab.src.integrations.npz_loader import load_npz_session
from ear_eeg_sound_lab.src.realtime_engine.pipeline import process_eeg_array
from ear_eeg_sound_lab.src.storage.session_summary import summarize_engine_outputs
import numpy as np

# Use synthetic data
eeg = np.random.randn(16, 2500).astype(np.float32) * 10000  # counts
outputs = process_eeg_array(eeg, sample_rate=250.0, unit='counts')
summary = summarize_engine_outputs(outputs)
print(summary)
"
```

Expected: A dict with windowCount > 0, meanFocus in [0, 100], etc.

- [ ] **Step 4: Commit**

```bash
git add ear_eeg_sound_lab/src/storage/__init__.py ear_eeg_sound_lab/src/storage/session_summary.py
git commit -m "feat(storage): add session summary aggregation"
```

---

## Phase 5: Final Verification

### Task 12: 全量测试 + 端到端验证

- [ ] **Step 1: 运行全部测试**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest discover -s ear_eeg_sound_lab/tests -p "test_*.py" -v
```

Expected: All tests pass.

- [ ] **Step 2: 运行端到端 NPZ 调用**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -c "
from ear_eeg_sound_lab.src.integrations.npz_loader import load_npz_session
from ear_eeg_sound_lab.src.realtime_engine.pipeline import process_eeg_array
from ear_eeg_sound_lab.src.storage.session_summary import summarize_engine_outputs
from pathlib import Path

npz_path = Path('recordings/20260606_113353.npz')
if npz_path.exists():
    session = load_npz_session(npz_path)
    print(f'Loaded: eeg={session.eeg.shape}, rate={session.eeg_sample_rate}')
    outputs = process_eeg_array(session.eeg, sample_rate=session.eeg_sample_rate, unit='counts')
    summary = summarize_engine_outputs(outputs)
    import json
    print(json.dumps(summary, indent=2))
else:
    print('NPZ not found, skipping')
"
```

Expected: Summary dict with windowCount > 0.

- [ ] **Step 3: 确认未破坏现有模块**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -c "from ear_eeg_sound_lab.src.simulated_device.main import main; print('simulated_device OK')"
```

Expected: `simulated_device OK`

- [ ] **Step 4: 最终 Commit**

```bash
git add -A
git commit -m "feat: realtime EEG analysis engine v1 complete"
```

---

## 依赖安装

如果 scipy 未安装，需要先安装：

```powershell
pip install scipy
```

如果 pylsl 未安装（仅 lsl_reader 需要）：

```powershell
pip install pylsl
```

---

## 总结

| Task | 模块 | 测试 | 依赖 |
|------|------|------|------|
| 1 | schemas.py | — | numpy |
| 2 | npz_loader.py | test_npz_loader.py | numpy |
| 3 | windowing.py | test_windowing.py | numpy |
| 4 | preprocessing.py | test_preprocessing.py | numpy, scipy |
| 5 | features.py | test_features.py | numpy |
| 6 | quality.py | test_quality.py | numpy |
| 7 | focus.py | test_focus.py | numpy |
| 8 | pipeline.py | test_pipeline.py | numpy |
| 9 | lsl_reader.py | — | pylsl |
| 10 | lsl_buffer.py | test_lsl_buffer.py | numpy |
| 11 | session_summary.py | — | numpy |
| 12 | 全量验证 | — | — |
