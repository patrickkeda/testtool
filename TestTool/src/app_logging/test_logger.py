"""
测试结果日志器 - 记录测试过程、结果和配置信息
"""

import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

from .config import LoggingConfig
from .handlers import TestResultFileHandler
from .formatters import create_formatter


class TestLogger:
    """测试结果日志器"""
    
    def __init__(self, port: str, sn: str = None, config: LoggingConfig = None):
        self.port = port
        self.sn = sn or "NULL"
        self.product = "NULL"  # 产品名称
        self.station = "NULL"  # 测试站
        self.version = "NULL"  # 版本
        self.config = config
        self.logger = None  # 延迟初始化
        self.test_start_time = None
        self.step_times = {}
    
    def _setup_logger(self) -> logging.Logger:
        """设置测试日志器"""
        try:
            if not self.config or not self.config.test_log.enabled:
                return logging.getLogger(f"Test.{self.port}")
            
            print(f"DEBUG: TestLogger._setup_logger - config类型: {type(self.config)}")
            print(f"DEBUG: TestLogger._setup_logger - config对象: {self.config}")
            print(f"DEBUG: TestLogger._setup_logger - config是否有get_log_dir方法: {hasattr(self.config, 'get_log_dir')}")
            
            logger = logging.getLogger(f"Test.{self.port}")
            logger.setLevel(getattr(logging, self.config.test_log.level))
            
            # 清除现有处理器
            logger.handlers.clear()
            
            # 创建日志文件路径
            try:
                log_dir = self.config.get_log_dir("test")
            except AttributeError as e:
                print(f"DEBUG: TestLogger._setup_logger - get_log_dir方法不存在: {e}")
                print(f"DEBUG: TestLogger._setup_logger - config对象属性: {dir(self.config)}")
                # 使用默认路径
                from pathlib import Path
                log_dir = Path("Result/TestResult")
            
            try:
                date_folder = self.config.get_date_folder("test")
            except AttributeError as e:
                print(f"DEBUG: TestLogger._setup_logger - get_date_folder方法不存在: {e}")
                # 使用默认日期格式
                date_folder = datetime.now().strftime("%Y%m%d")
            
            log_path = log_dir / date_folder
            log_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"DEBUG: TestLogger._setup_logger - 设置logger时出现异常: {e}")
            import traceback
            traceback.print_exc()
            # 返回一个基本的logger
            return logging.getLogger(f"Test.{self.port}")
        
        # 创建文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"DEBUG: TestLogger._setup_logger - 配置文件名格式: {self.config.test_log.filename}")
        print(f"DEBUG: TestLogger._setup_logger - 产品: {self.product}, 测试站: {self.station}, 版本: {self.version}")
        filename = self.config.test_log.filename.format(
            SN=self.sn or "NULL",
            product=self.product or "NULL",
            station=self.station or "NULL",
            version=self.version or "NULL",
            port=self.port or "NULL",
            timestamp=timestamp,
            result="RUNNING"  # 初始状态
        )
        print(f"DEBUG: TestLogger._setup_logger - 生成的文件名: {filename}")
        
        # 创建文件处理器
        handler = TestResultFileHandler(
            str(log_path / filename),
            when=self.config.rotation.when,
            backupCount=self.config.rotation.backup_count
        )
        handler.setFormatter(create_formatter("test_result", 
            include_config=self.config.test_log.include_config,
            include_measurements=self.config.test_log.include_measurements
        ))
        
        logger.addHandler(handler)
        return logger
    
    def update_config(self, new_config: LoggingConfig):
        """更新配置"""
        self.config = new_config
        self.logger = self._setup_logger()
    
    def log_test_start(self, sn: str, port: str, sequence_file: str, config_info: Dict[str, Any] = None):
        """记录测试开始和配置信息"""
        self.sn = sn or "NULL"
        self.test_start_time = datetime.now()
        
        # 从config_info中提取产品名称、测试站和版本信息
        if config_info:
            self.product = config_info.get("product", "NULL")
            self.station = config_info.get("station", "NULL")
            self.version = config_info.get("version", "NULL")
        
        # 现在设置logger，使用正确的产品名称和测试站信息
        self.logger = self._setup_logger()
        
        # 获取日志文件路径
        log_file_path = None
        print(f"DEBUG: TestLogger.log_test_start - logger handlers数量: {len(self.logger.handlers)}")
        for i, handler in enumerate(self.logger.handlers):
            print(f"DEBUG: TestLogger.log_test_start - handler {i}: {type(handler)}")
            if isinstance(handler, TestResultFileHandler):
                log_file_path = handler.baseFilename
                print(f"DEBUG: TestLogger.log_test_start - 找到文件处理器，路径: {log_file_path}")
                break
        
        # 记录测试开始信息
        self._log_section("测试开始")
        self.logger.info(f"SN: {sn}")
        self.logger.info(f"产品: {self.product}")
        self.logger.info(f"测试站: {self.station}")
        self.logger.info(f"测试端口: {port}")
        self.logger.info(f"测试序列: {sequence_file}")
        self.logger.info(f"开始时间: {self.test_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        if log_file_path:
            self.logger.info(f"测试日志文件: {log_file_path}")
        
        # 记录配置信息
        if self.config.test_log.include_config and config_info:
            self._log_config_info(config_info)
        
        # 返回日志文件路径，供主窗口显示
        return log_file_path
    
    def log_test_end(self, sn: str, port: str, result: str, duration: float, summary: Dict[str, Any] = None):
        """记录测试结束和结果汇总"""
        end_time = datetime.now()
        # 确保logger存在
        if self.logger is None:
            self.logger = self._setup_logger()
        # 更新SN，用于最终文件重命名
        self.sn = sn or "NULL"
        
        # 记录测试结束信息
        self._log_section("测试结果汇总")
        self.logger.info(f"SN: {sn}")
        self.logger.info(f"测试端口: {port}")
        self.logger.info(f"结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"总耗时: {duration:.3f}秒")
        self.logger.info(f"最终结果: {result}")
        
        # 记录结果汇总
        if summary:
            self.logger.info(f"总步骤数: {summary.get('total_steps', 0)}")
            self.logger.info(f"通过步骤: {summary.get('passed_steps', 0)}")
            self.logger.info(f"失败步骤: {summary.get('failed_steps', 0)}")
            self.logger.info(f"跳过步骤: {summary.get('skipped_steps', 0)}")
        
        # 重命名日志文件以包含最终结果
        renamed_file_path = self._rename_log_file(result)
        return renamed_file_path
    
    def log_step_start(self, step_id: str, step_name: str):
        """记录测试步骤开始"""
        self.step_times[step_id] = datetime.now()
        self.logger.info(f"步骤{step_id}: {step_name} - 开始")
    
    def log_step_end(self, step_id: str, result: str, duration: float, details: str = None):
        """记录测试步骤结束"""
        if step_id in self.step_times:
            actual_duration = duration or (datetime.now() - self.step_times[step_id]).total_seconds()
        else:
            actual_duration = duration or 0.0
        
        msg = f"步骤{step_id}: 结果: {result}, 耗时: {actual_duration:.3f}秒"
        if details:
            msg += f", 详情: {details}"
        
        self.logger.info(msg)
    
    def log_step_command(self, step_id: str, command: str, response: str = None):
        """记录测试步骤命令和响应"""
        self.logger.info(f"步骤{step_id}: 发送命令: {command}")
        if response is not None:
            self.logger.info(f"步骤{step_id}: 接收响应: {response}")
    
    def log_measurement(self, parameter: str, value: float, unit: str, 
                       min_val: float = None, max_val: float = None, result: str = None):
        """记录测量数据"""
        if not self.config.test_log.include_measurements:
            return
        
        # 构建测量信息
        range_info = ""
        if min_val is not None and max_val is not None:
            range_info = f" (范围: {min_val}{unit}-{max_val}{unit})"
        
        result_info = ""
        if result:
            result_info = f" - {result}"
        
        msg = f"{parameter}测量: {value}{unit}{range_info}{result_info}"
        self.logger.info(msg)
    
    def log_config_info(self, config_section: str, config_data: Dict[str, Any]):
        """记录配置信息"""
        if not self.config.test_log.include_config:
            return
        
        self.logger.info(f"配置信息 - {config_section}:")
        for key, value in config_data.items():
            self.logger.info(f"  {key}: {value}")
    
    def log_test_summary(self, summary: Dict[str, Any]):
        """记录测试结果汇总"""
        self._log_section("测试结果汇总")
        
        for key, value in summary.items():
            self.logger.info(f"{key}: {value}")
    
    def _log_section(self, title: str):
        """记录分隔线"""
        base_logger = self.logger or logging.getLogger(f"Test.{self.port}")
        record = logging.LogRecord(
            name=base_logger.name,
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=title,
            args=(),
            exc_info=None
        )
        record.is_section = True
        base_logger.handle(record)
    
    def _log_config_info(self, config_info: Dict[str, Any]):
        """记录配置信息"""
        self._log_section("当前配置")
        
        for section, data in config_info.items():
            if isinstance(data, dict):
                self.logger.info(f"{section}配置:")
                for key, value in data.items():
                    self.logger.info(f"  {key}: {value}")
            else:
                self.logger.info(f"{section}: {data}")
    
    def _rename_log_file(self, result: str):
        """重命名日志文件以包含最终结果"""
        if not self.config or not self.config.test_log.enabled:
            return
        
        try:
            # 获取当前处理器
            for handler in self.logger.handlers:
                if isinstance(handler, TestResultFileHandler):
                    old_path = Path(handler.baseFilename)
                    if old_path.exists():
                        # 先关闭文件句柄，避免文件被占用
                        handler.close()
                        
                        # 从原文件名中提取时间戳
                        # 原文件名格式: SN_product_station_version_port_timestamp_RUNNING.log
                        # 需要提取timestamp部分
                        stem_parts = old_path.stem.split('_')
                        if len(stem_parts) >= 6:
                            # 找到最后一个非RUNNING的部分作为时间戳
                            timestamp_parts = []
                            for part in reversed(stem_parts):
                                if part == "RUNNING":
                                    continue
                                timestamp_parts.insert(0, part)
                                if len(timestamp_parts) == 2:  # 取最后两部分作为时间戳
                                    break
                            timestamp = '_'.join(timestamp_parts)
                        else:
                            # 如果解析失败，使用当前时间
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        
                        # 构建新文件名
                        new_filename = self.config.test_log.filename.format(
                            SN=self.sn or "NULL",
                            product=self.product or "NULL",
                            station=self.station or "NULL",
                            version=self.version or "NULL",
                            port=self.port or "NULL",
                            timestamp=timestamp,
                            result=result
                        )
                        new_path = old_path.parent / new_filename
                        
                        # 等待一小段时间确保文件句柄完全释放
                        import time
                        time.sleep(0.1)
                        
                        old_path.rename(new_path)
                        return str(new_path)
        except Exception as e:
            # 重命名失败不影响测试
            if self.logger:
                self.logger.warning(f"重命名日志文件失败: {e}")
    
    def close(self):
        """关闭日志器"""
        for handler in self.logger.handlers:
            handler.close()
        self.logger.handlers.clear()
