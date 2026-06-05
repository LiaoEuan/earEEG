# earEEG 上位机使用入门指南

> Python PC 端软件 — TCP 数据接收、LSL 实时流、数据存储与校准

---

## 一、软件架构概览

```
upper_machine/
├── common/           # 共享协议（帧解析、CRC 校验）
│   └── protocol.py
├── lsl_proxy/        # 唯一 TCP 入口 → LSL 实时流
│   ├── main.py       # CLI 入口
│   ├── tcp_client.py # TCP 连接管理与帧收发
│   └── lsl_outlet.py # pylsl StreamOutlet 管理
├── recorder/         # LSL 下游：文件存储
│   ├── main.py       # CLI 入口
│   ├── lsl_inlet.py  # LSL 订阅
│   └── storage.py    # CSV / WAV 文件写入
├── calibration/      # LSL 下游：信号质量分析
│   ├── main.py       # 引导式校准流程
│   ├── impedance.py  # 阻抗检测
│   ├── baseline.py   # 基线漂移分析
│   └── report.py     # 校准报告生成
├── main.py           # 简易入口
├── README.md
└── pyproject.toml
```

数据流方向：

```
ESP32 (TCP Server :8888)
     │
     │ TCP 连接（唯一连接点）
     ▼
lsl_proxy (upper_machine/lsl_proxy/)
     │  接收 → 解析 → CRC 校验 → 拆包
     │
     ├──► LSL Stream: earEEG_EEG   (24ch, float32, 250Hz)
     ├──► LSL Stream: earEEG_Audio (1ch,  float32, 16kHz)
     └──► LSL Stream: earEEG_IMU   (11ch, float32, 250Hz)
              │
              ├──► recorder (存储为 CSV / WAV)
              └──► calibration (FFT 分析 / 阻抗检测)
```

**设计要点**：`lsl_proxy` 是唯一直接与 ESP32 建立 TCP 连接的程序。`recorder` 和 `calibration` 都作为 LSL 下游消费者，不需要知道 ESP32 的存在。

---

## 二、环境准备

### 2.1 Python 版本要求

- Python ≥ **3.10**

### 2.2 安装依赖

使用项目提供的虚拟环境（推荐）：

```bash
cd earEEG/upper_machine
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# 或 .venv\Scripts\activate  # Windows

pip install -e .             # 可编辑模式安装
```

或手动安装（根据 pyproject.toml）：

```bash
pip install pylsl numpy
# recorder 还需要：
pip install soundfile
```

### 2.3 项目文件确认

检查以下关键文件存在：
- `upper_machine/lsl_proxy/main.py` — LSL 代理入口
- `upper_machine/lsl_proxy/tcp_client.py` — TCP 客户端
- `upper_machine/lsl_proxy/lsl_outlet.py` — LSL 出口
- `upper_machine/recorder/main.py` — 记录器入口
- `upper_machine/common/protocol.py` — 协议解析

---

## 三、快速上手 — 连接并查看数据

### 3.1 前提条件

1. ESP32 已上电（默认创建 Wi-Fi 热点 `earEEG`）
2. 电脑连接到 ESP32 的 Wi-Fi 热点（SSID: `earEEG`, 密码: `password123`）
3. 上位机虚拟环境已激活

### 3.2 第一步：确定 ESP32 的 IP 地址

ESP32 在 AP（热点）模式下的 IP 固定为 **192.168.4.1**。电脑连接到热点后会自动获得一个 IP（如 192.168.4.2），无需额外查找。

> 如果 ESP32 通过路由器连接（STA 模式），则需从串口输出中查找 IP：`I (xxx) wifi_sta: Got IP: 192.168.x.x`

### 3.3 第二步：运行 LSL Proxy（实时数据预览）

```bash
cd earEEG/upper_machine

# 基本模式：连接设备并等待显式采集控制
# AP 模式下 --host 可省略（默认值 192.168.4.1 即 ESP32 热点 IP）
python -m upper_machine.lsl_proxy.main --lsl

# 调试时如需连接后立刻开始采集，可显式添加 --start
python -m upper_machine.lsl_proxy.main --lsl --start --verbose
```

