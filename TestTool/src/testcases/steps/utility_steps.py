"""
工具相关测试步骤
"""

from typing import Dict, Any
import asyncio
import logging

from ..step import UtilityStep, StepResult
from ..config import TestStepConfig

logger = logging.getLogger(__name__)


class DelayStep(UtilityStep):
    """延迟步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行延迟"""
        try:
            # 获取参数
            duration = self.resolve_param(context, "duration", 1000)  # 毫秒
            
            # 延迟
            await asyncio.sleep(duration / 1000.0)
            
            return self.create_result(
                True,
                message=f"延迟完成: {duration}ms"
            )
            
        except Exception as e:
            self.log_error(f"延迟失败: {e}")
            return self.create_result(False, error=str(e))


class LogStep(UtilityStep):
    """日志记录步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行日志记录"""
        try:
            # 获取参数
            message = self.resolve_param(context, "message", "")
            level = self.resolve_param(context, "level", "INFO")
            
            # 记录日志
            if level == "DEBUG":
                self.log_debug(message)
            elif level == "INFO":
                self.log_info(message)
            elif level == "WARNING":
                logger.warning(f"{self.step_name}: {message}")
            elif level == "ERROR":
                self.log_error(message)
            else:
                self.log_info(message)
            
            return self.create_result(
                True,
                message=f"日志记录完成: {message}"
            )
            
        except Exception as e:
            self.log_error(f"日志记录失败: {e}")
            return self.create_result(False, error=str(e))


class SetVariableStep(UtilityStep):
    """设置变量步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行设置变量"""
        try:
            # 获取参数
            name = self.resolve_param(context, "name", "")
            value = self.resolve_param(context, "value", "")
            
            if not name:
                return self.create_result(False, error="变量名为空")
            
            # 设置变量
            context.set_variable(name, value)
            
            return self.create_result(
                True,
                value=value,
                message=f"变量设置成功: {name} = {value}"
            )
            
        except Exception as e:
            self.log_error(f"设置变量失败: {e}")
            return self.create_result(False, error=str(e))


class IfStep(UtilityStep):
    """条件判断步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行条件判断"""
        try:
            # 获取参数
            condition = self.resolve_param(context, "condition", "")
            true_action = self.get_param("true_action", None)
            false_action = self.get_param("false_action", None)
            
            if not condition:
                return self.create_result(False, error="条件为空")
            
            # 评估条件
            is_true = context.resolve_expression(condition)
            
            if is_true:
                action = true_action
                message = f"条件为真: {condition}"
            else:
                action = false_action
                message = f"条件为假: {condition}"
            
            # 执行相应动作
            if action:
                # 这里可以执行更复杂的动作，比如调用其他步骤
                pass
            
            return self.create_result(
                True,
                value=is_true,
                message=message
            )
            
        except Exception as e:
            self.log_error(f"条件判断失败: {e}")
            return self.create_result(False, error=str(e))


class LoopStep(UtilityStep):
    """循环步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行循环"""
        try:
            # 获取参数
            count = self.resolve_param(context, "count", 1)
            step_id = self.get_param("step_id", "")
            
            if not step_id:
                return self.create_result(False, error="步骤ID为空")
            
            # 执行循环
            for i in range(count):
                # 这里可以执行指定的步骤
                # 实际实现中需要调用测试运行器来执行步骤
                pass
            
            return self.create_result(
                True,
                value=count,
                message=f"循环完成: {count}次"
            )
            
        except Exception as e:
            self.log_error(f"循环执行失败: {e}")
            return self.create_result(False, error=str(e))


def create_utility_step(step_config: TestStepConfig) -> UtilityStep:
    """创建工具步骤实例
    
    Parameters
    ----------
    step_config : TestStepConfig
        步骤配置
        
    Returns
    -------
    UtilityStep
        工具步骤实例
    """
    step_type = step_config.type
    
    if step_type == "utility.delay":
        return DelayStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "utility.log":
        return LogStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "utility.set_variable":
        return SetVariableStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "utility.if":
        return IfStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "utility.loop":
        return LoopStep(step_config.id, step_config.name, step_config.params)
    else:
        raise ValueError(f"未知的工具步骤类型: {step_type}")
