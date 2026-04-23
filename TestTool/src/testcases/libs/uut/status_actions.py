"""
UUT状态查询动作库

提供UUT状态查询相关的业务动作，可被测试用例调用。
"""
from typing import Optional
from ...context import Context


def get_uut_status(ctx: Context, command: str = "AT+STATUS") -> Optional[str]:
    """
    获取UUT状态
    
    Args:
        ctx: 测试上下文
        command: 状态查询命令
        
    Returns:
        str: UUT状态，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        ctx.uut.send(command.encode())
        ctx.sleep_ms(100)
        
        response = ctx.uut.receive()
        ctx.log_info(f"UUT状态: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"获取UUT状态失败: {e}")
        return None


def get_version_info(ctx: Context, command: str = "AT+VERSION") -> Optional[str]:
    """
    获取UUT版本信息
    
    Args:
        ctx: 测试上下文
        command: 版本查询命令
        
    Returns:
        str: 版本信息，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        ctx.uut.send(command.encode())
        ctx.sleep_ms(100)
        
        response = ctx.uut.receive()
        ctx.log_info(f"UUT版本信息: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"获取UUT版本信息失败: {e}")
        return None


def get_serial_number(ctx: Context, command: str = "AT+SN") -> Optional[str]:
    """
    获取UUT序列号
    
    Args:
        ctx: 测试上下文
        command: 序列号查询命令
        
    Returns:
        str: 序列号，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        ctx.uut.send(command.encode())
        ctx.sleep_ms(100)
        
        response = ctx.uut.receive()
        ctx.log_info(f"UUT序列号: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"获取UUT序列号失败: {e}")
        return None


def get_temperature(ctx: Context, command: str = "AT+TEMP") -> Optional[str]:
    """
    获取UUT温度
    
    Args:
        ctx: 测试上下文
        command: 温度查询命令
        
    Returns:
        str: 温度信息，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        ctx.uut.send(command.encode())
        ctx.sleep_ms(100)
        
        response = ctx.uut.receive()
        ctx.log_info(f"UUT温度: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"获取UUT温度失败: {e}")
        return None


def get_voltage_levels(ctx: Context, command: str = "AT+VOLTAGE") -> Optional[str]:
    """
    获取UUT电压等级
    
    Args:
        ctx: 测试上下文
        command: 电压查询命令
        
    Returns:
        str: 电压信息，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        ctx.uut.send(command.encode())
        ctx.sleep_ms(100)
        
        response = ctx.uut.receive()
        ctx.log_info(f"UUT电压等级: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"获取UUT电压等级失败: {e}")
        return None
