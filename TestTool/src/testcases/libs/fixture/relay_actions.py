"""
继电器控制动作库

提供继电器控制相关的业务动作，可被测试用例调用。
"""
from typing import Optional
from ...context import Context


def relay_on(ctx: Context, relay_id: str = "RELAY1") -> bool:
    """
    继电器吸合
    
    Args:
        ctx: 测试上下文
        relay_id: 继电器ID
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.fixture:
            ctx.log_warning("治具通讯不可用，跳过继电器控制")
            return True
            
        command = f"{relay_id},ON"
        ctx.fixture.send(command.encode())
        ctx.log_info(f"继电器 {relay_id} 吸合")
        return True
        
    except Exception as e:
        ctx.log_error(f"继电器 {relay_id} 吸合失败: {e}")
        return False


def relay_off(ctx: Context, relay_id: str = "RELAY1") -> bool:
    """
    继电器释放
    
    Args:
        ctx: 测试上下文
        relay_id: 继电器ID
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.fixture:
            ctx.log_warning("治具通讯不可用，跳过继电器控制")
            return True
            
        command = f"{relay_id},OFF"
        ctx.fixture.send(command.encode())
        ctx.log_info(f"继电器 {relay_id} 释放")
        return True
        
    except Exception as e:
        ctx.log_error(f"继电器 {relay_id} 释放失败: {e}")
        return False


def set_relay_state(ctx: Context, relay_id: str, state: bool) -> bool:
    """
    设置继电器状态
    
    Args:
        ctx: 测试上下文
        relay_id: 继电器ID
        state: 状态 (True=吸合, False=释放)
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.fixture:
            ctx.log_warning("治具通讯不可用，跳过继电器控制")
            return True
            
        command = f"{relay_id},{'ON' if state else 'OFF'}"
        ctx.fixture.send(command.encode())
        ctx.log_info(f"继电器 {relay_id} 设置为: {'吸合' if state else '释放'}")
        return True
        
    except Exception as e:
        ctx.log_error(f"继电器 {relay_id} 设置状态失败: {e}")
        return False


def get_relay_state(ctx: Context, relay_id: str) -> Optional[bool]:
    """
    获取继电器状态
    
    Args:
        ctx: 测试上下文
        relay_id: 继电器ID
        
    Returns:
        bool: 继电器状态，失败时返回None
    """
    try:
        if not ctx.fixture:
            ctx.log_error("治具通讯不可用")
            return None
            
        command = f"{relay_id},STATUS"
        ctx.fixture.send(command.encode())
        ctx.sleep_ms(100)
        
        response = ctx.fixture.receive()
        ctx.log_info(f"继电器 {relay_id} 状态: {response}")
        
        # 解析响应
        if "ON" in response.upper():
            return True
        elif "OFF" in response.upper():
            return False
        else:
            ctx.log_warning(f"无法解析继电器状态响应: {response}")
            return None
        
    except Exception as e:
        ctx.log_error(f"获取继电器 {relay_id} 状态失败: {e}")
        return None


def toggle_relay(ctx: Context, relay_id: str) -> bool:
    """
    切换继电器状态
    
    Args:
        ctx: 测试上下文
        relay_id: 继电器ID
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.fixture:
            ctx.log_warning("治具通讯不可用，跳过继电器控制")
            return True
            
        command = f"{relay_id},TOGGLE"
        ctx.fixture.send(command.encode())
        ctx.log_info(f"继电器 {relay_id} 切换状态")
        return True
        
    except Exception as e:
        ctx.log_error(f"继电器 {relay_id} 切换状态失败: {e}")
        return False
