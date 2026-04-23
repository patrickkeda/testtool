"""
MES模块数据模型
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class MESStatus(Enum):
    """MES状态枚举"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    AUTHENTICATING = "authenticating"
    ERROR = "error"


class TestResultStatus(Enum):
    """测试结果状态枚举"""
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    ERROR = "ERROR"


class WorkOrderStatus(Enum):
    """工单状态枚举"""
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    HOLD = "HOLD"


@dataclass
class TestStep:
    """测试步骤结果"""
    step_id: str
    step_name: str
    expected_value: Optional[float] = None
    actual_value: Optional[float] = None
    unit: Optional[str] = None
    min_limit: Optional[float] = None
    max_limit: Optional[float] = None
    result: TestResultStatus = TestResultStatus.PASS
    duration_ms: int = 0
    retry_count: int = 0
    error_message: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        return f"TestStep(id={self.step_id}, name={self.step_name}, result={self.result.value})"


@dataclass
class TestResult:
    """测试结果"""
    sn: str
    station_id: str
    port: str
    work_order: str
    product_number: str
    test_steps: List[TestStep] = field(default_factory=list)
    overall_result: TestResultStatus = TestResultStatus.PASS
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    total_duration_ms: int = 0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """初始化后处理"""
        if self.ended_at is None:
            self.ended_at = datetime.now()
        
        if self.total_duration_ms == 0:
            self.total_duration_ms = int((self.ended_at - self.started_at).total_seconds() * 1000)
    
    def add_step(self, step: TestStep):
        """添加测试步骤"""
        self.test_steps.append(step)
        
        # 更新整体结果
        if step.result == TestResultStatus.FAIL:
            self.overall_result = TestResultStatus.FAIL
        elif step.result == TestResultStatus.ERROR and self.overall_result != TestResultStatus.FAIL:
            self.overall_result = TestResultStatus.ERROR
        elif step.result == TestResultStatus.SKIP and self.overall_result == TestResultStatus.PASS:
            self.overall_result = TestResultStatus.SKIP
    
    def get_summary(self) -> Dict[str, Any]:
        """获取测试结果摘要"""
        total_steps = len(self.test_steps)
        passed_steps = len([s for s in self.test_steps if s.result == TestResultStatus.PASS])
        failed_steps = len([s for s in self.test_steps if s.result == TestResultStatus.FAIL])
        skipped_steps = len([s for s in self.test_steps if s.result == TestResultStatus.SKIP])
        error_steps = len([s for s in self.test_steps if s.result == TestResultStatus.ERROR])
        
        return {
            "sn": self.sn,
            "station_id": self.station_id,
            "port": self.port,
            "work_order": self.work_order,
            "product_number": self.product_number,
            "overall_result": self.overall_result.value,
            "total_steps": total_steps,
            "passed_steps": passed_steps,
            "failed_steps": failed_steps,
            "skipped_steps": skipped_steps,
            "error_steps": error_steps,
            "pass_rate": passed_steps / total_steps if total_steps > 0 else 0.0,
            "total_duration_ms": self.total_duration_ms,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None
        }
    
    def __str__(self) -> str:
        return f"TestResult(sn={self.sn}, result={self.overall_result.value}, steps={len(self.test_steps)})"


@dataclass
class WorkOrder:
    """工单信息"""
    work_order: str
    product_number: str
    revision: str
    batch: str
    quantity: int
    station_id: str
    status: WorkOrderStatus = WorkOrderStatus.ACTIVE
    parameters: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    description: Optional[str] = None
    
    def __post_init__(self):
        """初始化后处理"""
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
    
    def update_parameters(self, new_parameters: Dict[str, Any]):
        """更新参数"""
        self.parameters.update(new_parameters)
        self.updated_at = datetime.now()
    
    def get_parameter(self, key: str, default: Any = None) -> Any:
        """获取参数值"""
        return self.parameters.get(key, default)
    
    def __str__(self) -> str:
        return f"WorkOrder(wo={self.work_order}, pn={self.product_number}, qty={self.quantity})"


@dataclass
class MESConfig:
    """MES配置"""
    vendor: str
    base_url: str
    timeout_ms: int = 3000
    retries: int = 3
    retry_backoff_ms: int = 200
    heartbeat_interval_ms: int = 10000
    credentials: Dict[str, str] = field(default_factory=dict)
    endpoints: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    station_id: str = ""
    enabled: bool = True
    
    def get_endpoint(self, name: str) -> str:
        """获取端点URL"""
        endpoint = self.endpoints.get(name, "")
        if endpoint.startswith("/"):
            return f"{self.base_url.rstrip('/')}{endpoint}"
        elif endpoint.startswith("http"):
            return endpoint
        else:
            return f"{self.base_url.rstrip('/')}/{endpoint}"
    
    def get_header(self, name: str, default: str = "") -> str:
        """获取请求头"""
        return self.headers.get(name, default)
    
    def __str__(self) -> str:
        return f"MESConfig(vendor={self.vendor}, url={self.base_url}, enabled={self.enabled})"


@dataclass
class MESResponse:
    """MES响应"""
    success: bool
    status_code: int
    data: Any = None
    message: str = ""
    error_code: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    request_id: Optional[str] = None
    
    def is_success(self) -> bool:
        """判断是否成功"""
        return self.success and 200 <= self.status_code < 300
    
    def __str__(self) -> str:
        return f"MESResponse(success={self.success}, status={self.status_code}, message={self.message})"


@dataclass
class MESError(Exception):
    """MES错误"""
    message: str
    error_code: Optional[str] = None
    status_code: Optional[int] = None
    response_data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __str__(self) -> str:
        return f"MESError(code={self.error_code}, message={self.message})"


@dataclass
class HeartbeatStatus:
    """心跳状态"""
    is_alive: bool
    last_heartbeat: Optional[datetime] = None
    response_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    consecutive_failures: int = 0
    
    def __str__(self) -> str:
        return f"HeartbeatStatus(alive={self.is_alive}, failures={self.consecutive_failures})"


@dataclass
class MESConnectionInfo:
    """MES连接信息"""
    vendor: str
    base_url: str
    status: MESStatus = MESStatus.DISCONNECTED
    last_connected: Optional[datetime] = None
    last_error: Optional[str] = None
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
    
    def record_request(self, success: bool):
        """记录请求"""
        self.total_requests += 1
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
    
    def __str__(self) -> str:
        return f"MESConnectionInfo(vendor={self.vendor}, status={self.status.value}, success_rate={self.success_rate:.2%})"
