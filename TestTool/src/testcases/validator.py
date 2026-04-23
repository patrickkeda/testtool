"""
结果验证器 - 验证测试结果是否符合预期
"""

import re
from typing import Any, Optional
import logging

from .config import ExpectConfig

logger = logging.getLogger(__name__)


class ResultValidator:
    """结果验证器"""
    
    def __init__(self):
        self.custom_validators = {}
        
    def validate(self, result: 'StepResult', expect: ExpectConfig) -> bool:
        """验证测试结果
        
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
        if not result.success:
            logger.warning(f"步骤 {result.step_id} 执行失败，跳过验证")
            return False
            
        if expect.type == "range":
            return self.validate_range(result.value, expect.min_val, expect.max_val)
        elif expect.type == "regex":
            return self.validate_regex(result.value, expect.regex)
        elif expect.type == "exact":
            return self.validate_exact(result.value, expect.value)
        elif expect.type == "custom":
            return self.validate_custom(result.value, expect.custom_validator)
        else:
            logger.error(f"未知的验证类型: {expect.type}")
            return False
            
    def validate_range(self, value: float, min_val: float, max_val: float) -> bool:
        """范围验证
        
        Parameters
        ----------
        value : float
            实际值
        min_val : float
            最小值
        max_val : float
            最大值
            
        Returns
        -------
        bool
            验证是否通过
        """
        try:
            num_value = float(value)
            is_valid = min_val <= num_value <= max_val
            logger.debug(f"范围验证: {num_value} in [{min_val}, {max_val}] = {is_valid}")
            return is_valid
        except (ValueError, TypeError) as e:
            logger.error(f"范围验证失败，值无法转换为数字: {value}, 错误: {e}")
            return False
            
    def validate_regex(self, value: str, pattern: str) -> bool:
        """正则表达式验证
        
        Parameters
        ----------
        value : str
            实际值
        pattern : str
            正则表达式
            
        Returns
        -------
        bool
            验证是否通过
        """
        try:
            str_value = str(value)
            is_valid = bool(re.match(pattern, str_value))
            logger.debug(f"正则验证: '{str_value}' matches '{pattern}' = {is_valid}")
            return is_valid
        except re.error as e:
            logger.error(f"正则表达式验证失败，模式无效: {pattern}, 错误: {e}")
            return False
            
    def validate_exact(self, value: Any, expected: Any) -> bool:
        """精确匹配验证
        
        Parameters
        ----------
        value : Any
            实际值
        expected : Any
            期望值
            
        Returns
        -------
        bool
            验证是否通过
        """
        is_valid = value == expected
        logger.debug(f"精确匹配验证: {value} == {expected} = {is_valid}")
        return is_valid
        
    def validate_custom(self, value: Any, validator_name: str) -> bool:
        """自定义验证器
        
        Parameters
        ----------
        value : Any
            实际值
        validator_name : str
            验证器名称
            
        Returns
        -------
        bool
            验证是否通过
        """
        if validator_name not in self.custom_validators:
            logger.error(f"自定义验证器 {validator_name} 不存在")
            return False
            
        try:
            validator_func = self.custom_validators[validator_name]
            is_valid = validator_func(value)
            logger.debug(f"自定义验证: {validator_name}({value}) = {is_valid}")
            return is_valid
        except Exception as e:
            logger.error(f"自定义验证器 {validator_name} 执行失败: {e}")
            return False
            
    def register_custom_validator(self, name: str, validator_func):
        """注册自定义验证器
        
        Parameters
        ----------
        name : str
            验证器名称
        validator_func : callable
            验证器函数
        """
        self.custom_validators[name] = validator_func
        logger.info(f"注册自定义验证器: {name}")
        
    def get_validation_message(self, result: 'StepResult', expect: ExpectConfig) -> str:
        """获取验证消息
        
        Parameters
        ----------
        result : StepResult
            步骤结果
        expect : ExpectConfig
            期望结果配置
            
        Returns
        -------
        str
            验证消息
        """
        if not result.success:
            return f"步骤执行失败: {result.error}"
            
        if expect.type == "range":
            return f"值 {result.value} 不在范围 [{expect.min_val}, {expect.max_val}] 内"
        elif expect.type == "regex":
            return f"值 '{result.value}' 不匹配正则表达式 '{expect.regex}'"
        elif expect.type == "exact":
            return f"值 {result.value} 不等于期望值 {expect.value}"
        elif expect.type == "custom":
            return f"值 {result.value} 未通过自定义验证器 {expect.custom_validator}"
        else:
            return f"未知的验证类型: {expect.type}"


# 全局验证器实例
_global_validator = ResultValidator()


def get_validator() -> ResultValidator:
    """获取全局验证器实例"""
    return _global_validator


def register_custom_validator(name: str, validator_func):
    """注册自定义验证器（便捷函数）"""
    _global_validator.register_custom_validator(name, validator_func)
