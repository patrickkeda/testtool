"""
日志管理器 - 统一管理所有日志器
"""

import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any
from threading import Lock

from .config import LoggingConfig
from .handlers import TestResultFileHandler, ErrorFileHandler, SystemFileHandler, QtSignalHandler
from .formatters import create_formatter


class LoggingManager:
    """统一日志管理器"""
    
    def __init__(self, config: LoggingConfig):
        self.config = config
        self.test_loggers: Dict[str, 'TestLogger'] = {}
        self.error_loggers: Dict[str, 'ErrorLogger'] = {}
        self.system_logger: Optional[logging.Logger] = None
        self.qt_handler: Optional[QtSignalHandler] = None
        self._lock = Lock()
        
        # 初始化系统日志器
        self._setup_system_logger()
    
    def update_config(self, new_config):
        """更新日志配置（接受应用侧或日志侧配置，统一转换为日志侧配置）"""
        with self._lock:
            # 标准化为日志侧配置模型
            if not isinstance(new_config, LoggingConfig):
                from .config import (
                    LoggingConfig as LC,
                    RotationConfig as LR,
                    TestLogConfig as LT,
                    ErrorLogConfig as LE,
                    SystemLogConfig as LS,
                )
                try:
                    rotation = LR(**new_config.rotation.model_dump())
                except Exception:
                    rotation = LR(**getattr(new_config, "rotation").__dict__)
                try:
                    test_log = LT(**new_config.test_log.model_dump())
                except Exception:
                    test_log = LT(**getattr(new_config, "test_log").__dict__)
                try:
                    error_log = LE(**new_config.error_log.model_dump())
                except Exception:
                    error_log = LE(**getattr(new_config, "error_log").__dict__)
                try:
                    system_log = LS(**new_config.system_log.model_dump())
                except Exception:
                    system_log = LS(**getattr(new_config, "system_log").__dict__)

                converted = LC(
                    level=new_config.level,
                    base_dir=new_config.dir,
                    station_name=new_config.station_name,
                    rotation=rotation,
                    test_log=test_log,
                    error_log=error_log,
                    system_log=system_log,
                )
                # 统一强制文件名模板，包含产品与版本并使用下划线
                try:
                    converted.test_log.filename = '{SN}_{product}_{station}_{version}_{port}_{timestamp}_{result}.log'
                except Exception:
                    pass
                try:
                    converted.error_log.filename = '{SN}_{product}_{station}_{version}_{port}_{timestamp}.log'
                except Exception:
                    pass
                self.config = converted
            else:
                self.config = new_config

            # 重新设置系统日志器
            self._setup_system_logger()
            # 清除现有的测试和错误日志器，下次使用时重新创建
            self.test_loggers.clear()
            self.error_loggers.clear()
    
    def _setup_system_logger(self):
        """设置系统日志器"""
        if not self.config.system_log.enabled:
            return
        
        self.system_logger = logging.getLogger("System")
        self.system_logger.setLevel(getattr(logging, self.config.system_log.level))
        
        # 清除现有处理器
        self.system_logger.handlers.clear()
        
        # 创建系统日志文件路径（容错）
        try:
            log_dir = self.config.get_log_dir("system")
        except Exception:
            log_dir = Path(getattr(self.config.system_log, "base_dir", "Result/Log"))
        try:
            date_folder = self.config.get_date_folder("system")
        except Exception:
            date_folder = datetime.now().strftime(getattr(self.config.system_log, "date_format", "%Y%m%d"))
        log_path = log_dir / date_folder
        log_path.mkdir(parents=True, exist_ok=True)
        
        # 创建文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        config_filename = self.config.system_log.config_filename.format(
            station=self.config.station_name,
            timestamp=timestamp
        )
        system_filename = self.config.system_log.system_filename.format(
            station=self.config.station_name,
            timestamp=timestamp
        )
        
        # 配置日志处理器
        config_handler = SystemFileHandler(
            str(log_path / config_filename),
            when=self.config.rotation.when,
            backupCount=self.config.rotation.backup_count
        )
        config_handler.setFormatter(create_formatter("system"))
        config_handler.addFilter(lambda record: record.name == "Config")
        
        system_handler = SystemFileHandler(
            str(log_path / system_filename),
            when=self.config.rotation.when,
            backupCount=self.config.rotation.backup_count
        )
        system_handler.setFormatter(create_formatter("system"))
        system_handler.addFilter(lambda record: record.name != "Config")
        
        self.system_logger.addHandler(config_handler)
        self.system_logger.addHandler(system_handler)
        
        # 添加Qt处理器（如果存在）
        if self.qt_handler:
            self.system_logger.addHandler(self.qt_handler)
    
    def setup_qt_handler(self, qt_handler: QtSignalHandler):
        """设置Qt信号处理器"""
        self.qt_handler = qt_handler
        
        # 为所有现有日志器添加Qt处理器
        for logger in self.test_loggers.values():
            logger.logger.addHandler(qt_handler)
        for logger in self.error_loggers.values():
            logger.logger.addHandler(qt_handler)
        if self.system_logger:
            self.system_logger.addHandler(qt_handler)
    
    def setup_test_logger(self, port: str, sn: str = None) -> 'TestLogger':
        """设置测试结果日志器"""
        with self._lock:
            # 总是创建新的TestLogger以使用最新配置
            from .test_logger import TestLogger
            logger = TestLogger(port, sn, self.config)
            
            # 添加Qt处理器
            if self.qt_handler:
                logger.logger.addHandler(self.qt_handler)
            
            self.test_loggers[port] = logger
            return logger
    
    def setup_error_logger(self, port: str, sn: str = None) -> 'ErrorLogger':
        """设置错误日志器"""
        with self._lock:
            # 总是创建新的ErrorLogger以使用最新配置
            from .error_logger import ErrorLogger
            logger = ErrorLogger(port, sn, self.config)
            
            # 添加Qt处理器
            if self.qt_handler:
                logger.logger.addHandler(self.qt_handler)
            
            self.error_loggers[port] = logger
            return logger
    
    def get_test_logger(self, port: str) -> Optional['TestLogger']:
        """获取指定端口的测试日志器"""
        return self.test_loggers.get(port)
    
    def get_error_logger(self, port: str) -> Optional['ErrorLogger']:
        """获取指定端口的错误日志器"""
        return self.error_loggers[port]
    
    def get_system_logger(self) -> Optional[logging.Logger]:
        """获取系统日志器"""
        return self.system_logger
    
    def cleanup_old_logs(self, days: int = None):
        """清理过期日志文件"""
        if days is None:
            days = self.config.rotation.backup_count
        
        cutoff_date = datetime.now().timestamp() - (days * 24 * 3600)
        
        for log_type in ["test", "error", "system"]:
            log_dir = self.config.get_log_dir(log_type)
            if log_dir.exists():
                for date_folder in log_dir.iterdir():
                    if date_folder.is_dir():
                        try:
                            # 检查日期文件夹是否过期
                            folder_date = datetime.strptime(date_folder.name, self.config.test_log.date_format)
                            if folder_date.timestamp() < cutoff_date:
                                import shutil
                                shutil.rmtree(date_folder)
                                print(f"已清理过期日志文件夹: {date_folder}")
                        except ValueError:
                            # 不是日期格式的文件夹，跳过
                            continue
    
    
    
    def close_all(self):
        """关闭所有日志器"""
        with self._lock:
            for logger in self.test_loggers.values():
                logger.close()
            for logger in self.error_loggers.values():
                logger.close()
            if self.system_logger:
                for handler in self.system_logger.handlers:
                    handler.close()
            
            self.test_loggers.clear()
            self.error_loggers.clear()
            self.system_logger = None


# 全局日志管理器实例
_global_manager: Optional[LoggingManager] = None


def get_logging_manager() -> Optional[LoggingManager]:
    """获取全局日志管理器"""
    return _global_manager


def set_logging_manager(manager: LoggingManager):
    """设置全局日志管理器"""
    global _global_manager
    _global_manager = manager


def get_test_logger(port: str) -> Optional['TestLogger']:
    """获取测试日志器（便捷函数）"""
    if _global_manager:
        return _global_manager.get_test_logger(port)
    return None


def get_error_logger(port: str) -> Optional['ErrorLogger']:
    """获取错误日志器（便捷函数）"""
    if _global_manager:
        return _global_manager.get_error_logger(port)
    return None


def get_system_logger() -> Optional[logging.Logger]:
    """获取系统日志器（便捷函数）"""
    if _global_manager:
        return _global_manager.get_system_logger()
    return None
