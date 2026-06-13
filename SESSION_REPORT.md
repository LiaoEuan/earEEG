# 会话报告：UI 重做 + 电极配置 + 启动脚本

**时间：** 2026-06-14
**基线：** 828f2f0 (docs: add recent changes summary)
**最新：** ffae635 (Merge branch 'worktree-realtime-engine-v1')

---

## 一、变更总览

从 `828f2f0` 到 `ffae635`，共 10 个 commits，改动 6 个实际文件：

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `upper_machine/eeg_viewer/static/index.html` | 重写 | 从顶部工具栏改为左画布+右控制栏仪器布局 |
| `upper_machine/eeg_viewer/static/style.css` | 重写 | 仪器风格暗色主题 |
| `upper_machine/eeg_viewer/static/viewer.js` | 重写 | 5Hz 渲染、电极弹窗、阻抗弹窗、显示/滤波控制、配置导入 |
| `upper_machine/eeg_viewer/electrode_config.json` | 新建 | 16 通道电极模板配置 |
| `upper_machine/eeg_viewer/static/electrode_config.json` | 新建 | 同上（static 目录副本，供前端加载） |
| `upper_machine/eeg_viewer/main.py` | 小改 | 新增 `.json` MIME 类型支持 |
| `start_all.ps1` | 新建 | 一键启动 3 进程脚本 |
| `restart_viewer.ps1` | 新建 | 只重启 viewer 脚本 |

---

## 二、UI 重写详情

### 旧布局（改前）

```
┌─────────────────────────────────────────────┐
│ earEEG Viewer    [LSL] [Device] [FPS]       │  ← header
├─────────────────────────────────────────────┤
│ Window | Amplitude | Unit | Range | Start   │  ← toolbar
├─────────────────────────────────────────────┤
│ ▶ Controls: audio, recording, impedance     │  ← 折叠面板
├─────────────────────────────────────────────┤
│ Focus: 72 focused Q:84% δθαβγ θ/β α/β     │  ← focus panel
├─────────────────────────────────────────────┤
│                                             │
│            EEG Canvas                       │
│                                             │
├─────────────────────────────────────────────┤
│ MIC Canvas                                  │
└─────────────────────────────────────────────┘
```

### 新布局（改后）

```
┌───────────────────────────────────────────────────────────┐
│ earEEG Acquisition                 [LSL] [Device] [FPS]   │  ← 极简顶栏
├────────────────────────────────┬──────────────────────────┤
│                                │ Device                   │
│                                │  Connect / Disconnect    │
│  EEG Signal                    │  LSL: connected          │
│  [ 16 通道大画布 ]             │                          │
│  100uV/Div - 5s/page           │ Channels                 │
│                                │  Electrodes: Setup       │
│  Audio / MIC                   │  Impedance: View         │
│  [ 音频波形 ]                  │                          │
│                                │ Filter Setup             │
│  Focus                         │  HighPass / LowPass      │
│  [分数] [状态] [频段] [ratio]  │  Notch                   │
│                                │                          │
├────────────────────────────────┤ Display Setup             │
│                                │  TimeScale / VertScale   │
│                                │  Channels                │
│                                │                          │
│                                │ Record / Playback        │
│                                │  录制 / 音频 / MIC       │
│                                │                          │
│                                │ Trigger                  │
│                                │  [Configure]             │
└────────────────────────────────┴──────────────────────────┘
```

### 关键改进

| 项目 | 旧 | 新 |
|------|-----|-----|
| 布局 | 顶部工具栏堆叠 | 左画布+右控制栏 |
| 画布刷新 | 60fps requestAnimationFrame | 5Hz throttle (200ms) |
| 控件组织 | 散在顶部+折叠面板 | 右侧 6 个可折叠面板 |
| 电极选择 | 无 | 弹窗 + JSON 配置导入 |
| 阻抗 | 嵌在折叠面板 | 独立弹窗 |
| 滤波器 | 无 | HighPass/LowPass/Notch 下拉 |
| 显示控制 | Window/Amplitude/Unit | TimeScale/VertScale/Channels |
| 缩放信息 | 无 | 画布上显示 uV/Div 和 time/page |

---

## 三、电极配置详情

### 配置文件

`upper_machine/eeg_viewer/static/electrode_config.json`：

