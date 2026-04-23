"""
日志格式化器
"""

import logging
from datetime import datetime
from typing import Any, Dict


class TestResultFormatter(logging.Formatter):
    """测试结果日志格式化器"""
    
    def __init__(self, include_config: bool = True, include_measurements: bool = True):
        self.include_config = include_config
        self.include_measurements = include_measurements
        
        # 基础格式：时间戳 + 级别 + 模块 + 消息
        fmt = "%(asctime)s.%(msecs)03d %(levelname)-8s [%(name)s] %(message)s"
        super().__init__(fmt, datefmt="%Y-%m-%d %H:%M:%S")
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录"""
        # 添加分隔线用于重要事件
        if hasattr(record, 'is_section') and record.is_section:
            return f"\n{'='*20} {record.getMessage()} {'='*20}\n"
        
        # 添加配置信息格式
        if hasattr(record, 'is_config') and record.is_config:
            return f"%(asctime)s.%(msecs)03d %(levelname)-8s [%(name)s] %(message)s"
        
        # 添加测量数据格式
        if hasattr(record, 'is_measurement') and record.is_measurement:
            return f"%(asctime)s.%(msecs)03d %(levelname)-8s [%(name)s] %(message)s"
        
        return super().format(record)


class ErrorFormatter(logging.Formatter):
    """错误日志格式化器"""
    
    def __init__(self, include_stack_trace: bool = True):
        self.include_stack_trace = include_stack_trace
        
        # 错误格式：时间戳 + 级别 + 模块 + 错误类型 + 消息
        fmt = "%(asctime)s.%(msecs)03d %(levelname)-8s [%(name)s] %(message)s"
        super().__init__(fmt, datefmt="%Y-%m-%d %H:%M:%S")
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化错误日志记录"""
        # 添加错误类型信息
        if hasattr(record, 'error_type'):
            record.msg = f"[{record.error_type}] {record.msg}"
        
        # 添加堆栈跟踪
        if self.include_stack_trace and record.exc_info:
            return super().format(record) + "\n" + self.formatException(record.exc_info)
        
        return super().format(record)


class SystemFormatter(logging.Formatter):
    """系统日志格式化器"""
    
    def __init__(self):
        # 系统格式：时间戳 + 级别 + 模块 + 操作 + 消息
        fmt = "%(asctime)s.%(msecs)03d %(levelname)-8s [%(name)s] %(message)s"
        super().__init__(fmt, datefmt="%Y-%m-%d %H:%M:%S")
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化系统日志记录"""
        # 添加操作类型信息
        if hasattr(record, 'operation'):
            record.msg = f"[{record.operation}] {record.msg}"
        
        return super().format(record)


class JsonFormatter(logging.Formatter):
    """JSON格式日志格式化器（用于远程日志）"""
    
    def __init__(self):
        super().__init__()
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化为JSON格式"""
        import json
        
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
            "thread": record.thread,
            "process": record.process
        }
        
        # 添加额外字段
        if hasattr(record, 'sn'):
            log_data['sn'] = record.sn
        if hasattr(record, 'port'):
            log_data['port'] = record.port
        if hasattr(record, 'station'):
            log_data['station'] = record.station
        if hasattr(record, 'error_type'):
            log_data['error_type'] = record.error_type
        if hasattr(record, 'operation'):
            log_data['operation'] = record.operation
        
        return json.dumps(log_data, ensure_ascii=False)


def create_formatter(formatter_type: str, **kwargs) -> logging.Formatter:
    """创建指定类型的格式化器"""
    if formatter_type == "test_result":
        return TestResultFormatter(**kwargs)
    elif formatter_type == "error":
        return ErrorFormatter(**kwargs)
    elif formatter_type == "system":
        return SystemFormatter(**kwargs)
    elif formatter_type == "json":
        return JsonFormatter(**kwargs)
    else:
        return logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s")
