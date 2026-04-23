"""
系统自检管理器
"""

import asyncio
import logging
from typing import Dict, Optional, List
from datetime import datetime

from .interfaces import ISystemChecker, IResourceChecker, ICheckProgressCallback
from .models import (
    CheckResult, SystemCheckResult, CheckConfig, CheckCategory, 
    CheckStatus, CheckItem
)
from .checkers import (
    SoftwareEnvironmentChecker,
    HardwareResourceChecker,
    CommunicationChecker,
    ConfigChecker
)
from .checkers_ext import (
    InstrumentChecker,
    LoggingChecker
)

logger = logging.getLogger(__name__)


class SystemChecker(ISystemChecker):
    """系统自检管理器"""
    
    def __init__(self):
        self.checkers: Dict[CheckCategory, IResourceChecker] = {}
        self.progress_callback: Optional[ICheckProgressCallback] = None
        self._is_running = False
        
        # 注册默认检查器
        self._register_default_checkers()
    
    def _register_default_checkers(self):
        """注册默认检查器"""
        default_checkers = [
            SoftwareEnvironmentChecker(),
            HardwareResourceChecker(),
            CommunicationChecker(),
            ConfigChecker(),
            InstrumentChecker(),
            LoggingChecker()
        ]
        
        for checker in default_checkers:
            self.checkers[checker.get_category()] = checker
    
    async def run_full_check(self, config: CheckConfig) -> SystemCheckResult:
        """执行完整系统检查"""
        if self._is_running:
            logger.warning("系统检查已在运行中，跳过本次检查")
            return SystemCheckResult(
                overall_status=CheckStatus.ERROR,
                overall_success=False,
                summary="系统检查已在运行中"
            )
        
        self._is_running = True
        start_time = datetime.now()
        
        try:
            logger.info("开始执行系统自检")
            
            # 创建系统检查结果
            system_result = SystemCheckResult(
                overall_status=CheckStatus.PENDING,
                overall_success=False,
                summary="系统检查进行中"
            )
            
            # 按类别执行检查
            for category in CheckCategory:
                if not config.is_category_enabled(category):
                    logger.info(f"跳过{category.value}检查（已禁用）")
                    continue
                
                if category not in self.checkers:
                    logger.warning(f"未找到{category.value}检查器")
                    continue
                
                try:
                    # 执行单个类别检查
                    category_result = await self.check_category(category, config)
                    system_result.add_result(category, category_result)
                    
                    # 调用进度回调
                    if self.progress_callback:
                        await self.progress_callback.on_check_completed(category, category_result)
                    
                except Exception as e:
                    logger.error(f"{category.value}检查异常: {e}")
                    error_result = CheckResult(
                        success=False,
                        category=category,
                        message=f"检查异常: {e}",
                        summary="检查过程中发生异常"
                    )
                    system_result.add_result(category, error_result)
            
            # 更新总体状态
            system_result.total_duration = (datetime.now() - start_time).total_seconds()
            
            if system_result.has_errors():
                system_result.overall_status = CheckStatus.ERROR
                system_result.overall_success = False
                system_result.summary = f"系统检查失败: {system_result.get_total_errors()}个错误"
                system_result.recommendations = [
                    "请检查错误详情",
                    "根据建议修复问题",
                    "重新运行系统检查"
                ]
            elif system_result.has_warnings():
                system_result.overall_status = CheckStatus.WARNING
                system_result.overall_success = True
                system_result.summary = f"系统检查完成: {system_result.get_total_warnings()}个警告"
                system_result.recommendations = [
                    "建议处理警告信息",
                    "优化系统配置"
                ]
            else:
                system_result.overall_status = CheckStatus.SUCCESS
                system_result.overall_success = True
                system_result.summary = f"系统检查完全通过: {system_result.get_total_success()}/{system_result.get_total_items()}项成功"
                system_result.recommendations = []
            
            # 调用完成回调
            if self.progress_callback:
                await self.progress_callback.on_system_check_completed(system_result)
            
            logger.info(f"系统检查完成: {system_result.summary}")
            return system_result
            
        except Exception as e:
            logger.error(f"系统检查异常: {e}")
            return SystemCheckResult(
                overall_status=CheckStatus.ERROR,
                overall_success=False,
                summary=f"系统检查异常: {e}",
                recommendations=["请检查系统状态", "查看详细错误日志"]
            )
        finally:
            self._is_running = False
    
    async def check_category(self, category: CheckCategory, config: CheckConfig) -> CheckResult:
        """检查指定类别"""
        if category not in self.checkers:
            return CheckResult(
                success=False,
                category=category,
                message=f"未找到{category.value}检查器",
                summary="检查器未注册"
            )
        
        checker = self.checkers[category]
        category_config = config.get_category_config(category)
        
        # 调用开始回调
        if self.progress_callback:
            await self.progress_callback.on_check_started(category, checker.get_name())
        
        try:
            # 执行检查
            result = await checker.check(category_config)
            
            # 调用进度回调
            if self.progress_callback:
                for item in result.items:
                    await self.progress_callback.on_check_progress(
                        category, item.name, item.status.value
                    )
            
            return result
            
        except Exception as e:
            logger.error(f"{category.value}检查异常: {e}")
            return CheckResult(
                success=False,
                category=category,
                message=f"检查异常: {e}",
                summary="检查过程中发生异常"
            )
    
    async def register_checker(self, checker: IResourceChecker):
        """注册检查器"""
        self.checkers[checker.get_category()] = checker
        logger.info(f"注册检查器: {checker.get_name()}")
    
    async def unregister_checker(self, category: CheckCategory):
        """注销检查器"""
        if category in self.checkers:
            checker_name = self.checkers[category].get_name()
            del self.checkers[category]
            logger.info(f"注销检查器: {checker_name}")
    
    def get_available_checkers(self) -> Dict[CheckCategory, IResourceChecker]:
        """获取可用的检查器"""
        return self.checkers.copy()
    
    def set_progress_callback(self, callback: ICheckProgressCallback):
        """设置进度回调"""
        self.progress_callback = callback
    
    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._is_running
    
    async def get_system_status(self) -> Dict[str, any]:
        """获取系统状态摘要"""
        status = {
            "is_running": self._is_running,
            "available_checkers": len(self.checkers),
            "checker_categories": [cat.value for cat in self.checkers.keys()],
            "timestamp": datetime.now().isoformat()
        }
        return status


