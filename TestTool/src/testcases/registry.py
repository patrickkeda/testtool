"""
测试步骤注册机制

提供步骤类型的注册和实例化功能。
"""
import logging
from typing import Dict, Type, Any, Optional
from .base import BaseStep

logger = logging.getLogger(__name__)


class StepRegistry:
    """测试步骤注册表"""
    
    def __init__(self):
        self._steps: Dict[str, Type[BaseStep]] = {}
        self._aliases: Dict[str, str] = {}  # 别名映射
    
    def register(self, step_type: str, step_class: Type[BaseStep], aliases: list = None):
        """
        注册测试步骤类
        
        Args:
            step_type: 步骤类型标识
            step_class: 步骤类
            aliases: 别名列表
        """
        if not issubclass(step_class, BaseStep):
            raise ValueError(f"步骤类 {step_class.__name__} 必须继承自 BaseStep")
        
        self._steps[step_type] = step_class
        logger.info(f"注册步骤类型: {step_type} -> {step_class.__name__}")
        
        # 注册别名
        if aliases:
            for alias in aliases:
                self._aliases[alias] = step_type
                logger.debug(f"注册步骤别名: {alias} -> {step_type}")
    
    def unregister(self, step_type: str):
        """注销步骤类型"""
        if step_type in self._steps:
            del self._steps[step_type]
            logger.info(f"注销步骤类型: {step_type}")
            
            # 清理相关别名
            aliases_to_remove = [alias for alias, st in self._aliases.items() if st == step_type]
            for alias in aliases_to_remove:
                del self._aliases[alias]
    
    def get_step_class(self, step_type: str) -> Optional[Type[BaseStep]]:
        """
        获取步骤类
        
        Args:
            step_type: 步骤类型或别名
            
        Returns:
            步骤类，如果不存在则返回None
        """
        # 先检查直接类型
        if step_type in self._steps:
            return self._steps[step_type]
        
        # 再检查别名
        actual_type = self._aliases.get(step_type)
        if actual_type and actual_type in self._steps:
            return self._steps[actual_type]
        
        return None
    
    def create_step(self, step_type: str, step_id: str, step_name: str, 
                   timeout: int = 30, retries: int = 0, on_failure: str = "fail") -> Optional[BaseStep]:
        """
        创建步骤实例
        
        Args:
            step_type: 步骤类型
            step_id: 步骤ID
            step_name: 步骤名称
            timeout: 超时时间
            retries: 重试次数
            on_failure: 失败策略
            
        Returns:
            步骤实例，如果类型不存在则返回None
        """
        step_class = self.get_step_class(step_type)
        if step_class is None:
            logger.error(f"未知的步骤类型: {step_type}")
            return None
        
        try:
            return step_class(
                step_id=step_id,
                step_name=step_name,
                timeout=timeout,
                retries=retries,
                on_failure=on_failure
            )
        except Exception as e:
            logger.error(f"创建步骤实例失败: {e}")
            return None
    
    def list_step_types(self) -> list:
        """列出所有已注册的步骤类型"""
        return list(self._steps.keys())
    
    def list_aliases(self) -> Dict[str, str]:
        """列出所有别名映射"""
        return self._aliases.copy()
    
    def is_registered(self, step_type: str) -> bool:
        """检查步骤类型是否已注册"""
        return step_type in self._steps or step_type in self._aliases
    
    def get_step_info(self, step_type: str) -> Optional[Dict[str, Any]]:
        """
        获取步骤类型信息
        
        Args:
            step_type: 步骤类型
            
        Returns:
            步骤信息字典，包含类名、文档等
        """
        step_class = self.get_step_class(step_type)
        if step_class is None:
            return None
        
        return {
            "type": step_type,
            "class_name": step_class.__name__,
            "module": step_class.__module__,
            "docstring": step_class.__doc__,
            "is_communication": issubclass(step_class, BaseStep),  # 可以根据需要扩展
        }


# 全局注册表实例
_registry = StepRegistry()


def register(step_type: str, step_class: Type[BaseStep], aliases: list = None):
    """
    注册测试步骤（全局函数）
    
    Args:
        step_type: 步骤类型标识
        step_class: 步骤类
        aliases: 别名列表
    """
    _registry.register(step_type, step_class, aliases)


def unregister(step_type: str):
    """注销步骤类型（全局函数）"""
    _registry.unregister(step_type)


def get_step_class(step_type: str) -> Optional[Type[BaseStep]]:
    """获取步骤类（全局函数）"""
    return _registry.get_step_class(step_type)


def create_step(step_type: str, step_id: str, step_name: str, 
               timeout: int = 30, retries: int = 0, on_failure: str = "fail") -> Optional[BaseStep]:
    """创建步骤实例（全局函数）"""
    return _registry.create_step(step_type, step_id, step_name, timeout, retries, on_failure)


def list_step_types() -> list:
    """列出所有步骤类型（全局函数）"""
    return _registry.list_step_types()


def is_registered(step_type: str) -> bool:
    """检查步骤类型是否已注册（全局函数）"""
    return _registry.is_registered(step_type)


def get_registry() -> StepRegistry:
    """获取注册表实例"""
    return _registry


# 便捷的装饰器
def step_type(step_type_name: str, aliases: list = None):
    """
    步骤类型装饰器
    
    Usage:
        @step_type("measure.voltage", aliases=["voltage", "measure_v"])
        class MeasureVoltageStep(BaseStep):
            pass
    """
    def decorator(step_class: Type[BaseStep]):
        register(step_type_name, step_class, aliases)
        return step_class
    return decorator