**输出示例**：
```
[proxy] connecting to 192.168.1.100:8888 ...
[control] listening on http://127.0.0.1:8787
[proxy] acquisition is idle; use the control API or --start
[SENSOR] seq=   1 ts=     1234567 | EEG[ 8ch]  123  456  789 ... | MIC    1234    5678 ... | QUAT w=0.99 x=0.01 y=0.02 z=0.01
[SENSOR] seq=   2 ts=     1234571 | EEG[ 8ch]  124  457  788 ... | MIC    1235    5679 ... | QUAT w=0.99 x=0.01 y=0.02 z=0.01
[SENSOR] seq=   3 ts=     1234575 | EEG[ 8ch]  125  458  787 ... | MIC    1236    5680 ... | QUAT w=0.99 x=0.01 y=0.02 z=0.01
...
```

按 `Ctrl+C` 停止。

### 3.4 第三步（可选）：开启 LSL 实时流 + 录制

**终端 1 — LSL Proxy（数据桥接 + LSL 发布）**：
```bash
python -m upper_machine.lsl_proxy.main --lsl
```

**终端 2 — Recorder（数据存储）**：
```bash
python -m upper_machine.recorder.main --duration 60 --output ./recordings
```
这将录制 60 秒数据，输出文件：
- `earEEG_EEG_2026-05-27T120000.csv` — EEG 数据
- `earEEG_Audio_2026-05-27T120000.wav` — 音频数据
- `earEEG_IMU_2026-05-27T120000.csv` — IMU 数据

**终端 3 — Browser Viewer（可视化与控制）**：
```bash
python -m upper_machine.eeg_viewer.main
```
打开 `http://127.0.0.1:8765` 后，可以在网页中点击 `Start acquisition` / `Stop acquisition` 控制采集。拖入或选择 WAV 文件后，点击 `Play audio` 即可通过 `lsl_proxy` 的唯一 TCP 连接向设备发送下行音频；`Pause audio` / `Resume audio` / `Stop audio` 用于控制播放。

---

## 四、lsl_proxy 详细说明

### 4.1 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `192.168.4.1` | ESP32 的 IP 地址 |
| `--port` | `8888` | TCP 端口号 |
| `--cmd` | (无) | 单次命令模式，发送 ASCII 命令并退出 |
| `--start` | (False) | 连接后显式发送开始采集指令；默认不自动采集 |
| `--verbose` / `-v` | (False) | 打印每一帧传感器数据到终端 |
| `--stats` / `-s` | (False) | 每秒打印统计信息（帧率、丢包率） |
| `--lsl` | (False) | 将数据推送到 LSL 实时流（需 pylsl） |
| `--play` | (无) | 调试用：通过同一 TCP 连接播放指定 WAV 文件 |
| `--control-host` | `127.0.0.1` | 本机控制 API 监听地址 |
| `--control-port` | `8787` | 本机控制 API 端口 |
| `--no-control` | (False) | 禁用本机控制 API |

### 4.2 模式详解

**模式 1：纯终端预览**（默认）
```bash
python -m upper_machine.lsl_proxy.main --host 192.168.1.100
```
连接到 ESP32 并保持唯一 TCP 入口，但默认不开始采集。开始/停止采集由本机控制 API 或网页界面触发；调试时可加 `--start`。

**模式 2：详细终端输出**
```bash
python -m upper_machine.lsl_proxy.main --host 192.168.1.100 --verbose
```
如果采集已由控制 API 或 `--start` 打开，则每帧打印 EEG 前 8 通道、麦克风前 8 个采样、四元数。同时自动检测丢包。

**模式 3：统计模式**
```bash
python -m upper_machine.lsl_proxy.main --host 192.168.1.100 --stats
```
每秒输出帧率和丢包率：
```
[stats] 10s | frames=2500 (250/s) | lost=0 (0.0%)
[stats] 20s | frames=5000 (250/s) | lost=0 (0.0%)
```

**模式 4：LSL 实时流模式**
```bash
python -m upper_machine.lsl_proxy.main --host 192.168.1.100 --lsl
```
将数据发布到三条 LSL 流，供 recorder、calibration 或其他 LSL 消费者使用。LSL 流定义：

