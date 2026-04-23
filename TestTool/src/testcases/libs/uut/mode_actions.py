"""
UUT模式切换动作库

提供UUT模式切换相关的业务动作，可被测试用例调用。
"""
from typing import Optional
from ...context import Context


def enter_test_mode(ctx: Context, command: str = "AT+MODE=TEST") -> bool:
    """
    让UUT进入测试模式
    
    Args:
        ctx: 测试上下文
        command: 测试模式命令
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.uut:
            ctx.log_warning("UUT通讯不可用，跳过模式切换")
            return True
            
        ctx.uut.send(command.encode())
        ctx.log_info(f"UUT进入测试模式: {command}")
        return True
        
    except Exception as e:
        ctx.log_error(f"UUT进入测试模式失败: {e}")
        return False


def enter_normal_mode(ctx: Context, command: str = "AT+MODE=NORMAL") -> bool:
    """
    让UUT进入正常模式
    
    Args:
        ctx: 测试上下文
        command: 正常模式命令
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.uut:
            ctx.log_warning("UUT通讯不可用，跳过模式切换")
            return True
            
        ctx.uut.send(command.encode())
        ctx.log_info(f"UUT进入正常模式: {command}")
        return True
        
    except Exception as e:
        ctx.log_error(f"UUT进入正常模式失败: {e}")
        return False


def enter_debug_mode(ctx: Context, command: str = "AT+MODE=DEBUG") -> bool:
    """
    让UUT进入调试模式
    
    Args:
        ctx: 测试上下文
        command: 调试模式命令
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.uut:
            ctx.log_warning("UUT通讯不可用，跳过模式切换")
            return True
            
        ctx.uut.send(command.encode())
        ctx.log_info(f"UUT进入调试模式: {command}")
        return True
        
    except Exception as e:
        ctx.log_error(f"UUT进入调试模式失败: {e}")
        return False


def enter_factory_mode(ctx: Context, command: str = "AT+MODE=FACTORY") -> bool:
    """
    让UUT进入工厂模式
    
    Args:
        ctx: 测试上下文
        command: 工厂模式命令
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.uut:
            ctx.log_warning("UUT通讯不可用，跳过模式切换")
            return True
            
        ctx.uut.send(command.encode())
        ctx.log_info(f"UUT进入工厂模式: {command}")
        return True
        
    except Exception as e:
        ctx.log_error(f"UUT进入工厂模式失败: {e}")
        return False


def get_current_mode(ctx: Context, command: str = "AT+MODE?") -> Optional[str]:
    """
    获取UUT当前模式
    
    Args:
        ctx: 测试上下文
        command: 模式查询命令
        
    Returns:
        str: 当前模式，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        ctx.uut.send(command.encode())
        ctx.sleep_ms(100)
        
        response = ctx.uut.receive()
        ctx.log_info(f"UUT当前模式: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"获取UUT当前模式失败: {e}")
        return None
