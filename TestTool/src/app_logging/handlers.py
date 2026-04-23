"""
自定义日志处理器
"""

import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging.handlers
from PySide6.QtCore import QObject, Signal


class QtSignalHandler(logging.Handler):
    """Qt信号处理器，用于将日志发送到UI"""
    
    def __init__(self):
        super().__init__()
        self.log_record_signal = Signal(str, str, str)  # level, message, module
        
    def emit(self, record):
        """发送日志记录到Qt信号"""
        try:
            msg = self.format(record)
            level = record.levelname
            module = record.name
            self.log_record_signal.emit(level, msg, module)
        except Exception:
            self.handleError(record)


class DateRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """按日期轮转的文件处理器"""
    
    def __init__(self, filename, when='midnight', interval=1, backupCount=14, 
                 encoding='utf-8', delay=False, utc=False, atTime=None):
        # 确保目录存在
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        super().__init__(filename, when, interval, backupCount, encoding, delay, utc, atTime)
    
    def doRollover(self):
        """执行日志轮转"""
        if self.stream:
            self.stream.close()
            self.stream = None
        
        # 重命名当前文件
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename(f"{self.baseFilename}.{i}")
                dfn = self.rotation_filename(f"{self.baseFilename}.{i + 1}")
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        os.remove(dfn)
                    os.rename(sfn, dfn)
            
            dfn = self.rotation_filename(f"{self.baseFilename}.1")
            if os.path.exists(dfn):
                os.remove(dfn)
            os.rename(self.baseFilename, dfn)
        
        # 创建新文件
        if not self.delay:
            self.stream = self._open()


class SizeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """按大小轮转的文件处理器"""
    
    def __init__(self, filename, maxBytes=100*1024*1024, backupCount=14, encoding='utf-8', delay=False):
        # 确保目录存在
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        super().__init__(filename, maxBytes=maxBytes, backupCount=backupCount, 
                        encoding=encoding, delay=delay)


class TestResultFileHandler(DateRotatingFileHandler):
    """测试结果专用文件处理器"""
    
    def __init__(self, filename, when='midnight', interval=1, backupCount=14, 
                 encoding='utf-8', delay=False, utc=False, atTime=None):
        super().__init__(filename, when, interval, backupCount, encoding, delay, utc, atTime)
        self.setLevel(logging.INFO)


class ErrorFileHandler(DateRotatingFileHandler):
    """错误日志专用文件处理器"""
    
    def __init__(self, filename, when='midnight', interval=1, backupCount=14, 
                 encoding='utf-8', delay=False, utc=False, atTime=None):
        super().__init__(filename, when, interval, backupCount, encoding, delay, utc, atTime)
        self.setLevel(logging.ERROR)


class SystemFileHandler(DateRotatingFileHandler):
    """系统日志专用文件处理器"""
    
    def __init__(self, filename, when='midnight', interval=1, backupCount=14, 
                 encoding='utf-8', delay=False, utc=False, atTime=None):
        super().__init__(filename, when, interval, backupCount, encoding, delay, utc, atTime)
        self.setLevel(logging.INFO)
