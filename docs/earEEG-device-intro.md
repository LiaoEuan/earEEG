# earEEG 设备使用入门指南

> 基于 ESP32-S3 DevKit (N16R8) 的头戴式 EEG/音频/IMU 数据采集原型设备

---

## 一、硬件连接

### 1.1 模块引脚分配总表

| 信号 | GPIO | 板卡丝印 | 目标器件 | 接口 |
|------|------|-----------|---------|------|
| I2S0 BCLK | GPIO1 | GPIO1 | PCM5102 BCK | I2S TX |
| I2S0 LRCLK | GPIO2 | GPIO2 | PCM5102 LCK | I2S TX |
| I2S0 DIN | GPIO4 | GPIO4 | PCM5102 DIN | I2S TX |
| I2C SDA | GPIO5 | GPIO5 | BNO085 SDA | I2C |
| I2C SCL | GPIO6 | GPIO6 | BNO085 SCL | I2C |
| UART TX | GPIO17 | GPIO17 / U1TXD | OpenBCI RX | UART1 |
| UART RX | GPIO18 | GPIO18 / U1RXD | OpenBCI TX | UART1 |
| I2S1 BCLK | GPIO7 | GPIO7 | INMP441 SCK | I2S RX |
| I2S1 LRCLK | GPIO8 | GPIO8 | INMP441 WS | I2S RX |
| I2S1 DIN | GPIO9 | GPIO9 | INMP441 SD | I2S RX |

> 当前硬件是 ESP32-S3 DevKit，不是 Seeed Xiao。请按照板上标出的 `GPIOx`
> 连接，不要按照 Xiao 的 `Dx` 编号连接。

除上表中的信号线外，还必须连接以下辅助引脚：

| 模块 | 必接辅助连线 | 说明 |
|------|-------------|------|
| PCM5102 | GND → GND；VIN → 模块支持的电源 | 常见模块支持 3.3V 或 5V，接线前确认模块丝印 |
| INMP441 | GND → GND；VDD → 3.3V；L/R → GND | 固件读取左声道，因此 `L/R` 必须接 GND |
| BNO085 | GND → GND；VIN → 3.3V | 确认模块侧已有 I2C 上拉电阻 |
| OpenBCI | TX → GPIO18；RX → GPIO17；GND → GND | UART 信号必须交叉连接 |

OpenBCI 可以独立供电，但直接使用 UART 连接时仍然必须与 ESP32 共地。
如果需要真正的电气隔离，应增加数字隔离器，不能只断开 GND。

### 1.2 接线注意事项

- **GPIO3 不接** — 这是 strapping pin，保留悬空
- **PCM5102 音频输出** — Line-level (典型 2V RMS)，可直接推 32Ω 耳机，原型阶段音量有限
- **INMP441 麦克风** — 标准 I2S 模式（不需要外部 MCLK）
- **BNO085 IMU** — I2C 地址 0x4A；确认模块侧已有上拉电阻
- **OpenBCI 脑电板** — 建议独立供电以降低干扰；直接 UART 连接时仍需共地

### 1.3 通过 USB-C 连接电脑（推荐调试方式）

当前 DevKit 的板载 UART0 调试桥使用 GPIO43/44。这是推荐的日志连接方式，与 OpenBCI 使用的 UART1 GPIO17/18 互不冲突。

接线步骤：
1. 用 USB-C 线将 DevKit 的 UART 调试接口连接到电脑
2. 电脑上会出现一个新的串口设备（Windows 上为 COM 端口，Linux 上为 `/dev/ttyACM0` 或类似）
3. 运行串口监视器即可看到调试输出

### 1.4 通过外部 CH340（或类似 USB-UART 转换器）连接

如果希望使用外部 UART 转换器：

| CH340 / USB-UART | ESP32-S3 DevKit |
|-----------------|-------------|
| TX | GPIO44 (RX) — 注意：TX→RX 交叉 |
| RX | GPIO43 (TX) — 注意：RX→TX 交叉 |
| GND | GND |
| （VCC 可选） | 3.3V |

**注意**：GPIO43/44 保留给 UART0 调试桥。OpenBCI 必须连接 GPIO17/18。

---

## 二、Wi-Fi 热点连接 (AP 模式)

### 2.1 默认 Wi-Fi 凭据

| 参数 | 默认值 |
|------|--------|
| SSID | `earEEG` |
| 密码 | `password123` |

