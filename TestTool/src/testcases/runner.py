"""
测试执行引擎 - 管理测试序列的执行
"""

import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging

from .config import TestSequenceConfig, TestStepConfig
from .context import TestContext
from .mode_manager import ModeManager
from .step import StepResult, IStep
from .validator import get_validator

logger = logging.getLogger(__name__)


class TestResult:
    """测试结果"""
    
    def __init__(self, sn: str, station: str, port: str, result: str, 
                 start_time: datetime, end_time: datetime, duration: float,
                 steps: List[StepResult], failed_steps: List[str], 
                 error_message: Optional[str] = None, work_order: Optional[str] = None,
                 product_number: Optional[str] = None):
        self.sn = sn
        self.station = station
        self.port = port
        self.result = result
        self.start_time = start_time
        self.end_time = end_time
        self.duration = duration
        self.steps = steps
        self.failed_steps = failed_steps
        self.error_message = error_message
        self.work_order = work_order
        self.product_number = product_number
        
    def get_summary(self) -> Dict[str, Any]:
        """获取测试摘要"""
        return {
            "sn": self.sn,
            "station": self.station,
            "port": self.port,
            "result": self.result,
            "work_order": self.work_order,
            "product_number": self.product_number,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration": self.duration,
            "total_steps": len(self.steps),
            "passed_steps": len([s for s in self.steps if s.success]),
            "failed_steps": len(self.failed_steps),
            "skipped_steps": 0,
            "success_rate": len([s for s in self.steps if s.success]) / len(self.steps) if self.steps else 0
        }


