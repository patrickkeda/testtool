"""
UUT控制动作库

提供UUT通讯相关的业务动作，可被测试用例调用。
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


def send_at_command(ctx: Context, command: str, timeout_ms: int = 3000) -> Optional[str]:
    """
    发送AT命令并获取响应
    
    Args:
        ctx: 测试上下文
        command: AT命令
        timeout_ms: 超时时间(毫秒)
        
    Returns:
        str: 响应内容，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        # 发送命令
        ctx.uut.send(command.encode())
        ctx.log_info(f"发送AT命令: {command}")
        
        # 等待响应（这里简化处理，实际应该根据协议实现）
        ctx.sleep_ms(100)
        
        # 读取响应（这里简化处理，实际应该根据协议实现）
        response = ctx.uut.receive()
        ctx.log_info(f"AT命令响应: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"AT命令发送失败: {e}")
        return None


def enter_mode(ctx: Context, mode: str) -> bool:
    """
    让UUT进入指定模式
    
    Args:
        ctx: 测试上下文
        mode: 模式名称
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.uut:
            ctx.log_warning("UUT通讯不可用，跳过模式切换")
            return True
            
        command = f"AT+MODE={mode}"
        ctx.uut.send(command.encode())
        ctx.log_info(f"UUT进入模式: {mode}")
        return True
        
    except Exception as e:
        ctx.log_error(f"UUT模式切换失败: {e}")
        return False


def get_uut_status(ctx: Context) -> Optional[str]:
    """
    获取UUT状态
    
    Args:
        ctx: 测试上下文
        
    Returns:
        str: UUT状态，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        # 发送状态查询命令
        ctx.uut.send(b"AT+STATUS")
        ctx.sleep_ms(100)
        
        # 读取响应
        response = ctx.uut.receive()
        ctx.log_info(f"UUT状态: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"获取UUT状态失败: {e}")
        return None
