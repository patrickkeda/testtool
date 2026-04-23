"""
UUT模块 - 被测单元通信适配

主要组件：
- IUUTAdapter: UUT适配器接口
- UUTAdapter: UUT适配器实现
- IProtocolAdapter: 协议适配器接口
- UUTCommand: UUT命令模型
- UUTResponse: UUT响应模型
- UUTStatus: UUT状态模型
- 协议适配器实现
"""

from .models import UUTCommand, UUTResponse, UUTStatus, UUTError, UUTConfig, UUTTestResult, UUTMeasurement
from .interfaces import IUUTAdapter, IProtocolAdapter
from .adapter import UUTAdapter
from .protocols import ProtocolFactory, SerialProtocolAdapter, TcpProtocolAdapter
from .command_manager import CommandManager
from .status_manager import StatusManager

__all__ = [
    'UUTCommand',
    'UUTResponse', 
    'UUTStatus',
    'UUTError',
    'UUTConfig',
    'UUTTestResult',
    'UUTMeasurement',
    'IUUTAdapter',
    'IProtocolAdapter',
    'UUTAdapter',
    'ProtocolFactory',
    'SerialProtocolAdapter',
    'TcpProtocolAdapter',
    'CommandManager',
    'StatusManager'
]
