"""
测试步骤接口和基类
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """步骤结果"""
    step_id: str
    step_name: str
    success: bool
    value: Any = None
    unit: str = ""
    message: str = ""
    duration: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class IStep(ABC):
    """测试步骤接口"""
    
    def __init__(self, step_id: str, step_name: str, params: Dict[str, Any]):
        self.step_id = step_id
        self.step_name = step_name
        self.params = params
        
    @abstractmethod
    async def prepare(self, context: 'TestContext') -> bool:
        """步骤准备
        
        Parameters
        ----------
        context : TestContext
            测试上下文
            
        Returns
        -------
        bool
            准备是否成功
        """
        pass
        
    @abstractmethod
    async def execute(self, context: 'TestContext') -> StepResult:
        """执行步骤
        
        Parameters
        ----------
        context : TestContext
            测试上下文
            
        Returns
        -------
        StepResult
            步骤执行结果
        """
        pass
        
    @abstractmethod
    async def validate(self, result: StepResult, expect: 'ExpectConfig') -> bool:
        """验证结果
        
        Parameters
        ----------
        result : StepResult
            步骤结果
        expect : ExpectConfig
            期望结果配置
            
        Returns
        -------
        bool
            验证是否通过
        """
        pass
        
    @abstractmethod
    async def cleanup(self, context: 'TestContext'):
        """清理资源
        
        Parameters
        ----------
        context : TestContext
            测试上下文
        """
        pass


class BaseStep(IStep):
    """测试步骤基类"""
    
    def __init__(self, step_id: str, step_name: str, params: Dict[str, Any]):
        super().__init__(step_id, step_name, params)
        self.logger = logging.getLogger(f"Step.{step_id}")
        
    async def prepare(self, context: 'TestContext') -> bool:
        """默认准备实现"""
        self.logger.debug(f"准备步骤: {self.step_name}")
        return True
        
    async def cleanup(self, context: 'TestContext'):
        """默认清理实现"""
        self.logger.debug(f"清理步骤: {self.step_name}")
        
    def get_param(self, key: str, default: Any = None) -> Any:
        """获取参数值
        
        Parameters
        ----------
        key : str
            参数名
        default : Any
            默认值
            
        Returns
        -------
        Any
            参数值
        """
        return self.params.get(key, default)
        
    def resolve_param(self, context: 'TestContext', key: str, default: Any = None) -> Any:
        """解析参数值（支持变量替换）
        
        Parameters
        ----------
        context : TestContext
            测试上下文
        key : str
            参数名
        default : Any
            默认值
            
        Returns
        -------
        Any
            解析后的参数值
        """
        value = self.get_param(key, default)
        if isinstance(value, str):
            return context.resolve_expression(value)
        return value
        
    def create_result(self, success: bool, value: Any = None, unit: str = "", 
                     message: str = "", error: str = None, metadata: Dict[str, Any] = None) -> StepResult:
        """创建步骤结果
        
        Parameters
        ----------
        success : bool
            是否成功
        value : Any
            结果值
        unit : str
            单位
        message : str
            消息
        error : str
            错误信息
        metadata : Dict[str, Any]
            元数据
            
        Returns
        -------
        StepResult
            步骤结果
        """
        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            success=success,
            value=value,
            unit=unit,
            message=message,
            error=error,
            metadata=metadata or {}
        )
        
    def log_info(self, message: str):
        """记录信息日志"""
        self.logger.info(f"{self.step_name}: {message}")
        
    def log_error(self, message: str, error: Exception = None):
        """记录错误日志"""
        if error:
            self.logger.error(f"{self.step_name}: {message} - {error}")
        else:
            self.logger.error(f"{self.step_name}: {message}")
            
    def log_debug(self, message: str):
        """记录调试日志"""
        self.logger.debug(f"{self.step_name}: {message}")


class CommStep(BaseStep):
    """通信步骤基类"""
    
    async def prepare(self, context: 'TestContext') -> bool:
        """准备通信步骤"""
        if not await super().prepare(context):
            return False
            
        # 检查通信驱动是否可用
        driver_type = self.get_param("driver_type", "default")
        driver = context.get_comm_driver(driver_type)
        if not driver:
            self.log_error(f"通信驱动 {driver_type} 不可用")
            return False
            
        return True


class InstrumentStep(BaseStep):
    """仪器步骤基类"""
    
    async def prepare(self, context: 'TestContext') -> bool:
        """准备仪器步骤"""
        if not await super().prepare(context):
            return False
            
        # 检查仪器驱动是否可用
        instrument_type = self.get_param("instrument_type", "default")
        driver = context.get_instrument_driver(instrument_type)
        if not driver:
            self.log_error(f"仪器驱动 {instrument_type} 不可用")
            return False
            
        return True


class UUTStep(BaseStep):
    """UUT步骤基类"""
    
    async def prepare(self, context: 'TestContext') -> bool:
        """准备UUT步骤"""
        if not await super().prepare(context):
            return False
            
        # 检查UUT连接是否可用
        if not context.sn:
            self.log_error("SN未设置")
            return False
            
        return True


class MesStep(BaseStep):
    """MES步骤基类"""
    
    async def prepare(self, context: 'TestContext') -> bool:
        """准备MES步骤"""
        if not await super().prepare(context):
            return False
            
        # 检查MES客户端是否可用
        if not context.mes_client:
            self.log_error("MES客户端不可用")
            return False
            
        return True


class UtilityStep(BaseStep):
    """工具步骤基类"""
    
    async def prepare(self, context: 'TestContext') -> bool:
        """准备工具步骤"""
        return await super().prepare(context)
