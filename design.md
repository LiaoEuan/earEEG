1. 项目概述

本项目旨在快速开发一款包含脑电采集、高品质音频录制与播放、以及头部姿态监测的头戴式原型设备。系统以高实时性和低底噪为首要目标，核心数据流需保证严格的时间戳对齐，为下游深度学习模型（如 Target Speaker Extraction、脑纹识别）提供高质量的多模态数据集。

2. 硬件架构选型

2.1 核心控制与通信

主控单片机: ESP32-S3 (双核，具备 Wi-Fi 4/蓝牙)

内存配置: N16R8 (16MB Flash / 8MB Octal PSRAM)

说明: 必须启用 PSRAM 以开辟大容量环形缓冲区，应对网络波动，防止数据溢出。⚠️ 当前 sdkconfig 中 `CONFIG_SPIRAM` 已启用（Octal 模式，80 MHz），缓冲区代码优先从 PSRAM 分配，失败回退到 DRAM。

2.2 传感器与前端模块

脑电采集: OpenBCI (Cyton 板或等效定制板)

接口: UART (硬连线)

说明: 采用独立供电系统，物理隔离射频干扰，确保脑电底噪最小化。

音频输出 (播放): PCM5102 (I2S DAC 模块)

采样率: 44.1 kHz，双通道 (立体声)

外设: 直推“水月雨·竹”或同级别有线耳机。注：PCM5102 输出为 line-level（典型 2V RMS），直推 32Ω 耳机音量有限，原型阶段可接受，后续可考虑加耳机放大器。

音频输入 (录音): INMP441 (I2S 数字麦克风模块)

采样率: 16 kHz，单通道。注：INMP441 标准 I2S 模式不需要外部 MCLK（BCLK 作位时钟即可），ESP32-S3 I2S 控制器可在标准模式下无 MCLK 工作。

姿态监测 (IMU): BNO085

接口: I2C

说明: 利用其内置的 Sensor Fusion 引擎直接输出四元数，释放主控算力。

### 2.3 引脚分配

| 信号 | GPIO | Xiao 丝印 | 目标器件 |
|------|------|-----------|---------|
| I2S0 BCLK | GPIO1 | D0 | PCM5102 BCK |
| I2S0 LRCLK | GPIO2 | D1 | PCM5102 LCK |
| I2S0 DIN | GPIO4 | D3 | PCM5102 DIN |
| I2C SDA | GPIO5 | D4 | BNO085 SDA |
| I2C SCL | GPIO6 | D5 | BNO085 SCL |
| UART TX | GPIO43 | D6 | OpenBCI RX |
| UART RX | GPIO44 | D7 | OpenBCI TX |
| I2S1 BCLK | GPIO7 | D8 | INMP441 SCK |
| I2S1 LRCLK | GPIO8 | D9 | INMP441 WS |
| I2S1 DIN | GPIO9 | D10 | INMP441 SD |

说明:
- GPIO3 (D2) 为 JTAG strapping pin，保留不接
- 调试日志通过 USB Serial/JTAG（板载 USB-C 接口）输出，释放 UART0 给 OpenBCI
- I2C 复用 Xiao 默认引脚 (D4/D5)，板载已有上拉电阻
- I2S0 和 I2S1 使用独立的时钟引脚，物理分离，减少干扰

3. 软件架构设计 (基于 FreeRTOS)

采用“双核分离、DMA 搬运、环形缓冲”的设计模式。

3.1 任务调度与核分配

Core 1 (高实时采集核):

I2S0 (TX) DMA 中断: 处理音频下行播放 (PCM5102)。

I2S1 (RX) DMA 中断: 处理音频上行录制 (INMP441)，获取环境声。

UART 接收中断: 从 OpenBCI FIFO 读取字节，切勿在其中做协议解析。

I2C 轮询任务: 定时获取 BNO085 姿态数据 (250Hz，与 EEG 包率对齐)。

核心逻辑: 在所有输入中断发生时，第一时间通过硬件周期计数器（`esp_cpu_get_cycle_count()`）记录时间戳，待退出中断后在 task 上下文中调用 `esp_timer_get_time()` 转为微秒值。切勿在 ISR 中直接调用 `esp_timer_get_time()`（其内部使用 spinlock，可能导致死锁）。

注：EEG 帧率 250Hz → 发包间隔 4ms，16kHz 麦克风每 4ms 正好采样 64 个样本（16k / 250 = 64），可实现每包对齐一帧 EEG + 64 个 PCM 样本 + 最新一组 IMU 数据。

