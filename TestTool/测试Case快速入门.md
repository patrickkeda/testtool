# 测试Case快速入门

## 5分钟快速添加测试Case

### 步骤1: 创建测试步骤文件

在 `src/testcases/steps/cases/` 目录下创建新文件，例如 `my_test.py`：

```python
"""
我的自定义测试步骤
"""
from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any


class MyTestStep(BaseStep):
    """我的自定义测试步骤"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """执行测试逻辑"""
        try:
            # 1. 获取参数
            test_value = params.get("test_value", 100)
            expect_min = params.get("expect_min", 90)
            expect_max = params.get("expect_max", 110)
            
            ctx.log_info(f"开始测试，测试值: {test_value}")
            
            # 2. 执行测试逻辑（这里只是示例）
            # 实际测试中，这里会调用设备、发送命令等
            measured_value = test_value + 2  # 模拟测量值
            
            # 3. 判断结果
            passed = expect_min <= measured_value <= expect_max
            
            # 4. 构建结果数据
            result_data = {
                "measured_value": measured_value,
                "test_value": test_value,
                "expect_min": expect_min,
                "expect_max": expect_max
            }
            
            if passed:
                message = f"测试通过: {measured_value} (范围: {expect_min}-{expect_max})"
                return self.create_success_result(result_data, message)
            else:
                message = f"测试失败: {measured_value} 超出范围 [{expect_min}, {expect_max}]"
                return self.create_failure_result(message, data=result_data)
                
        except Exception as e:
            ctx.log_error(f"测试执行异常: {e}")
            return self.create_failure_result(f"测试执行异常: {e}")
```

### 步骤2: 注册测试步骤

编辑 `src/testcases/register_steps.py`，添加注册代码：

```python
# 在文件顶部添加导入
from .steps.cases.my_test import MyTestStep

# 在 register_all_steps() 函数中添加注册
def register_all_steps():
    """注册所有测试步骤"""
    
    # 现有注册...
    
    # 注册新的测试步骤
    register(
        step_type="case.my_test",
        step_class=MyTestStep,
        aliases=["my_test", "我的测试", "custom_test"]
    )
```

### 步骤3: 创建测试序列配置

创建 `test_sequences/my_test_sequence.yaml`：

```yaml
version: "1.0"
metadata:
  name: "我的测试序列"
  description: "自定义测试序列示例"
  product: "示例产品"

steps:
  - id: "my_test_1"
    name: "我的测试1"
    type: "case.my_test"
    timeout: 30
    retries: 1
    on_failure: "fail"
    params:
      test_value: 100
      expect_min: 95
      expect_max: 105

  - id: "my_test_2"
    name: "我的测试2"
    type: "case.my_test"
    timeout: 30
    retries: 1
    on_failure: "fail"
    params:
      test_value: 200
      expect_min: 190
      expect_max: 210
```

### 步骤4: 在工具中使用

1. 启动测试工具
2. 在配置页面配置设备连接
3. 加载测试序列文件
4. 开始测试

## 常用模板

### 模板1: 设备控制测试

```python
class DeviceControlStep(BaseStep):
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        try:
            # 获取设备
            device_id = params.get("device_id", "device1")
            if not ctx.has_instrument(device_id):
                return self.create_failure_result(f"设备 {device_id} 不可用")
            
            device = ctx.get_instrument(device_id)
            
            # 发送命令
            command = params.get("command", "")
            device.send(command.encode())
            ctx.log_info(f"发送命令: {command}")
            
            # 等待响应
            ctx.sleep_ms(params.get("wait_ms", 100))
            
            # 读取响应
            response = device.receive()
            ctx.log_info(f"收到响应: {response}")
            
            # 判断结果
            expected = params.get("expected_response", "")
            passed = expected in response.decode()
            
            result_data = {
                "command": command,
                "response": response.decode(),
                "expected": expected
            }
            
            if passed:
                return self.create_success_result(result_data, "设备控制成功")
            else:
                return self.create_failure_result("设备响应不符合预期", data=result_data)
                
        except Exception as e:
            return self.create_failure_result(f"设备控制失败: {e}")
```

### 模板2: 测量测试

