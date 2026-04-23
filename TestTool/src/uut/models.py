"""
UUT数据模型
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, List
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class UUTConnectionStatus(Enum):
    """UUT连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class UUTTestStatus(Enum):
    """UUT测试状态"""
    IDLE = "idle"
    TESTING = "testing"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


class UUTErrorType(Enum):
    """UUT错误类型"""
    CONNECTION_ERROR = "connection_error"
    PROTOCOL_ERROR = "protocol_error"
    TIMEOUT_ERROR = "timeout_error"
    DEVICE_ERROR = "device_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class UUTError:
    """UUT错误信息"""
    type: UUTErrorType
    message: str
    code: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    details: Optional[Dict[str, Any]] = None
    
    def __str__(self) -> str:
        return f"[{self.type.value}] {self.message}"


@dataclass
class UUTCommand:
    """UUT命令"""
    name: str
    command: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout: int = 2000  # 毫秒
    retries: int = 0
    response_format: str = "string"  # string, json, float, int, binary
    expected_response: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """命令初始化后处理"""
        if not self.name:
            raise ValueError("命令名称不能为空")
        if not self.command:
            raise ValueError("命令内容不能为空")


@dataclass
class UUTResponse:
    """UUT响应"""
    success: bool
    data: Any = None
    raw_data: bytes = b""
    error: Optional[UUTError] = None
    timestamp: datetime = field(default_factory=datetime.now)
    command_name: Optional[str] = None
    response_time: float = 0.0  # 响应时间(毫秒)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        if self.success:
            return f"成功: {self.data}"
        else:
            return f"失败: {self.error}"


@dataclass
class UUTStatus:
    """UUT状态"""
    connection_status: UUTConnectionStatus = UUTConnectionStatus.DISCONNECTED
    test_status: UUTTestStatus = UUTTestStatus.IDLE
    last_command: Optional[str] = None
    last_response: Optional[UUTResponse] = None
    error_count: int = 0
    success_count: int = 0
    last_error: Optional[UUTError] = None
    last_activity: Optional[datetime] = None
    uptime: float = 0.0  # 运行时间(秒)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def update_activity(self):
        """更新活动时间"""
        self.last_activity = datetime.now()
    
    def increment_success(self):
        """增加成功计数"""
        self.success_count += 1
        self.update_activity()
    
    def increment_error(self, error: UUTError):
        """增加错误计数"""
        self.error_count += 1
        self.last_error = error
        self.update_activity()
    
    def get_success_rate(self) -> float:
        """获取成功率"""
        total = self.success_count + self.error_count
        return self.success_count / total if total > 0 else 0.0
    
    def is_healthy(self) -> bool:
        """检查UUT是否健康"""
        return (
            self.connection_status == UUTConnectionStatus.CONNECTED and
            self.test_status != UUTTestStatus.ERROR and
            self.error_count < 5  # 错误次数少于5次
        )


@dataclass
class UUTConfig:
    """UUT配置"""
    name: str
    adapter_type: str  # serial, tcp, udp, custom
    protocol: str  # 协议类型
    connection: Dict[str, Any] = field(default_factory=dict)
    commands: List[UUTCommand] = field(default_factory=list)
    retry: Dict[str, int] = field(default_factory=lambda: {"max_attempts": 3, "delay": 1000})
    timeout: Dict[str, int] = field(default_factory=lambda: {"default": 2000, "connect": 5000})
    validation: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_command(self, name: str) -> Optional[UUTCommand]:
        """根据名称获取命令"""
        for cmd in self.commands:
            if cmd.name == name:
                return cmd
        return None
    
    def add_command(self, command: UUTCommand):
        """添加命令"""
        # 检查是否已存在同名命令
        existing = self.get_command(command.name)
        if existing:
            logger.warning(f"命令 {command.name} 已存在，将被覆盖")
            self.commands.remove(existing)
        self.commands.append(command)
    
    def remove_command(self, name: str) -> bool:
        """删除命令"""
        command = self.get_command(name)
        if command:
            self.commands.remove(command)
            return True
        return False


@dataclass
class UUTMeasurement:
    """UUT测量数据"""
    name: str
    value: float
    unit: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    channel: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        return f"{self.name}: {self.value}{self.unit}"


@dataclass
class UUTTestResult:
    """UUT测试结果"""
    test_name: str
    success: bool
    measurements: List[UUTMeasurement] = field(default_factory=list)
    error: Optional[UUTError] = None
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    duration: float = 0.0  # 测试耗时(秒)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """测试结果初始化后处理"""
        if self.end_time is None:
            self.end_time = datetime.now()
        self.duration = (self.end_time - self.start_time).total_seconds()
    
    def add_measurement(self, measurement: UUTMeasurement):
        """添加测量数据"""
        self.measurements.append(measurement)
    
    def get_measurement(self, name: str) -> Optional[UUTMeasurement]:
        """获取指定名称的测量数据"""
        for measurement in self.measurements:
            if measurement.name == name:
                return measurement
        return None
    
    def get_summary(self) -> Dict[str, Any]:
        """获取测试摘要"""
        return {
            "test_name": self.test_name,
            "success": self.success,
            "duration": self.duration,
            "measurement_count": len(self.measurements),
            "error": str(self.error) if self.error else None,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None
        }
