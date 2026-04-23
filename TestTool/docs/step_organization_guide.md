# 测试步骤组织指南

## 概述

测试步骤的组织方式直接影响代码的可维护性和可扩展性。本指南提供了几种组织策略和最佳实践。

## 组织策略

### 1. 按功能分组（推荐）

```
src/testcases/steps/
├── __init__.py
├── measurement/          # 测量相关步骤
│   ├── __init__.py
│   ├── measure_current.py
│   ├── measure_voltage.py
│   └── measure_power.py
├── communication/        # 通信相关步骤
│   ├── __init__.py
│   ├── at_command.py
│   └── uut_communication.py
├── utility/             # 工具步骤
│   ├── __init__.py
│   ├── scan_sn.py
│   ├── delay.py
│   └── manual_judgment.py
└── fixture/             # 治具控制步骤
    ├── __init__.py
    ├── relay_control.py
    └── motor_control.py
```

**优点：**
- 相关功能集中，易于维护
- 便于团队协作（不同开发者负责不同模块）
- 代码复用性好
- 扩展性强

### 2. 单文件多步骤（适合简单步骤）

```python
# src/testcases/steps/measurement.py
from ..base import InstrumentStep, StepResult

class MeasureCurrentStep(InstrumentStep):
    # ...

class MeasureVoltageStep(InstrumentStep):
    # ...

class MeasurePowerStep(InstrumentStep):
    # ...
```

**适用场景：**
- 步骤功能相似且简单
- 团队规模较小
- 步骤数量不多

### 3. 按设备类型分组

```
src/testcases/steps/
├── psu_steps.py          # 电源相关
├── dmm_steps.py          # 万用表相关
├── scope_steps.py        # 示波器相关
└── fixture_steps.py      # 治具相关
```

**适用场景：**
- 设备类型明确且相对独立
- 每个设备类型的步骤较多

## 最佳实践

### 1. 命名规范

- **文件名**: 使用小写字母和下划线，如 `measure_current.py`
- **类名**: 使用大驼峰命名，如 `MeasureCurrentStep`
- **步骤类型**: 使用点分隔的小写字母，如 `measure.current`

### 2. 目录结构

- 每个功能模块都有独立的 `__init__.py`
- 在 `__init__.py` 中导出所有步骤类
- 主 `__init__.py` 导入各模块的步骤类

### 3. 步骤实现

```python
# 示例：测量电流步骤
class MeasureCurrentStep(InstrumentStep):
    """测量电流步骤"""
    
    def execute_instrument(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        # 1) 读取参数
        psu_id = self.get_param_str(params, "psu_id", "psu1")
        set_voltage = self.get_param_float(params, "set_voltage", 5.0)
        
        # 2) 获取设备实例
        psu = ctx.get_instrument(psu_id)
        
        # 3) 执行测试逻辑
        psu.set_voltage(set_voltage)
        current = psu.measure_current()
        
        # 4) 返回结果
        return self.create_success_result({"current": current})
```

### 4. 注册步骤

```python
# 在 register_steps.py 中注册
register(
    step_type="measure.current",
    step_class=MeasureCurrentStep,
    aliases=["current", "measure_current"]
)
```

## 添加新步骤的流程

### 1. 确定步骤类型
- 测量类：继承 `InstrumentStep`
- 通信类：继承 `CommunicationStep`
- 工具类：继承 `UtilityStep`
- 治具类：继承 `FixtureStep`

### 2. 选择组织方式
- 简单步骤：添加到现有文件
- 复杂步骤：创建新文件
- 新功能模块：创建新目录

### 3. 实现步骤类
```python
class NewStep(BaseStep):
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        # 实现具体逻辑
        pass
```

### 4. 注册步骤
```python
register("new.step", NewStep, aliases=["new_step"])
```

### 5. 更新文档
- 在对应模块的 `__init__.py` 中添加导出
- 更新步骤类型文档
- 添加使用示例

## 示例：添加新的测量步骤

### 1. 创建文件
```bash
# 在 measurement 目录下创建新文件
touch src/testcases/steps/measurement/measure_resistance.py
```

### 2. 实现步骤类
```python
# measure_resistance.py
from ..base import InstrumentStep, StepResult
from ..context import Context
from typing import Dict, Any

class MeasureResistanceStep(InstrumentStep):
    def execute_instrument(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        # 实现电阻测量逻辑
        pass
```

### 3. 更新模块导出
```python
# measurement/__init__.py
from .measure_resistance import MeasureResistanceStep

__all__ = [
    'MeasureCurrentStep',
    'MeasureVoltageStep',
    'MeasureResistanceStep',  # 添加新步骤
]
```

### 4. 注册步骤
```python
# register_steps.py
register(
    step_type="measure.resistance",
    step_class=MeasureResistanceStep,
    aliases=["resistance", "measure_resistance"]
)
```

## 总结

- **推荐使用按功能分组**的组织方式
- 每个步骤一个文件，便于维护和扩展
- 遵循命名规范和目录结构
- 及时更新文档和注册信息
- 根据项目规模和团队情况选择合适的组织方式