Core 0 (通信与协议核):

负责 Wi-Fi 协议栈维护。

UART 数据解析任务: 从 FreeRTOS 队列接收原始字节，解析 OpenBCI 协议帧，打上硬件时间戳后推入 PSRAM 环形缓冲区。

数据打包与发送任务: 监控 PSRAM 中的各类数据流 Buffer，按照自定义协议格式组包，通过 TCP Socket 发送给上位机（优先 TCP，避免丢包）。

数据接收任务: 接收上位机发来的下行音频流。

### 3.2 环形缓冲区分配 (PSRAM)

| 数据流 | 速率 | 缓冲时长 | 分配大小 |
|--------|------|---------|---------|
| EEG (24ch) | 24ch × 3B × 250Hz = 18 KB/s | 1s | 24 KB |
| Mic (16kHz mono) | 16k × 2B = 32 KB/s | 1s | 64 KB |
| Downlink Audio (44.1kHz stereo) | 44.1k × 2ch × 2B = 176 KB/s | 1s | 256 KB |
| IMU | ~1 KB/s | 1s | 4 KB |
| **总计** | **~227 KB/s** | **1s** | **~348 KB** |

PSRAM 共 8 MB，上述分配仅占 4.3%，留有充足余量。缓冲区分配前须确保已启用 PSRAM（见 2.1 节说明）。

### 3.3 数据流对齐机制

采用统一的硬件定时器作为基准时钟。

发送的数据包必须包含单片机端生成的微秒级相对时间戳和序列号 (Sequence Number)，以便上位机处理微小的物理时钟漂移。

4. 数据协议设计

### 4.1 带宽评估

| 数据流 | 比特率 |
|--------|--------|
| EEG 上行 (24ch × 24bit × 250Hz) | 144 kbps |
| Mic 音频上行 (16kHz × 16bit × 1ch) | 256 kbps |
| Speaker 音频下行 (44.1kHz × 16bit × 2ch) | 1.4 Mbps |
| **总带宽** | **约 2 Mbps** |

2.4G Wi-Fi (TCP) 完全满足无损传输。

### 4.2 通用帧结构 (上下行共用)

```
┌──────┬──────┬──────┬──────────┬───────────────┬──────┐
│ SYNC │ TYPE │ LEN  │ TIMESTAMP│    PAYLOAD    │ CRC16│
│  2B  │  1B  │  2B  │    8B    │   variable    │  2B  │
└──────┴──────┴──────┴──────────┴───────────────┴──────┘
```

| 字段 | 长度 | 说明 |
|------|------|------|
| SYNC | 2B | `0xEE 0x01` — 帧起始标记，双字节降低误判概率 |
| TYPE | 1B | 数据类型枚举 |
| LEN | 2B | Payload 字节数（Big-endian），不含 SYNC/CRC16 |
| TIMESTAMP | 8B | MCU 微秒时间戳，u64 little-endian |
| PAYLOAD | 变长 | 按 TYPE 定义 |
| CRC16 | 2B | CRC-16-IBM (0x8005)，覆盖 SYNC→PAYLOAD 全部字节 |

### 4.3 数据类型枚举

| TYPE | 名称 | 方向 | 说明 |
|------|------|------|------|
| `0x01` | `SENSOR_DATA` | ESP32 → PC | 复合传感器数据（EEG+Mic+IMU） |
| `0x02` | `DOWNLINK_AUDIO` | PC → ESP32 | 下行 44.1kHz 立体声音频 |
| `0x03` | `COMMAND` | PC → ESP32 | 控制指令 |
| `0x04` | `ACK` | ESP32 → PC | 通用确认 |
| `0x05`–`0x7F` | — | — | 预留扩展 |

### 4.4 传感器数据帧 (TYPE=0x01)

每 4ms 一包（与 EEG 帧率 250Hz 对齐），每包包含 1 帧 EEG + 64 个 PCM 样本 + 最新一组 IMU 数据。

```
┌────────┬────────────┬──────────────────┬──────────────────┐
│ SEQ ID │ EEG HEADER │   EEG DATA       │   MIC PAYLOAD    │
│  2B    │   1+1=2B   │   24ch × 3B      │   64smp × 2B     │
├────────┴────────────┴──────────────────┴──────────────────┤
│                     IMU PAYLOAD                           │
│               quat(w,x,y,z)=4×4B + reserved 22B          │
└───────────────────────────────────────────────────────────┘
```

