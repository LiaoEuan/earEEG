# earEEG 项目当前状态报告

**日期：** 2026-06-14
**分支：** master (已合并 worktree-realtime-engine-v1)
**GitHub：** https://github.com/LiaoEuan/earEEG

---

## 一、项目结构

```
earEEG/
├── earEEG/                      # ESP32-S3 固件 (C / ESP-IDF / PlatformIO)
│   ├── include/                 # protocol.h, earEEG_config.h
│   └── src/                     # protocol.c, uart_eeg.c
├── upper_machine/               # PC 上位机 (Python)
│   ├── common/                  # protocol.py, eeg_units.py
│   ├── lsl_proxy/               # TCP 客户端 + LSL 发布 + 控制 API
│   ├── eeg_viewer/              # HTTP/WebSocket 浏览器查看器
│   │   ├── main.py              # HTTP + WebSocket 服务
│   │   ├── eeg_buffer.py        # 线程安全滚动缓存
│   │   ├── lsl_reader.py        # LSL 输入线程
│   │   ├── recording_service.py # NPZ 录制
│   │   ├── impedance_service.py # 阻抗测量
│   │   └── static/              # index.html, style.css, viewer.js
│   └── impedance/               # 阻抗计算
├── ear_eeg_sound_lab/           # 声音-EEG 闭环应用（本次开发重点）
│   ├── src/
│   │   ├── integrations/        # LSL 读取、NPZ 加载、滚动缓存
│   │   ├── realtime_engine/     # 预处理、频段特征、信号质量、专注度、管线
│   │   ├── storage/             # 会话汇总
│   │   ├── web_app/             # 独立 Web 服务 + 最小 UI
│   │   └── simulated_device/    # 模拟设备
│   ├── tests/                   # 10 个测试文件，68 个测试
│   └── docs/                    # 设计文档、实施计划
├── recordings/                  # 3 个 NPZ 文件
│   ├── 20260606_113353.npz
│   ├── 20260606_115909.npz
│   └── 20260606_123049.npz
└── ear_eeg_sound_lab/pyproject.toml  # 依赖: numpy>=2.4.5, scipy>=1.11.0
```

---

## 二、已完成功能

### M1：离线算法原型（已完成）

从 NPZ 文件或 LSL 流读取 EEG 数据，经过完整处理链路输出结构化结果。

**处理链路：**
```
EEG 数据 → 窗口切片(2s/0.5s) → 预处理(counts→uV + demean + 带通 + 陷波)
→ 频段特征(FFT: delta/theta/alpha/beta/gamma) → 信号质量评估
→ 专注度评分(启发式) → 结构化输出(EngineOutput)
```

**源码文件（17 个）：**

| 模块 | 文件 | 功能 |
|------|------|------|
| schemas | `src/realtime_engine/schemas.py` | 9 个 dataclass：EEGWindow, PreprocessedWindow, BandPower, FeatureFrame, SignalQuality, FocusEstimate, EngineOutput, EEGChunk, NPZSession |
| windowing | `src/realtime_engine/windowing.py` | `iter_eeg_windows()` — 连续 EEG 切成 2s 窗口，0.5s 步长 |
| preprocessing | `src/realtime_engine/preprocessing.py` | counts→uV 转换 + NaN 清理 + demean + 4 阶 Butterworth 带通 1-45Hz + 可配置 50/60Hz 陷波 |
| features | `src/realtime_engine/features.py` | Hann 窗 FFT → 5 频段功率 + theta/beta ratio + alpha/beta ratio + artifact ratio |
| quality | `src/realtime_engine/quality.py` | flatline/high-amplitude/high-ptp/noisy 检测，score 0-1 |
| focus | `src/realtime_engine/focus.py` | 启发式评分：theta/beta + alpha/beta + beta 存在性 + artifact 惩罚 + quality 加权，score 0-100 |
| pipeline | `src/realtime_engine/pipeline.py` | `process_window()` 串联所有模块，`process_eeg_array()` 离线入口 |
| npz_loader | `src/integrations/npz_loader.py` | 读取 NPZ 文件，返回 NPZSession |
| lsl_reader | `src/integrations/lsl_reader.py` | LSLStreamReader — 连接 LSL 流，拉取 EEGChunk |
| lsl_buffer | `src/integrations/lsl_buffer.py` | EEGRollingBuffer — 三量游标追踪，capacity 裁剪，输出 EEGWindow |
| session_summary | `src/storage/session_summary.py` | 汇总 EngineOutput 列表为 dict |
| state_provider | `src/web_app/state_provider.py` | 线程安全的 Dashboard 状态汇聚 |
| recording_service | `src/web_app/recording_service.py` | NPZ 录制服务 |
| server | `src/web_app/server.py` | HTTP + WebSocket 服务 + LSL 主循环 |
| web_app/__init__ | `src/web_app/__init__.py` | 包初始化 |
| integrations/__init__ | `src/integrations/__init__.py` | 包初始化 |
| realtime_engine/__init__ | `src/realtime_engine/__init__.py` | 包初始化 |

