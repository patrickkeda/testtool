"""
测试用例模块 - 测试序列编排与执行、权限控制、模式管理

主要组件：
- TestRunner: 测试执行引擎
- ModeManager: 模式管理器
- TestContext: 测试上下文
- IStep: 测试步骤接口
- 内置测试步骤库
"""

# 导入新架构组件
from .context import Context, create_context
from .base import BaseStep, StepResult
from .registry import create_step, register
from .simple_config import TestSequenceConfig, TestStepConfig, TestMetadata

# 导入旧组件（保持兼容性）
# 暂时注释掉有问题的导入，专注于新架构
# from .config import (
#     ExpectConfig, ATExpectConfig, ATCommandStepConfig,
#     StateControlConfig, MeasurementConfig, StateMeasurementStepConfig,
#     JudgmentConfig, ManualJudgmentStepConfig
# )
# from .mode_manager import ModeManager, TestMode
# from .step import IStep
# from .runner import TestRunner, TestResult
# from .validator import ResultValidator
# from .variables import VariableManager
# from .utils import (
#     load_test_sequence, 
#     save_test_sequence, 
#     create_default_test_sequence,
#     validate_test_sequence,
#     get_step_statistics,
#     export_test_sequence,
#     import_test_sequence
# )

__all__ = [
    # 新架构组件
    'Context',
    'create_context',
    'BaseStep',
    'StepResult',
    'create_step',
    'register',
    'TestSequenceConfig',
    'TestStepConfig',
    'TestMetadata',
    # 旧组件（暂时注释）
    # 'ExpectConfig',
    # 'ATExpectConfig',
    # 'ATCommandStepConfig',
    # 'StateControlConfig',
    # 'MeasurementConfig',
    # 'StateMeasurementStepConfig',
    # 'JudgmentConfig',
    # 'ManualJudgmentStepConfig',
    # 'ModeManager',
    # 'TestMode',
    # 'IStep',
    # 'TestRunner',
    # 'TestResult',
    # 'ResultValidator',
    # 'VariableManager',
    # 'load_test_sequence',
    # 'save_test_sequence',
    # 'create_default_test_sequence',
    # 'validate_test_sequence',
    # 'get_step_statistics',
    # 'export_test_sequence',
    # 'import_test_sequence'
]
