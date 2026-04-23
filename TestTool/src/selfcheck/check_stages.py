"""
系统自检阶段管理
"""

import asyncio
import logging
from typing import Dict, Optional, List, Any
from datetime import datetime
from enum import Enum

from .models import CheckResult, SystemCheckResult, CheckConfig, CheckCategory, CheckStatus
from .manager import SystemChecker

logger = logging.getLogger(__name__)


class CheckStage(Enum):
    """检查阶段枚举"""
    SYSTEM_STARTUP = "system_startup"      # 系统启动检查
    CONFIG_COMPLETED = "config_completed"   # 配置完成检查
    TEST_READY = "test_ready"              # 测试前检查


class SystemCheckState:
    """系统检查状态管理"""
    
    def __init__(self):
        # 各阶段检查状态
        self.stage_states: Dict[CheckStage, bool] = {
            CheckStage.SYSTEM_STARTUP: False,
            CheckStage.CONFIG_COMPLETED: False,
            CheckStage.TEST_READY: False
        }
        
        # 各阶段检查结果
        self.stage_results: Dict[CheckStage, Optional[SystemCheckResult]] = {
            CheckStage.SYSTEM_STARTUP: None,
            CheckStage.CONFIG_COMPLETED: None,
            CheckStage.TEST_READY: None
        }
        
        # 检查时间戳
        self.stage_timestamps: Dict[CheckStage, Optional[datetime]] = {
            CheckStage.SYSTEM_STARTUP: None,
            CheckStage.CONFIG_COMPLETED: None,
            CheckStage.TEST_READY: None
        }
        
        # 系统整体状态
        self.system_ready = False
        self.config_ready = False
        self.test_ready = False
    
    def set_stage_state(self, stage: CheckStage, success: bool, result: Optional[SystemCheckResult] = None):
        """设置阶段状态"""
        self.stage_states[stage] = success
        self.stage_results[stage] = result
        self.stage_timestamps[stage] = datetime.now()
        
        # 更新系统状态
        self._update_system_status()
        
        logger.info(f"阶段 {stage.value} 状态更新: {'成功' if success else '失败'}")
    
    def _update_system_status(self):
        """更新系统整体状态"""
        self.system_ready = self.stage_states[CheckStage.SYSTEM_STARTUP]
        self.config_ready = self.stage_states[CheckStage.CONFIG_COMPLETED]
        self.test_ready = self.stage_states[CheckStage.TEST_READY]
    
    def get_stage_state(self, stage: CheckStage) -> bool:
        """获取阶段状态"""
        return self.stage_states.get(stage, False)
    
    def get_stage_result(self, stage: CheckStage) -> Optional[SystemCheckResult]:
        """获取阶段检查结果"""
        return self.stage_results.get(stage)
    
    def get_stage_timestamp(self, stage: CheckStage) -> Optional[datetime]:
        """获取阶段检查时间"""
        return self.stage_timestamps.get(stage)
    
    def is_system_ready(self) -> bool:
        """系统是否就绪"""
        return self.system_ready
    
    def is_config_ready(self) -> bool:
        """配置是否就绪"""
        return self.config_ready
    
    def is_test_ready(self) -> bool:
        """测试是否就绪"""
        return self.test_ready
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return {
            "system_ready": self.system_ready,
            "config_ready": self.config_ready,
            "test_ready": self.test_ready,
            "stage_states": {
                stage.value: {
                    "success": self.stage_states[stage],
                    "timestamp": self.stage_timestamps[stage].isoformat() if self.stage_timestamps[stage] else None,
                    "has_result": self.stage_results[stage] is not None
                }
                for stage in CheckStage
            }
        }
    
    def reset_stage(self, stage: CheckStage):
        """重置阶段状态"""
        self.stage_states[stage] = False
        self.stage_results[stage] = None
        self.stage_timestamps[stage] = None
        self._update_system_status()
        logger.info(f"阶段 {stage.value} 状态已重置")


