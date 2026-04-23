"""
测试步骤基类模块

提供测试步骤的基础实现，包括重试、超时、异常处理等通用功能。
"""
import time
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass
from datetime import datetime

from .context import Context


@dataclass
class StepResult:
    """
    步骤执行结果
    
    Attributes:
        passed: 是否通过
        data: 测试数据字典
        message: 结果消息
        error: 错误信息（如果有）
        error_code: 错误代码（如果有）
        duration: 执行时长（秒）
    """
    passed: bool
    data: Dict[str, Any] = None
    message: str = ""
    error: Optional[str] = None
    error_code: Optional[str] = None
    duration: float = 0.0
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}


class BaseStep(ABC):
    """
    测试步骤基类
    
    提供通用的重试、超时、异常处理机制。
    子类只需实现 run_once 方法定义具体的测试逻辑。
    """
    
    def __init__(self, step_id: str, step_name: str, 
                 timeout: int = 30, retries: int = 0, 
                 on_failure: str = "fail"):
        """
        初始化测试步骤
        
        Args:
            step_id: 步骤ID
            step_name: 步骤名称
            timeout: 超时时间（秒）
            retries: 重试次数
            on_failure: 失败策略 (fail/continue/stop_port/stop_all)
        """
        self.step_id = step_id
        self.step_name = step_name
        self.timeout = timeout
        self.retries = retries
        self.on_failure = on_failure
        self.logger = logging.getLogger(f"Step.{step_id}")
    
    def run(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行测试步骤（包含重试和超时处理）
        
        Args:
            ctx: 测试上下文
            params: 步骤参数
            
        Returns:
            StepResult: 步骤执行结果
        """
        start_time = time.time()
        last_error = None
        
        self.logger.info(f"开始执行步骤: {self.step_name}")
        self.logger.debug(f"参数: {params}")
        
        # 执行重试循环
        for attempt in range(self.retries + 1):
            try:
                if attempt > 0:
                    self.logger.info(f"重试第 {attempt} 次")
                    ctx.sleep_ms(1000)  # 重试前等待1秒
                
                # 执行具体步骤逻辑
                result = self.run_once(ctx, params)
                
                # 记录执行时间
                duration = time.time() - start_time
                result.duration = duration
                
                # 记录结果
                if result.passed:
                    self.logger.info(f"步骤通过: {result.message}")
                    # 步骤成功后等待1秒，确保硬件有足够时间响应
                    ctx.sleep_ms(1000)
                else:
                    self.logger.warning(f"步骤失败: {result.message}")
                
                return result
                
            except Exception as e:
                last_error = str(e)
                self.logger.error(f"步骤执行异常 (尝试 {attempt + 1}/{self.retries + 1}): {e}")
                
                # 如果是最后一次尝试，返回失败结果
                if attempt == self.retries:
                    duration = time.time() - start_time
                    return StepResult(
                        passed=False,
                        message=f"步骤执行失败: {self.step_name}",
                        error=last_error,
                        duration=duration
                    )
        
        # 理论上不会到达这里
        duration = time.time() - start_time
        return StepResult(
            passed=False,
            message=f"步骤执行失败: {self.step_name}",
            error=last_error or "未知错误",
            duration=duration
        )
    
    @abstractmethod
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行一次步骤逻辑（子类必须实现）
        
        Args:
            ctx: 测试上下文
            params: 步骤参数
            
        Returns:
            StepResult: 步骤执行结果
        """
        pass
    
    def get_param(self, params: Dict[str, Any], key: str, default: Any = None) -> Any:
        """
        获取参数值
        
        Args:
            params: 参数字典
            key: 参数名
            default: 默认值
            
        Returns:
            参数值
        """
        return params.get(key, default)
    
    def get_param_float(self, params: Dict[str, Any], key: str, default: float = 0.0) -> float:
        """获取浮点数参数"""
        try:
            return float(self.get_param(params, key, default))
        except (ValueError, TypeError):
            self.logger.warning(f"参数 {key} 不是有效的浮点数，使用默认值 {default}")
            return default
    
    def get_param_int(self, params: Dict[str, Any], key: str, default: int = 0) -> int:
        """获取整数参数"""
        try:
            return int(self.get_param(params, key, default))
        except (ValueError, TypeError):
            self.logger.warning(f"参数 {key} 不是有效的整数，使用默认值 {default}")
            return default
    
    def get_param_str(self, params: Dict[str, Any], key: str, default: str = "") -> str:
        """获取字符串参数"""
        value = self.get_param(params, key, default)
        return str(value) if value is not None else default
    
    def get_param_bool(self, params: Dict[str, Any], key: str, default: bool = False) -> bool:
        """获取布尔参数"""
        value = self.get_param(params, key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on', 'enabled')
        return bool(value)
    
    def validate_required_params(self, params: Dict[str, Any], required_keys: list) -> bool:
        """
        验证必需参数是否存在
        
        Args:
            params: 参数字典
            required_keys: 必需参数列表
            
        Returns:
            是否所有必需参数都存在
        """
        missing_keys = [key for key in required_keys if key not in params]
        if missing_keys:
            self.logger.error(f"缺少必需参数: {missing_keys}")
            return False
        return True
    
    def create_success_result(self, data: Dict[str, Any] = None, message: str = "") -> StepResult:
        """创建成功结果"""
        return StepResult(
            passed=True,
            data=data or {},
            message=message or f"{self.step_name} 执行成功"
        )
    
    def create_failure_result(self, message: str, error: str = None, data: Dict[str, Any] = None) -> StepResult:
        """创建失败结果"""
        return StepResult(
            passed=False,
            data=data or {},
            message=message,
            error=error
        )
    
    def log_step_start(self, ctx: Context, params: Dict[str, Any]):
        """记录步骤开始日志"""
        ctx.log_info(f"开始执行步骤: {self.step_name}")
        ctx.log_debug(f"步骤参数: {params}")
    
    def log_step_end(self, ctx: Context, result: StepResult):
        """记录步骤结束日志"""
        if result.passed:
            ctx.log_info(f"步骤完成: {result.message}")
        else:
            ctx.log_error(f"步骤失败: {result.message}")
            if result.error:
                ctx.log_error(f"错误详情: {result.error}")


class CommunicationStep(BaseStep):
    """通信步骤基类"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """通信步骤的通用实现"""
        # 检查UUT连接
        if not ctx.uut:
            return self.create_failure_result("UUT连接不可用")
        
        return self.execute_communication(ctx, params)
    
    @abstractmethod
    def execute_communication(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """执行具体的通信逻辑"""
        pass


class InstrumentStep(BaseStep):
    """仪器步骤基类"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """仪器步骤的通用实现"""
        # 获取仪器ID
        instrument_id = self.get_param_str(params, "instrument_id", "default")
        
        # 检查仪器是否可用
        if not ctx.has_instrument(instrument_id):
            return self.create_failure_result(f"仪器 {instrument_id} 不可用")
        
        return self.execute_instrument(ctx, params)
    
    @abstractmethod
    def execute_instrument(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """执行具体的仪器操作"""
        pass


class FixtureStep(BaseStep):
    """治具步骤基类"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """治具步骤的通用实现"""
        # 检查治具连接
        if not ctx.fixture:
            return self.create_failure_result("治具连接不可用")
        
        return self.execute_fixture(ctx, params)
    
    @abstractmethod
    def execute_fixture(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """执行具体的治具操作"""
        pass


class UtilityStep(BaseStep):
    """工具步骤基类（如延时、判断等）"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """工具步骤的通用实现"""
        return self.execute_utility(ctx, params)
    
    @abstractmethod
    def execute_utility(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """执行具体的工具操作"""
        pass
