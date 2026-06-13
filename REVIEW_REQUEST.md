# earEEG 项目当前状态 — 供审查

**日期：** 2026-06-14
**分支：** master（已合并 worktree-realtime-engine-v1）
**GitHub：** https://github.com/LiaoEuan/earEEG

---

## 一、项目概述

ESP32-S3 EEG 耳机工程项目，包含三层：

```
earEEG/
├── earEEG/                  # ESP32-S3 固件 (C / ESP-IDF / PlatformIO)
├── upper_machine/           # PC 上位机 (Python / LSL / 浏览器查看器)
├── ear_eeg_sound_lab/       # 声音-EEG 闭环应用（本次开发重点）
└── recordings/              # 实验数据 (.npz)
```

## 二、本次开发内容

实现了 **M1（离线算法原型）** 和 **M2（实时运行器）**：

```
NPZ / LSL 实时流
  → 窗口切片 (2s 窗口, 0.5s 步长)
  → 预处理 (counts→uV + demean + 1-45Hz Butterworth 带通 + 50Hz 陷波)
  → 频段特征 (FFT: delta/theta/alpha/beta/gamma)
  → 信号质量 (flatline/high-amplitude/noisy 检测)
  → 专注度评分 (启发式: theta/beta ratio + alpha/beta + artifact + quality 加权)
  → 结构化输出
  → WebSocket 推送到浏览器
```

## 三、文件结构

### 源码 (ear_eeg_sound_lab/src/)

```
src/
├── integrations/
│   ├── npz_loader.py          # NPZ 文件读取，纯 I/O
│   ├── lsl_reader.py          # LSL 实时读取（依赖 pylsl）
│   └── lsl_buffer.py          # 滚动缓存，LSL chunk → EEGWindow
├── realtime_engine/
│   ├── schemas.py             # 所有 dataclass 定义
│   ├── windowing.py           # NPZ 离线窗口切片
│   ├── preprocessing.py       # counts→uV + demean + 带通 + 陷波 (依赖 scipy)
│   ├── features.py            # FFT 频段特征提取
│   ├── quality.py             # 信号质量评估
│   ├── focus.py               # 专注度启发式
│   └── pipeline.py            # 串联所有模块
├── storage/
│   └── session_summary.py     # 汇总 EngineOutput 列表
└── web_app/
    ├── server.py              # HTTP + WebSocket 服务 + 主循环
    ├── state_provider.py      # 线程安全的状态汇聚
    └── static/
        └── index.html         # 最小浏览器 UI
```

### 测试 (ear_eeg_sound_lab/tests/)

```
tests/
├── test_npz_loader.py         # 5 tests
├── test_windowing.py          # 8 tests
├── test_preprocessing.py      # 8 tests
├── test_features.py           # 9 tests
├── test_quality.py            # 5 tests
├── test_focus.py              # 7 tests
├── test_pipeline.py           # 6 tests
├── test_pipeline_profiles.py  # 5 tests (算法区分度验证)
├── test_lsl_buffer.py         # 8 tests (含实时稳定性)
└── test_state_provider.py     # 7 tests
```

**总计：74 tests passed**

## 四、核心数据结构

```python
@dataclass
class EEGWindow:
    data: np.ndarray          # (channels, samples) float64
    sample_rate: float
    start_sample: int
    start_time: float | None
    unit: str                 # "counts" or "uv"
    gain: float = 24.0
    vref: float = 4.5

@dataclass
class EngineOutput:
    window: EEGWindow
    preprocessed: PreprocessedWindow
    features: FeatureFrame
    quality: SignalQuality
    focus: FocusEstimate

@dataclass
class FocusEstimate:
    score: int                # 0-100
    quality: float            # 0.0-1.0
    state: str                # "focused"/"stable"/"relaxed"/"fatigued"/"noisy"
    reasons: list[str]
```

## 五、已修复的问题

初始实现后 code review 发现 5 个问题，已全部修复：

| # | 问题 | 修复 |
|---|------|------|
| 1 | windowing.py 边界 `< n_samples` 漏掉最后一个窗口 | 改为 `<= n_samples` |
| 2 | lsl_buffer.py 游标逻辑：`_popped_samples` 在 capacity 裁剪后失效 | 重写为三量追踪 (`_buffer_start_sample`/`_total_received`/`_next_window_start`) |
| 3 | scipy 依赖未声明 | 创建 `ear_eeg_sound_lab/pyproject.toml` |
| 4 | lsl_reader.py 的 `stream_type` 参数未使用 | 增加 name 失败后 fallback 到 type |
| 5 | pipeline 测试覆盖不足 | 新增 5 个 profile 测试验证算法区分度 |

## 六、设计文档

- `ear_eeg_sound_lab/docs/superpowers/specs/2026-06-14-realtime-engine-v1-design.md` — M1 设计
- `ear_eeg_sound_lab/docs/superpowers/plans/2026-06-14-realtime-engine-v1.md` — M1 实施计划
- `ear_eeg_sound_lab/docs/superpowers/plans/2026-06-14-realtime-runner-m2.md` — M2 实施计划

说明：M2 当前以实施计划和完成报告作为设计/验收依据，未单独维护 runner design spec。

## 七、使用方式

```powershell
# 终端 1：模拟设备
python -m ear_eeg_sound_lab.src.simulated_device --auto-start --eeg-profile focused

# 终端 2：lsl_proxy (TCP → LSL 桥接)
uv run --project upper_machine python -m upper_machine.lsl_proxy.main --host 127.0.0.1 --port 8889 --lsl --start

# 终端 3：实时引擎
python -m ear_eeg_sound_lab.src.web_app.server --port 8765

# 浏览器打开 http://127.0.0.1:8765
```

## 八、测试命令

```powershell
# 全量测试
python -m unittest discover -s ear_eeg_sound_lab/tests -p "test_*.py"

# 单模块测试
python -m unittest ear_eeg_sound_lab.tests.test_pipeline -v
python -m unittest ear_eeg_sound_lab.tests.test_pipeline_profiles -v
```

## 九、已知限制和待改进

1. **算法效果未充分验证** — 端到端测试用的是随机数据和合成正弦波，未用真实 EEG 数据验证专注度准确性
2. **WebSocket 无鉴权** — 监听 localhost，暂无安全风险，但如果改为 0.0.0.0 需要加鉴权
3. **UI 很基础** — 只有波形 + focus + 频段功率，没有会话时间线、录制、设备控制
4. **preprocessing 每通道独立滤波** — 可以优化为向量化操作
5. **无录制功能** — M2 没有保存会话数据的功能
6. **lsl_reader 依赖 pylsl** — 如果 pylsl 未安装，LSL 功能不可用（NPZ 离线分析仍可用）

## 十、待审查重点

请重点检查：

1. **lsl_buffer.py 游标逻辑** — 是否在 capacity 裁剪后仍能正确输出窗口
2. **preprocessing.py 滤波** — Butterworth 带通 + 陷波实现是否正确
3. **focus.py 启发式** — 评分公式和状态判断是否合理
4. **server.py 线程安全** — 主循环和 WebSocket 推送是否正确同步
5. **state_provider.py 波形滚动** — 是否正确维护最近 N 秒数据
6. **测试覆盖** — 是否有遗漏的关键场景