固件以 **AP（热点）** 模式创建 Wi-Fi 网络。默认凭据硬编码在 `earEEG/src/wifi_ap.c` 中：

```c
#define AP_SSID     "earEEG"
#define AP_PASSWORD "password123"
```

### 2.2 修改固件中的 Wi-Fi 配置

编辑 `earEEG/src/wifi_ap.c`，修改第 18-29 行的默认宏定义：

```c
#define AP_SSID     "earEEG"       // 改为你的热点名称
#define AP_PASSWORD "password123"  // 改为你的热点密码
```

你也可以通过 `earEEG_config.h` 中预先定义 `AP_SSID` / `AP_PASSWORD` 等宏来覆盖默认值。修改后重新编译烧录。

### 2.3 Wi-Fi 连接状态反馈（串口输出）

固件通过 `ESP_LOGI` 输出 AP 状态信息。串口监视器上可以看到：

```
I (xxx) wifi_ap: Starting AP "earEEG" on channel 1...  ← 热点启动
I (xxx) wifi_ap: AP started. IP: 192.168.4.1            ← 热点就绪
I (xxx) wifi_ap: station XX:XX:XX:XX:XX:XX connected    ← 客户端（电脑/手机）已连接
```

主循环（来自 `main.c`）也会输出：
```
I (xxx) main: AP ready at 192.168.4.1
```

### 2.4 Wi-Fi 连接行为

- **即开即用**：热点启动无阻塞，ESP32 上电后立即创建 Wi-Fi 网络
- **固定 IP**：ESP32 的 IP 为 **192.168.4.1**，客户端由 DHCP 分配 192.168.4.x 地址
- **独立网络**：无需路由器、无需互联网连接
- **初始化顺序**：AP 热点启动 → Core 1 I/O 任务启动 → TCP 服务器等待客户端

---

## 三、串口调试输出 (UART)

### 3.1 关键参数

| 参数 | 值 |
|------|-----|
| 波特率 | **115200** |
| 数据位 | 8 |
| 校验位 | 无 (None) |
| 停止位 | 1 |
| 流控 | 无 |

### 3.2 启动串口监视器

使用 PlatformIO：
```bash
pio run -d earEEG/earEEG -t monitor
# monitor_speed = 115200 已在 platformio.ini 中配置
```

使用 `idf.py`：
```bash
idf.py -p /dev/ttyACM0 monitor -b 115200
```

### 3.3 输出内容说明

**启动阶段输出**：
```
I (xxx) main: ========== earEEG firmware starting ==========
I (xxx) main: allocating ring buffers...
I (xxx) main: ring buffers: eeg=24576 mic=65536 dnl=262144 imu=4096 bytes
I (xxx) main: initializing peripherals...
I (xxx) wifi_ap: Starting AP "earEEG" on channel 1...
I (xxx) wifi_ap: AP started. IP: 192.168.4.1
I (xxx) main: AP ready at 192.168.4.1
I (xxx) tcp: listening on port 8888
I (xxx) tcp: client connected from 192.168.1.50:54321
I (xxx) main: system running. waiting for commands...
```

**运行阶段周期输出**（每 5 秒）：
```
I (xxx) main: ringbuf: eeg=1234 mic=5678 dnl=0 | acq=on connected=yes
```
- `eeg=xxx`：EEG 环形缓冲区的可用字节数
- `mic=xxx`：麦克风环形缓冲区的可用字节数
- `dnl=xxx`：下行音频缓冲区的可用字节数
- `acq=on/off`：数据采集是否开启
- `connected=yes/no`：上位机 TCP 客户端是否已连接

**TCP 命令处理输出**：
```
I (xxx) tcp: CMD 0x01       ← 收到开始采集指令
I (xxx) tcp: CMD 0x10       ← 收到阻抗控制指令
I (xxx) tcp: client disconnected  ← 客户端断开
```

---

## 四、TCP 服务器与数据传输

### 4.1 服务器参数

| 参数 | 值 |
|------|-----|
| 监听端口 | **8888** |
| 最大客户端数 | 1（单客户端） |
| 连接方式 | TCP（保证不丢包） |
| 初始化行为 | 阻塞等待客户端连接 |

### 4.2 数据帧协议格式