| 流名 | 通道数 | 数据类型 | 采样率 | 时间戳 |
|------|--------|---------|--------|--------|
| `earEEG_EEG` | 24 | float32 | 250 Hz | ESP32 时间戳映射到 PC 时间 |
| `earEEG_Audio` | 1 | float32 | 16000 Hz | 帧内 64 个样本均匀内插 |
| `earEEG_IMU` | 11 | float32 | 250 Hz | ESP32 时间戳映射到 PC 时间 |

**模式 5：单次命令模式**
```bash
# 发送开始采集指令
python -m upper_machine.lsl_proxy.main --host 192.168.1.100 --cmd ""

# 发送阻抗控制指令（透传到 OpenBCI）
python -m upper_machine.lsl_proxy.main --host 192.168.1.100 --cmd "z110Z"

# 发送自定义 ASCII 命令
python -m upper_machine.lsl_proxy.main --host 192.168.1.100 --cmd "b"
```

### 4.3 丢包检测

`lsl_proxy` 通过检查 `SEQ ID`（序列号 0-65535 循环）自动检测丢包。输出示例：
```
[stats] 30s | frames=7498 (250/s) | lost=2 (0.03%)
```
丢包率 > 1% 表示 Wi-Fi 信号不稳定。

---

## 五、recorder 详细说明

### 5.1 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--duration` / `-d` | (无，手动 Ctrl+C 停止) | 录制时长（秒） |
| `--output` / `-o` | 当前目录 | 输出文件夹路径 |
| `--tag` / `-t` | (无) | 文件名附加标签（如 `--tag session1`） |
| `--flush-interval` | 60 | 文件刷新间隔（秒） |

### 5.2 存储格式

| 数据类型 | 格式 | 文件名示例 |
|---------|------|-----------|
| EEG | CSV | `earEEG_EEG_2026-05-27T120000.csv` |
| 音频 | WAV (16kHz, 16-bit, mono) | `earEEG_Audio_2026-05-27T120000.wav` |
| IMU | CSV | `earEEG_IMU_2026-05-27T120000.csv` |

**CSV 格式示例**（EEG）：
```csv
timestamp, ch0, ch1, ch2, ..., ch23
2026-05-27T12:00:00.000001, 123, 456, 789, ...
2026-05-27T12:00:00.004001, 124, 457, 788, ...
```

**CSV 格式示例**（IMU）：
```csv
timestamp, qw, qx, qy, qz, gx, gy, gz, ax, ay, az
2026-05-27T12:00:00.000001, 0.99, 0.01, 0.02, 0.01, ...
```

### 5.3 使用示例

```bash
# 录制 30 秒
python -m upper_machine.recorder.main --duration 30

# 指定输出目录
python -m upper_machine.recorder.main --duration 120 --output ./data/session1

# 添加标签
python -m upper_machine.recorder.main --duration 60 --tag experiment_01
```

---

## 六、calibration（校准模块）

### 6.1 模块功能

| 子模块 | 功能 |
|--------|------|
| `impedance.py` | 逐个检测电极-皮肤接触阻抗（31.5Hz 测试信号法） |
| `baseline.py` | 闭眼静息 2 分钟，分析直流偏移和漂移 |
| `report.py` | 生成完整的校准报告（.txt） |

### 6.2 阻抗检测流程

```
1. lsl_proxy --cmd "z{ch}10Z"     → 开启第 ch 通道阻抗测试
2. 从 LSL 流接收 EEG 数据
3. 对目标通道做 FFT → 提取 31.5Hz 幅值 → 换算为阻抗 (kΩ)
4. lsl_proxy --cmd "z{ch}00Z"     → 关闭该通道
5. 对 Ch1–Ch8 重复步骤 1-4
6. lsl_proxy --cmd "z100Zz200Z...z800Z" → 批量关闭全部
```

**阻抗判断标准**：
- ✅ < 10 kΩ：良好
- ⚠️ 10-20 kΩ：可接受
- ❌ > 20 kΩ：需要调整电极

---

## 七、完整使用流程示例

### 场景：首次连接 + 实时数据预览