```python
class MeasurementStep(BaseStep):
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        try:
            # 获取测量设备
            meter_id = params.get("meter_id", "dmm1")
            if not ctx.has_instrument(meter_id):
                return self.create_failure_result(f"测量设备 {meter_id} 不可用")
            
            meter = ctx.get_instrument(meter_id)
            
            # 配置测量
            range_val = params.get("range", "AUTO")
            meter.set_range(range_val)
            
            # 执行测量
            measured_value = meter.measure()
            ctx.log_info(f"测量值: {measured_value}")
            
            # 判断结果
            expect_min = float(params.get("expect_min", 0))
            expect_max = float(params.get("expect_max", 999))
            passed = expect_min <= measured_value <= expect_max
            
            result_data = {
                "measured_value": measured_value,
                "expect_min": expect_min,
                "expect_max": expect_max,
                "range": range_val
            }
            
            if passed:
                message = f"测量通过: {measured_value} (范围: {expect_min}-{expect_max})"
                return self.create_success_result(result_data, message)
            else:
                message = f"测量失败: {measured_value} 超出范围 [{expect_min}, {expect_max}]"
                return self.create_failure_result(message, data=result_data)
                
        except Exception as e:
            return self.create_failure_result(f"测量失败: {e}")
```

### 模板3: 延时等待

```python
class WaitStep(BaseStep):
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        try:
            delay_ms = int(params.get("delay_ms", 1000))
            message = params.get("message", f"等待 {delay_ms}ms")
            
            ctx.log_info(f"开始等待: {message}")
            ctx.sleep_ms(delay_ms)
            ctx.log_info("等待完成")
            
            result_data = {
                "delay_ms": delay_ms,
                "message": message
            }
            
            return self.create_success_result(result_data, f"等待完成: {delay_ms}ms")
            
        except Exception as e:
            return self.create_failure_result(f"等待失败: {e}")
```

## 参数说明

### 常用参数类型

| 参数类型 | 示例 | 说明 |
|----------|------|------|
| 字符串 | `"device1"` | 设备ID、命令等 |
| 数字 | `100`, `3.3` | 电压、电流、时间等 |
| 布尔值 | `true`, `false` | 开关状态 |
| 列表 | `[1, 2, 3]` | 多个值 |
| 字典 | `{"key": "value"}` | 复杂配置 |

### 参数获取方法

```python
# 获取参数，提供默认值
device_id = params.get("device_id", "default_device")
voltage = float(params.get("voltage", 3.3))
enabled = bool(params.get("enabled", True))

# 获取必需参数
if "required_param" not in params:
    return self.create_failure_result("缺少必需参数: required_param")
required_value = params["required_param"]
```

## 结果构建

### 成功结果

```python
# 简单成功结果
return self.create_success_result("测试通过")

# 带数据的成功结果
result_data = {
    "measured_value": 3.25,
    "unit": "V",
    "timestamp": time.time()
}
return self.create_success_result(result_data, "电压测量通过")
```

### 失败结果

```python
# 简单失败结果
return self.create_failure_result("测试失败")

# 带数据的失败结果
result_data = {
    "error_code": "E001",
    "error_message": "设备无响应"
}
return self.create_failure_result("设备通信失败", data=result_data)
```

### 跳过结果

```python
# 跳过执行
return self.create_skip_result("条件不满足，跳过测试")
```

## 日志记录

```python
# 不同级别的日志
ctx.log_debug("调试信息")
ctx.log_info("一般信息")
ctx.log_warning("警告信息")
ctx.log_error("错误信息")

# 带异常信息的错误日志
try:
    # 可能出错的代码
    pass
except Exception as e:
    ctx.log_error(f"操作失败: {e}", exc_info=True)
```

## 常见问题

### Q1: 如何检查设备是否可用？

```python
if not ctx.has_instrument("device_id"):
    return self.create_failure_result("设备不可用")

device = ctx.get_instrument("device_id")
```

### Q2: 如何实现延时？

```python
# 延时1000毫秒
ctx.sleep_ms(1000)

# 延时2秒
ctx.sleep_ms(2000)
```

### Q3: 如何获取测试上下文数据？

```python
# 获取SN
sn = ctx.get_sn()

# 设置和获取自定义数据
ctx.set_data("my_key", "my_value")
value = ctx.get_data("my_key", "default_value")
```

### Q4: 如何处理异常？

```python
try:
    # 测试逻辑
    pass
except Exception as e:
    ctx.log_error(f"测试异常: {e}", exc_info=True)
    return self.create_failure_result(f"测试异常: {e}")
```

### Q5: 如何实现重试？

重试机制由测试框架自动处理，在配置中设置：

```yaml
- id: "test_step"
  name: "测试步骤"
  type: "case.my_test"
  retries: 3  # 重试3次
  timeout: 30  # 超时30秒
```

## 下一步

1. 查看现有步骤实现了解更多模式
2. 阅读完整的开发指南了解高级功能
3. 编写单元测试验证步骤功能
4. 创建测试序列配置文件
5. 在工具中测试和调试

通过这个快速入门指南，您可以在几分钟内添加自定义测试case！