class StageBasedChecker:
    """基于阶段的检查器"""
    
    def __init__(self, config: CheckConfig):
        self.config = config
        self.checker = SystemChecker()
        self.state = SystemCheckState()
        
        # 定义各阶段检查类别
        self.stage_categories = {
            CheckStage.SYSTEM_STARTUP: [
                CheckCategory.SOFTWARE_ENVIRONMENT,
                CheckCategory.HARDWARE_RESOURCES,
                CheckCategory.LOGGING
            ],
            CheckStage.CONFIG_COMPLETED: [
                CheckCategory.COMMUNICATION,
                CheckCategory.INSTRUMENTS
            ],
            CheckStage.TEST_READY: [
                CheckCategory.CONFIG
            ]
        }
    
    async def run_stage_check(self, stage: CheckStage) -> SystemCheckResult:
        """运行指定阶段检查"""
        logger.info(f"开始执行 {stage.value} 阶段检查")
        
        if stage not in self.stage_categories:
            logger.error(f"未知的检查阶段: {stage}")
            return SystemCheckResult(
                overall_status=CheckStatus.ERROR,
                overall_success=False,
                summary=f"未知的检查阶段: {stage}"
            )
        
        start_time = datetime.now()
        
        try:
            # 创建阶段检查结果
            stage_result = SystemCheckResult(
                overall_status=CheckStatus.PENDING,
                overall_success=False,
                summary=f"{stage.value} 阶段检查进行中"
            )
            
            # 执行该阶段的检查类别
            categories = self.stage_categories[stage]
            for category in categories:
                if not self.config.is_category_enabled(category):
                    logger.info(f"跳过 {category.value} 检查（已禁用）")
                    continue
                
                try:
                    category_result = await self.checker.check_category(category, self.config)
                    stage_result.add_result(category, category_result)
                    logger.info(f"{category.value} 检查完成: {category_result.message}")
                    
                except Exception as e:
                    logger.error(f"{category.value} 检查异常: {e}")
                    error_result = CheckResult(
                        success=False,
                        category=category,
                        message=f"检查异常: {e}",
                        summary="检查过程中发生异常"
                    )
                    stage_result.add_result(category, error_result)
            
            # 更新阶段结果
            stage_result.total_duration = (datetime.now() - start_time).total_seconds()
            
            if stage_result.has_errors():
                stage_result.overall_status = CheckStatus.ERROR
                stage_result.overall_success = False
                stage_result.summary = f"{stage.value} 阶段检查失败: {stage_result.get_total_errors()}个错误"
            elif stage_result.has_warnings():
                stage_result.overall_status = CheckStatus.WARNING
                stage_result.overall_success = True
                stage_result.summary = f"{stage.value} 阶段检查完成: {stage_result.get_total_warnings()}个警告"
            else:
                stage_result.overall_status = CheckStatus.SUCCESS
                stage_result.overall_success = True
                stage_result.summary = f"{stage.value} 阶段检查完全通过"
            
            # 更新状态
            self.state.set_stage_state(stage, stage_result.overall_success, stage_result)
            
            logger.info(f"{stage.value} 阶段检查完成: {stage_result.summary}")
            return stage_result
            
        except Exception as e:
            logger.error(f"{stage.value} 阶段检查异常: {e}")
            error_result = SystemCheckResult(
                overall_status=CheckStatus.ERROR,
                overall_success=False,
                summary=f"{stage.value} 阶段检查异常: {e}"
            )
            self.state.set_stage_state(stage, False, error_result)
            return error_result
    
    async def run_system_startup_check(self) -> SystemCheckResult:
        """运行系统启动检查"""
        return await self.run_stage_check(CheckStage.SYSTEM_STARTUP)
    
    async def run_config_completed_check(self) -> SystemCheckResult:
        """运行配置完成检查"""
        return await self.run_stage_check(CheckStage.CONFIG_COMPLETED)
    
    async def run_test_ready_check(self) -> SystemCheckResult:
        """运行测试前检查"""
        return await self.run_stage_check(CheckStage.TEST_READY)
    
    def get_state(self) -> SystemCheckState:
        """获取检查状态"""
        return self.state
    
    def is_stage_ready(self, stage: CheckStage) -> bool:
        """检查阶段是否就绪"""
        return self.state.get_stage_state(stage)
    
    def get_stage_result(self, stage: CheckStage) -> Optional[SystemCheckResult]:
        """获取阶段检查结果"""
        return self.state.get_stage_result(stage)
    
    def reset_stage(self, stage: CheckStage):
        """重置阶段状态"""
        self.state.reset_stage(stage)
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return self.state.get_status_summary()


class GlobalCheckState:
    """全局检查状态管理（单例模式）"""
    
    _instance: Optional['GlobalCheckState'] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.state = SystemCheckState()
            self._initialized = True
    
    @classmethod
    async def get_instance(cls) -> 'GlobalCheckState':
        """获取单例实例"""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def set_stage_state(self, stage: CheckStage, success: bool, result: Optional[SystemCheckResult] = None):
        """设置阶段状态"""
        self.state.set_stage_state(stage, success, result)
    
    def get_stage_state(self, stage: CheckStage) -> bool:
        """获取阶段状态"""
        return self.state.get_stage_state(stage)
    
    def get_stage_result(self, stage: CheckStage) -> Optional[SystemCheckResult]:
        """获取阶段检查结果"""
        return self.state.get_stage_result(stage)
    
    def is_system_ready(self) -> bool:
        """系统是否就绪"""
        return self.state.is_system_ready()
    
    def is_config_ready(self) -> bool:
        """配置是否就绪"""
        return self.state.is_config_ready()
    
    def is_test_ready(self) -> bool:
        """测试是否就绪"""
        return self.state.is_test_ready()
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return self.state.get_status_summary()
    
    def reset_all_stages(self):
        """重置所有阶段状态"""
        for stage in CheckStage:
            self.state.reset_stage(stage)
        logger.info("所有阶段状态已重置")


# 全局状态实例
global_check_state = GlobalCheckState()