class SimpleProgressCallback(ICheckProgressCallback):
    """简单进度回调实现"""
    
    def __init__(self, logger_instance: Optional[logging.Logger] = None):
        self.logger = logger_instance or logger
    
    async def on_check_started(self, category: CheckCategory, checker_name: str):
        """检查开始回调"""
        self.logger.info(f"开始{category.value}检查: {checker_name}")
    
    async def on_check_progress(self, category: CheckCategory, item_name: str, status: str):
        """检查进度回调"""
        self.logger.debug(f"{category.value} - {item_name}: {status}")
    
    async def on_check_completed(self, category: CheckCategory, result: CheckResult):
        """检查完成回调"""
        if result.success:
            self.logger.info(f"{category.value}检查完成: {result.message}")
        else:
            self.logger.error(f"{category.value}检查失败: {result.message}")
    
    async def on_system_check_completed(self, result: SystemCheckResult):
        """系统检查完成回调"""
        if result.overall_success:
            self.logger.info(f"系统检查完成: {result.summary}")
        else:
            self.logger.error(f"系统检查失败: {result.summary}")


class SystemCheckRunner:
    """系统检查运行器"""
    
    def __init__(self, config: CheckConfig):
        self.config = config
        self.checker = SystemChecker()
        self.progress_callback = SimpleProgressCallback()
        self.checker.set_progress_callback(self.progress_callback)
    
    async def run_check(self) -> SystemCheckResult:
        """运行系统检查"""
        return await self.checker.run_full_check(self.config)
    
    async def run_quick_check(self) -> SystemCheckResult:
        """运行快速检查（仅检查关键项目）"""
        # 创建快速检查配置
        quick_config = CheckConfig()
        quick_config.software_environment = self.config.software_environment.copy()
        quick_config.hardware_resources = self.config.hardware_resources.copy()
        quick_config.config = self.config.config.copy()
        
        # 禁用非关键检查
        quick_config.communication["enabled"] = False
        quick_config.instruments["enabled"] = False
        quick_config.logging["enabled"] = False
        
        return await self.checker.run_full_check(quick_config)
    
    def get_checker(self) -> SystemChecker:
        """获取检查器实例"""
        return self.checker
