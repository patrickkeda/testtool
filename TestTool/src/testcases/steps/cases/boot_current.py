"""
开机电流测试用例

完整的开机电流测试流程：
1. 扫描/输入SN
2. 配置电源并上电
3. 控制治具（如果需要）
4. 发送UUT开机命令
5. 等待电流稳定
6. 测量开机电流
7. 判断结果并记录
"""
from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any


class BootCurrentStep(BaseStep):
    """开机电流测试用例"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行开机电流测试
        
        参数示例：
        - psu_id: 电源ID (默认 "psu1")
        - set_voltage: 设置电压 (默认 5.0V)
        - current_limit: 电流限制 (默认 2.0A)
        - settle_ms: 稳定时间 (默认 500ms)
        - expect_min: 期望最小值 (默认 0.05A)
        - expect_max: 期望最大值 (默认 0.12A)
        - enable_fixture: 是否启用治具控制 (默认 False)
        - enable_uut: 是否启用UUT控制 (默认 True)
        - fixture_command: 治具命令 (可选)
        - uut_command: UUT开机命令 (默认 "AT+POWER_ON")
        """
        try:
            # 1) 读取参数
            psu_id = params.get("psu_id", "psu1")
            set_voltage = float(params.get("set_voltage", 5.0))
            current_limit = float(params.get("current_limit", 2.0))
            settle_ms = int(params.get("settle_ms", 500))
            expect_min = float(params.get("expect_min", 0.05))
            expect_max = float(params.get("expect_max", 0.12))
            enable_fixture = bool(params.get("enable_fixture", False))
            enable_uut = bool(params.get("enable_uut", True))
            fixture_command = params.get("fixture_command", "")
            uut_command = params.get("uut_command", "AT+POWER_ON")
            
            ctx.log_info(f"开始开机电流测试: 电压={set_voltage}V, 限流={current_limit}A")
            
            # 2) 检查设备可用性
            if not ctx.has_instrument(psu_id):
                return self.create_failure_result(f"电源 {psu_id} 不可用")
            
            psu = ctx.get_instrument(psu_id)
            
            # 3) 配置电源
            ctx.log_info(f"配置电源 {psu_id}: 电压={set_voltage}V, 限流={current_limit}A")
            psu.set_voltage(set_voltage)
            psu.set_current_limit(current_limit)
            psu.set_output(True)  # 开启输出
            
            # 4) 控制治具（如果需要）
            if enable_fixture and ctx.fixture and fixture_command:
                try:
                    ctx.fixture.send(fixture_command.encode())
                    ctx.log_info(f"发送治具命令: {fixture_command}")
                    ctx.sleep_ms(100)  # 治具动作延时
                except Exception as e:
                    ctx.log_warning(f"治具命令发送失败: {e}")
            
            # 5) 控制UUT开机（如果需要）
            if enable_uut and ctx.uut and uut_command:
                try:
                    ctx.uut.send(uut_command.encode())
                    ctx.log_info(f"发送UUT开机命令: {uut_command}")
                    ctx.sleep_ms(200)  # UUT开机延时
                except Exception as e:
                    ctx.log_warning(f"UUT开机命令发送失败: {e}")
            
            # 6) 等待电流稳定
            ctx.log_info(f"等待电流稳定 {settle_ms}ms...")
            ctx.sleep_ms(settle_ms)
            
            # 7) 测量电流
            current_a = psu.measure_current()
            ctx.log_info(f"测量到开机电流: {current_a:.3f}A")
            
            # 8) 判断结果
            passed = (expect_min <= current_a <= expect_max)
            
            # 9) 构建结果数据
            result_data = {
                "current": current_a,
                "set_voltage": set_voltage,
                "current_limit": current_limit,
                "expect_min": expect_min,
                "expect_max": expect_max,
                "psu_id": psu_id,
                "sn": ctx.get_sn()
            }
            
            if passed:
                message = f"开机电流测试通过: {current_a:.3f}A (期望范围: {expect_min:.3f}A - {expect_max:.3f}A)"
                return self.create_success_result(result_data, message)
            else:
                message = f"开机电流测试失败: {current_a:.3f}A 超出期望范围 [{expect_min:.3f}A, {expect_max:.3f}A]"
                return self.create_failure_result(message, data=result_data)
                
        except Exception as e:
            ctx.log_error(f"开机电流测试执行异常: {e}", exc_info=True)
            return self.create_failure_result(f"开机电流测试执行异常: {e}", error=str(e))
        
        finally:
            # 10) 清理：关闭电源输出
            try:
                if ctx.has_instrument(psu_id):
                    psu = ctx.get_instrument(psu_id)
                    psu.set_output(False)
                    ctx.log_info("已关闭电源输出")
            except Exception as e:
                ctx.log_warning(f"关闭电源输出失败: {e}")

