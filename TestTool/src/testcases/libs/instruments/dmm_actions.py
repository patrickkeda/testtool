"""
万用表控制动作库

提供万用表相关的业务动作，可被测试用例调用。
"""
from typing import Optional
from ...context import Context


def measure_voltage_dc(ctx: Context, dmm_id: str, channel: int = 1) -> Optional[float]:
    """
    测量直流电压
    
    Args:
        ctx: 测试上下文
        dmm_id: 万用表ID
        channel: 通道号
        
    Returns:
        float: 电压值(V)，失败时返回None
    """
    try:
        if not ctx.has_instrument(dmm_id):
            ctx.log_error(f"万用表 {dmm_id} 不可用")
            return None
            
        dmm = ctx.get_instrument(dmm_id)
        voltage = dmm.measure_voltage_dc(channel)
        
        ctx.log_info(f"万用表 {dmm_id} 测量直流电压: {voltage:.3f}V")
        return voltage
        
    except Exception as e:
        ctx.log_error(f"万用表 {dmm_id} 测量直流电压失败: {e}")
        return None


def measure_voltage_ac(ctx: Context, dmm_id: str, channel: int = 1) -> Optional[float]:
    """
    测量交流电压
    
    Args:
        ctx: 测试上下文
        dmm_id: 万用表ID
        channel: 通道号
        
    Returns:
        float: 电压值(V)，失败时返回None
    """
    try:
        if not ctx.has_instrument(dmm_id):
            ctx.log_error(f"万用表 {dmm_id} 不可用")
            return None
            
        dmm = ctx.get_instrument(dmm_id)
        voltage = dmm.measure_voltage_ac(channel)
        
        ctx.log_info(f"万用表 {dmm_id} 测量交流电压: {voltage:.3f}V")
        return voltage
        
    except Exception as e:
        ctx.log_error(f"万用表 {dmm_id} 测量交流电压失败: {e}")
        return None


def measure_current_dc(ctx: Context, dmm_id: str, channel: int = 1) -> Optional[float]:
    """
    测量直流电流
    
    Args:
        ctx: 测试上下文
        dmm_id: 万用表ID
        channel: 通道号
        
    Returns:
        float: 电流值(A)，失败时返回None
    """
    try:
        if not ctx.has_instrument(dmm_id):
            ctx.log_error(f"万用表 {dmm_id} 不可用")
            return None
            
        dmm = ctx.get_instrument(dmm_id)
        current = dmm.measure_current_dc(channel)
        
        ctx.log_info(f"万用表 {dmm_id} 测量直流电流: {current:.3f}A")
        return current
        
    except Exception as e:
        ctx.log_error(f"万用表 {dmm_id} 测量直流电流失败: {e}")
        return None


def measure_current_ac(ctx: Context, dmm_id: str, channel: int = 1) -> Optional[float]:
    """
    测量交流电流
    
    Args:
        ctx: 测试上下文
        dmm_id: 万用表ID
        channel: 通道号
        
    Returns:
        float: 电流值(A)，失败时返回None
    """
    try:
        if not ctx.has_instrument(dmm_id):
            ctx.log_error(f"万用表 {dmm_id} 不可用")
            return None
            
        dmm = ctx.get_instrument(dmm_id)
        current = dmm.measure_current_ac(channel)
        
        ctx.log_info(f"万用表 {dmm_id} 测量交流电流: {current:.3f}A")
        return current
        
    except Exception as e:
        ctx.log_error(f"万用表 {dmm_id} 测量交流电流失败: {e}")
        return None


def measure_resistance(ctx: Context, dmm_id: str, channel: int = 1) -> Optional[float]:
    """
    测量电阻
    
    Args:
        ctx: 测试上下文
        dmm_id: 万用表ID
        channel: 通道号
        
    Returns:
        float: 电阻值(Ω)，失败时返回None
    """
    try:
        if not ctx.has_instrument(dmm_id):
            ctx.log_error(f"万用表 {dmm_id} 不可用")
            return None
            
        dmm = ctx.get_instrument(dmm_id)
        resistance = dmm.measure_resistance(channel)
        
        ctx.log_info(f"万用表 {dmm_id} 测量电阻: {resistance:.3f}Ω")
        return resistance
        
    except Exception as e:
        ctx.log_error(f"万用表 {dmm_id} 测量电阻失败: {e}")
        return None


def measure_frequency(ctx: Context, dmm_id: str, channel: int = 1) -> Optional[float]:
    """
    测量频率
    
    Args:
        ctx: 测试上下文
        dmm_id: 万用表ID
        channel: 通道号
        
    Returns:
        float: 频率值(Hz)，失败时返回None
    """
    try:
        if not ctx.has_instrument(dmm_id):
            ctx.log_error(f"万用表 {dmm_id} 不可用")
            return None
            
        dmm = ctx.get_instrument(dmm_id)
        frequency = dmm.measure_frequency(channel)
        
        ctx.log_info(f"万用表 {dmm_id} 测量频率: {frequency:.3f}Hz")
        return frequency
        
    except Exception as e:
        ctx.log_error(f"万用表 {dmm_id} 测量频率失败: {e}")
        return None


def set_measurement_range(ctx: Context, dmm_id: str, measurement_type: str, range_value: float) -> bool:
    """
    设置测量范围
    
    Args:
        ctx: 测试上下文
        dmm_id: 万用表ID
        measurement_type: 测量类型 (voltage_dc, voltage_ac, current_dc, current_ac, resistance)
        range_value: 范围值
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.has_instrument(dmm_id):
            ctx.log_error(f"万用表 {dmm_id} 不可用")
            return False
            
        dmm = ctx.get_instrument(dmm_id)
        
        # 根据测量类型设置范围
        if measurement_type == "voltage_dc":
            dmm.set_voltage_dc_range(range_value)
        elif measurement_type == "voltage_ac":
            dmm.set_voltage_ac_range(range_value)
        elif measurement_type == "current_dc":
            dmm.set_current_dc_range(range_value)
        elif measurement_type == "current_ac":
            dmm.set_current_ac_range(range_value)
        elif measurement_type == "resistance":
            dmm.set_resistance_range(range_value)
        else:
            ctx.log_error(f"不支持的测量类型: {measurement_type}")
            return False
        
        ctx.log_info(f"万用表 {dmm_id} 设置 {measurement_type} 范围: {range_value}")
        return True
        
    except Exception as e:
        ctx.log_error(f"万用表 {dmm_id} 设置测量范围失败: {e}")
        return False
