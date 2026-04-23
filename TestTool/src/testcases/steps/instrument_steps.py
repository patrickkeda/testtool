"""
仪器控制相关测试步骤
"""

from typing import Dict, Any
import asyncio
import logging

from ..step import InstrumentStep, StepResult
from ..config import TestStepConfig

logger = logging.getLogger(__name__)


class SetVoltageStep(InstrumentStep):
    """设置电压步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行设置电压"""
        try:
            instrument_type = self.get_param("instrument_type", "default")
            driver = context.get_instrument_driver(instrument_type)
            
            if not driver:
                return self.create_result(False, error="仪器驱动不可用")
            
            # 获取参数
            channel = self.resolve_param(context, "channel", 1)
            voltage = self.resolve_param(context, "voltage", 0.0)
            
            # 设置电压
            await driver.set_voltage(channel, voltage)
            
            return self.create_result(
                True,
                value=voltage,
                unit="V",
                message=f"电压设置成功: {voltage}V (通道{channel})"
            )
            
        except Exception as e:
            self.log_error(f"设置电压失败: {e}")
            return self.create_result(False, error=str(e))


class SetCurrentStep(InstrumentStep):
    """设置电流步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行设置电流"""
        try:
            instrument_type = self.get_param("instrument_type", "default")
            driver = context.get_instrument_driver(instrument_type)
            
            if not driver:
                return self.create_result(False, error="仪器驱动不可用")
            
            # 获取参数
            channel = self.resolve_param(context, "channel", 1)
            current = self.resolve_param(context, "current", 0.0)
            
            # 设置电流
            await driver.set_current_limit(channel, current)
            
            return self.create_result(
                True,
                value=current,
                unit="A",
                message=f"电流设置成功: {current}A (通道{channel})"
            )
            
        except Exception as e:
            self.log_error(f"设置电流失败: {e}")
            return self.create_result(False, error=str(e))


class MeasureVoltageStep(InstrumentStep):
    """测量电压步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行测量电压"""
        try:
            instrument_type = self.get_param("instrument_type", "default")
            driver = context.get_instrument_driver(instrument_type)
            
            if not driver:
                return self.create_result(False, error="仪器驱动不可用")
            
            # 获取参数
            channel = self.resolve_param(context, "channel", 1)
            
            # 测量电压
            voltage = await driver.measure_voltage(channel)
            
            return self.create_result(
                True,
                value=voltage,
                unit="V",
                message=f"电压测量成功: {voltage}V (通道{channel})"
            )
            
        except Exception as e:
            self.log_error(f"测量电压失败: {e}")
            return self.create_result(False, error=str(e))


class MeasureCurrentStep(InstrumentStep):
    """测量电流步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行测量电流"""
        try:
            instrument_type = self.get_param("instrument_type", "default")
            driver = context.get_instrument_driver(instrument_type)
            
            if not driver:
                return self.create_result(False, error="仪器驱动不可用")
            
            # 获取参数
            channel = self.resolve_param(context, "channel", 1)
            
            # 测量电流
            current = await driver.measure_current(channel)
            
            return self.create_result(
                True,
                value=current,
                unit="A",
                message=f"电流测量成功: {current}A (通道{channel})"
            )
            
        except Exception as e:
            self.log_error(f"测量电流失败: {e}")
            return self.create_result(False, error=str(e))


class OutputOnStep(InstrumentStep):
    """开启输出步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行开启输出"""
        try:
            instrument_type = self.get_param("instrument_type", "default")
            driver = context.get_instrument_driver(instrument_type)
            
            if not driver:
                return self.create_result(False, error="仪器驱动不可用")
            
            # 获取参数
            channel = self.resolve_param(context, "channel", 1)
            
            # 开启输出
            await driver.output(True, channel)
            
            return self.create_result(
                True,
                message=f"输出已开启 (通道{channel})"
            )
            
        except Exception as e:
            self.log_error(f"开启输出失败: {e}")
            return self.create_result(False, error=str(e))


class OutputOffStep(InstrumentStep):
    """关闭输出步骤"""
    
    async def execute(self, context) -> StepResult:
        """执行关闭输出"""
        try:
            instrument_type = self.get_param("instrument_type", "default")
            driver = context.get_instrument_driver(instrument_type)
            
            if not driver:
                return self.create_result(False, error="仪器驱动不可用")
            
            # 获取参数
            channel = self.resolve_param(context, "channel", 1)
            
            # 关闭输出
            await driver.output(False, channel)
            
            return self.create_result(
                True,
                message=f"输出已关闭 (通道{channel})"
            )
            
        except Exception as e:
            self.log_error(f"关闭输出失败: {e}")
            return self.create_result(False, error=str(e))


def create_instrument_step(step_config: TestStepConfig) -> InstrumentStep:
    """创建仪器步骤实例
    
    Parameters
    ----------
    step_config : TestStepConfig
        步骤配置
        
    Returns
    -------
    InstrumentStep
        仪器步骤实例
    """
    step_type = step_config.type
    
    if step_type == "instrument.set_voltage":
        return SetVoltageStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "instrument.set_current":
        return SetCurrentStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "instrument.measure_voltage":
        return MeasureVoltageStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "instrument.measure_current":
        return MeasureCurrentStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "instrument.output_on":
        return OutputOnStep(step_config.id, step_config.name, step_config.params)
    elif step_type == "instrument.output_off":
        return OutputOffStep(step_config.id, step_config.name, step_config.params)
    else:
        raise ValueError(f"未知的仪器步骤类型: {step_type}")
