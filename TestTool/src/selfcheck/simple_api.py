"""
系统自检简化API接口
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Callable
from datetime import datetime

from .check_stages import StageBasedChecker, CheckStage, global_check_state
from .stage_configs import StageConfigManager
from .models import CheckConfig, SystemCheckResult

logger = logging.getLogger(__name__)


class SimpleCheckAPI:
    """简化的检查API"""
    
    def __init__(self):
        self.stage_checker: Optional[StageBasedChecker] = None
        self.config_manager = StageConfigManager()
        self.callbacks: Dict[str, Callable] = {}
    
    def initialize(self, config: Optional[CheckConfig] = None):
        """初始化检查器"""
        if config is None:
            config = CheckConfig()
        
        self.stage_checker = StageBasedChecker(config)
        logger.info("系统自检API已初始化")
    
    def add_callback(self, stage: str, callback: Callable[[SystemCheckResult], None]):
        """添加阶段检查完成回调"""
        self.callbacks[stage] = callback
        logger.info(f"已添加 {stage} 阶段回调")
    
    async def check_system_startup(self) -> SystemCheckResult:
        """检查系统启动（第一类）"""
        logger.info("开始系统启动检查")
        
        if not self.stage_checker:
            self.initialize()
        
        # 使用系统启动配置
        startup_config = self.config_manager.get_config("system_startup")
        self.stage_checker.config = startup_config
        
        # 执行检查
        result = await self.stage_checker.run_system_startup_check()
        
        # 更新全局状态
        global_check_state.set_stage_state(
            CheckStage.SYSTEM_STARTUP, 
            result.overall_success, 
            result
        )
        
        # 调用回调
        if "system_startup" in self.callbacks:
            try:
                self.callbacks["system_startup"](result)
            except Exception as e:
                logger.error(f"系统启动检查回调执行失败: {e}")
        
        return result
    
    async def check_config_completed(self) -> SystemCheckResult:
        """检查配置完成（第二类）"""
        logger.info("开始配置完成检查")
        
        if not self.stage_checker:
            self.initialize()
        
        # 使用配置完成配置
        config_completed_config = self.config_manager.get_config("config_completed")
        self.stage_checker.config = config_completed_config
        
        # 执行检查
        result = await self.stage_checker.run_config_completed_check()
        
        # 更新全局状态
        global_check_state.set_stage_state(
            CheckStage.CONFIG_COMPLETED, 
            result.overall_success, 
            result
        )
        
        # 调用回调
        if "config_completed" in self.callbacks:
            try:
                self.callbacks["config_completed"](result)
            except Exception as e:
                logger.error(f"配置完成检查回调执行失败: {e}")
        
        return result
    
    async def check_test_ready(self) -> SystemCheckResult:
        """检查测试就绪（第三类）"""
        logger.info("开始测试就绪检查")
        
        if not self.stage_checker:
            self.initialize()
        
        # 使用测试就绪配置
        test_ready_config = self.config_manager.get_config("test_ready")
        self.stage_checker.config = test_ready_config
        
        # 执行检查
        result = await self.stage_checker.run_test_ready_check()
        
        # 更新全局状态
        global_check_state.set_stage_state(
            CheckStage.TEST_READY, 
            result.overall_success, 
            result
        )
        
        # 调用回调
        if "test_ready" in self.callbacks:
            try:
                self.callbacks["test_ready"](result)
            except Exception as e:
                logger.error(f"测试就绪检查回调执行失败: {e}")
        
        return result
    
    def is_system_ready(self) -> bool:
        """系统是否就绪"""
        return global_check_state.is_system_ready()
    
    def is_config_ready(self) -> bool:
        """配置是否就绪"""
        return global_check_state.is_config_ready()
    
    def is_test_ready(self) -> bool:
        """测试是否就绪"""
        return global_check_state.is_test_ready()
    
    def get_system_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        return global_check_state.get_status_summary()
    
    def get_stage_result(self, stage: str) -> Optional[SystemCheckResult]:
        """获取阶段检查结果"""
        stage_enum = {
            "system_startup": CheckStage.SYSTEM_STARTUP,
            "config_completed": CheckStage.CONFIG_COMPLETED,
            "test_ready": CheckStage.TEST_READY
        }.get(stage)
        
        if stage_enum:
            return global_check_state.get_stage_result(stage_enum)
        return None
    
    def reset_stage(self, stage: str):
        """重置阶段状态"""
        stage_enum = {
            "system_startup": CheckStage.SYSTEM_STARTUP,
            "config_completed": CheckStage.CONFIG_COMPLETED,
            "test_ready": CheckStage.TEST_READY
        }.get(stage)
        
        if stage_enum:
            global_check_state.state.reset_stage(stage_enum)
            logger.info(f"已重置 {stage} 阶段状态")
    
    def reset_all_stages(self):
        """重置所有阶段状态"""
        global_check_state.reset_all_stages()
        logger.info("已重置所有阶段状态")


# 全局API实例
check_api = SimpleCheckAPI()


# 便捷函数
async def check_system_startup() -> SystemCheckResult:
    """检查系统启动"""
    return await check_api.check_system_startup()


async def check_config_completed() -> SystemCheckResult:
    """检查配置完成"""
    return await check_api.check_config_completed()


async def check_test_ready() -> SystemCheckResult:
    """检查测试就绪"""
    return await check_api.check_test_ready()


def is_system_ready() -> bool:
    """系统是否就绪"""
    return check_api.is_system_ready()


def is_config_ready() -> bool:
    """配置是否就绪"""
    return check_api.is_config_ready()


def is_test_ready() -> bool:
    """测试是否就绪"""
    return check_api.is_test_ready()


def get_system_status() -> Dict[str, Any]:
    """获取系统状态"""
    return check_api.get_system_status()


def get_stage_result(stage: str) -> Optional[SystemCheckResult]:
    """获取阶段检查结果"""
    return check_api.get_stage_result(stage)


def reset_stage(stage: str):
    """重置阶段状态"""
    check_api.reset_stage(stage)


def reset_all_stages():
    """重置所有阶段状态"""
    check_api.reset_all_stages()
