"""
系统自检数据模型
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    """检查状态枚举"""
    PENDING = "pending"      # 待检查
    RUNNING = "running"      # 检查中
    SUCCESS = "success"      # 检查成功
    WARNING = "warning"      # 检查警告
    ERROR = "error"          # 检查错误
    SKIPPED = "skipped"      # 跳过检查


class CheckCategory(Enum):
    """检查类别枚举"""
    SOFTWARE_ENVIRONMENT = "software_environment"
    HARDWARE_RESOURCES = "hardware_resources"
    COMMUNICATION = "communication"
    CONFIG = "config"
    INSTRUMENTS = "instruments"
    LOGGING = "logging"


@dataclass
class CheckItem:
    """检查项目"""
    name: str
    category: CheckCategory
    status: CheckStatus = CheckStatus.PENDING
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0  # 检查耗时(秒)
    recommendations: List[str] = field(default_factory=list)
    
    def __str__(self) -> str:
        return f"[{self.status.value.upper()}] {self.name}: {self.message}"


@dataclass
class CheckResult:
    """检查结果"""
    success: bool
    category: CheckCategory
    message: str
    items: List[CheckItem] = field(default_factory=list)
    summary: str = ""
    recommendations: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0  # 总检查耗时(秒)
    details: Dict[str, Any] = field(default_factory=dict)
    
    def add_item(self, item: CheckItem):
        """添加检查项目"""
        self.items.append(item)
    
    def get_success_count(self) -> int:
        """获取成功项目数量"""
        return len([item for item in self.items if item.status == CheckStatus.SUCCESS])
    
    def get_warning_count(self) -> int:
        """获取警告项目数量"""
        return len([item for item in self.items if item.status == CheckStatus.WARNING])
    
    def get_error_count(self) -> int:
        """获取错误项目数量"""
        return len([item for item in self.items if item.status == CheckStatus.ERROR])
    
    def get_total_count(self) -> int:
        """获取总项目数量"""
        return len(self.items)
    
    def get_success_rate(self) -> float:
        """获取成功率"""
        total = self.get_total_count()
        return self.get_success_count() / total if total > 0 else 0.0
    
    def has_errors(self) -> bool:
        """是否有错误"""
        return self.get_error_count() > 0
    
    def has_warnings(self) -> bool:
        """是否有警告"""
        return self.get_warning_count() > 0
    
    def is_healthy(self) -> bool:
        """是否健康（无错误）"""
        return not self.has_errors()


@dataclass
class SystemCheckResult:
    """系统检查结果"""
    overall_status: CheckStatus
    overall_success: bool
    check_results: Dict[CheckCategory, CheckResult] = field(default_factory=dict)
    summary: str = ""
    recommendations: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    total_duration: float = 0.0  # 总检查耗时(秒)
    details: Dict[str, Any] = field(default_factory=dict)
    
    def add_result(self, category: CheckCategory, result: CheckResult):
        """添加检查结果"""
        self.check_results[category] = result
    
    def get_result(self, category: CheckCategory) -> Optional[CheckResult]:
        """获取指定类别的检查结果"""
        return self.check_results.get(category)
    
    def get_total_items(self) -> int:
        """获取总检查项目数"""
        return sum(result.get_total_count() for result in self.check_results.values())
    
    def get_total_success(self) -> int:
        """获取总成功项目数"""
        return sum(result.get_success_count() for result in self.check_results.values())
    
    def get_total_warnings(self) -> int:
        """获取总警告项目数"""
        return sum(result.get_warning_count() for result in self.check_results.values())
    
    def get_total_errors(self) -> int:
        """获取总错误项目数"""
        return sum(result.get_error_count() for result in self.check_results.values())
    
    def get_overall_success_rate(self) -> float:
        """获取总体成功率"""
        total = self.get_total_items()
        return self.get_total_success() / total if total > 0 else 0.0
    
    def has_errors(self) -> bool:
        """是否有错误"""
        return self.get_total_errors() > 0
    
    def has_warnings(self) -> bool:
        """是否有警告"""
        return self.get_total_warnings() > 0
    
    def is_healthy(self) -> bool:
        """系统是否健康"""
        return not self.has_errors()
    
    def get_summary(self) -> Dict[str, Any]:
        """获取检查摘要"""
        return {
            "overall_status": self.overall_status.value,
            "overall_success": self.overall_success,
            "total_items": self.get_total_items(),
            "success_count": self.get_total_success(),
            "warning_count": self.get_total_warnings(),
            "error_count": self.get_total_errors(),
            "success_rate": self.get_overall_success_rate(),
            "is_healthy": self.is_healthy(),
            "has_warnings": self.has_warnings(),
            "total_duration": self.total_duration,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class CheckConfig:
    """检查配置"""
    enabled: bool = True
    timeout: int = 30000  # 总超时时间(毫秒)
    auto_check_on_startup: bool = True
    
    # 软件环境检查配置
    software_environment: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "check_python_version": True,
        "min_python_version": "3.10",
        "check_dependencies": True,
        "critical_dependencies": [
            {"name": "PySide6", "min_version": "6.0.0"},
            {"name": "pyserial", "min_version": "3.5"},
            {"name": "pyvisa", "min_version": "1.11.0"},
            {"name": "pandas", "min_version": "1.5.0"},
            {"name": "matplotlib", "min_version": "3.5.0"},
            {"name": "requests", "min_version": "2.28.0"},
            {"name": "pydantic", "min_version": "1.10.0"},
            {"name": "pyyaml", "min_version": "6.0"}
        ],
        "check_environment_variables": True,
        "required_env_vars": ["PATH", "PYTHONPATH"]
    })
    
    # 硬件资源检查配置
    hardware_resources: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "check_disk_space": True,
        "min_disk_space_gb": 1,
        "check_memory": True,
        "min_total_memory_gb": 4,
        "min_available_memory_mb": 512,
        "max_memory_usage_percent": 90,
        "check_network": True,
        "network_test_timeout": 5000
    })
    
    # 通信接口检查配置
    communication: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "check_serial_ports": True,
        "check_tcp_connections": True,
        "test_timeout": 3000,
        "test_ports": ["COM3", "COM4"],
        "test_tcp_connections": [
            {"host": "192.168.1.100", "port": 5020},
            {"host": "localhost", "port": 8080}
        ]
    })
    
    # 配置文件检查配置
    config: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "check_file_integrity": True,
        "validate_parameters": True,
        "config_files": ["config.yaml", "test_sequence_example.yaml"]
    })
    
    # 仪器连接检查配置
    instruments: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "check_power_supply": True,
        "test_connection": True,
        "test_timeout": 5000,
        "test_commands": ["*IDN?", "*STB?"]
    })
    
    # 日志系统检查配置
    logging: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "check_directory": True,
        "check_permissions": True,
        "log_directories": [
            "D:/Logs/TestTool",
            "D:/Logs/TestTool/Result",
            "D:/Logs/TestTool/System"
        ]
    })
    
    def get_category_config(self, category: CheckCategory) -> Dict[str, Any]:
        """获取指定类别的配置"""
        config_map = {
            CheckCategory.SOFTWARE_ENVIRONMENT: self.software_environment,
            CheckCategory.HARDWARE_RESOURCES: self.hardware_resources,
            CheckCategory.COMMUNICATION: self.communication,
            CheckCategory.CONFIG: self.config,
            CheckCategory.INSTRUMENTS: self.instruments,
            CheckCategory.LOGGING: self.logging
        }
        return config_map.get(category, {})
    
    def is_category_enabled(self, category: CheckCategory) -> bool:
        """检查指定类别是否启用"""
        config = self.get_category_config(category)
        return config.get("enabled", True)
