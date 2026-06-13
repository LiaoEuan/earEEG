# CLAUDE.md — earEEG

## 项目概述

ESP32 EEG 耳机工程项目，包含固件和上位机。

```
earEEG/
├── earEEG/            # ESP32 固件 (C, PlatformIO)
│   ├── include/       # protocol.h, earEEG_config.h
│   └── src/           # protocol.c, uart_eeg.c
├── upper_machine/     # 上位机 (Python)
│   ├── common/        # 协议解析、EEG 单位转换
│   ├── lsl_proxy/     # TCP 客户端 + LSL 发布 + 控制 API
│   ├── eeg_viewer/    # HTTP/WebSocket 浏览器查看器
│   └── impedance/     # 阻抗计算
├── recordings/        # 实验数据 (.npz)
└── ear_eeg_sound_lab/ # 声音实验
```

## 开发环境速查

```powershell
# 运行上位机（在项目根目录执行）
uv run --project upper_machine python -m upper_machine.lsl_proxy.main --help
uv run --project upper_machine python -m upper_machine.eeg_viewer.main --help

# 运行全部测试
uv run --project upper_machine python -m unittest discover -s upper_machine -p "test_*.py"

# 运行单个测试文件
uv run --project upper_machine python -m unittest upper_machine.test_protocol
```

Python 要求：>=3.14（见 `upper_machine/pyproject.toml`）

## 核心原则（红线）

1. **lsl_proxy 独占 TCP 连接** — 不要让 viewer、调试脚本直接连 ESP32
2. **协议层保持小而稳定** — `common/protocol.py` 不依赖 LSL、HTTP、UI 或 numpy
3. **任何单位/采样率/通道数变化必须全链路同步** — 固件 → protocol.py → LSL → viewer → 阻抗 → NPZ → 测试 → 文档
4. **CRC 必须与固件一致** — `crc16_ibm()` 初值 0xFFFF，表驱动实现
5. **EEG raw 是 big-endian signed 24-bit** — 不能用 little-endian 解析

## 始终生效的 Skills

以下规范在每次会话中自动生效，无需手动调用：

### 代码规范（python-expert）
- 函数签名必须有类型提示
- 使用 dataclass 而非裸 dict
- docstring 用 Google 格式
- 遵循 PEP 8

### 设计原则（karpathy-guidelines）
- 不加没有被要求的功能
- 不为单次使用写抽象
- 改动时只碰必须碰的代码
- 假设要显式说出来，不确定就问

### 调试规则（systematic-debugging）
- **遇到任何 bug、测试失败、异常行为，先找根因再修**
- 禁止跳过根因分析直接修
- 流程：理解问题 → 收集信息 → 形成假设 → 验证假设 → 确认根因 → 修复 → 验证

### 开发规则（test-driven-development）
- **协议/格式/采样率/通道数变更，先写测试再写实现**
- 先看测试失败，再写最少代码让它通过
- 新功能、bug 修复、重构、行为变更都适用

### 验证规则（verification-before-completion）
- **声称"完成"/"修复"/"通过"之前，必须跑验证命令并拿到输出**
- 没跑过测试就不能说通过
- 证据优先于断言

## 自动触发规则

**AI 必须在以下条件满足时自动执行对应 skill，不需要用户手动调用。**

| 条件 | 自动执行 | 做什么 |
|------|---------|--------|
| 开始任何新功能或修改行为 | **brainstorming** | 先理解项目上下文，逐个问澄清问题，提出 2-3 个方案并推荐，获得用户批准后才能动手写代码 |
| 协议/格式/采样率/通道数/帧类型/命令 ID 变更 | **writing-plans** | 自动生成实施计划，列出所有需要同步修改的文件和检查清单，用户确认后执行 |
| 遇到 bug / 测试失败 / 异常行为 | **systematic-debugging** | 进入根因分析流程，禁止直接给修复方案 |
| 实现任何功能或修复 | **test-driven-development** | 先写测试，看它失败，再写实现 |
| 准备声称"完成"或"通过" | **verification-before-completion** | 跑 `uv run --project upper_machine python -m unittest discover` 并展示输出 |
| 用户说"整理"/"同步"/"收尾"/"梳理"/"这个阶段做完了" | **neat-freak** | 审查并同步 CLAUDE.md、DEVELOPMENT_GUIDE.md、README.md、docs/ 与代码一致；删除过期内容；合并重复；检查尺寸膨胀 |
| 完成大功能 / 修改了 3+ 个文件 / 准备合并 | **requesting-code-review** | 派 code-reviewer 子 agent 做安全/性能/正确性审查 |

## 按需调用 Skills（备查）

需要时通过 `/name` 手动调用：

| Skill | 何时用 |
|-------|--------|
| `/project-planner` | 规划 P0-P3 路线图、拆解任务、估算时间 |
| `/frontend-design` | 改 viewer 浏览器 UI 设计 |
| `/simplify` | 重构已有代码、降低复杂度 |
| `/code-reviewer` | 安全审查（如控制 API 鉴权问题） |
| `/neat-freak` | 也可以手动触发文档同步 |

## 协议变更检查清单

修改 TCP 帧/payload/采样率/通道数/命令 ID 时，必须同步修改以下所有位置：

1. 固件 `earEEG/include/protocol.h` + `earEEG/src/protocol.c`
2. 固件 `earEEG/include/earEEG_config.h`（采样率/通道数）
3. 上位机 `upper_machine/common/protocol.py`
4. 测试 payload builder
5. `upper_machine/lsl_proxy/lsl_outlet.py` 的 LSL stream info
6. `upper_machine/eeg_viewer/main.py` 的常量
7. `upper_machine/eeg_viewer/static/viewer.js` 的前端常量
8. `upper_machine/eeg_viewer/recording_service.py` 的采样率和 NPZ 元数据
9. `upper_machine/impedance/core.py` 的默认参数
10. 所有相关测试
11. `upper_machine/DEVELOPMENT_GUIDE.md` 对应章节
12. 用真实设备抓一帧作为 golden frame 加入测试

## 深入文档

详细协议、架构、排查指南见：

- `upper_machine/DEVELOPMENT_GUIDE.md` — 完整交接文档（协议、API、NPZ 格式、排查、路线图）
