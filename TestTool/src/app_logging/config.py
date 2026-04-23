"""
日志配置模型
"""

from pydantic import BaseModel, Field
from typing import Optional
from pathlib import Path
import os


class RotationConfig(BaseModel):
    """日志轮转配置"""
    when: str = Field(default="midnight", description="轮转时间：midnight, hour, size")
    backup_count: int = Field(default=14, description="保留文件数量")
    max_file_size: int = Field(default=100 * 1024 * 1024, description="最大文件大小(字节)")


class TestLogConfig(BaseModel):
    """测试结果日志配置"""
    enabled: bool = Field(default=True, description="是否启用")
    base_dir: str = Field(default="Result/TestResult", description="基础目录")
    date_format: str = Field(default="%Y%m%d", description="日期文件夹格式")
    filename: str = Field(default="{SN}-{station}-{port}-{timestamp}-{result}.log", description="文件名格式")
    level: str = Field(default="INFO", description="日志级别")
    include_config: bool = Field(default=True, description="是否包含配置信息")
    include_measurements: bool = Field(default=True, description="是否包含测量数据")


class ErrorLogConfig(BaseModel):
    """错误日志配置"""
    enabled: bool = Field(default=True, description="是否启用")
    base_dir: str = Field(default="Result/ErrorLog", description="基础目录")
    date_format: str = Field(default="%Y%m%d", description="日期文件夹格式")
    filename: str = Field(default="{SN}-{station}-{port}-{timestamp}.log", description="文件名格式")
    level: str = Field(default="ERROR", description="日志级别")
    include_stack_trace: bool = Field(default=True, description="是否包含堆栈跟踪")


class SystemLogConfig(BaseModel):
    """系统日志配置"""
    enabled: bool = Field(default=True, description="是否启用")
    base_dir: str = Field(default="System", description="基础目录")
    date_format: str = Field(default="%Y%m%d", description="日期文件夹格式")
    config_filename: str = Field(default="CONFIG-{station}-{timestamp}.log", description="配置日志文件名")
    system_filename: str = Field(default="SYSTEM-{station}-{timestamp}.log", description="系统日志文件名")
    level: str = Field(default="INFO", description="日志级别")


class LoggingConfig(BaseModel):
    """日志模块配置"""
    level: str = Field(default="INFO", description="全局日志级别")
    base_dir: str = Field(default="D:/Logs/TestTool", description="日志根目录")
    station_name: str = Field(default="FT-1", description="测试站名称")
    
    # 各类型日志配置
    test_log: TestLogConfig = Field(default_factory=TestLogConfig)
    error_log: ErrorLogConfig = Field(default_factory=ErrorLogConfig)
    system_log: SystemLogConfig = Field(default_factory=SystemLogConfig)
    
    # 轮转配置
    rotation: RotationConfig = Field(default_factory=RotationConfig)
    
    def get_log_dir(self, log_type: str) -> Path:
        """获取指定类型日志的目录路径"""
        base_path = Path(self.base_dir)

        def _resolve(child: str) -> Path:
            child_path = Path(child)
            # 绝对路径则直接使用
            if child_path.is_absolute():
                return child_path
            # 若子路径以顶层目录 Result 开头，则视为工程根目录下的相对路径
            parts = child_path.parts
            if parts and parts[0].lower() == "result":
                return child_path
            # 避免 base_dir 与子路径重复拼接，如 base_dir=Result, child=Result/Log
            child_str = str(child_path).lstrip("./\\")
            base_str = str(base_path).rstrip("/\\")
            if child_str.lower().startswith(base_str.lower() + os.sep) or child_str.lower().startswith(base_str.lower() + "/"):
                return Path(child_str)
            return base_path / child_path

        if log_type == "test":
            return _resolve(self.test_log.base_dir)
        elif log_type == "error":
            return _resolve(self.error_log.base_dir)
        elif log_type == "system":
            return _resolve(self.system_log.base_dir)
        else:
            return base_path
    
    def get_date_folder(self, log_type: str) -> str:
        """获取日期文件夹名称"""
        from datetime import datetime
        return datetime.now().strftime(self.test_log.date_format)
