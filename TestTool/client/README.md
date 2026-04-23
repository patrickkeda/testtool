# VITA Engineer Service Client

VITA机器人工程服务客户端，提供完整的机器人测试和调试功能。

## 项目概述

### 核心功能

- **工程模式连接** - 安全连接到机器人工程服务
- **多功能测试** - 支持TTS、激光雷达、摄像头、头部运动、灯光、电池等测试
- **实时数据处理** - 点云数据处理和可视化
- **加密通信** - 基于RSA+AES的安全通信协议
- **跨平台支持** - Windows、Linux、macOS全平台兼容

### 核心组件

- **EngineerServiceClient** - 主要客户端类，处理与机器人的通信
- **ProtocolHelper** - 协议处理器，定义通信协议和数据结构
- **CryptoUtils** - 加密工具，提供安全的数据传输
- **PointCloudProcessor** - 点云数据处理器，处理激光雷达数据

### 测试框架

- **命令行测试工具** - `vita-engineer-test` 支持各种测试用例
- **GUI测试界面** - `vita-engineer-gui` 提供图形化测试界面
- **自动化测试** - 支持批量测试和结果验证

## 快速开始

### 安装

```bash
# 进入项目目录
cd src/application/engineer_service/client

# 运行安装脚本
python3 install.py
```

### 使用

```bash
# 命令行测试
python3 bin/vita-engineer-test tts 10.100.100.96
python3 bin/vita-engineer-test all 10.100.100.96

# GUI界面
python3 bin/vita-engineer-gui

# 直接运行（开发模式）
python3 vita_engineer_client/test_engineer_client.py tts 10.100.100.96
python3 vita_engineer_client/gui_example.py
```

## 使用方式

### 1. 标准安装

```bash
# 进入项目目录
cd src/application/engineer_service/client

# 安装依赖和创建启动脚本
python3 install.py

# 运行程序
python3 bin/vita-engineer-test tts 10.100.100.96
python3 bin/vita-engineer-gui
```

### 2. 开发模式

```bash
# 方式1: 使用模块方式运行
cd src/application/engineer_service/client
python3 -m vita_engineer_client.test_engineer_client tts 10.100.100.96
python3 -m vita_engineer_client.gui_example

# 方式2: 直接运行脚本（推荐）
cd src/application/engineer_service/client/vita_engineer_client
python3 test_engineer_client.py tts 10.100.100.96
python3 gui_example.py
```

### 3. 作为Python库

```python
from vita_engineer_client import EngineerServiceClient

# 创建客户端
client = EngineerServiceClient(host="robot-ip", port=3579)

# 异步操作
await client.connect()
await client.enter_engineer_mode()
success, result = await client.test_tts("Hello World")
```

## 系统要求

- Python >= 3.8
- 支持平台：Windows、Linux、macOS
- 网络连接（安装依赖时需要）

## 依赖管理

install.py脚本会自动安装以下依赖：

- `cryptography>=3.4.8` - 加密通信
- `websockets>=10.0` - WebSocket连接
- `numpy>=1.21.0` - 数值计算
- `matplotlib>=3.5.0` - 数据可视化
- `pytest>=6.0` - 测试框架
- `pytest-asyncio>=0.18.0` - 异步测试
- `black>=22.0` - 代码格式化
- `flake8>=4.0` - 代码检查

## 故障排除

### 依赖安装失败

```bash
# 升级pip
python3 -m pip install --upgrade pip

# 手动安装依赖
python3 -m pip install --user cryptography websockets numpy matplotlib

# 使用虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows
python3 install.py
```

### Windows用户

```cmd
# 安装
python.exe install.py

# 运行（推荐使用.bat文件）
bin\vita-engineer-test.bat tts 10.100.100.96
bin\vita-engineer-gui.bat

# 或直接使用Python
python.exe bin\vita-engineer-test tts 10.100.100.96
python.exe bin\vita-engineer-gui

# 使用完整路径
C:\Python310\python.exe install.py
C:\Python310\python.exe bin\vita-engineer-test tts 10.100.100.96

# 检查Python版本
python.exe --version
```

### 编码问题解决

如果在Windows上遇到编码错误（如 `SyntaxError: Non-UTF-8 code`），install.py已经自动处理：

- ✅ 启动脚本包含UTF-8编码声明
- ✅ 自动创建Windows .bat批处理文件
- ✅ 使用UTF-8编码保存所有脚本文件

### GUI问题修复

GUI界面已修复多个关键问题：

**异步事件循环问题：**
- ✅ 修复了 `got Future attached to a different loop` 错误
- ✅ 保持事件循环引用，避免多次创建
- ✅ 正确的异步命令执行机制

**参数传递问题：**
- ✅ 修复了头部运动测试参数错误（`Action not found: 0.100000`）
- ✅ 修复了所有测试用例的参数格式
- ✅ 使用正确的命名参数调用

**默认配置：**
- ✅ 默认IP和端口已更新为 192.168.126.2:3579
- ✅ 所有测试用例使用正确的默认参数

### 权限问题

```bash
# 使用用户安装
python3 -m pip install --user [package]

# 或使用虚拟环境
python3 -m venv venv
source venv/bin/activate
python3 install.py
```

## 测试用例

支持的测试用例：

- `tts` - TTS语音合成测试
- `lidar` - 激光雷达测试
- `camera` - 摄像头测试
- `head` - 头部运动测试
- `light` - 灯光测试
- `battery` - 电池状态测试
- `all` - 运行所有测试

## 开发指南

详细的开发指南请参考 `USER_GUIDE.md`。

## 许可证

本项目遵循公司内部许可证。
- websockets >= 10.0 - WebSocket连接
- numpy >= 1.21.0 - 数据处理
- matplotlib >= 3.5.0 - 数据可视化

**注意：** 所有平台的wheel文件已预下载在deps目录中，首次运行时会自动安装。
