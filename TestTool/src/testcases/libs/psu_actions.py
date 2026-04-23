"""
电源控制动作库

提供电源相关的业务动作，可被测试用例调用。
"""
from typing import Optional
from ...context import Context
from ...instruments.base import IPowerSupply


def power_on(ctx: Context, psu_id: str, voltage: float, current_limit: float) -> bool:
    """
    电源上电并设置参数
    
    Args:
        ctx: 测试上下文
        psu_id: 电源ID
        voltage: 设置电压
        current_limit: 电流限制
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.has_instrument(psu_id):
            ctx.log_error(f"电源 {psu_id} 不可用")
            return False
            
        psu: IPowerSupply = ctx.get_instrument(psu_id)
        
        # 设置参数
        psu.set_voltage(voltage)
        psu.set_current_limit(current_limit)
        psu.set_output(True)
        
        ctx.log_info(f"电源 {psu_id} 上电: {voltage}V, 限流 {current_limit}A")
        return True
        
    except Exception as e:
        ctx.log_error(f"电源 {psu_id} 上电失败: {e}")
        return False


def power_off(ctx: Context, psu_id: str) -> bool:
    """
    关闭电源输出
    
    Args:
        ctx: 测试上下文
        psu_id: 电源ID
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.has_instrument(psu_id):
            ctx.log_warning(f"电源 {psu_id} 不可用，跳过关闭操作")
            return True
            
        psu: IPowerSupply = ctx.get_instrument(psu_id)
        psu.set_output(False)
        
        ctx.log_info(f"电源 {psu_id} 已关闭输出")
        return True
        
    except Exception as e:
        ctx.log_error(f"电源 {psu_id} 关闭失败: {e}")
        return False


def measure_current(ctx: Context, psu_id: str) -> Optional[float]:
    """
    测量电源电流
    
    Args:
        ctx: 测试上下文
        psu_id: 电源ID
        
    Returns:
        float: 电流值(A)，失败时返回None
    """
    try:
        if not ctx.has_instrument(psu_id):
            ctx.log_error(f"电源 {psu_id} 不可用")
            return None
            
        psu: IPowerSupply = ctx.get_instrument(psu_id)
        current = psu.measure_current()
        
        ctx.log_info(f"电源 {psu_id} 测量电流: {current:.3f}A")
        return current
        
    except Exception as e:
        ctx.log_error(f"电源 {psu_id} 测量电流失败: {e}")
        return None


def measure_voltage(ctx: Context, psu_id: str) -> Optional[float]:
    """
    测量电源电压
    
    Args:
        ctx: 测试上下文
        psu_id: 电源ID
        
    Returns:
        float: 电压值(V)，失败时返回None
    """
    try:
        if not ctx.has_instrument(psu_id):
            ctx.log_error(f"电源 {psu_id} 不可用")
            return None
            
        psu: IPowerSupply = ctx.get_instrument(psu_id)
        voltage = psu.measure_voltage()
        
        ctx.log_info(f"电源 {psu_id} 测量电压: {voltage:.3f}V")
        return voltage
        
    except Exception as e:
        ctx.log_error(f"电源 {psu_id} 测量电压失败: {e}")
        return None


def set_voltage(ctx: Context, psu_id: str, voltage: float) -> bool:
    """
    设置电源电压
    
    Args:
        ctx: 测试上下文
        psu_id: 电源ID
        voltage: 电压值
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.has_instrument(psu_id):
            ctx.log_error(f"电源 {psu_id} 不可用")
            return False
            
        psu: IPowerSupply = ctx.get_instrument(psu_id)
        psu.set_voltage(voltage)
        
        ctx.log_info(f"电源 {psu_id} 设置电压: {voltage}V")
        return True
        
    except Exception as e:
        ctx.log_error(f"电源 {psu_id} 设置电压失败: {e}")
        return False


def set_current_limit(ctx: Context, psu_id: str, current_limit: float) -> bool:
    """
    设置电源电流限制
    
    Args:
        ctx: 测试上下文
        psu_id: 电源ID
        current_limit: 电流限制值
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.has_instrument(psu_id):
            ctx.log_error(f"电源 {psu_id} 不可用")
            return False
            
        psu: IPowerSupply = ctx.get_instrument(psu_id)
        psu.set_current_limit(current_limit)
        
        ctx.log_info(f"电源 {psu_id} 设置电流限制: {current_limit}A")
        return True
        
    except Exception as e:
        ctx.log_error(f"电源 {psu_id} 设置电流限制失败: {e}")
        return False