| 子字段 | 长度 | 说明 |
|--------|------|------|
| SEQ ID | 2B | 包序列号 (0–65535 循环)，用于上位机检测丢包 |
| EEG HEADER | 1+1=2B | `[有效通道数] [保留]` |
| EEG DATA | 24ch × 3B = 72B | 24-bit signed，Big-endian（与 OpenBCI 原始格式一致） |
| MIC PAYLOAD | 2B + 128B = 130B | `[样本数=64 (u16)]` + 64 × 16-bit signed little-endian PCM |
| IMU PAYLOAD | 38B | `[四元数 w x y z 各 4B float]` + 22B 保留 |
| **PAYLOAD 总计** | **244B** | |

### 4.5 下行音频帧 (TYPE=0x02)

```
┌──────┬──────────────────┐
│ CHN  │  PCM DATA        │
│  1B  │  N × 4B          │
└──────┴──────────────────┘
```

| 子字段 | 长度 | 说明 |
|--------|------|------|
| CHN | 1B | `0x02` = 立体声 |
| PCM DATA | N × 4B | 交错格式 L/R/L/R，每采样 4B（左2+右2），little-endian |

TIMESTAMP 字段表示"期望播放时间"，ESP32 应在其到达时将音频写入 I2S TX 缓冲区。

### 4.6 指令帧 (TYPE=0x03)

```
┌─────────┬──────────────┐
│ CMD ID  │  CMD DATA    │
│  1B     │  variable    │
└─────────┴──────────────┘
```

| CMD ID | 功能 | DATA | 响应 |
|--------|------|------|------|
| `0x01` | 开始采集 | 无 | ACK (TYPE=0x04) |
| `0x02` | 停止采集 | 无 | ACK |
| `0x03` | 设置 EEG 参数 | `[通道数 1B] [使能位掩码 3B]` | ACK + 确认值 |
| `0x10` | 阻抗控制 | payload 为待透传的 ASCII 字节（如 `z410Z`） | ACK（透传完成） |
| `0x11` | 关闭全部阻抗 | 无 | ACK（ESP32 发送 `z100Zz200Z...z800Z`） |

后续指令可在此表中扩展。

### 4.7 阻抗测量（UART 透传方案）

OpenBCI 阻抗测量协议（官方 SDK §LeadOff Impedance Commands）：

```
命令格式:  z (通道号, P端, N端) Z
示例:      z 4 1 0 Z  → 简写为 "z410Z"
           z = 进入阻抗模式
           4 = 通道号 (1-8 主控, QWERTYUI 对应 Daisy 9-16)
           1 = P 输入端施加 31.5Hz AC 测试信号
           0 = N 输入端不施加测试信号 (默认)
           Z = 锁存到 ADS1299 寄存器
```

**注意**：阻抗测量不产生单独的返回值。它通过正常 EEG 数据流完成——施加测试信号后，通道输出中会叠加 31.5Hz 分量，上位机对 EEG 数据做 FFT 提取该分量幅度，根据当前增益转换为阻抗值（单位 kΩ）。

**下位机改动**：
- CMD=0x10（`REQUEST_IMPEDANCE`）→ ESP32 将 payload 中的 ASCII 字节透传到 OpenBCI UART → 返回 ACK
- CMD=0x11（`STOP_IMPEDANCE`）→ ESP32 向 OpenBCI UART 发送 `z100Zz200Z...z800Z`（全通道关闭阻抗）→ 返回 ACK
- 无需新增 TYPE 帧类型；阻抗期间的 EEG 数据仍用 TYPE=0x01 传输

**上位机阻抗测量流程**：
1. 发 CMD=0x10，payload=`z110Z`（开启 Ch1 阻抗）
2. 正常采集 2-3 秒 EEG 数据（TYPE=0x01）
3. 对 Ch1 做 FFT，提取 31.5Hz 幅值 → 计算阻抗
4. 发 CMD=0x10，payload=`z100Z`（关闭 Ch1）
5. 对 Ch2–Ch8 重复步骤 1-4
6. 发 CMD=0x11 批量关闭所有通道的阻抗测试信号

此方案下位机只需要实现一条"透传 OpenBCI 命令"的指令，阻抗值由上位机从 EEG 数据流中分析得出。

5. 上位机设计

上位机分为两个独立程序，通过 LSL 总线串联（实时采集路径），另有一个离线校准模块亦作为 LSL 下游消费者：

