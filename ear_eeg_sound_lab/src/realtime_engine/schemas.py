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