```bash
# 终端 1：编译并烧录固件
cd earEEG
pio run -d earEEG/earEEG -t upload

# 终端 2：串口监视器（查看 IP 地址）
pio run -d earEEG/earEEG -t monitor
# 等待看到 "Got IP: 192.168.1.100"

# 终端 3：运行 LSL Proxy（实时数据预览）
cd earEEG/upper_machine
python -m upper_machine.lsl_proxy.main --host 192.168.1.100 --lsl --stats

# 终端 4：运行网页 viewer，点击 Start acquisition 开始采集
python -m upper_machine.eeg_viewer.main
```

### 场景：采集并保存数据

```bash
# 终端 1：LSL Proxy（持续运行）
python -m upper_machine.lsl_proxy.main --host 192.168.1.100 --lsl

# 终端 2：网页 viewer，点击 Start acquisition 开始采集
python -m upper_machine.eeg_viewer.main

# 终端 3：Recorder（录制 5 分钟）
python -m upper_machine.recorder.main --duration 300 --output ./my_recording
```

---

## 八、常见问题

**Q: 连接不上 ESP32？**
A: 确认：
1. ESP32 已上电（指示灯亮起）
2. 电脑已连接到 `earEEG` 热点，或与 ESP32 在同一个局域网
3. 防火墙没有阻止 8888 端口
4. 使用正确的 IP 地址（AP 模式下为 192.168.4.1）

**Q: 看到帧数据但 LSL 流没有数据？**
A: 确认已安装 `pylsl`：
```bash
pip install pylsl
```
并确保使用 `--lsl` 参数启动 proxy。

**Q: Recorder 没有录到数据？**
A: 确保 LSL Proxy 正在运行（且使用 `--lsl` 参数），两条流必须同时运行。先启动 Proxy，再启动 Recorder。

**Q: 如何停止采集？**
A: 在 LSL Proxy 终端按 `Ctrl+C`，它会自动发送 `CMD_STOP_ACQ` 指令并断开连接。

**Q: 丢包率很高？**
A: 检查 Wi-Fi 信号强度，尽量让 ESP32 和电脑靠近。TCP 协议会保证最终数据到达，但高延迟会导致缓冲区溢出丢包。

**Q: 单次命令模式有什么用？**
A: 用于发送控制指令而不启动持续数据流。典型用途是阻抗控制：
```bash
python -m upper_machine.lsl_proxy.main --host 192.168.1.100 --cmd "z110Z"
```

**Q: 移动模式下需要指定 `--host` 吗？**
A: 不需要。`lsl_proxy` 的 `--host` 默认值为 `192.168.4.1`，正好匹配 ESP32 在 AP 模式下的 IP。连接电脑到 `earEEG` 热点后直接运行即可：
```bash
python -m upper_machine.lsl_proxy.main --lsl
```
然后运行 `python -m upper_machine.eeg_viewer.main`，在网页中点击 `Start acquisition`。

---

## 九、移动使用 — 全流程示例

此场景适用于无路由器环境：ESP32 作为 Wi-Fi 热点，电脑直接连接。

### 流程步骤

```bash
# 1. ESP32 上电（自动创建热点 earEEG）

# 2. 电脑连接 Wi-Fi "earEEG"（密码: password123）
#    电脑自动获取 IP，例如 192.168.4.2

# 3. 运行 lsl_proxy（无需指定 --host，默认 192.168.4.1 即为 ESP32 热点 IP）
cd earEEG/upper_machine
python -m upper_machine.lsl_proxy.main --lsl

# 4. 运行网页 viewer，点击 Start acquisition 开始采集
python -m upper_machine.eeg_viewer.main
```

### 全程示例（带 LSL 流和录制）

**终端 1 — LSL Proxy：**
```bash
python -m upper_machine.lsl_proxy.main --lsl
```

**终端 2 — Recorder：**
```bash
python -m upper_machine.recorder.main --duration 60 --output ./recordings
```

> **提示**：移动模式下 `--host` 的默认值 `192.168.4.1` 恰好是 ESP32 热点 IP，因此无需指定 `--host`。如果 ESP32 通过路由器连接（STA 模式），则需像第三章示例那样指定 `--host <实际IP>`。
```