**测试文件（10 个）：**

| 测试文件 | 测试数 | 覆盖内容 |
|----------|--------|----------|
| test_npz_loader.py | 5 | NPZ 读取、shape 校验、缺失字段 |
| test_windowing.py | 8 | 窗口数量、shape、步长、边界条件 |
| test_preprocessing.py | 8 | DC 偏置去除、NaN 清理、counts→uV、滤波 |
| test_features.py | 9 | 10Hz→alpha 最大、20Hz→beta 最大、除零保护 |
| test_quality.py | 5 | 全零低质量、正弦波高质量、score 范围 |
| test_focus.py | 7 | 质量门控、beta/theta 对比、score 范围 |
| test_pipeline.py | 6 | 10s EEG 多窗口、counts 输入、无 NaN |
| test_pipeline_profiles.py | 5 | focused/fatigued/noisy/relaxed 区分度 |
| test_lsl_buffer.py | 8 | chunk 累积、窗口输出、容量裁剪、30s 连续稳定性 |
| test_state_provider.py | 7 | focus 更新、频段功率、波形滚动、设备状态 |

**测试结果：68 passed, 2 skipped（real NPZ not in worktree）**

### M2：实时运行器（已完成）

独立的 Web 服务，从 LSL 读取实时数据，通过 pipeline 处理，WebSocket 推送结果到浏览器。

**功能：**
- HTTP 服务（`GET /` 静态页面，`GET /api/state` JSON 状态）
- WebSocket 推送（`/ws`，10Hz 推送完整状态）
- LSL 自动连接和重连
- 录制控制（`POST /api/recording/start`，`POST /api/recording/stop`）
- 录制列表（`GET /api/recordings`）
- 最小浏览器 UI（EEG 波形 + focus + 频段功率 + 通道选择 + 录制控制）

**浏览器 UI 功能：**
- 16 通道 EEG 波形（Canvas 绘图，时间轴，网格线，uV 缩放）
- 通道选择器（Ch1-Ch16 点击切换显示/隐藏）
- 专注度仪表盘（分数 + 状态 + 原因列表）
- 频段功率柱状图（delta/theta/alpha/beta/gamma，不同颜色）
- 录制按钮（Start/Stop，脉冲指示，已录制时长）
- 录制列表（显示已保存的 NPZ 文件）
- 连接状态、设备状态、FPS

---

## 三、已修复的问题

初始实现后 code review 发现 5 个问题，已全部修复：

| # | 问题 | 文件 | 修复 | Commit |
|---|------|------|------|--------|
| 1 | windowing 边界 `< n_samples` 漏掉最后一个窗口 | windowing.py:51 | 改为 `<= n_samples` | ec39f83 |
| 2 | lsl_buffer 游标 `_popped_samples` 在 capacity 裁剪后失效 | lsl_buffer.py | 重写为三量追踪 (`_buffer_start_sample`/`_total_received`/`_next_window_start`) | 410749c |
| 3 | scipy 依赖未声明 | pyproject.toml | 创建 ear_eeg_sound_lab/pyproject.toml | abbdced |
| 4 | lsl_reader 的 `stream_type` 参数未使用 | lsl_reader.py | name 查找失败后 fallback 到 type | 6a4bec0 |
| 5 | pipeline 测试覆盖不足 | test_pipeline_profiles.py | 新增 5 个 profile 测试 | b826fcc |

