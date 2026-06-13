# 最近变更（PROJECT_STATUS.md 之后）

**时间：** 2026-06-14
**范围：** 把 focus score 集成到 eeg_viewer，测试收口

---

## 一、新增文件

### `upper_machine/eeg_viewer/focus_service.py`（新建）

后台线程，每 0.5 秒从 EEGBuffer 取 2 秒快照，跑 realtime_engine pipeline，输出 focus/quality/bandPowers。

```python
class FocusService:
    def __init__(self, eeg_buffer, interval=0.5, window_seconds=2.0, sample_rate=250.0): ...
    def start(self) -> None: ...   # 启动后台线程
    def stop(self) -> None: ...    # 停止
    def get_focus(self) -> dict: ...  # 返回最新结果
```

内部调用 `ear_eeg_sound_lab.src.realtime_engine.pipeline.process_window()`。

---

## 二、修改文件

### `upper_machine/eeg_viewer/main.py`（6 行改动）

1. 新增 import：`from .focus_service import FocusService`
2. 新增类属性：`focus_service: FocusService`
3. `main()` 中创建：`ViewerHandler.focus_service = FocusService(eeg_buffer, sample_rate=SAMPLE_RATE)`
4. 启动：`ViewerHandler.focus_service.start()`
5. 停止：`ViewerHandler.focus_service.stop()` 在 finally 块中
6. WebSocket payload 新增：`"focus": self.focus_service.get_focus()`

### `upper_machine/eeg_viewer/static/index.html`

新增 focus panel HTML（在 recording toolbar 和 EEG plot 之间）：
- 大字分数显示
- 状态标签
- 质量百分比
- 原因标签
- 5 频段功率柱状图（delta/theta/alpha/beta/gamma）
- theta/beta 和 alpha/beta ratio

### `upper_machine/eeg_viewer/static/viewer.js`

新增 `updateFocus(focus)` 函数：
- 更新分数、状态（带 CSS 颜色类）
- 渲染原因标签为 pill badges
- 构建频段功率柱状图（归一化到最大值）
- 更新 ratio 读取
- 在 `socket.onmessage` 末尾调用 `updateFocus(frame.focus)`

### `upper_machine/eeg_viewer/static/style.css`

新增样式：
- `.focus-panel` — flex row 暗色背景
- `.focus-score` — 48px 等宽字体
- `.focus-state` — 按状态着色（focused 绿、stable 蓝、relaxed 紫、fatigued 橙、noisy 红）
- `.focus-band-bar` — 频段柱状图，0.4s 过渡动画
- `.focus-reason-tag` — pill badge 样式
- 调整 `.plot-panel` 高度从 `calc(100vh - 470px)` 到 `calc(100vh - 580px)`

### `ear_eeg_sound_lab/tests/test_state_provider.py`

新增 `test_state_schema` 测试，验证 `get_state()` 返回的完整 schema 结构，包含 `recording` 字段。

---

## 三、WebSocket payload 新增字段

```json
{
  "focus": {
    "score": 72,
    "quality": 0.84,
    "state": "focused",
    "reasons": ["beta_present", "low_theta_beta"],
    "bandPowers": {"delta": 12.3, "theta": 8.1, "alpha": 15.2, "beta": 22.4, "gamma": 3.1},
    "thetaBetaRatio": 0.36,
    "alphaBetaRatio": 0.68
  }
}
```

---

## 四、测试状态

- `ear_eeg_sound_lab`：74 tests, 0 failures（main repo）
- `upper_machine`：18 tests OK

---

## 五、当前问题

**三进程联调未跑通：**
1. 终端 1 启动模拟设备 ✅
2. 终端 2 启动 lsl_proxy — 需要用户手动在 PowerShell 运行（bash 环境找不到 `uv`）
3. 终端 3 启动 eeg_viewer — 同上

**联调命令：**
```powershell
# 终端 1
python -m ear_eeg_sound_lab.src.simulated_device --auto-start --eeg-profile focused --mic-mode chirp --stats

# 终端 2
uv run --project upper_machine python -m upper_machine.lsl_proxy.main --host 127.0.0.1 --port 8889 --lsl --start --stats

# 终端 3
uv run --project upper_machine python -m upper_machine.eeg_viewer.main --host 127.0.0.1 --port 8765 --proxy-url http://127.0.0.1:8787

# 浏览器
http://127.0.0.1:8765
```

**预期结果：**
- 模拟设备显示 `frames` 增长、`fps>0`
- lsl_proxy 显示连接成功、帧率统计
- eeg_viewer 显示 EEG/MIC 波形、focus 分数、频段功率
- 浏览器 focus panel 显示实时更新的专注度

---

## 六、Git commits（按时间顺序）

```
b5d8c38 fix(test): add recording field to state schema test
b3e2306 docs: update PROJECT_STATUS.md — focus integration complete
90d653e Merge focus integration into master
1ac46f7 feat(viewer): integrate FocusService into WebSocket payload
4730891 feat(viewer): add focus panel to eeg_viewer frontend
fa0c3e0 feat(viewer): add background focus computation service
```
