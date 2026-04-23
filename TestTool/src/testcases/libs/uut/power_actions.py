"""
UUT电源控制动作库

提供UUT电源相关的业务动作，可被测试用例调用。
"""
from typing import Optional
from ...context import Context


def power_on_uut(ctx: Context, command: str = "AT+POWER_ON") -> bool:
    """
    发送UUT开机命令
    
    Args:
        ctx: 测试上下文
        command: 开机命令
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.uut:
            ctx.log_warning("UUT通讯不可用，跳过开机命令")
            return True
            
        ctx.uut.send(command.encode())
        ctx.log_info(f"发送UUT开机命令: {command}")
        return True
        
    except Exception as e:
        ctx.log_error(f"UUT开机命令发送失败: {e}")
        return False


def power_off_uut(ctx: Context, command: str = "AT+POWER_OFF") -> bool:
    """
    发送UUT关机命令
    
    Args:
        ctx: 测试上下文
        command: 关机命令
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.uut:
            ctx.log_warning("UUT通讯不可用，跳过关机命令")
            return True
            
        ctx.uut.send(command.encode())
        ctx.log_info(f"发送UUT关机命令: {command}")
        return True
        
    except Exception as e:
        ctx.log_error(f"UUT关机命令发送失败: {e}")
        return False


def soft_reset_uut(ctx: Context, command: str = "AT+RESET") -> bool:
    """
    发送UUT软复位命令
    
    Args:
        ctx: 测试上下文
        command: 软复位命令
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.uut:
            ctx.log_warning("UUT通讯不可用，跳过软复位命令")
            return True
            
        ctx.uut.send(command.encode())
        ctx.log_info(f"发送UUT软复位命令: {command}")
        return True
        
    except Exception as e:
        ctx.log_error(f"UUT软复位命令发送失败: {e}")
        return False


def hard_reset_uut(ctx: Context, command: str = "AT+HARD_RESET") -> bool:
    """
    发送UUT硬复位命令
    
    Args:
        ctx: 测试上下文
        command: 硬复位命令
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.uut:
            ctx.log_warning("UUT通讯不可用，跳过硬复位命令")
            return True
            
        ctx.uut.send(command.encode())
        ctx.log_info(f"发送UUT硬复位命令: {command}")
        return True
        
    except Exception as e:
        ctx.log_error(f"UUT硬复位命令发送失败: {e}")
        return False


def check_power_status(ctx: Context, command: str = "AT+POWER_STATUS") -> Optional[str]:
    """
    检查UUT电源状态
    
    Args:
        ctx: 测试上下文
        command: 电源状态查询命令
        
    Returns:
        str: 电源状态，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        ctx.uut.send(command.encode())
        ctx.sleep_ms(100)
        
        response = ctx.uut.receive()
        ctx.log_info(f"UUT电源状态: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"获取UUT电源状态失败: {e}")
        return None