```
┌───────────────────────┐
│  lsl_proxy (唯一TCP入口) │  TCP ←→ ESP32
│  TCP → parse → LSL    │
└──────────┬────────────┘
           │ LSL Outlets (EEG/Audio/IMU)
           ├──────────────►  recorder (Storage)
           │                  LSL Inlet → CSV/WAV
           │
           └──────────────►  calibration (Analysis)
                              LSL Inlet → FFT → 报告

命令通道: lsl_proxy 提供 --cmd 参数进行单次命令透传
  python -m upper_machine.lsl_proxy.main --host IP --cmd "z410Z"
```

> **设计要点**: `lsl_proxy` 是唯一直接与 ESP32 建立 TCP 连接的程序。`recorder` 和 `calibration` 均作为 LSL 下游消费者。校准过程中向 OpenBCI 发送指令（如阻抗控制）通过 `lsl_proxy --cmd` 子进程调用完成，不与 ESP32 建立第二条 TCP 连接。

目录结构：

```
upper_machine/
├── common/
│   └── protocol.py          # 帧解析/CRC校验 (与protocol.h一致)
├── lsl_proxy/               # 唯一 TCP 入口 + LSL 出口
│   ├── main.py              # CLI入口，读取配置，启动TCP连接
│   │                        #   --cmd "..." 单次命令模式
│   │                        #   --lsl        持续流模式
│   ├── tcp_client.py        # TCP连接管理 + 帧接收 / 帧发送
│   └── lsl_outlet.py        # pylsl StreamOutlet 管理
├── recorder/                # LSL 下游：存储落盘
│   ├── main.py              # CLI入口，启动LSL Inlet订阅
│   ├── lsl_inlet.py         # pylsl StreamInlet 订阅
│   └── storage.py           # 文件写入 (EEG/MIC→CSV, Audio→WAV, IMU→CSV)
└── calibration/             # LSL 下游：信号质量分析
    ├── main.py              # CLI入口，引导式校准流程
    │                        #   通过 subprocess 调用 lsl_proxy --cmd 发指令
    ├── impedance.py         # LSL Inlet → FFT@31.5Hz → 阻抗值
    ├── baseline.py          # LSL Inlet → 漂移/偏移分析
    └── report.py            # 校准报告生成
```

### 5.1 LSL Proxy 核心程序

**职责**: 连接下位机 TCP Server → 接收并校验 TYPE=0x01 帧 → 拆包 → 推入 LSL 三条流。

**启动顺序**:
```
read config (.toml 或 CLI 参数)
  → open TCP socket to ESP32 (host:port)
    → send CMD_START_ACQ (TYPE=0x03, CMD=0x01)
      → enter recv loop:
          recv(4096) → frame_parser → crc check
            → TYPE=0x01: depack(SEQ, EEG, MIC, IMU)
              → lsl_outlet.push_sample(EEG, ts=...) @ 250Hz
              → lsl_outlet.push_chunk(MIC, ts=...) @ 16kHz
              → lsl_outlet.push_sample(IMU, ts=...) @ 250Hz
```

**LSL 三条流定义**:

| 流名 | 通道数 | 数据类型 | 标称采样率 | 每次推送 | 时间戳来源 |
|------|--------|---------|-----------|---------|-----------|
| `earEEG_EEG` | 24 | float32 | 250 Hz | 1 样本/次 | ESP32 时间戳 → LSL 映射 |
| `earEEG_Audio` | 1 | float32 | 16000 Hz | 64 样本/次 (chunk) | ESP32 时间戳 + 样本内插值 |
| `earEEG_IMU` | 11 | float32 | 250 Hz | 1 样本/次 | ESP32 时间戳 → LSL 映射 |

**IMU 通道映射**: `[quat_w, quat_x, quat_y, quat_z, gyro_x, gyro_y, gyro_z, accel_x, accel_y, accel_z]`（11 通道，实际推送 11 个 float）。

**时间戳映射方案**:
1. 连接建立后，记录 PC 时间 `T_pc` 和 ESP32 时间 `T_esp`（从第一个 SENSOR_DATA 帧提取）
2. 后续每帧：`LSL_ts = T_pc + (esp_ts - T_esp) / 1e6`
3. 音频 64 个样本在帧内均匀内插：第 k 样本的时间戳 = `LSL_ts + k / 16000`

**可选的第二数据通道 — TCP接收转存原始文件**:

校验正确的 TYPE=0x01 帧原始字节按顺序追加写入原始存储文件 (`.raw`)，用于事后重放或调试。

### 5.2 Recorder 存储程序

**职责**: 从 LSL 订阅三条流 → 分别落盘。

