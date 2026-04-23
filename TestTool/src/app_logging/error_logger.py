"""
错误日志器 - 记录各模块运行错误和异常信息
"""

import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

from .config import LoggingConfig
from .handlers import ErrorFileHandler
from .formatters import create_formatter


class ErrorLogger:
    """错误日志器"""
    
    def __init__(self, port: str, sn: str = None, config: LoggingConfig = None):
        self.port = port
        self.sn = sn or "NULL"
        self.product = "NULL"  # 产品名称
        self.station = "NULL"  # 测试站
        self.version = "NULL"  # 版本
        self.config = config
        self.logger = None  # 延迟初始化
        self.error_count = 0
    
    def _setup_logger(self) -> logging.Logger:
        """设置错误日志器"""
        if not self.config or not self.config.error_log.enabled:
            return logging.getLogger(f"Error.{self.port}")
        
        logger = logging.getLogger(f"Error.{self.port}")
        logger.setLevel(getattr(logging, self.config.error_log.level))
        
        # 清除现有处理器
        logger.handlers.clear()
        
        # 创建日志文件路径
        log_dir = self.config.get_log_dir("error")
        date_folder = self.config.get_date_folder("error")
        log_path = log_dir / date_folder
        log_path.mkdir(parents=True, exist_ok=True)
        
        # 创建文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.config.error_log.filename.format(
            SN=self.sn or "NULL",
            product=self.product or "NULL",
            station=self.station or "NULL",
            version=self.version or "NULL",
            port=self.port or "NULL",
            timestamp=timestamp
        )
        
        # 创建文件处理器
        handler = ErrorFileHandler(
            str(log_path / filename),
            when=self.config.rotation.when,
            backupCount=self.config.rotation.backup_count
        )
        handler.setFormatter(create_formatter("error", 
            include_stack_trace=self.config.error_log.include_stack_trace
        ))
        
        logger.addHandler(handler)
        return logger
    
    def update_config(self, new_config: LoggingConfig):
        """更新配置"""
        self.config = new_config
        self.logger = self._setup_logger()
    
    def set_product_info(self, product: str, station: str, version: str = None):
        """设置产品名称、测试站和版本信息"""
        self.product = product or "NULL"
        self.station = station or "NULL"
        self.version = version or "NULL"
        # 重新设置logger以使用新的信息
        if self.config:
            self.logger = self._setup_logger()
    
    def log_test_error(self, step_id: str, error: str, details: str = None):
        """记录测试相关错误"""
        self.error_count += 1
        record = logging.LogRecord(
            name=f"Test.{self.port}",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg=error,
            args=(),
            exc_info=None
        )
        record.error_type = "TEST"
        record.sn = self.sn
        record.port = self.port
        record.station = self.config.station_name if self.config else "UNKNOWN"
        record.step_id = step_id
        
        if details:
            record.msg = f"步骤{step_id}执行失败: {error}, 详情: {details}"
        else:
            record.msg = f"步骤{step_id}执行失败: {error}"
        
        self.logger.handle(record)
    
    def log_comm_error(self, module: str, error: str, details: str = None):
        """记录通信模块错误"""
        self.error_count += 1
        record = logging.LogRecord(
            name=f"Comm.{module}",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg=error,
            args=(),
            exc_info=None
        )
        record.error_type = "COMM"
        record.sn = self.sn
        record.port = self.port
        record.station = self.config.station_name if self.config else "UNKNOWN"
        record.module = module
        
        if details:
            record.msg = f"{module}通信失败: {error}, 详情: {details}"
        else:
            record.msg = f"{module}通信失败: {error}"
        
        self.logger.handle(record)
    
    def log_instrument_error(self, instrument: str, error: str, details: str = None):
        """记录仪器模块错误"""
        self.error_count += 1
        record = logging.LogRecord(
            name=f"Instrument.{instrument}",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg=error,
            args=(),
            exc_info=None
        )
        record.error_type = "INSTRUMENT"
        record.sn = self.sn
        record.port = self.port
        record.station = self.config.station_name if self.config else "UNKNOWN"
        record.instrument = instrument
        
        if details:
            record.msg = f"{instrument}操作失败: {error}, 详情: {details}"
        else:
            record.msg = f"{instrument}操作失败: {error}"
        
        self.logger.handle(record)
    
    def log_mes_error(self, operation: str, error: str, details: str = None):
        """记录MES模块错误"""
        self.error_count += 1
        record = logging.LogRecord(
            name="MES",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg=error,
            args=(),
            exc_info=None
        )
        record.error_type = "MES"
        record.sn = self.sn
        record.port = self.port
        record.station = self.config.station_name if self.config else "UNKNOWN"
        record.operation = operation
        
        if details:
            record.msg = f"MES {operation}失败: {error}, 详情: {details}"
        else:
            record.msg = f"MES {operation}失败: {error}"
        
        self.logger.handle(record)
    
    def log_system_error(self, module: str, error: str, details: str = None):
        """记录系统级错误"""
        self.error_count += 1
        record = logging.LogRecord(
            name=f"System.{module}",
            level=logging.CRITICAL,
            pathname="",
            lineno=0,
            msg=error,
            args=(),
            exc_info=None
        )
        record.error_type = "SYSTEM"
        record.sn = self.sn
        record.port = self.port
        record.station = self.config.station_name if self.config else "UNKNOWN"
        record.module = module
        
        if details:
            record.msg = f"系统{module}错误: {error}, 详情: {details}"
        else:
            record.msg = f"系统{module}错误: {error}"
        
        self.logger.handle(record)
    
    def log_exception(self, module: str, exception: Exception, context: str = None):
        """记录异常信息"""
        self.error_count += 1
        record = logging.LogRecord(
            name=f"Exception.{module}",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg=str(exception),
            args=(),
            exc_info=(type(exception), exception, exception.__traceback__)
        )
        record.error_type = "EXCEPTION"
        record.sn = self.sn
        record.port = self.port
        record.station = self.config.station_name if self.config else "UNKNOWN"
        record.module = module
        
        if context:
            record.msg = f"{module}异常: {exception}, 上下文: {context}"
        else:
            record.msg = f"{module}异常: {exception}"
        
        self.logger.handle(record)
    
    def log_retry_error(self, operation: str, attempt: int, max_attempts: int, error: str):
        """记录重试错误"""
        record = logging.LogRecord(
            name=f"Retry.{self.port}",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg=error,
            args=(),
            exc_info=None
        )
        record.error_type = "RETRY"
        record.sn = self.sn
        record.port = self.port
        record.station = self.config.station_name if self.config else "UNKNOWN"
        record.operation = operation
        record.attempt = attempt
        record.max_attempts = max_attempts
        
        record.msg = f"{operation}重试失败 ({attempt}/{max_attempts}): {error}"
        
        self.logger.handle(record)
    
    def log_timeout_error(self, operation: str, timeout: float, error: str = None):
        """记录超时错误"""
        self.error_count += 1
        record = logging.LogRecord(
            name=f"Timeout.{self.port}",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg=error or "操作超时",
            args=(),
            exc_info=None
        )
        record.error_type = "TIMEOUT"
        record.sn = self.sn
        record.port = self.port
        record.station = self.config.station_name if self.config else "UNKNOWN"
        record.operation = operation
        record.timeout = timeout
        
        if error:
            record.msg = f"{operation}超时 ({timeout}s): {error}"
        else:
            record.msg = f"{operation}超时 ({timeout}s)"
        
        self.logger.handle(record)
    
    def get_error_count(self) -> int:
        """获取错误计数"""
        return self.error_count
    
    def reset_error_count(self):
        """重置错误计数"""
        self.error_count = 0
    
    def close(self):
        """关闭日志器"""
        for handler in self.logger.handlers:
            handler.close()
        self.logger.handlers.clear()
