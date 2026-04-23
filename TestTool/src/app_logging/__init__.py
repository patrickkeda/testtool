"""
日志模块 - 标准化日志记录、分级存储、按日期组织

主要组件：
- LoggingManager: 统一日志管理器
- TestLogger: 测试结果日志器
- ErrorLogger: 错误日志器
- LoggingConfig: 日志配置模型
"""

from .config import LoggingConfig
from .manager import (
    LoggingManager,
    set_logging_manager,
    get_logging_manager,
    get_test_logger,
    get_error_logger,
    get_system_logger,
)
from .test_logger import TestLogger
from .error_logger import ErrorLogger

__all__ = [
    'LoggingConfig',
    'LoggingManager',
    'TestLogger',
    'ErrorLogger',
    'set_logging_manager',
    'get_logging_manager',
    'get_test_logger',
    'get_error_logger',
    'get_system_logger',
]