class TestRunner:
    """测试执行引擎"""
    
    def __init__(self, config: TestSequenceConfig, context: TestContext, 
                 mode_manager: ModeManager):
        self.config = config
        self.context = context
        self.mode_manager = mode_manager
        self.current_step = None
        self.step_results = []
        self.is_running = False
        self.is_paused = False
        self.skipped_steps = set()  # 跳过的步骤
        self.validator = get_validator()
        
    async def start_test(self, sn: str, work_order: str = None, 
                        product_number: str = None) -> bool:
        """开始测试
        
        Parameters
        ----------
        sn : str
            序列号
        work_order : str
            工单号
        product_number : str
            产品型号
            
        Returns
        -------
        bool
            是否启动成功
        """
        try:
            # 设置测试上下文
            self.context.sn = sn
            self.context.work_order = work_order
            self.context.product_number = product_number
            
            # 开始执行测试序列
            self.is_running = True
            self.is_paused = False
            self.step_results = []
            self.skipped_steps.clear()
            
            # 记录测试开始
            logger.info(f"开始测试 SN: {sn}, 工单: {work_order}")
            
            return True
            
        except Exception as e:
            logger.error(f"启动测试失败: {e}")
            return False
    
    async def run(self) -> TestResult:
        """执行测试序列
        
        Returns
        -------
        TestResult
            测试结果
        """
        if not self.is_running:
            raise RuntimeError("测试未启动")
            
        start_time = datetime.now()
        failed_steps = []
        
        try:
            for step_config in self.config.steps:
                if not self.is_running:
                    break
                    
                # 检查是否跳过此步骤
                if step_config.id in self.skipped_steps:
                    logger.info(f"跳过步骤: {step_config.name}")
                    continue
                    
                # 检查暂停状态
                while self.is_paused and self.is_running:
                    await asyncio.sleep(0.1)
                    
                # 执行步骤
                step_result = await self._execute_step(step_config)
                self.step_results.append(step_result)
                self.context.set_result(step_config.id, step_result)
                
                # 检查步骤结果
                if not step_result.success:
                    failed_steps.append(step_config.id)
                    
                    # 根据失败策略处理
                    if step_config.on_failure == "fail":
                        logger.error(f"步骤 {step_config.id} 失败，停止测试")
                        break
                    elif step_config.on_failure == "continue":
                        logger.warning(f"步骤 {step_config.id} 失败，继续执行")
                        continue
                    elif step_config.on_failure == "retry" and self.mode_manager.can_retry_step():
                        # 重试逻辑
                        logger.info(f"重试步骤 {step_config.id}")
                        for retry in range(step_config.retries):
                            step_result = await self._execute_step(step_config)
                            if step_result.success:
                                # 更新结果
                                self.step_results[-1] = step_result
                                self.context.set_result(step_config.id, step_result)
                                break
                            await asyncio.sleep(1)  # 重试间隔
                            
                        if not step_result.success:
                            if step_config.on_failure == "fail":
                                logger.error(f"步骤 {step_config.id} 重试后仍失败，停止测试")
                                break
                                
        except Exception as e:
            logger.error(f"测试执行异常: {e}")
            
        finally:
            self.is_running = False
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # 生成测试结果
            test_result = TestResult(
                sn=self.context.sn,
                station=self.context.station,
                port=self.context.port,
                result="PASS" if not failed_steps else "FAIL",
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                steps=self.step_results,
                failed_steps=failed_steps,
                error_message=failed_steps[0] if failed_steps else None,
                work_order=self.context.work_order,
                product_number=self.context.product_number
            )
            
            logger.info(f"测试完成: {test_result.result}, 耗时: {duration:.3f}秒")
            return test_result
    
    async def pause(self):
        """暂停测试"""
        if not self.mode_manager.can_pause():
            raise PermissionError("当前模式不允许暂停")
        self.is_paused = True
        logger.info("测试已暂停")
        
    async def resume(self):
        """恢复测试"""
        if not self.mode_manager.can_pause():
            raise PermissionError("当前模式不允许恢复")
        self.is_paused = False
        logger.info("测试已恢复")
        
    async def stop(self):
        """停止测试"""
        self.is_running = False
        self.is_paused = False
        logger.info("测试已停止")
        
    async def skip_step(self, step_id: str):
        """跳过指定步骤"""
        if not self.mode_manager.can_skip_step():
            raise PermissionError("当前模式不允许跳过步骤")
        self.skipped_steps.add(step_id)
        logger.info(f"跳过步骤: {step_id}")
        
    async def retry_step(self, step_id: str):
        """重试指定步骤"""
        if not self.mode_manager.can_retry_step():
            raise PermissionError("当前模式不允许重试步骤")
            
        # 找到步骤配置
        step_config = self.config.get_step_by_id(step_id)
        if not step_config:
            logger.error(f"步骤 {step_id} 不存在")
            return
            
        # 重试逻辑：重新执行指定步骤
        step_result = await self._execute_step(step_config)
        
        # 更新结果
        for i, result in enumerate(self.step_results):
            if result.step_id == step_id:
                self.step_results[i] = step_result
                self.context.set_result(step_id, step_result)
                break
                
        logger.info(f"重试步骤: {step_id}, 结果: {step_result.success}")
        
    async def _execute_step(self, step_config: TestStepConfig) -> StepResult:
        """执行单个测试步骤
        
        Parameters
        ----------
        step_config : TestStepConfig
            步骤配置
            
        Returns
        -------
        StepResult
            步骤执行结果
        """
        start_time = datetime.now()
        
        try:
            # 创建步骤实例
            step = self._create_step(step_config)
            self.current_step = step
            
            # 准备步骤
            if not await step.prepare(self.context):
                return StepResult(
                    step_id=step_config.id,
                    step_name=step_config.name,
                    success=False,
                    error="步骤准备失败",
                    duration=0.0
                )
            
            # 执行步骤
            result = await step.execute(self.context)
            
            # 验证结果
            if step_config.expect and result.success:
                is_valid = await step.validate(result, step_config.expect)
                if not is_valid:
                    result.success = False
                    result.error = "结果验证失败"
                    result.message = self.validator.get_validation_message(result, step_config.expect)
            
            # 计算耗时
            result.duration = (datetime.now() - start_time).total_seconds()
            
            # 记录日志
            if result.success:
                logger.info(f"步骤 {step_config.id} 执行成功: {result.message}")
            else:
                logger.error(f"步骤 {step_config.id} 执行失败: {result.error}")
            
            return result
            
        except Exception as e:
            logger.error(f"步骤 {step_config.id} 执行异常: {e}")
            return StepResult(
                step_id=step_config.id,
                step_name=step_config.name,
                success=False,
                error=str(e),
                duration=(datetime.now() - start_time).total_seconds()
            )
        finally:
            # 清理步骤
            if 'step' in locals():
                await step.cleanup(self.context)
            self.current_step = None
    
    def _create_step(self, step_config: TestStepConfig) -> IStep:
        """创建步骤实例
        
        Parameters
        ----------
        step_config : TestStepConfig
            步骤配置
            
        Returns
        -------
        IStep
            步骤实例
        """
        # 根据步骤类型创建相应的步骤实例
        step_type = step_config.type
        if step_type.startswith("comm."):
            from .steps.comm_steps import create_comm_step
            return create_comm_step(step_config)
        elif step_type.startswith("instrument."):
            from .steps.instrument_steps import create_instrument_step
            return create_instrument_step(step_config)
        elif step_type.startswith("uut."):
            from .steps.uut_steps import create_uut_step
            return create_uut_step(step_config)
        elif step_type.startswith("mes."):
            # 统一走注册表（cases/mes_steps.py 中已注册），避免旧版 mes_steps 分叉实现。
            from .registry import get_step_class
            step_class = get_step_class(step_type)
            if step_class is None:
                logger.error(f"未知的步骤类型: {step_type}")
                raise ValueError(f"未知的步骤类型: {step_type}")
            return step_class(
                step_id=step_config.id,
                step_name=step_config.name,
                timeout=step_config.timeout or 30,
                retries=step_config.retries,
                on_failure=step_config.on_failure
            )
        elif step_type.startswith("utility."):
            from .steps.utility_steps import create_utility_step
            return create_utility_step(step_config)
        elif step_type.startswith("at."):
            from .steps.at_steps import create_at_step
            return create_at_step(step_config)
        elif step_type in ["state_measurement", "at.led_test", "at.speaker_test", "at.motor_test"]:
            from .steps.state_measurement_steps import create_state_measurement_step
            return create_state_measurement_step(step_config)
        elif step_type in ["manual_judgment", "at.manual_display_test", "at.manual_led_test", "at.manual_audio_test"]:
            from .steps.manual_judgment_steps import create_manual_judgment_step
            return create_manual_judgment_step(step_config)
        elif step_type.startswith("case.") or step_type in ["case.connect", "case.disconnect", "connect_engineer", "disconnect_engineer", "scan.sn", "measure.current"]:
            # 使用注册表创建步骤实例
            from .registry import get_step_class, create_step
            step_class = get_step_class(step_type)
            if step_class is None:
                logger.error(f"未知的步骤类型: {step_type}")
                raise ValueError(f"未知的步骤类型: {step_type}")
            return step_class(
                step_id=step_config.id,
                step_name=step_config.name,
                timeout=step_config.timeout or 30,
                retries=step_config.retries,
                on_failure=step_config.on_failure
            )
        else:
            raise ValueError(f"未知的步骤类型: {step_type}")
    
    def get_current_status(self) -> Dict[str, Any]:
        """获取当前状态
        
        Returns
        -------
        Dict[str, Any]
            当前状态信息
        """
        return {
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "current_step": self.current_step.step_id if self.current_step else None,
            "completed_steps": len(self.step_results),
            "total_steps": len(self.config.steps),
            "skipped_steps": list(self.skipped_steps),
            "mode": self.mode_manager.get_mode_description()
        }
