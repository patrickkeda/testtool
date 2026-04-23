# VITA Engineer Client 测试用例开发指南

## 概述

本指南介绍如何为VITA Engineer Client添加新的测试用例，以及如何测试和验证功能。

## 测试框架结构

### 核心测试模块

- **test_engineer_client.py** - 命令行测试工具
- **gui_example.py** - GUI测试界面
- **protocol.py** - 测试用例参数定义

### 支持的测试类型

- **TTS测试** - 文本转语音功能
- **激光雷达测试** - 点云数据获取和处理
- **摄像头测试** - 图像采集和处理
- **头部运动测试** - 机器人头部控制
- **耳朵灯测试** - LED灯光控制
- **电池测试** - 电源状态查询

## 添加新测试用例

### 1. 定义测试参数

在 `protocol.py` 中添加新的测试参数类：

```python
@dataclass
class YourTestParams:
    """你的测试参数"""
    param1: str = "default_value"
    param2: int = 100
    param3: bool = True

    def to_dict(self) -> dict:
        return {
            "param1": self.param1,
            "param2": self.param2,
            "param3": self.param3,
        }
```

### 2. 在客户端中添加测试方法

在 `engineer_client.py` 的 `EngineerServiceClient` 类中添加新方法：

```python
async def test_your_function(self, params: YourTestParams) -> Tuple[bool, str]:
    """
    测试你的功能

    Args:
        params: 测试参数

    Returns:
        (success, message): 测试结果和消息
    """
    try:
        # 构造命令
        command = {
            "type": CommandType.YOUR_COMMAND.value,
            "data": params.to_dict()
        }

        # 发送命令并等待响应
        response = await self._send_command(command)

        if response["status"] == ResponseStatus.SUCCESS.value:
            return True, "测试成功"
        else:
            return False, f"测试失败: {response.get('message', '未知错误')}"

    except Exception as e:
        return False, f"测试异常: {str(e)}"
```

### 3. 在命令行工具中添加测试用例

在 `test_engineer_client.py` 的 `test_single_case` 函数中添加新的测试分支：

```python
async def test_single_case(test_case: str, robot_ip: str = "10.100.100.88", port: int = 3579):
    """测试单个用例"""
    client = EngineerServiceClient(host=robot_ip, port=port)

    try:
        # ... 连接和进入工程模式的代码 ...

        # 添加你的测试用例
        elif test_case.lower() == "your_test":
            print("🧪 测试你的功能...")
            params = YourTestParams(
                param1="test_value",
                param2=200,
                param3=False
            )
            success, message = await client.test_your_function(params)

            if success:
                print(f"✅ 测试成功: {message}")
            else:
                print(f"❌ 测试失败: {message}")
                return False
```

### 4. 在GUI中添加测试界面

在 `gui_example.py` 中添加新的测试按钮和处理函数：

```python
def setup_ui(self):
    # ... 现有UI代码 ...

    # 添加你的测试按钮
    your_test_frame = ttk.LabelFrame(self.test_frame, text="你的功能测试", padding="10")
    your_test_frame.grid(row=6, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

    # 参数输入
    ttk.Label(your_test_frame, text="参数1:").grid(row=0, column=0, sticky=tk.W)
    self.your_param1 = tk.StringVar(value="default_value")
    ttk.Entry(your_test_frame, textvariable=self.your_param1, width=30).grid(row=0, column=1, sticky=(tk.W, tk.E))

    # 测试按钮
    ttk.Button(your_test_frame, text="测试你的功能",
              command=lambda: self.run_async_test(self.test_your_function)).grid(row=1, column=0, columnspan=2, pady=5)

async def test_your_function(self):
    """GUI中的测试函数"""
    if not self.is_connected:
        self.log_message("❌ 请先连接机器人")
        return

    try:
        params = YourTestParams(
            param1=self.your_param1.get(),
            param2=int(self.your_param2.get()),
            param3=self.your_param3.get()
        )

        self.log_message("🧪 开始测试你的功能...")
        success, message = await self.client.test_your_function(params)

        if success:
            self.log_message(f"✅ 测试成功: {message}")
        else:
            self.log_message(f"❌ 测试失败: {message}")

    except Exception as e:
        self.log_message(f"❌ 测试异常: {str(e)}")
```

## 测试和验证

### 1. 命令行测试

```bash
# 构建独立包
python3 create_standalone_package.py

# 测试新功能（免安装）
mkdir test-env && cd test-env
tar -xzf ../vita-engineer-client.tar.gz
python3 bin/vita-engineer-test your_test 192.168.1.100

# 测试所有功能
python3 bin/vita-engineer-test all 192.168.1.100
```

### 2. GUI测试

```bash
# 启动GUI
python3 bin/vita-engineer-gui

# 在GUI中：
# 1. 输入机器人IP
# 2. 点击"连接机器人"
# 3. 点击"进入工程模式"
# 4. 测试你的新功能
```

### 3. 单元测试

创建单元测试文件 `test_your_function.py`：

```python
import pytest
import asyncio
from vita_engineer_client import EngineerServiceClient
from vita_engineer_client.protocol import YourTestParams

@pytest.mark.asyncio
async def test_your_function():
    """测试你的功能"""
    client = EngineerServiceClient(host="localhost", port=3579)

    # 模拟测试
    params = YourTestParams(param1="test", param2=100)

    # 这里可以使用mock来模拟服务器响应
    # success, message = await client.test_your_function(params)
    # assert success == True
```

### 4. 集成测试

```bash
# 运行所有测试用例
python3 bin/vita-engineer-test all

# 检查测试结果
echo $?  # 0表示成功，非0表示失败
```

## 最佳实践

### 1. 错误处理

- 总是使用 try-catch 处理异常
- 提供清晰的错误消息
- 记录详细的日志信息

### 2. 参数验证

- 在发送命令前验证参数
- 提供合理的默认值
- 检查参数范围和类型

### 3. 测试数据

- 使用真实的测试数据
- 提供多种测试场景
- 包含边界条件测试

### 4. 文档更新

- 更新命令行帮助信息
- 添加GUI使用说明
- 记录新功能的使用方法

## 调试技巧

### 1. 启用详细日志

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 2. 使用调试模式

```bash
# 设置调试环境变量
export VITA_DEBUG=1
python3 bin/vita-engineer-test your_test
```

### 3. 网络抓包

```bash
# 使用tcpdump监控网络流量
sudo tcpdump -i any port 3579 -A
```

通过遵循这个指南，你可以轻松地为VITA Engineer Client添加新的测试用例，并确保功能的正确性和稳定性。
