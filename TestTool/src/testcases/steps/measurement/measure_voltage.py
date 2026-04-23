"""
测量电压测试步骤

示例：测量指定通道的电压值。
"""
from ..base import InstrumentStep, StepResult
from ..context import Context
from typing import Dict, Any


class MeasureVoltageStep(InstrumentStep):
    """测量电压步骤"""
    
    def execute_instrument(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行电压测量
        
        参数示例：
        - instrument_id: 仪器ID (默认 "dmm1")
        - channel: 测量通道 (默认 1)
        - range: 测量范围 (默认 "auto")
        - expect_min: 期望最小值 (默认 0.0V)
        - expect_max: 期望最大值 (默认 999.0V)
        """
        # 1) 读取本步参数
        instrument_id = self.get_param_str(params, "instrument_id", "dmm1")
        channel = self.get_param_int(params, "channel", 1)
        range_val = self.get_param_str(params, "range", "auto")
        expect_min = self.get_param_float(params, "expect_min", 0.0)
        expect_max = self.get_param_float(params, "expect_max", 999.0)
        
        # 2) 从上下文获取设备实例
        if not ctx.has_instrument(instrument_id):
            return self.create_failure_result(f"仪器 {instrument_id} 不可用")
        
        instrument = ctx.get_instrument(instrument_id)
        
        # 3) 具体测试逻辑
        try:
            # 设置测量范围
            if hasattr(instrument, 'set_range'):
                instrument.set_range(range_val, channel)
            
            # 测量电压
            voltage = instrument.measure_voltage_dc(channel)
            ctx.log_info(f"测量电压: {voltage:.3f}V")
            
            # 判断结果
            passed = (expect_min <= voltage <= expect_max)
            
            # 构建结果数据
            result_data = {
                "voltage": voltage,
                "channel": channel,
                "range": range_val,
                "expect_min": expect_min,
                "expect_max": expect_max,
                "instrument_id": instrument_id
            }
            
            if passed:
                message = f"电压测量通过: {voltage:.3f}V (期望范围: {expect_min:.3f}V - {expect_max:.3f}V)"
                return self.create_success_result(result_data, message)
            else:
                message = f"电压测量失败: {voltage:.3f}V 超出期望范围 [{expect_min:.3f}V, {expect_max:.3f}V]"
                return self.create_failure_result(message, data=result_data)
                
        except Exception as e:
            ctx.log_error(f"电压测量执行异常: {e}")
            return self.create_failure_result(f"电压测量执行异常: {e}")
