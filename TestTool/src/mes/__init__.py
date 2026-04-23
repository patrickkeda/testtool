"""
MES模块 - 制造执行系统集成

主要组件：
- IMESClient: MES客户端接口
- MESClient: MES客户端基类
- MESAdapter: MES适配器基类
- MESFactory: 适配器工厂
- 各厂商适配器实现
"""

from .models import (
    WorkOrder, TestResult, TestStep, MESConfig, 
    MESResponse, MESError, HeartbeatStatus
)
from .interfaces import IMESClient, IMESAdapter
from .client import MESClient
from .adapters.base import MESAdapter
from .adapters.huaqin_qmes import HuaqinQMESAdapter
from .factory import MESFactory
from .heartbeat import HeartbeatManager

__all__ = [
    'WorkOrder',
    'TestResult', 
    'TestStep',
    'MESConfig',
    'MESResponse',
    'MESError',
    'HeartbeatStatus',
    'IMESClient',
    'IMESAdapter',
    'MESClient',
    'MESAdapter',
    'HuaqinQMESAdapter',
    'MESFactory',
    'HeartbeatManager'
]
