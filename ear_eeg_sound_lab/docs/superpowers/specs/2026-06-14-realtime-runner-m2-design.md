# Realtime Runner (M2) — Design Spec

**Date:** 2026-06-14
**Status:** Approved
**Scope:** 实时运行器 — LSL → pipeline → WebSocket → 浏览器 UI

## 目标

完成 Milestone 2：一个独立的实时运行器，从 LSL 读取 EEG 数据，通过 pipeline 处理，通过 WebSocket 推送结果到浏览器，并包含一个最小 UI。

```
LSL → buffer → pipeline → WebSocket 推送 → 浏览器 UI
```

## 架构

```
模拟设备(127.0.0.1:8889) / 真实设备(192.168.4.1:8888)
  │ TCP
  ▼
upper_machine.lsl_proxy
  │ LSL: earEEG_EEG (16ch, 250Hz, counts)
  ▼
ear_eeg_sound_lab.src.web_app.server
  │
  ├── LSLStreamReader.connect()
  │
  ├── 主循环:
  │     reader.pull_chunk()
  │     → buffer.append_chunk()
  │     → buffer.pop_next_window()
  │     → pipeline.process_window()
  │     → state_provider.update(output)
  │
  ├── WebSocket /ws   ← 推送 dashboard 状态
  ├── GET /api/state  ← 查询最新状态
  └── GET /           ← 浏览器 UI
```

### 模块结构

```
ear_eeg_sound_lab/src/web_app/
  __init__.py
  server.py           # HTTP + WebSocket 服务，主循环
  state_provider.py   # 汇聚 EngineOutput → dashboard 状态 dict
  static/
    index.html        # 最小 UI
```

### 关键约束

- `web_app` 模块在 `ear_eeg_sound_lab` 内，独立于 `upper_machine`
- 参考 `upper_machine/eeg_viewer` 的 WebSocket 实现模式
- 不直接连接 ESP32 TCP，通过 LSL 获取数据
- 使用 `LSLStreamReader` + `EEGRollingBuffer` + `process_window()`

## WebSocket Payload

每 100-200ms 推送一次：

```json
{
  "timestamp": 1234567890.123,
  "device": {
    "connected": true,
    "streamName": "earEEG_EEG",
    "sampleRate": 250.0,
    "channels": 16
  },
  "focus": {
    "score": 72,
    "quality": 0.84,
    "state": "focused",
    "reasons": ["beta_present", "low_theta_beta"]
  },
  "features": {
    "globalBandPowers": {
      "delta": 12.3,
      "theta": 8.1,
      "alpha": 15.2,
      "beta": 22.4,
      "gamma": 3.1
    },
    "thetaBetaRatio": 0.36,
    "alphaBetaRatio": 0.68,
    "artifactRatio": 0.05
  },
  "eeg": {
    "channels": 16,
    "sampleRate": 250,
    "samples": [[...], "... 16 arrays, 最近 2 秒"],
    "timestamps": [0.0, 0.004, "..."]
  }
}
```

## 模块设计

### 1. server.py — 主服务

```python
class RealtimeServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        stream_name: str = "earEEG_EEG",
        stream_type: str = "EEG",
        channels: int = 16,
        sample_rate: float = 250.0,
        window_seconds: float = 2.0,
        step_seconds: float = 0.5,
        push_interval: float = 0.1,  # WebSocket 推送间隔(秒)
    ): ...

    def run(self) -> None:
        """主循环。"""
        # 1. 创建 LSLStreamReader + EEGRollingBuffer + DashboardStateProvider
        # 2. 启动 HTTP/WebSocket 服务（单独线程）
        # 3. 主循环: pull_chunk → buffer → pop_next_window → process_window → state_provider.update
        # 4. WebSocket 推送线程: 每 push_interval 秒广播 state_provider.get_state()
```

启动命令：
```powershell
python -m ear_eeg_sound_lab.src.web_app.server --port 8765
```

HTTP 路由：
- `GET /` → 浏览器 UI (static/index.html)
- `GET /ws` → WebSocket 升级，推送 dashboard 状态
- `GET /api/state` → 返回最新状态 JSON

错误处理：
- LSL 断连 → 自动重连，UI 显示 "disconnected"
- pipeline 异常 → 记录日志，跳过该窗口
- WebSocket 断连 → 清理客户端，不阻塞主循环

### 2. state_provider.py — 状态汇聚

```python
class DashboardStateProvider:
    def __init__(self, waveform_seconds: float = 2.0, channels: int = 16): ...

    def update(self, output: EngineOutput) -> None:
        """接收 pipeline 输出，更新内部状态。"""

    def get_state(self) -> dict:
        """返回完整的 dashboard 状态 dict。"""

    def set_device_status(self, connected: bool, stream_name: str, ...) -> None:
        """更新设备连接状态。"""
```

内部维护：
- 最近 N 秒 EEG 波形（滚动 buffer，shape (channels, N*sample_rate)）
- 最新 focus/quality/features
- 设备连接状态

### 3. static/index.html — 最小 UI

单页面，无构建工具，原生 HTML/CSS/JS：

- **顶部**：设备状态、连接状态、采样率、FPS
- **中央**：16 通道 EEG 波形（Canvas 绘图）
- **右侧**：专注度仪表盘（分数 + 状态 + 原因列表）
- **底部**：频段功率柱状图（delta/theta/alpha/beta/gamma）

WebSocket 客户端：
```javascript
const ws = new WebSocket(`ws://${location.host}/ws`);
ws.onmessage = (e) => {
    const state = JSON.parse(e.data);
    updateWaveform(state.eeg);
    updateFocus(state.focus);
    updateBands(state.features.globalBandPowers);
};
```

参考 `upper_machine/eeg_viewer/static/viewer.js` 的 Canvas 绘图模式。

## 联调流程

```powershell
# 终端 1：模拟设备
python -m ear_eeg_sound_lab.src.simulated_device --auto-start --eeg-profile focused

# 终端 2：lsl_proxy
uv run --project upper_machine python -m upper_machine.lsl_proxy.main --host 127.0.0.1 --port 8889 --lsl --start

# 终端 3：实时引擎
python -m ear_eeg_sound_lab.src.web_app.server --port 8765

# 浏览器打开 http://127.0.0.1:8765
```

## 依赖

```
numpy        — 已有
scipy        — 已有
标准库 http.server — HTTP 服务
标准库 hashlib, struct — WebSocket 握手和帧编码（参考 eeg_viewer，不引入第三方库）
```

参考 eog_viewer 的实现，用标准库 `http.server` + 手动 WebSocket 握手（不引入第三方库）。

## 测试策略

| 测试 | 覆盖 |
|------|------|
| test_state_provider.py | update/get_state, 波形滚动, 设备状态 |
| test_server_integration.py | 启动→WebSocket 连接→接收状态（可选，需要 mock LSL）|

## 验收标准

1. 可以通过模拟设备 → lsl_proxy → 实时引擎 → 浏览器看到 EEG 波形
2. 专注度分数实时更新
3. 频段功率柱状图实时更新
4. 设备断连时 UI 显示 disconnected
5. 切换模拟设备 eeg-profile 时 focus/state 变化可见
6. 不破坏现有 ear_eeg_sound_lab 和 upper_machine 代码
