# 测试Case二次开发指南

## 概述

本指南详细说明如何在生产线测试工具中添加自定义测试case，包括步骤开发、注册、配置和使用。

## 目录结构

```
src/testcases/
├── steps/                    # 测试步骤实现
│   ├── cases/               # 测试用例步骤
│   │   ├── boot_current.py  # 开机电流测试
│   │   └── scan_sn.py       # SN扫描测试
│   ├── common/              # 通用测量步骤
│   │   └── measure_current.py
│   ├── utility/             # 工具步骤
│   │   └── delay.py         # 延时步骤
│   └── ...
├── registry.py              # 步骤注册机制
├── register_steps.py        # 步骤注册入口
├── base.py                  # 步骤基类
├── context.py               # 测试上下文
└── simple_config.py         # 配置模型
```

## 开发步骤

### 步骤1: 创建测试步骤类

#### 1.1 选择步骤类型

根据功能选择步骤类型：
- **cases/**: 完整的测试用例（如开机电流测试）
- **common/**: 通用测量步骤（如电压、电流测量）
- **utility/**: 工具步骤（如延时、条件判断）
- **communication/**: 通信步骤（如串口、TCP通信）
- **instrument/**: 仪器控制步骤（如电源、万用表）

#### 1.2 实现步骤类

创建新的测试步骤文件，例如 `src/testcases/steps/cases/voltage_test.py`：

```python
"""
电压测试用例

完整的电压测试流程：
1. 配置电源
2. 开启输出
3. 测量电压
4. 判断结果
"""
from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any


class VoltageTestStep(BaseStep):
    """电压测试用例"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行电压测试
        
        参数示例：
        - psu_id: 电源ID (默认 "psu1")
        - set_voltage: 设置电压 (默认 3.3V)
        - current_limit: 电流限制 (默认 1.0A)
        - settle_ms: 稳定时间 (默认 500ms)
        - expect_min: 期望最小值 (默认 3.2V)
        - expect_max: 期望最大值 (默认 3.4V)
        - tolerance: 容差百分比 (默认 3%)
        """
        try:
            # 1) 读取参数
            psu_id = params.get("psu_id", "psu1")
            set_voltage = float(params.get("set_voltage", 3.3))
            current_limit = float(params.get("current_limit", 1.0))
            settle_ms = int(params.get("settle_ms", 500))
            expect_min = float(params.get("expect_min", 3.2))
            expect_max = float(params.get("expect_max", 3.4))
            tolerance = float(params.get("tolerance", 3.0))
            
            ctx.log_info(f"开始电压测试: 设置电压={set_voltage}V, 限流={current_limit}A")
            
            # 2) 检查设备可用性
            if not ctx.has_instrument(psu_id):
                return self.create_failure_result(f"电源 {psu_id} 不可用")
            
            psu = ctx.get_instrument(psu_id)
            
            # 3) 配置电源
            ctx.log_info(f"配置电源 {psu_id}: 电压={set_voltage}V, 限流={current_limit}A")
            psu.set_voltage(set_voltage)
            psu.set_current_limit(current_limit)
            psu.set_output(True)  # 开启输出
            
            # 4) 等待电压稳定
            ctx.log_info(f"等待电压稳定 {settle_ms}ms...")
            ctx.sleep_ms(settle_ms)
            
            # 5) 测量电压
            measured_voltage = psu.measure_voltage()
            ctx.log_info(f"测量到电压: {measured_voltage:.3f}V")
            
            # 6) 判断结果
            passed = (expect_min <= measured_voltage <= expect_max)
            
            # 7) 计算容差
            voltage_error = abs(measured_voltage - set_voltage) / set_voltage * 100
            
            # 8) 构建结果数据
            result_data = {
                "voltage": measured_voltage,
                "set_voltage": set_voltage,
                "current_limit": current_limit,
                "expect_min": expect_min,
                "expect_max": expect_max,
                "tolerance": tolerance,
                "voltage_error": voltage_error,
                "psu_id": psu_id,
                "sn": ctx.get_sn()
            }
            
            if passed:
                message = f"电压测试通过: {measured_voltage:.3f}V (期望范围: {expect_min:.3f}V - {expect_max:.3f}V)"
                return self.create_success_result(result_data, message)
            else:
                message = f"电压测试失败: {measured_voltage:.3f}V 超出期望范围 [{expect_min:.3f}V, {expect_max:.3f}V]"
                return self.create_failure_result(message, data=result_data)
                
        except Exception as e:
            ctx.log_error(f"电压测试执行异常: {e}", exc_info=True)
            return self.create_failure_result(f"电压测试执行异常: {e}", error=str(e))
        
        finally:
            # 9) 清理：关闭电源输出
            try:
                if ctx.has_instrument(psu_id):
                    psu = ctx.get_instrument(psu_id)
                    psu.set_output(False)
                    ctx.log_info("已关闭电源输出")
            except Exception as e:
                ctx.log_warning(f"关闭电源输出失败: {e}")
```

#### 1.3 步骤类设计要点

1. **继承BaseStep**: 所有步骤必须继承自`BaseStep`
2. **实现run_once方法**: 核心测试逻辑
3. **参数处理**: 使用`params.get()`获取参数，提供默认值
4. **设备检查**: 使用`ctx.has_instrument()`检查设备可用性
5. **日志记录**: 使用`ctx.log_*()`方法记录日志
6. **结果构建**: 使用`create_success_result()`和`create_failure_result()`
7. **资源清理**: 在`finally`块中清理资源

### 步骤2: 注册测试步骤

#### 2.1 在register_steps.py中注册

编辑 `src/testcases/register_steps.py`：

```python
"""
测试步骤注册

将所有测试步骤注册到全局注册表中。
"""
from .registry import register
from .steps.common.measure_current import MeasureCurrentStep
from .steps.utility.delay import DelayStep
from .steps.cases.boot_current import BootCurrentStep
from .steps.cases.scan_sn import ScanSNStep as ScanSN
# 导入新步骤
from .steps.cases.voltage_test import VoltageTestStep


def register_all_steps():
    """注册所有测试步骤"""
    
    # 注册测试用例
    register(
        step_type="case.boot_current",
        step_class=BootCurrentStep,
        aliases=["boot_current", "开机电流", "boot_current_test"]
    )
    
    # 注册新的电压测试用例
    register(
        step_type="case.voltage_test",
        step_class=VoltageTestStep,
        aliases=["voltage_test", "电压测试", "voltage_measurement"]
    )
    
    # 注册通用步骤
    register(
        step_type="measure.current",
        step_class=MeasureCurrentStep,
        aliases=["current", "measure_current", "measure.i"]
    )
    
    # 注册工具相关步骤
    register(
        step_type="scan.sn",
        step_class=ScanSN,
        aliases=["scan_sn", "scan_serial", "get_sn"]
    )
    
    register(
        step_type="utility.delay",
        step_class=DelayStep,
        aliases=["delay", "wait", "sleep"]
    )


# 自动注册所有步骤
register_all_steps()
```

#### 2.2 使用装饰器注册（可选）

也可以使用装饰器方式注册：

```python
from ...registry import step_type

@step_type("case.voltage_test", aliases=["voltage_test", "电压测试"])
class VoltageTestStep(BaseStep):
    # 步骤实现
    pass
```

### 步骤3: 创建测试序列配置

#### 3.1 YAML配置文件

创建测试序列配置文件，例如 `test_sequences/voltage_test_sequence.yaml`：

```yaml
version: "1.0"
metadata:
  name: "电压测试序列"
  description: "产品电压功能测试"
  author: "TestTool"
  product: "ABC-1000"
  station: "FT-1"
  version: "1.0"

steps:
  - id: "init"
    name: "初始化"
    type: "utility.delay"
    timeout: 5
    retries: 0
    on_failure: "fail"
    params:
      delay_ms: 1000
      message: "系统初始化"

  - id: "voltage_test_3v3"
    name: "3.3V电压测试"
    type: "case.voltage_test"
    timeout: 30
    retries: 1
    on_failure: "fail"
    params:
      psu_id: "psu1"
      set_voltage: 3.3
      current_limit: 1.0
      settle_ms: 500
      expect_min: 3.2
      expect_max: 3.4
      tolerance: 3.0

  - id: "voltage_test_5v"
    name: "5V电压测试"
    type: "case.voltage_test"
    timeout: 30
    retries: 1
    on_failure: "fail"
    params:
      psu_id: "psu1"
      set_voltage: 5.0
      current_limit: 1.0
      settle_ms: 500
      expect_min: 4.9
      expect_max: 5.1
      tolerance: 2.0

  - id: "cleanup"
    name: "清理"
    type: "utility.delay"
    timeout: 5
    retries: 0
    on_failure: "continue"
    params:
      delay_ms: 500
      message: "测试完成清理"
```

#### 3.2 配置参数说明

- **id**: 步骤唯一标识符
- **name**: 步骤显示名称
- **type**: 步骤类型（对应注册的step_type）
- **timeout**: 超时时间（秒）
- **retries**: 重试次数
- **on_failure**: 失败策略
  - `fail`: 失败（默认）
  - `continue`: 继续执行
  - `stop_port`: 停止当前端口
  - `stop_all`: 停止所有端口
- **params**: 步骤业务参数

### 步骤4: 测试和验证

#### 4.1 单元测试

创建测试文件 `tests/test_voltage_test_step.py`：

```python
"""
电压测试步骤单元测试
"""
import pytest
from src.testcases.steps.cases.voltage_test import VoltageTestStep
from src.testcases.context import Context


class MockPSU:
    """模拟电源"""
    def __init__(self):
        self.voltage = 0.0
        self.current_limit = 0.0
        self.output_enabled = False
    
    def set_voltage(self, voltage):
        self.voltage = voltage
    
    def set_current_limit(self, current):
        self.current_limit = current
    
    def set_output(self, enabled):
        self.output_enabled = enabled
    
    def measure_voltage(self):
        return 3.25  # 模拟测量值


@pytest.fixture
def mock_context():
    """创建模拟上下文"""
    ctx = Context(port="TestPort")
    ctx.instruments["psu1"] = MockPSU()
    return ctx


def test_voltage_test_success(mock_context):
    """测试电压测试成功场景"""
    step = VoltageTestStep("test1", "电压测试", {})
    params = {
        "psu_id": "psu1",
        "set_voltage": 3.3,
        "expect_min": 3.2,
        "expect_max": 3.4
    }
    
    result = step.run_once(mock_context, params)
    
    assert result.success is True
    assert result.value["voltage"] == 3.25
    assert "电压测试通过" in result.message


def test_voltage_test_failure(mock_context):
    """测试电压测试失败场景"""
    step = VoltageTestStep("test1", "电压测试", {})
    params = {
        "psu_id": "psu1",
        "set_voltage": 3.3,
        "expect_min": 3.3,
        "expect_max": 3.3
    }
    
    result = step.run_once(mock_context, params)
    
    assert result.success is False
    assert "电压测试失败" in result.message


def test_voltage_test_missing_psu(mock_context):
    """测试电源不存在场景"""
    step = VoltageTestStep("test1", "电压测试", {})
    params = {
        "psu_id": "psu2",  # 不存在的电源
        "set_voltage": 3.3
    }
    
    result = step.run_once(mock_context, params)
    
    assert result.success is False
    assert "不可用" in result.message
```

#### 4.2 集成测试

在工具中加载测试序列进行集成测试：

1. 启动测试工具
2. 加载新创建的测试序列
3. 配置相应的设备（电源等）
4. 执行测试序列
5. 检查测试结果和日志

### 步骤5: 文档和示例

#### 5.1 创建步骤文档

创建 `docs/steps/case.voltage_test.md`：

```markdown
# 电压测试步骤 (case.voltage_test)

## 功能描述

执行产品电压功能测试，包括电源配置、电压测量和结果判断。

## 参数说明

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| psu_id | string | "psu1" | 电源设备ID |
| set_voltage | float | 3.3 | 设置电压值(V) |
| current_limit | float | 1.0 | 电流限制(A) |
| settle_ms | int | 500 | 稳定等待时间(ms) |
| expect_min | float | 3.2 | 期望最小电压(V) |
| expect_max | float | 3.4 | 期望最大电压(V) |
| tolerance | float | 3.0 | 容差百分比(%) |

## 返回值

成功时返回包含以下数据的字典：
- voltage: 测量电压值
- set_voltage: 设置电压值
- voltage_error: 电压误差百分比
- psu_id: 使用的电源ID

## 使用示例

```yaml
- id: "voltage_test"
  name: "电压测试"
  type: "case.voltage_test"
  params:
    psu_id: "psu1"
    set_voltage: 3.3
    expect_min: 3.2
    expect_max: 3.4
```

## 注意事项

1. 确保电源设备已正确配置和连接
2. 根据产品规格设置合适的期望值范围
3. 测试完成后会自动关闭电源输出
```

#### 5.2 创建使用示例

创建 `examples/voltage_test_example.yaml`：

```yaml
# 电压测试序列示例
version: "1.0"
metadata:
  name: "电压测试示例"
  description: "演示电压测试步骤的使用"
  product: "示例产品"

steps:
  - id: "voltage_3v3"
    name: "3.3V电压测试"
    type: "case.voltage_test"
    params:
      set_voltage: 3.3
      expect_min: 3.2
      expect_max: 3.4

  - id: "voltage_5v"
    name: "5V电压测试"
    type: "case.voltage_test"
    params:
      set_voltage: 5.0
      expect_min: 4.9
      expect_max: 5.1
```

## 高级功能

### 1. 条件执行

实现条件判断的步骤：

```python
class ConditionalStep(BaseStep):
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        # 检查条件
        condition = params.get("condition", True)
        if not condition:
            return self.create_skip_result("条件不满足，跳过执行")
        
        # 执行实际逻辑
        # ...
```

### 2. 循环执行

实现循环执行的步骤：

```python
class LoopStep(BaseStep):
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        loop_count = int(params.get("loop_count", 1))
        results = []
        
        for i in range(loop_count):
            # 执行循环逻辑
            result = self.execute_single_loop(ctx, params, i)
            results.append(result)
            
            if not result.success:
                break
        
        return self.create_success_result({"results": results})
```

### 3. 并行执行

实现并行执行的步骤：

```python
import asyncio

class ParallelStep(BaseStep):
    async def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        tasks = params.get("tasks", [])
        
        # 并行执行任务
        results = await asyncio.gather(*[
            self.execute_task(ctx, task) for task in tasks
        ])
        
        return self.create_success_result({"results": results})
```

### 4. 数据验证

实现数据验证的步骤：

```python
class ValidationStep(BaseStep):
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        data = params.get("data")
        validation_rules = params.get("validation_rules", {})
        
        # 执行验证
        validation_result = self.validate_data(data, validation_rules)
        
        if validation_result.is_valid:
            return self.create_success_result(validation_result.data)
        else:
            return self.create_failure_result(validation_result.errors)
```

## 调试和故障排除

### 1. 日志调试

使用上下文日志功能进行调试：

```python
def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
    ctx.log_debug(f"步骤参数: {params}")
    ctx.log_info("开始执行测试")
    
    try:
        # 测试逻辑
        ctx.log_info("测试执行成功")
        return self.create_success_result(data)
    except Exception as e:
        ctx.log_error(f"测试执行失败: {e}", exc_info=True)
        return self.create_failure_result(str(e))
```

### 2. 参数验证

在步骤开始时验证参数：

```python
def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
    # 验证必需参数
    required_params = ["psu_id", "set_voltage"]
    for param in required_params:
        if param not in params:
            return self.create_failure_result(f"缺少必需参数: {param}")
    
    # 验证参数类型和范围
    try:
        voltage = float(params["set_voltage"])
        if voltage <= 0 or voltage > 30:
            return self.create_failure_result("电压值超出有效范围")
    except (ValueError, TypeError):
        return self.create_failure_result("电压值格式错误")
```

### 3. 设备状态检查

检查设备状态和连接：

```python
def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
    psu_id = params.get("psu_id", "psu1")
    
    # 检查设备是否存在
    if not ctx.has_instrument(psu_id):
        return self.create_failure_result(f"设备 {psu_id} 不存在")
    
    psu = ctx.get_instrument(psu_id)
    
    # 检查设备状态
    if not psu.is_connected():
        return self.create_failure_result(f"设备 {psu_id} 未连接")
    
    # 继续执行测试
```

## 最佳实践

### 1. 代码组织

- 将相关步骤放在同一目录下
- 使用清晰的命名约定
- 添加详细的文档字符串
- 保持代码简洁和可读性

### 2. 错误处理

- 使用try-catch处理异常
- 提供有意义的错误信息
- 在finally块中清理资源
- 记录详细的错误日志

### 3. 参数设计

- 提供合理的默认值
- 验证参数类型和范围
- 使用清晰的参数名称
- 提供参数说明文档

### 4. 测试覆盖

- 编写单元测试
- 测试正常和异常场景
- 验证边界条件
- 进行集成测试

### 5. 性能优化

- 避免不必要的延时
- 合理使用资源
- 优化数据处理
- 考虑并发执行

## 总结

通过本指南，您可以：

1. **创建自定义测试步骤**: 继承BaseStep并实现run_once方法
2. **注册步骤**: 在register_steps.py中注册新步骤
3. **配置测试序列**: 使用YAML文件配置测试序列
4. **测试和验证**: 编写单元测试和集成测试
5. **文档和示例**: 提供完整的使用文档和示例

这个框架提供了灵活的扩展机制，支持各种类型的测试需求，是进行二次开发的强大基础。

