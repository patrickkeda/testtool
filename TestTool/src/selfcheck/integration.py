"""
系统自检模块集成示例
"""

import asyncio
import logging
from typing import Optional, Callable, Any
from datetime import datetime

from .manager import SystemChecker, SystemCheckRunner
from .models import CheckConfig, SystemCheckResult, CheckStatus

logger = logging.getLogger(__name__)


class SystemCheckIntegration:
    """系统自检集成类"""
    
    def __init__(self, config: Optional[CheckConfig] = None):
        self.config = config or CheckConfig()
        self.runner = SystemCheckRunner(self.config)
        self.last_check_result: Optional[SystemCheckResult] = None
        self.check_callbacks: list[Callable[[SystemCheckResult], None]] = []
    
    def add_check_callback(self, callback: Callable[[SystemCheckResult], None]):
        """添加检查完成回调"""
        self.check_callbacks.append(callback)
    
    async def run_startup_check(self) -> SystemCheckResult:
        """运行启动检查"""
        logger.info("开始启动系统检查")
        
        try:
            # 运行快速检查（仅检查关键项目）
            result = await self.runner.run_quick_check()
            self.last_check_result = result
            
            # 调用回调
            for callback in self.check_callbacks:
                try:
                    callback(result)
                except Exception as e:
                    logger.error(f"检查回调执行失败: {e}")
            
            if result.is_healthy():
                logger.info("启动检查通过，系统可以正常启动")
            else:
                logger.warning(f"启动检查发现问题: {result.summary}")
            
            return result
            
        except Exception as e:
            logger.error(f"启动检查失败: {e}")
            # 创建错误结果
            error_result = SystemCheckResult(
                overall_status=CheckStatus.ERROR,
                overall_success=False,
                summary=f"启动检查异常: {e}"
            )
            self.last_check_result = error_result
            return error_result
    
    async def run_full_check(self) -> SystemCheckResult:
        """运行完整检查"""
        logger.info("开始完整系统检查")
        
        try:
            result = await self.runner.run_check()
            self.last_check_result = result
            
            # 调用回调
            for callback in self.check_callbacks:
                try:
                    callback(result)
                except Exception as e:
                    logger.error(f"检查回调执行失败: {e}")
            
            return result
            
        except Exception as e:
            logger.error(f"完整检查失败: {e}")
            error_result = SystemCheckResult(
                overall_status=CheckStatus.ERROR,
                overall_success=False,
                summary=f"完整检查异常: {e}"
            )
            self.last_check_result = error_result
            return error_result
    
    def get_last_check_result(self) -> Optional[SystemCheckResult]:
        """获取最后一次检查结果"""
        return self.last_check_result
    
    def is_system_healthy(self) -> bool:
        """检查系统是否健康"""
        if self.last_check_result is None:
            return False
        return self.last_check_result.is_healthy()
    
    def get_system_status_summary(self) -> dict[str, Any]:
        """获取系统状态摘要"""
        if self.last_check_result is None:
            return {
                "status": "unknown",
                "healthy": False,
                "last_check": None,
                "message": "未进行系统检查"
            }
        
        return {
            "status": self.last_check_result.overall_status.value,
            "healthy": self.last_check_result.is_healthy(),
            "last_check": self.last_check_result.timestamp.isoformat(),
            "message": self.last_check_result.summary,
            "total_items": self.last_check_result.get_total_items(),
            "success_count": self.last_check_result.get_total_success(),
            "warning_count": self.last_check_result.get_total_warnings(),
            "error_count": self.last_check_result.get_total_errors(),
            "success_rate": self.last_check_result.get_overall_success_rate()
        }


class StartupCheckHandler:
    """启动检查处理器"""
    
    def __init__(self, integration: SystemCheckIntegration):
        self.integration = integration
        self.check_passed = False
        self.check_result: Optional[SystemCheckResult] = None
    
    async def handle_startup_check(self) -> bool:
        """处理启动检查"""
        logger.info("执行启动系统检查")
        
        try:
            # 运行启动检查
            result = await self.integration.run_startup_check()
            self.check_result = result
            self.check_passed = result.is_healthy()
            
            if self.check_passed:
                logger.info("启动检查通过，系统可以正常启动")
                return True
            else:
                logger.warning(f"启动检查发现问题: {result.summary}")
                return False
                
        except Exception as e:
            logger.error(f"启动检查处理失败: {e}")
            return False
    
    def get_check_result(self) -> Optional[SystemCheckResult]:
        """获取检查结果"""
        return self.check_result
    
    def is_check_passed(self) -> bool:
        """检查是否通过"""
        return self.check_passed


class SystemHealthMonitor:
    """系统健康监控器"""
    
    def __init__(self, integration: SystemCheckIntegration, check_interval: int = 300):
        self.integration = integration
        self.check_interval = check_interval  # 检查间隔(秒)
        self.monitoring = False
        self.monitor_task: Optional[asyncio.Task] = None
    
    async def start_monitoring(self):
        """开始监控"""
        if self.monitoring:
            logger.warning("系统健康监控已在运行中")
            return
        
        self.monitoring = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"开始系统健康监控，检查间隔: {self.check_interval}秒")
    
    async def stop_monitoring(self):
        """停止监控"""
        if not self.monitoring:
            return
        
        self.monitoring = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("系统健康监控已停止")
    
    async def _monitor_loop(self):
        """监控循环"""
        while self.monitoring:
            try:
                # 运行健康检查
                result = await self.integration.run_full_check()
                
                if not result.is_healthy():
                    logger.warning(f"系统健康检查发现问题: {result.summary}")
                    # 这里可以添加告警逻辑
                else:
                    logger.debug("系统健康检查通过")
                
                # 等待下次检查
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"系统健康监控异常: {e}")
                await asyncio.sleep(60)  # 异常时等待1分钟再重试
    
    def is_monitoring(self) -> bool:
        """检查是否正在监控"""
        return self.monitoring


# 使用示例
async def example_usage():
    """使用示例"""
    # 创建系统检查集成
    integration = SystemCheckIntegration()
    
    # 添加检查完成回调
    def on_check_completed(result: SystemCheckResult):
        print(f"系统检查完成: {result.summary}")
        if not result.is_healthy():
            print("发现系统问题，请检查日志")
    
    integration.add_check_callback(on_check_completed)
    
    # 创建启动检查处理器
    startup_handler = StartupCheckHandler(integration)
    
    # 执行启动检查
    if await startup_handler.handle_startup_check():
        print("系统启动检查通过，可以继续启动")
    else:
        print("系统启动检查失败，请修复问题后重试")
        return
    
    # 创建系统健康监控器
    monitor = SystemHealthMonitor(integration, check_interval=300)
    
    # 开始监控（在实际应用中，这通常在后台运行）
    # await monitor.start_monitoring()
    
    # 获取系统状态
    status = integration.get_system_status_summary()
    print(f"系统状态: {status}")


if __name__ == "__main__":
    asyncio.run(example_usage())