**存储格式选择**:

| 数据 | 推荐格式 | 说明 |
|------|---------|------|
| EEG | CSV | 每行: `timestamp(ISO8601), ch0, ch1, ..., ch23` |
| Audio | WAV | 16kHz 单声道 16-bit PCM，与 MIC 原始信号一致 |
| IMU | CSV | 每行: `timestamp(ISO8601), qw, qx, qy, qz, gx, gy, gz, ax, ay, az` |

CSV 的优势在于通用性（Excel/Pandas/Matlab 开箱即读），缺点是文件体积略大。对于原型阶段完全可接受。长期大批量采集可迁移至 HDF5 或 NPZ。

**文件命名**: `{stream_name}_{session_start_ISO8601}.csv`（或 `.wav`）

**采集控制**:
- 通过 Recorder 的 CLI 参数指定采集时长（`-d 60` = 60 秒后自动停止）
- 或手动 Ctrl+C 结束
- 会话结束后在所有文件末尾写入采集元数据（时长、有效包数、丢包率等）

### 5.3 依赖与环境

运行所需 Python 包：

```
pylsl>=1.16.0     # Lab Streaming Layer
numpy>=1.24       # 数值处理
soundfile>=0.12   # WAV 写入 (可选，Recorder 用)
```

Python 版本 ≥ 3.10。

### 5.4 实现状态

上位机实现状态：

| 模块 | 状态 | 说明 |
|------|------|------|
| `common/protocol.py` | ✅ 已完成 | 帧解析状态机 + CRC16 校验 |
| `lsl_proxy/main.py` | ✅ 已完成 | `--host` / `--lsl` / `--cmd` / `--verbose` / `--stats` |
| `lsl_proxy/tcp_client.py` | ✅ 已完成 | TCP 连接管理 + recv 循环 + 帧回调 |
| `lsl_proxy/lsl_outlet.py` | ✅ 已完成 | 3 条 StreamOutlet (EEG/Audio/IMU) + 时间戳映射 |
| `recorder/main.py` | ✅ 已完成 | `--duration` / `--output` / `--tag` / `--flush-interval` |
| `recorder/lsl_inlet.py` | ✅ 已完成 | 3 条 StreamInlet 订阅 + 缓冲 |
| `recorder/storage.py` | ✅ 已完成 | CSV 写入 / WAV 写入 / 元数据报告 |
| `calibration/` | ⏳ 待实现 | 引导式校准流程：阻抗 / 基线 / 噪声 / 报告 |

6. 实验前校准流程

本流程由上位机 Python 脚本主导，下位机配合转发指令和数据。所有校准步骤的输入输出均经过 TCP 协议层（§4），校准结果写入报告文件与最终采集数据一起存档。

校准程序目录：

```
upper_machine/
├── calibration/
│   ├── main.py              # CLI 入口，按流程引导或单步执行
│   ├── impedance.py         # 阻抗检测：发CMD→ESP32→OpenBCI→报告
│   ├── baseline.py          # 基线漂移分析 (LSL inlet→matplotlib)
│   └── report.py            # 生成校准报告 (txt/csv)
├── lsl_proxy/
├── recorder/
└── common/
```

### 6.1 电极阻抗检查 (OpenBCI)

**目的**: 逐个检查电极与皮肤接触阻抗，确保信号质量。

**原理**: OpenBCI 使用 ADS1299 内置的 Lead-Off 检测功能。向指定通道注入 31.5Hz 交流测试信号（命令 `z{ch}10Z`），该信号通过电极→皮肤的阻抗回路，在 EEG 数据流中呈现为 31.5Hz 分量。阻抗越高 → 该分量幅度越大。

**流程**:
1. 上位机通过 `lsl_proxy --cmd "z{ch}10Z"` 将阻抗使能命令透传至 OpenBCI
2. `lsl_proxy` 持续流模式正在运行，TYPE=0x01 EEG 数据经 LSL 到达 calibration
3. calibration 对目标通道做 FFT@31.5Hz → 提取幅值 → 转换为阻抗值（kΩ）
4. 通过 `lsl_proxy --cmd "z{ch}00Z"` 关闭该通道阻抗测试
5. 对 Ch1–Ch8 重复
6. 通过 `lsl_proxy --cmd "z100Zz200Z...z800Z"` 批量关闭全部阻抗测试

