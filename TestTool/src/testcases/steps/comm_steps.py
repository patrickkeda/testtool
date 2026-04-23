"""
通信相关测试步骤
"""

from typing import Dict, Any
import asyncio
import logging

from ..step import CommStep, StepResult
from ..config import TestStepConfig

logger = logging.getLogger(__name__)


class OpenCommStep(CommStep):
    """打开通信连接步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行打开通信连接"""
        try:
            driver_type = self.get_param("driver_type", "default")
            driver = context.get_comm_driver(driver_type)
            
            if not driver:
                return self.create_result(False, error="通信驱动不可用")
            
            # 获取连接参数
            interface = self.resolve_param(context, "interface", "serial")
            port = self.resolve_param(context, "port", "COM3")
            baudrate = self.resolve_param(context, "baudrate", 115200)
            
            # 打开连接
            await driver.connect()
            
            return self.create_result(
                True,
                message=f"通信连接已打开: {interface} {port} {baudrate}"
            )
            
        except Exception as e:
            self.log_error(f"打开通信连接失败: {e}")
            return self.create_result(False, error=str(e))


class SendCommandStep(CommStep):
    """发送命令步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行发送命令"""
        try:
            driver_type = self.get_param("driver_type", "default")
            driver = context.get_comm_driver(driver_type)
            
            if not driver:
                return self.create_result(False, error="通信驱动不可用")
            
            # 获取命令参数
            command = self.resolve_param(context, "command", "")
            timeout = self.resolve_param(context, "timeout", 2000)
            
            if not command:
                return self.create_result(False, error="命令为空")
            
            # 发送命令
            await driver.send(command.encode(), timeout=timeout)
            
            return self.create_result(
                True,
                value=command,
                message=f"命令发送成功: {command}"
            )
            
        except Exception as e:
            self.log_error(f"发送命令失败: {e}")
            return self.create_result(False, error=str(e))


class ReadResponseStep(CommStep):
    """读取响应步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行读取响应"""
        try:
            driver_type = self.get_param("driver_type", "default")
            driver = context.get_comm_driver(driver_type)
            
            if not driver:
                return self.create_result(False, error="通信驱动不可用")
            
            # 获取参数
            timeout = self.resolve_param(context, "timeout", 2000)
            max_length = self.resolve_param(context, "max_length", 1024)
            
            # 读取响应
            response = await driver.recv(timeout=timeout, max_length=max_length)
            response_str = response.decode() if response else ""
            
            return self.create_result(
                True,
                value=response_str,
                message=f"响应读取成功: {response_str}"
            )
            
        except Exception as e:
            self.log_error(f"读取响应失败: {e}")
            return self.create_result(False, error=str(e))


class CloseCommStep(CommStep):
    """关闭通信连接步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行关闭通信连接"""
        try:
            driver_type = self.get_param("driver_type", "default")
            driver = context.get_comm_driver(driver_type)
            
            if not driver:
                return self.create_result(False, error="通信驱动不可用")
            
            # 关闭连接
            await driver.disconnect()
            
            return self.create_result(
                True,
                message="通信连接已关闭"
            )
            
        except Exception as e:
            self.log_error(f"关闭通信连接失败: {e}")
            return self.create_result(False, error=str(e))


def create_comm_step(step_config: TestStepConfig) -> CommStep:
    """创建通信步骤实例
    
    Parameters
    ----------
    step_config : TestStepConfig
        步骤配置
        
    Returns
    -------
    CommStep
        通信步骤实例
    """
    step_type = step_config.type
    
    if step_type == "comm.open":
        return OpenCommStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "comm.send_command":
        return SendCommandStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "comm.read_response":
        return ReadResponseStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "comm.close":
        return CloseCommStep(step_config.id, step_config.name, step_config.params)
    else:
        raise ValueError(f"未知的通信步骤类型: {step_type}")
