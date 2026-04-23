"""
系统自检模块 - 启动时资源检查与系统健康监控

主要组件：
- SystemChecker: 系统自检管理器
- CheckResult: 检查结果模型
- CheckStatus: 检查状态枚举
- 各种检查器实现
"""

from .models import CheckResult, CheckStatus, SystemCheckResult, CheckItem, CheckConfig
from .interfaces import ISystemChecker, IResourceChecker
from .manager import SystemChecker, SystemCheckRunner
from .checkers import (
    SoftwareEnvironmentChecker,
    HardwareResourceChecker,
    CommunicationChecker,
    ConfigChecker
)
from .checkers_ext import (
    InstrumentChecker,
    LoggingChecker
)
from .simple_api import (
    check_system_startup,
    check_config_completed,
    check_test_ready,
    is_system_ready,
    is_config_ready,
    is_test_ready,
    get_system_status,
    get_stage_result,
    reset_stage,
    reset_all_stages,
    SimpleCheckAPI,
    check_api
)
from .check_stages import CheckStage, SystemCheckState, global_check_state

__all__ = [
    'CheckResult',
    'CheckStatus',
    'SystemCheckResult',
    'CheckItem',
    'CheckConfig',
    'ISystemChecker',
    'IResourceChecker',
    'SystemChecker',
    'SystemCheckRunner',
    'SoftwareEnvironmentChecker',
    'HardwareResourceChecker',
    'CommunicationChecker',
    'ConfigChecker',
    'InstrumentChecker',
    'LoggingChecker',
    'check_system_startup',
    'check_config_completed',
    'check_test_ready',
    'is_system_ready',
    'is_config_ready',
    'is_test_ready',
    'get_system_status',
    'get_stage_result',
    'reset_stage',
    'reset_all_stages',
    'SimpleCheckAPI',
    'check_api',
    'CheckStage',
    'SystemCheckState',
    'global_check_state'
]