```json
{
  "name": "earEEG 16ch",
  "channels": [
    {"id": 1, "name": "Fp1", "position": "left", "type": "eeg", "enabled": true, "focus": true},
    {"id": 2, "name": "Fp2", "position": "right", "type": "eeg", "enabled": true, "focus": true},
    {"id": 3, "name": "F3", "position": "left", "type": "eeg", "enabled": true, "focus": true},
    {"id": 4, "name": "F4", "position": "right", "type": "eeg", "enabled": true, "focus": true},
    {"id": 5, "name": "C3", "position": "left", "type": "eeg", "enabled": true, "focus": true},
    {"id": 6, "name": "C4", "position": "right", "type": "eeg", "enabled": true, "focus": true},
    {"id": 7, "name": "P3", "position": "left", "type": "eeg", "enabled": true, "focus": true},
    {"id": 8, "name": "P4", "position": "right", "type": "eeg", "enabled": true, "focus": true},
    {"id": 9, "name": "O1", "position": "left", "type": "eeg", "enabled": true, "focus": true},
    {"id": 10, "name": "O2", "position": "right", "type": "eeg", "enabled": true, "focus": true},
    {"id": 11, "name": "T3", "position": "left", "type": "eeg", "enabled": true, "focus": true},
    {"id": 12, "name": "T4", "position": "right", "type": "eeg", "enabled": true, "focus": true},
    {"id": 13, "name": "A1", "position": "left", "type": "ref", "enabled": false, "focus": false},
    {"id": 14, "name": "A2", "position": "right", "type": "ref", "enabled": false, "focus": false},
    {"id": 15, "name": "GND", "position": "center", "type": "ground", "enabled": false, "focus": false},
    {"id": 16, "name": "EXT", "position": "center", "type": "ext", "enabled": false, "focus": false}
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 通道编号 (1-16) |
| `name` | string | 通道名称（显示在弹窗和画布上） |
| `position` | string | 位置：left/right/center |
| `type` | string | 类型：eeg/ref/ground/ext |
| `enabled` | bool | 是否默认启用（显示波形） |
| `focus` | bool | 是否参与 focus 计算 |

### 加载逻辑

1. viewer 启动时 `fetch("/electrode_config.json")` 自动加载
2. 加载成功 → 应用 `enabled` 到电极选择，弹窗显示通道名称
3. 加载失败 → 使用默认 CH01-CH16，全部启用
4. 弹窗中点击 "Import Config" → 选择 JSON 文件手动导入

---

## 四、启动脚本详情

### start_all.ps1

一键启动 3 个进程（模拟设备 + lsl_proxy + viewer），每个在独立窗口中运行。按任意键停止全部。

```powershell
.\start_all.ps1
```

内部流程：
1. `Start-Process python -m ear_eeg_sound_lab.src.simulated_device --auto-start --eeg-profile focused --mic-mode chirp`
2. `Start-Process python -m upper_machine.lsl_proxy.main --host 127.0.0.1 --port 8889 --lsl --start --stats`
3. `Start-Process python -m upper_machine.eeg_viewer.main --host 127.0.0.1 --port 8765 --proxy-url http://127.0.0.1:8787`

### restart_viewer.ps1

只重启 viewer，模拟设备和 lsl_proxy 保持运行。

```powershell
.\restart_viewer.ps1
```

内部流程：
1. 查找并杀掉 `upper_machine.eeg_viewer.main` 进程
2. 启动新 viewer 进程
3. 提示刷新浏览器

---

## 五、已修复的问题

| # | 问题 | 修复 |
|---|------|------|
| 1 | electrode_config.json 放错目录 | 移到 `static/` 目录 |
| 2 | start_all.ps1 中文编码报错 | 改用英文文本 |
| 3 | .json 文件 MIME 类型错误 | main.py 新增 `application/json` |

---

## 六、当前测试状态

- `ear_eeg_sound_lab`：74 tests, 0 failures
- `upper_machine`：18 tests OK

---

## 七、待做事项

### 已确认的下一步

| 事项 | 说明 | 优先级 |
|------|------|--------|
| Trigger 功能 | 键盘按键映射状态，画布上显示竖线标记 | 高 |
| 电极配置增强 | 改进选中通道的显示效果 | 中 |

### 后续弹窗规划（按顺序）

1. 电极配置弹窗 ✅ 已完成
2. 阻抗测量弹窗 ✅ 已完成
3. Focus Detail 弹窗 — 点击 focus 条弹出详情
4. Music Library 弹窗 — 歌曲库、推荐、反馈
5. Adaptive Switching 弹窗 — 自适应切歌规则
6. Session Review 弹窗 — 回放、报告、LLM 生成

---

## 八、Git Commits

```
ffae635 Merge branch 'worktree-realtime-engine-v1'
ecbfb19 feat(viewer): add import config button to electrode modal
da7ca22 fix: move electrode_config.json to static directory
78007fd Merge branch 'worktree-realtime-engine-v1'
115bcd2 fix: use ASCII text in startup scripts to avoid encoding issues
17c2508 Merge branch 'worktree-realtime-engine-v1'
668be51 chore: add one-click startup and viewer restart scripts
7612625 Merge branch 'worktree-realtime-engine-v1'
b16255a feat(viewer): add electrode config JSON template with auto-load
ae85cd5 Merge branch 'worktree-realtime-engine-v1'
975324d Rewrite eeg_viewer frontend as medical instrument console
```

---

## 九、使用方式

```powershell
# 一键启动
cd E:\yuan_space\10_projects\earEEG
.\start_all.ps1

# 浏览器打开
http://127.0.0.1:8765

# 只重启 viewer
.\restart_viewer.ps1
```
