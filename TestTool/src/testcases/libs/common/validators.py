"""
通用验证器库

提供各种验证功能，可被测试用例调用。
"""
import re
from typing import Any, Union, Tuple


def validate_range(value: float, min_val: float, max_val: float, name: str = "值") -> Tuple[bool, str]:
    """
    验证数值是否在指定范围内
    
    Args:
        value: 要验证的值
        min_val: 最小值
        max_val: 最大值
        name: 值的名称（用于错误信息）
        
    Returns:
        Tuple[bool, str]: (是否通过, 错误信息)
    """
    if min_val <= value <= max_val:
        return True, ""
    else:
        return False, f"{name} {value} 超出期望范围 [{min_val}, {max_val}]"


def validate_regex(text: str, pattern: str, name: str = "文本") -> Tuple[bool, str]:
    """
    验证文本是否匹配正则表达式
    
    Args:
        text: 要验证的文本
        pattern: 正则表达式
        name: 文本的名称（用于错误信息）
        
    Returns:
        Tuple[bool, str]: (是否通过, 错误信息)
    """
    try:
        if re.match(pattern, text):
            return True, ""
        else:
            return False, f"{name} '{text}' 不匹配模式 '{pattern}'"
    except re.error as e:
        return False, f"正则表达式错误: {e}"


def validate_sn_format(sn: str, pattern: str = r"^[A-Z0-9_-]{6,64}$") -> Tuple[bool, str]:
    """
    验证SN格式
    
    Args:
        sn: 序列号
        pattern: 验证模式
        
    Returns:
        Tuple[bool, str]: (是否通过, 错误信息)
    """
    return validate_regex(sn, pattern, "SN")


def validate_voltage(voltage: float, min_voltage: float = 0.0, max_voltage: float = 100.0) -> Tuple[bool, str]:
    """
    验证电压值
    
    Args:
        voltage: 电压值
        min_voltage: 最小电压
        max_voltage: 最大电压
        
    Returns:
        Tuple[bool, str]: (是否通过, 错误信息)
    """
    return validate_range(voltage, min_voltage, max_voltage, "电压")


def validate_current(current: float, min_current: float = 0.0, max_current: float = 10.0) -> Tuple[bool, str]:
    """
    验证电流值
    
    Args:
        current: 电流值
        min_current: 最小电流
        max_current: 最大电流
        
    Returns:
        Tuple[bool, str]: (是否通过, 错误信息)
    """
    return validate_range(current, min_current, max_current, "电流")


def validate_temperature(temp: float, min_temp: float = -40.0, max_temp: float = 85.0) -> Tuple[bool, str]:
    """
    验证温度值
    
    Args:
        temp: 温度值
        min_temp: 最小温度
        max_temp: 最大温度
        
    Returns:
        Tuple[bool, str]: (是否通过, 错误信息)
    """
    return validate_range(temp, min_temp, max_temp, "温度")


def validate_frequency(freq: float, min_freq: float = 1.0, max_freq: float = 1000000.0) -> Tuple[bool, str]:
    """
    验证频率值
    
    Args:
        freq: 频率值
        min_freq: 最小频率
        max_freq: 最大频率
        
    Returns:
        Tuple[bool, str]: (是否通过, 错误信息)
    """
    return validate_range(freq, min_freq, max_freq, "频率")


def validate_power(power: float, min_power: float = 0.0, max_power: float = 1000.0) -> Tuple[bool, str]:
    """
    验证功率值
    
    Args:
        power: 功率值
        min_power: 最小功率
        max_power: 最大功率
        
    Returns:
        Tuple[bool, str]: (是否通过, 错误信息)
    """
    return validate_range(power, min_power, max_power, "功率")


def validate_timeout(timeout: int, min_timeout: int = 100, max_timeout: int = 300000) -> Tuple[bool, str]:
    """
    验证超时时间
    
    Args:
        timeout: 超时时间(毫秒)
        min_timeout: 最小超时时间
        max_timeout: 最大超时时间
        
    Returns:
        Tuple[bool, str]: (是否通过, 错误信息)
    """
    return validate_range(timeout, min_timeout, max_timeout, "超时时间")


def validate_retries(retries: int, min_retries: int = 0, max_retries: int = 10) -> Tuple[bool, str]:
    """
    验证重试次数
    
    Args:
        retries: 重试次数
        min_retries: 最小重试次数
        max_retries: 最大重试次数
        
    Returns:
        Tuple[bool, str]: (是否通过, 错误信息)
    """
    return validate_range(retries, min_retries, max_retries, "重试次数")