---

## 四、已安装的 Claude Code 插件

**全局安装（用户级）：**

| 插件 | 来源 | 状态 |
|------|------|------|
| superpowers | claude-plugins-official | ✅ 已安装 |
| frontend-design | claude-plugins-official | ✅ 已安装 |
| ui-ux-pro-max | ui-ux-pro-max-skill | ✅ 刚安装 |
| andrej-karpathy-skills | karpathy-skills | ✅ 已安装 |
| code-review | claude-plugins-official | ✅ 已安装 |
| 其他 | 多个 | ✅ 已安装 |

**项目级安装（worktree 中）：**

| 插件 | 来源 | 状态 |
|------|------|------|
| impeccable | pbakaus/impeccable | ✅ 通过 `npx impeccable skills install` 安装到 `.claude/skills/impeccable` |

**注意：** impeccable 安装在 worktree 目录 `.claude/skills/impeccable`，不在主仓库中。ui-ux-pro-max 通过 plugin marketplace 安装在全局。

---

## 五、当前存在的两套 UI

### UI 1：upper_machine.eeg_viewer

**位置：** `upper_machine/eeg_viewer/`
**端口：** 8765
**功能：**
- 16 通道 EEG 波形
- MIC 波形
- LSL 连接状态
- Start/Stop acquisition
- WAV 上传、播放、暂停、恢复、停止
- MIC monitor（Web Audio API）
- NPZ 录制 Start/Stop
- 阻抗测量
- 单位切换（uV/mV/V/counts）
- 幅值范围选择

**启动方式：**
```powershell
# 终端 1：模拟设备
python -m ear_eeg_sound_lab.src.simulated_device --auto-start --eeg-profile focused --mic-mode chirp

# 终端 2：lsl_proxy
uv run --project upper_machine python -m upper_machine.lsl_proxy.main --host 127.0.0.1 --port 8889 --lsl --start

# 终端 3：viewer
uv run --project upper_machine python -m upper_machine.eeg_viewer.main --host 127.0.0.1 --port 8765 --proxy-url http://127.0.0.1:8787
```

### UI 2：ear_eeg_sound_lab.web_app

**位置：** `ear_eeg_sound_lab/src/web_app/`
**端口：** 8765（默认，可配置）
**功能：**
- 16 通道 EEG 波形（带时间轴、网格线、uV 缩放）
- 通道选择器
- 专注度分数 + 状态 + 原因
- 频段功率柱状图
- NPZ 录制 Start/Stop
- 录制文件列表

**启动方式：**
```powershell
# 终端 1：模拟设备
python -m ear_eeg_sound_lab.src.simulated_device --auto-start --eeg-profile focused

# 终端 2：lsl_proxy
uv run --project upper_machine python -m upper_machine.lsl_proxy.main --host 127.0.0.1 --port 8889 --lsl --start

# 终端 3：web_app
python -m ear_eeg_sound_lab.src.web_app.server --port 8766
```

### 两套 UI 的区别

| 功能 | eeg_viewer | web_app |
|------|-----------|---------|
| EEG 波形 | ✅ | ✅ |
| MIC 波形 | ✅ | ❌ |
| 音频播放控制 | ✅ | ❌ |
| 阻抗测量 | ✅ | ❌ |
| 单位切换 | ✅ | ❌ |
| 专注度分数 | ❌ | ✅ |
| 频段功率 | ❌ | ✅ |
| 通道选择器 | ❌ | ✅ |
| 录制 | ✅ | ✅ |

---

## 六、待做事项

### 已规划但未实施

| 事项 | 说明 | 优先级 |
|------|------|--------|
| 合并两套 UI | 把 focus score 接入 eeg_viewer，一个页面看全部功能 | 高 |
| 后台 FocusService | 在 eeg_viewer 中加后台线程跑 pipeline | 高 |
| viewer.js 加 focus panel | 前端显示专注度和频段功率 | 高 |