```
┌──────┬──────┬──────┬──────────┬───────────────┬──────┐
│ SYNC │ TYPE │ LEN  │ TIMESTAMP│    PAYLOAD    │ CRC16│
│  2B  │  1B  │  2B  │    8B    │   variable    │  2B  │
└──────┴──────┴──────┴──────────┴───────────────┴──────┘
```

- **SYNC**：`0xEE 0x01` — 帧起始标记
- **TYPE**：数据类型（见下表）
- **LEN**：Payload 长度（大端序）
- **TIMESTAMP**：ESP32 微秒时间戳（小端序 u64）
- **CRC16**：CRC-16-IBM (poly 0x8005, init 0xFFFF, 无最终 XOR)

### 4.3 数据类型枚举

| TYPE | 名称 | 方向 | 说明 |
|------|------|------|------|
| `0x01` | `SENSOR_DATA` | ESP32 → PC | 复合传感器数据（EEG + 麦克风 + IMU） |
| `0x02` | `DOWNLINK_AUDIO` | PC → ESP32 | 下行 44.1kHz 立体声音频 |
| `0x03` | `COMMAND` | PC → ESP32 | 控制指令 |
| `0x04` | `ACK` | ESP32 → PC | 通用确认 |

---

## 五、固件烧录与编译

### 5.1 常用命令

```bash
# 编译
pio run -d earEEG/earEEG

# 烧录
pio run -d earEEG/earEEG -t upload

# 串口监视器
pio run -d earEEG/earEEG -t monitor

# 配置 menuconfig
pio run -d earEEG/earEEG -t menuconfig

# 清理
pio run -d earEEG/earEEG -t clean

# 运行测试
pio test -d earEEG/earEEG
```

### 5.2 编译环境

- **平台**：PlatformIO + ESP-IDF 6.0 框架（非 Arduino）
- **开发板**：ESP32-S3 DevKit N16R8；`seeed_xiao_esp32s3` 暂作为 PlatformIO 兼容占位符
- **内存**：N16R8（16MB Flash / 8MB Octal PSRAM）
- **PSRAM**：已启用（Octal 模式，80 MHz）

---

## 六、初始化流程（设备上电后）

```
1. 创建 PSRAM 环形缓冲区
2. 初始化外设 (I2S 音频、UART EEG、I2C IMU)
3. 初始化 Wi-Fi AP（创建热点，即开即用，无超时等待）
4. 启动 Core 1 I/O 任务（I2S 收发、IMU 轮询）
5. 启动 TCP 服务器（阻塞等待客户端连接）
6. 启动数据打包发送任务
7. 发送 OpenBCI 开始采集指令
8. 进入主循环：每 5 秒输出状态信息
```

任何一个步骤失败，`app_main` 会立即返回（固件停止运行）。

---

## 七、常见问题

**Q: 串口监视器看不到输出？**
A: 优先连接 DevKit 的 UART 调试 USB-C 接口。固件日志走 UART0 GPIO43/44；OpenBCI 走 UART1 GPIO17/18。

**Q: Wi-Fi 热点创建失败？**
A: ESP32 默认 SSID 为 "earEEG"，密码 "password123"。如果信道干扰严重，可以通过修改 `wifi_ap.c` 中的 `AP_CHANNEL` 更换信道。

**Q: 如何查看 ESP32 的 IP 地址？**
A: AP 模式下 ESP32 的固定 IP 为 **192.168.4.1**。串口输出中会显示 `AP started. IP: 192.168.4.1`。客户端（电脑/手机）连接后将分配到 192.168.4.x 地址。

**Q: 波特率为什么是 115200？**
A: 这是 ESP-IDF 的默认控制台波特率，由 `CONFIG_ESP_CONSOLE_UART_BAUDRATE=115200` 和 `CONFIG_ESPTOOLPY_MONITOR_BAUD=115200` 共同配置。

---

## 八、移动使用场景

1. 给 ESP32 上电（电池供电或 USB 充电宝）
2. 等待约 2 秒，ESP32 创建 Wi-Fi 热点 "earEEG"
3. 电脑打开 Wi-Fi 列表 → 连接到 "earEEG"（密码 "password123"）
4. 打开终端运行：`python -m upper_machine.lsl_proxy.main --verbose`
   > lsl_proxy 的默认 `--host` 已经是 192.168.4.1，无需额外指定
5. EEG / 麦克风 / IMU 数据通过直连 Wi-Fi 传输到电脑
6. 采集完成后按 Ctrl+C 停止

无需路由器、无需互联网、完全可移动。
