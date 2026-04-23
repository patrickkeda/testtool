"""
状态切换+测量步骤实现
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from ..step import BaseStep, StepResult
from ..config import StateMeasurementStepConfig, StateControlConfig, MeasurementConfig
from ..context import TestContext
from .at_steps import ATCommunicator

logger = logging.getLogger(__name__)


class MeasurementValidator:
    """测量结果验证器"""
    
    def validate_conditions(self, measurement_results: Dict[str, Any], pass_conditions: List[str]) -> bool:
        """验证测量条件
        
        Parameters
        ----------
        measurement_results : Dict[str, Any]
            测量结果
        pass_conditions : List[str]
            通过条件列表
            
        Returns
        -------
        bool
            是否通过验证
        """
        try:
            for condition in pass_conditions:
                if not self._evaluate_condition(condition, measurement_results):
                    logger.warning(f"条件验证失败: {condition}")
                    return False
            return True
        except Exception as e:
            logger.error(f"条件验证出错: {e}")
            return False
    
    def _evaluate_condition(self, condition: str, measurement_results: Dict[str, Any]) -> bool:
        """评估单个条件
        
        Parameters
        ----------
        condition : str
            条件表达式
        measurement_results : Dict[str, Any]
            测量结果
            
        Returns
        -------
        bool
            条件是否满足
        """
        try:
            # 替换测量结果变量
            for key, value in measurement_results.items():
                if isinstance(value, (int, float)):
                    condition = condition.replace(key, str(value))
                else:
                    condition = condition.replace(key, f'"{value}"')
            
            # 安全评估表达式
            # 只允许基本的比较操作
            allowed_chars = set('0123456789.+-*/<>=!()"\' ')
            if not all(c in allowed_chars for c in condition):
                logger.error(f"条件包含非法字符: {condition}")
                return False
            
            result = eval(condition, {"__builtins__": {}}, {})
            return bool(result)
            
        except Exception as e:
            logger.error(f"条件评估失败: {condition} - {e}")
            return False


class InstrumentController:
    """仪器控制器"""
    
    def __init__(self, instrument_manager):
        self.instrument_manager = instrument_manager
    
    async def measure_voltage(self, channel: int = 1, range_val: str = "auto", samples: int = 1) -> float:
        """测量电压
        
        Parameters
        ----------
        channel : int
            测量通道
        range_val : str
            测量范围
        samples : int
            采样次数
            
        Returns
        -------
        float
            电压值
        """
        try:
            # 获取电压表驱动
            driver = self.instrument_manager.get_driver("voltmeter")
            if not driver:
                raise RuntimeError("电压表驱动不可用")
            
            # 执行测量
            values = []
            for _ in range(samples):
                value = await driver.measure_voltage(channel, range_val)
                values.append(value)
                await asyncio.sleep(0.1)  # 采样间隔
            
            # 返回平均值
            return sum(values) / len(values)
            
        except Exception as e:
            logger.error(f"电压测量失败: {e}")
            raise
    
    async def measure_current(self, channel: int = 1, range_val: str = "auto", samples: int = 1) -> float:
        """测量电流
        
        Parameters
        ----------
        channel : int
            测量通道
        range_val : str
            测量范围
        samples : int
            采样次数
            
        Returns
        -------
        float
            电流值
        """
        try:
            # 获取电流表驱动
            driver = self.instrument_manager.get_driver("ammeter")
            if not driver:
                raise RuntimeError("电流表驱动不可用")
            
            # 执行测量
            values = []
            for _ in range(samples):
                value = await driver.measure_current(channel, range_val)
                values.append(value)
                await asyncio.sleep(0.1)  # 采样间隔
            
            # 返回平均值
            return sum(values) / len(values)
            
        except Exception as e:
            logger.error(f"电流测量失败: {e}")
            raise
    
    async def measure_light_intensity(self, channel: int = 1, range_val: str = "auto", samples: int = 1) -> float:
        """测量光强
        
        Parameters
        ----------
        channel : int
            测量通道
        range_val : str
            测量范围
        samples : int
            采样次数
            
        Returns
        -------
        float
            光强值
        """
        try:
            # 获取光强计驱动
            driver = self.instrument_manager.get_driver("light_meter")
            if not driver:
                raise RuntimeError("光强计驱动不可用")
            
            # 执行测量
            values = []
            for _ in range(samples):
                value = await driver.measure_light_intensity(channel, range_val)
                values.append(value)
                await asyncio.sleep(0.1)  # 采样间隔
            
            # 返回平均值
            return sum(values) / len(values)
            
        except Exception as e:
            logger.error(f"光强测量失败: {e}")
            raise
    
    async def measure_sound_level(self, channel: int = 1, range_val: str = "auto", samples: int = 1) -> float:
        """测量声音强度
        
        Parameters
        ----------
        channel : int
            测量通道
        range_val : str
            测量范围
        samples : int
            采样次数
            
        Returns
        -------
        float
            声音强度值
        """
        try:
            # 获取声级计驱动
            driver = self.instrument_manager.get_driver("sound_meter")
            if not driver:
                raise RuntimeError("声级计驱动不可用")
            
            # 执行测量
            values = []
            for _ in range(samples):
                value = await driver.measure_sound_level(channel, range_val)
                values.append(value)
                await asyncio.sleep(0.1)  # 采样间隔
            
            # 返回平均值
            return sum(values) / len(values)
            
        except Exception as e:
            logger.error(f"声音强度测量失败: {e}")
            raise
    
    async def measure_temperature(self, channel: int = 1, range_val: str = "auto", samples: int = 1) -> float:
        """测量温度
        
        Parameters
        ----------
        channel : int
            测量通道
        range_val : str
            测量范围
        samples : int
            采样次数
            
        Returns
        -------
        float
            温度值
        """
        try:
            # 获取温度计驱动
            driver = self.instrument_manager.get_driver("thermometer")
            if not driver:
                raise RuntimeError("温度计驱动不可用")
            
            # 执行测量
            values = []
            for _ in range(samples):
                value = await driver.measure_temperature(channel, range_val)
                values.append(value)
                await asyncio.sleep(0.1)  # 采样间隔
            
            # 返回平均值
            return sum(values) / len(values)
            
        except Exception as e:
            logger.error(f"温度测量失败: {e}")
            raise


class StateMeasurementStep(BaseStep):
    """状态切换+测量步骤"""
    
    def __init__(self, step_id: str, step_name: str, params: Dict[str, Any]):
        super().__init__(step_id, step_name, params)
        self.at_comm = None
        self.instrument = None
        self.validator = MeasurementValidator()
        
    async def prepare(self, context: TestContext) -> bool:
        """准备状态测量步骤"""
        if not await super().prepare(context):
            return False
            
        # 初始化AT通信器
        self.at_comm = ATCommunicator(context.comm_manager)
        
        # 初始化仪器控制器
        self.instrument = InstrumentController(context.instrument_manager)
        
        # 检查必要参数
        state_control = self.get_param("state_control")
        if not state_control or not state_control.get("at_command"):
            self.log_error("状态控制AT指令不能为空")
            return False
            
        measurements = self.get_param("measurements", [])
        if not measurements:
            self.log_error("测量配置不能为空")
            return False
            
        return True
    
    async def execute(self, context: TestContext) -> StepResult:
        """执行状态测量步骤"""
        try:
            # 1. 执行状态控制
            state_control = self.get_param("state_control")
            at_command = state_control["at_command"]
            port = self.get_param("port", "A")
            timeout = self.get_param("timeout", 5.0)
            
            self.log_info(f"执行状态控制: {at_command}")
            await self.at_comm.send_command(at_command, port, timeout)
            
            # 2. 等待状态稳定
            stabilization_time = state_control.get("stabilization_time", 1000)
            self.log_info(f"等待状态稳定: {stabilization_time}ms")
            await asyncio.sleep(stabilization_time / 1000)
            
            # 3. 执行外部测量
            measurements = self.get_param("measurements", [])
            measurement_results = {}
            
            for measurement in measurements:
                measurement_type = measurement["type"]
                channel = measurement.get("channel", 1)
                range_val = measurement.get("range", "auto")
                samples = measurement.get("samples", 1)
                
                self.log_info(f"执行测量: {measurement_type}, 通道: {channel}")
                
                if measurement_type == "电压测量":
                    value = await self.instrument.measure_voltage(channel, range_val, samples)
                elif measurement_type == "电流测量":
                    value = await self.instrument.measure_current(channel, range_val, samples)
                elif measurement_type == "光强测量":
                    value = await self.instrument.measure_light_intensity(channel, range_val, samples)
                elif measurement_type == "声音测量":
                    value = await self.instrument.measure_sound_level(channel, range_val, samples)
                elif measurement_type == "温度测量":
                    value = await self.instrument.measure_temperature(channel, range_val, samples)
                else:
                    self.log_error(f"不支持的测量类型: {measurement_type}")
                    continue
                
                measurement_results[measurement_type] = value
                self.log_info(f"测量结果: {measurement_type} = {value}")
            
            # 4. 验证测量结果
            pass_conditions = self.get_param("pass_conditions", [])
            passed = self.validator.validate_conditions(measurement_results, pass_conditions)
            
            if passed:
                return self.create_result(
                    success=True,
                    value=measurement_results,
                    message="状态切换+测量执行成功",
                    metadata={
                        "measurement_results": measurement_results,
                        "pass_conditions": pass_conditions
                    }
                )
            else:
                return self.create_result(
                    success=False,
                    value=measurement_results,
                    message="测量结果验证失败",
                    metadata={
                        "measurement_results": measurement_results,
                        "pass_conditions": pass_conditions
                    }
                )
            
        except Exception as e:
            self.log_error(f"状态测量执行失败: {e}", e)
            return self.create_result(
                success=False,
                error=str(e),
                message="状态测量执行失败"
            )
    
    async def validate(self, result: StepResult, expect) -> bool:
        """验证状态测量结果"""
        if not result.success:
            return False
        
        # 对于状态测量步骤，验证在execute方法中已经完成
        return True
    
    async def cleanup(self, context: TestContext):
        """清理状态测量步骤"""
        await super().cleanup(context)


def create_state_measurement_step(step_config) -> StateMeasurementStep:
    """创建状态测量步骤实例
    
    Parameters
    ----------
    step_config : TestStepConfig
        步骤配置
        
    Returns
    -------
    StateMeasurementStep
        状态测量步骤实例
    """
    # 从配置中提取参数
    if step_config.state_measurement_config:
        config = step_config.state_measurement_config
        params = {
            "state_control": {
                "type": config.state_control.type,
                "at_command": config.state_control.at_command,
                "parameters": config.state_control.parameters,
                "stabilization_time": config.state_control.stabilization_time
            },
            "measurements": [
                {
                    "type": m.type,
                    "channel": m.channel,
                    "range": m.range,
                    "samples": m.samples,
                    "expect": m.expect
                }
                for m in config.measurements
            ],
            "pass_conditions": config.pass_conditions,
            "timeout": config.timeout,
            "retries": config.retries
        }
    else:
        # 从传统参数中提取
        params = step_config.params
    
    return StateMeasurementStep(
        step_id=step_config.id,
        step_name=step_config.name,
        params=params
    )