**涉及的下位机改动**:
- `tcp_stream.c` 增加 CMD=0x10 处理：将 payload 透传到 OpenBCI UART → 返回 ACK
- `tcp_stream.c` 增加 CMD=0x11 处理：向 OpenBCI UART 发送全通道关闭阻抗序列 → 返回 ACK
- 无需新增 TYPE 帧类型——阻抗期间的 EEG 数据仍以 TYPE=0x01 传输

### 6.2 基线漂移检测

**目的**: 被试闭眼静息状态下，检测各通道的直流偏移和缓慢漂移。

**流程**:
1. 上位机引导界面提示"请被试闭眼静息 2 分钟"
2. 通过 LSL 录制 2 分钟 EEG 数据（可复用 recorder 或内嵌 inlet）
3. 分析每个通道：
   - 全段均值（直流偏移）
   - 线性趋势拟合（漂移斜率 μV/s）
   - 波动范围（max-min）
4. 任一通道漂移 > 100 μV → 标记为不合格

**处理建议**: 调整电极接触、排查接地与参考电极、增加屏蔽。

### 6.3 通道增益一致性（可选，推荐）

**目的**: 验证所有通道对同一信号的增益是否一致。

**流程**:
1. 将已知正弦波信号（如 10 Hz, 50 μV p-p）接入所有通道
2. 录制 30 秒
3. 计算各通道 10 Hz 频点的幅度
4. 任一通道偏差 > 10% → 标记并记录偏差系数

**说明**: 此步骤在原型阶段可手动完成；若后期定制 PCB 集成了信号发生器，则将此步骤自动化。

### 6.4 环境噪声测量

**目的**: 在无被试条件下测量系统本底噪声。

**流程**:
1. 上位机提示"请移除被试，保持环境安静"
2. 录制 1 分钟数据
3. 对每个通道做 FFT，检查：
   - 50/60 Hz 工频峰（线缆耦合）
   - >100 Hz 持续高频干扰（开关电源、Wi-Fi 谐波）
4. 输出噪声频谱图（matplotlib）

**处理建议**: 开启工频陷波、检查接地、确认电极线未缠绕/远离电源适配器。

### 6.5 校准报告

**目的**: 生成一份可存档的校准报告，与后续实验数据一起保存。

**报告内容**:
```
=== earEEG 校准报告 ===
时间: 2026-05-18 14:30:00
设备: earEEG-esp32 (SN: —)

[阻抗检查]
  Ch0:  3.2 kΩ ✅
  Ch1:  4.1 kΩ ✅
  Ch2: 12.5 kΩ ❌ (>10k)
  ...

[基线漂移]
  Ch0: 均值=2.3μV 漂移=0.05μV/s ✅
  ...

[通道一致性] (若执行)
  偏差最大通道: Ch3 (+7.2%) ✅
  ...

[环境噪声]
  50Hz工频峰: -68dB ✅
  >100Hz干扰: 无异常 ✅
  ...

结论: 3/8 通道阻抗偏高，建议重新调整 Ch2 后重测。
```

报告输出为 `.txt` 纯文本，每项结果附 `✅` / `⚠️` / `❌` 标记。

### 6.6 实验前检查表

每次实验前逐项确认：

- [ ] 阻抗全通道 < 10 kΩ
- [ ] 基线稳定（漂移 < 100 μV）
- [ ] 通道一致性良好（可选）
- [ ] 环境噪声无异常
- [ ] 校准报告已保存至本次实验目录

7. 开发路线与阶段目标

阶段一：敏捷验证 (飞线阶段)

采购所有核心模块，在面包板上完成硬件连接。

编写测试代码，跑通音频回环 (INMP441 → PCM5102) 以及 Wi-Fi 吞吐量测试。

完成基础数据打包和上位机接收测试。

阶段二：多模态集成

接入 OpenBCI 和 BNO085 数据流。

完善 FreeRTOS 任务调度和 PSRAM Buffer 管理。

开发上位机 Python LSL 代理脚本，并在局域网内验证多流同步效果。

阶段三：闭环与优化 (定制 PCB)

在下游模型初步验证可用后，设计高度集成的定制 PCB。

考虑将独立的 PCM5102 和 INMP441 替换为高集成度的音频 Codec 芯片以减小体积。

8. 注意事项与避坑指南

电源底噪: 切勿使用 ESP32 开发板的 3.3V 直接给 OpenBCI 供电，务必保证电源隔离和良好的接地设计。

网络协议: 优先使用 TCP 保证不丢包。避免使用 UDP 广播。

硬件连线: 录音与播放的 I2S 时钟引脚在原型阶段建议物理分离，减少干扰。
