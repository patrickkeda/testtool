"""
测量电流测试步骤

示例：配置电源，控制治具，发送命令给UUT，然后读取电源数据。
"""
from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any


class MeasureCurrentStep(BaseStep):
    """测量电流步骤"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行电流测量
        
        参数示例：
        - psu_id: 电源ID (默认 "psu1")
        - set_voltage: 设置电压 (默认 5.0V)
        - current_limit: 电流限制 (默认 2.0A)
        - settle_ms: 稳定时间 (默认 300ms)
        - expect_min: 期望最小值 (默认 0.0A)
        - expect_max: 期望最大值 (默认 999.0A)
        """
        # 1) 读取本步参数（只来自 sequence）
        psu_id = params.get("psu_id", "psu1")
        set_voltage = float(params.get("set_voltage", 5.0))
        current_limit = float(params.get("current_limit", 2.0))
        settle_ms = int(params.get("settle_ms", 300))
        expect_min = float(params.get("expect_min", 0.0))
        expect_max = float(params.get("expect_max", 999.0))
        
        # 2) 从上下文获取设备实例（由配置页面→主程序构建）
        if not ctx.has_instrument(psu_id):
            return self.create_failure_result(f"电源 {psu_id} 不可用")
        
        psu = ctx.get_instrument(psu_id)
        
        # 可选：治具控制（若本步需要）
        if ctx.fixture and params.get("enable_fixture", False):
            fixture_cmd = params.get("fixture_command", "")
            if fixture_cmd:
                try:
                    ctx.fixture.send(fixture_cmd.encode())
                    ctx.log_info(f"发送治具命令: {fixture_cmd}")
                except Exception as e:
                    ctx.log_warning(f"治具命令发送失败: {e}")
        
        # 可选：UUT控制（若本步需要）
        if ctx.uut and params.get("enable_uut", False):
            uut_cmd = params.get("uut_command", "")
            if uut_cmd:
                try:
                    ctx.uut.send(uut_cmd.encode())
                    ctx.log_info(f"发送UUT命令: {uut_cmd}")
                except Exception as e:
                    ctx.log_warning(f"UUT命令发送失败: {e}")
        
        # 3) 具体测试逻辑
        try:
            # 配置电源
            ctx.log_info(f"配置电源 {psu_id}: 电压={set_voltage}V, 限流={current_limit}A")
            psu.set_voltage(set_voltage)
            psu.set_current_limit(current_limit)
            psu.set_output(True)  # 开启输出
            
            # 等待稳定
            ctx.sleep_ms(settle_ms)
            
            # 测量电流
            current_a = psu.measure_current()
            ctx.log_info(f"测量电流: {current_a:.3f}A")
            
            # 判断结果
            passed = (expect_min <= current_a <= expect_max)
            
            # 构建结果数据
            result_data = {
                "current": current_a,
                "set_voltage": set_voltage,
                "current_limit": current_limit,
                "expect_min": expect_min,
                "expect_max": expect_max,
                "psu_id": psu_id
            }
            
            if passed:
                message = f"电流测量通过: {current_a:.3f}A (期望范围: {expect_min:.3f}A - {expect_max:.3f}A)"
                return self.create_success_result(result_data, message)
            else:
                message = f"电流测量失败: {current_a:.3f}A 超出期望范围 [{expect_min:.3f}A, {expect_max:.3f}A]"
                return self.create_failure_result(message, data=result_data)
                
        except Exception as e:
            ctx.log_error(f"电流测量执行异常: {e}")
            return self.create_failure_result(f"电流测量执行异常: {e}")
        
        finally:
            # 可选：关闭电源输出
            if params.get("auto_disable_output", True):
                try:
                    psu.set_output(False)
                    ctx.log_info("已关闭电源输出")
                except Exception as e:
                    ctx.log_warning(f"关闭电源输出失败: {e}")