### 未规划

| 事项 | 说明 |
|------|------|
| M3 Dashboard MVP | 增强 UI：会话时间线、更多可视化 |
| M4 Music Library | 本地歌曲库、播放历史、用户反馈 |
| M5 Recommendation | 基于历史响应的规则推荐 |
| M6 Adaptive Switching | 自适应切换规则 |
| M7 LLM Reports | 结构化摘要 → LLM 报告 |
| M8 Validation | 合成信号测试、NPZ 回放测试、硬件验证 |

---

## 七、设计文档和计划

| 文件 | 内容 |
|------|------|
| `ear_eeg_sound_lab/docs/superpowers/specs/2026-06-14-realtime-engine-v1-design.md` | M1 设计文档 |
| `ear_eeg_sound_lab/docs/superpowers/specs/2026-06-14-realtime-runner-m2-design.md` | M2 设计文档 |
| `ear_eeg_sound_lab/docs/superpowers/plans/2026-06-14-realtime-engine-v1.md` | M1 实施计划（12 个 Task） |
| `ear_eeg_sound_lab/docs/superpowers/plans/2026-06-14-realtime-runner-m2.md` | M2 实施计划（4 个 Task） |
| `ear_eeg_sound_lab/docs/architecture.md` | 架构文档 |
| `ear_eeg_sound_lab/docs/data_contracts.md` | 数据契约 |
| `ear_eeg_sound_lab/docs/roadmap.md` | 路线图（M0-M8） |
| `upper_machine/DEVELOPMENT_GUIDE.md` | 上位机交接文档 |
| `CLAUDE.md` | 项目开发规则 |
| `REVIEW_REQUEST.md` | M1+M2 审查请求 |

---

## 八、Git 提交历史（本次开发）

```
e0af6e7 feat(web_app): add recording service, recording API, and enhanced UI
1a8187a docs: add M2 realtime runner implementation plan
4844b9e feat(web_app): add realtime server with HTTP + WebSocket
7456cf9 feat(web_app): add minimal browser UI with waveform, focus, bands
503455d feat(web_app): add dashboard state provider
6081d04 docs: add design spec and implementation plan for realtime engine v1
6a4bec0 fix(integrations): use stream_type as fallback in LSL reader
b826fcc test(engine): add pipeline profile tests for algorithm differentiation
abbdced chore: add scipy dependency declaration
ec39f83 fix(engine): windowing boundary — include last complete window
410749c fix(integrations): rewrite lsl_buffer cursor for correct real-time windowing
dff4fe1 feat(storage): add session summary aggregation
eb11c3c feat(integrations): add EEG rolling buffer for LSL data
9076728 feat(integrations): add LSL stream reader
26e7b41 feat(engine): add processing pipeline chaining all modules
81c2dfa feat(engine): add heuristic-based focus estimation
84bb234 feat(engine): add signal quality assessment
cbc7c58 feat(engine): add FFT-based band power feature extraction
50f25a4 feat(engine): add preprocessing with counts-to-uV, demean, bandpass, notch
031d456 feat(engine): add EEG windowing module
105ac9b feat(integrations): add NPZ session loader
b966657 feat(engine): add dataclass schemas for realtime pipeline
```

---

## 九、已知限制

1. **两套 UI 独立运行** — eeg_viewer 有 MIC/音频/阻抗但无 focus；web_app 有 focus 但无 MIC/音频/阻抗
2. **算法效果未用真实 EEG 验证** — 测试用的是合成正弦波和随机数据
3. **web_app 的 WebSocket 无鉴权** — 监听 localhost，暂无安全风险
4. **preprocessing 每通道独立滤波** — 可优化为向量化
5. **impeccable 插件安装在 worktree** — 不在主仓库，需要在主仓库重新安装或复制
6. **模拟设备在 worktree 中不存在** — `simulated_device` 只在主分支有，worktree 中没有（已合并回 master）
