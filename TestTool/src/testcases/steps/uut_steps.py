"""
UUT测试相关步骤
"""

from typing import Dict, Any
import asyncio
import logging

from ..step import UUTStep, StepResult
from ..config import TestStepConfig

logger = logging.getLogger(__name__)


class ReadSNStep(UUTStep):
    """读取序列号步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行读取序列号"""
        try:
            # 获取参数
            command = self.resolve_param(context, "command", "*IDN?")
            timeout = self.resolve_param(context, "timeout", 2000)
            
            # 通过通信驱动发送命令
            driver_type = self.get_param("driver_type", "default")
            driver = context.get_comm_driver(driver_type)
            
            if not driver:
                return self.create_result(False, error="通信驱动不可用")
            
            # 发送命令
            await driver.send(command.encode(), timeout=timeout)
            
            # 读取响应
            response = await driver.recv(timeout=timeout)
            sn = response.decode().strip() if response else ""
            
            if not sn:
                return self.create_result(False, error="未收到响应")
            
            # 更新上下文中的SN
            context.sn = sn
            
            return self.create_result(
                True,
                value=sn,
                message=f"序列号读取成功: {sn}"
            )
            
        except Exception as e:
            self.log_error(f"读取序列号失败: {e}")
            return self.create_result(False, error=str(e))


class StartTestStep(UUTStep):
    """启动测试步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行启动测试"""
        try:
            # 获取参数
            command = self.resolve_param(context, "command", "START_TEST")
            timeout = self.resolve_param(context, "timeout", 2000)
            
            # 通过通信驱动发送命令
            driver_type = self.get_param("driver_type", "default")
            driver = context.get_comm_driver(driver_type)
            
            if not driver:
                return self.create_result(False, error="通信驱动不可用")
            
            # 发送命令
            await driver.send(command.encode(), timeout=timeout)
            
            # 读取响应
            response = await driver.recv(timeout=timeout)
            result = response.decode().strip() if response else ""
            
            if not result:
                return self.create_result(False, error="未收到响应")
            
            return self.create_result(
                True,
                value=result,
                message=f"测试启动成功: {result}"
            )
            
        except Exception as e:
            self.log_error(f"启动测试失败: {e}")
            return self.create_result(False, error=str(e))


class ReadMeasurementStep(UUTStep):
    """读取测量值步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行读取测量值"""
        try:
            # 获取参数
            command = self.resolve_param(context, "command", "READ_MEAS")
            timeout = self.resolve_param(context, "timeout", 2000)
            unit = self.resolve_param(context, "unit", "")
            
            # 通过通信驱动发送命令
            driver_type = self.get_param("driver_type", "default")
            driver = context.get_comm_driver(driver_type)
            
            if not driver:
                return self.create_result(False, error="通信驱动不可用")
            
            # 发送命令
            await driver.send(command.encode(), timeout=timeout)
            
            # 读取响应
            response = await driver.recv(timeout=timeout)
            result = response.decode().strip() if response else ""
            
            if not result:
                return self.create_result(False, error="未收到响应")
            
            # 尝试转换为数字
            try:
                value = float(result)
            except ValueError:
                value = result
            
            return self.create_result(
                True,
                value=value,
                unit=unit,
                message=f"测量值读取成功: {value}{unit}"
            )
            
        except Exception as e:
            self.log_error(f"读取测量值失败: {e}")
            return self.create_result(False, error=str(e))


class WaitStep(UUTStep):
    """等待步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行等待"""
        try:
            # 获取参数
            duration = self.resolve_param(context, "duration", 1000)  # 毫秒
            condition = self.get_param("condition", None)
            
            if condition:
                # 条件等待
                timeout = self.resolve_param(context, "timeout", 10000)
                start_time = asyncio.get_event_loop().time()
                
                while (asyncio.get_event_loop().time() - start_time) * 1000 < timeout:
                    if context.resolve_expression(condition):
                        return self.create_result(
                            True,
                            message=f"条件满足: {condition}"
                        )
                    await asyncio.sleep(0.1)
                
                return self.create_result(
                    False,
                    error=f"等待条件超时: {condition}"
                )
            else:
                # 固定时间等待
                await asyncio.sleep(duration / 1000.0)
                
                return self.create_result(
                    True,
                    message=f"等待完成: {duration}ms"
                )
            
        except Exception as e:
            self.log_error(f"等待失败: {e}")
            return self.create_result(False, error=str(e))


def create_uut_step(step_config: TestStepConfig) -> UUTStep:
    """创建UUT步骤实例
    
    Parameters
    ----------
    step_config : TestStepConfig
        步骤配置
        
    Returns
    -------
    UUTStep
        UUT步骤实例
    """
    step_type = step_config.type
    
    if step_type == "uut.read_sn":
        return ReadSNStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "uut.start_test":
        return StartTestStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "uut.read_measurement":
        return ReadMeasurementStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "uut.wait":
        return WaitStep(step_config.id, step_config.name, step_config.params)
    else:
        raise ValueError(f"未知的UUT步骤类型: {step_type}")
