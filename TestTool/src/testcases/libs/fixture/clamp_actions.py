"""
夹具控制动作库

提供夹具控制相关的业务动作，可被测试用例调用。
"""
from typing import Optional
from ...context import Context


def clamp_on(ctx: Context, clamp_id: str = "CLAMP1") -> bool:
    """
    夹具夹紧
    
    Args:
        ctx: 测试上下文
        clamp_id: 夹具ID
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.fixture:
            ctx.log_warning("治具通讯不可用，跳过夹具控制")
            return True
            
        command = f"{clamp_id},ON"
        ctx.fixture.send(command.encode())
        ctx.log_info(f"夹具 {clamp_id} 夹紧")
        return True
        
    except Exception as e:
        ctx.log_error(f"夹具 {clamp_id} 夹紧失败: {e}")
        return False


def clamp_off(ctx: Context, clamp_id: str = "CLAMP1") -> bool:
    """
    夹具松开
    
    Args:
        ctx: 测试上下文
        clamp_id: 夹具ID
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.fixture:
            ctx.log_warning("治具通讯不可用，跳过夹具控制")
            return True
            
        command = f"{clamp_id},OFF"
        ctx.fixture.send(command.encode())
        ctx.log_info(f"夹具 {clamp_id} 松开")
        return True
        
    except Exception as e:
        ctx.log_error(f"夹具 {clamp_id} 松开失败: {e}")
        return False


def set_clamp_force(ctx: Context, clamp_id: str, force: float) -> bool:
    """
    设置夹具夹持力
    
    Args:
        ctx: 测试上下文
        clamp_id: 夹具ID
        force: 夹持力值
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.fixture:
            ctx.log_warning("治具通讯不可用，跳过夹具控制")
            return True
            
        command = f"{clamp_id},FORCE,{force}"
        ctx.fixture.send(command.encode())
        ctx.log_info(f"夹具 {clamp_id} 设置夹持力: {force}")
        return True
        
    except Exception as e:
        ctx.log_error(f"夹具 {clamp_id} 设置夹持力失败: {e}")
        return False


def get_clamp_status(ctx: Context, clamp_id: str) -> Optional[str]:
    """
    获取夹具状态
    
    Args:
        ctx: 测试上下文
        clamp_id: 夹具ID
        
    Returns:
        str: 夹具状态，失败时返回None
    """
    try:
        if not ctx.fixture:
            ctx.log_error("治具通讯不可用")
            return None
            
        command = f"{clamp_id},STATUS"
        ctx.fixture.send(command.encode())
        ctx.sleep_ms(100)
        
        response = ctx.fixture.receive()
        ctx.log_info(f"夹具 {clamp_id} 状态: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"获取夹具 {clamp_id} 状态失败: {e}")
        return None


def emergency_release(ctx: Context) -> bool:
    """
    紧急释放所有夹具
    
    Args:
        ctx: 测试上下文
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.fixture:
            ctx.log_warning("治具通讯不可用，跳过紧急释放")
            return True
            
        command = "EMERGENCY_RELEASE"
        ctx.fixture.send(command.encode())
        ctx.log_info("紧急释放所有夹具")
        return True
        
    except Exception as e:
        ctx.log_error(f"紧急释放夹具失败: {e}")
        return False
