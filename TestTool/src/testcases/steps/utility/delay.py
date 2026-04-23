"""
延时测试步骤

示例：简单的延时等待功能。
"""
from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any


class DelayStep(BaseStep):
    """延时步骤"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行延时
        
        参数示例（兼容多种写法，优先级从上到下）：
        - delay_ms: 延时时间（毫秒）
        - duration_ms: 延时时间（毫秒，示例 YAML 中使用的字段）
        - duration: 延时时间（毫秒）
        - message: 延时期间的提示信息（可选）
        - show_countdown: 是否显示倒计时弹窗（可选）
        - title: 倒计时弹窗标题（可选）
        """
        # 1) 读取本步参数（兼容多个字段名）
        raw_delay = None
        if "delay_ms" in params:
            raw_delay = params.get("delay_ms")
        elif "duration_ms" in params:
            raw_delay = params.get("duration_ms")
        elif "duration" in params:
            raw_delay = params.get("duration")
        
        try:
            delay_ms = int(raw_delay) if raw_delay is not None else 1000
        except (TypeError, ValueError):
            ctx.log_warning(f"延时参数解析失败: {raw_delay}，使用默认值 1000ms")
            delay_ms = 1000

        message = self.get_param_str(params, "message", f"延时 {delay_ms}ms")
        show_countdown = self.get_param_bool(params, "show_countdown", False)
        title = self.get_param_str(params, "title", "倒计时")
        
        # 2) 执行延时
        try:
            ctx.log_info(f"开始延时: {message}")
            if show_countdown:
                try:
                    from src.app.ui_invoker import invoke_in_gui_countdown
                    invoke_in_gui_countdown(
                        title=title,
                        message=message,
                        duration_ms=delay_ms,
                        port=ctx.port,
                    )
                except Exception as exc:
                    # 在无 GUI 或 GUI 调用失败时，回退为普通延时，避免流程中断。
                    ctx.log_warning(f"倒计时弹窗显示失败，回退为普通延时: {exc}")
                    ctx.sleep_ms(delay_ms)
            else:
                ctx.sleep_ms(delay_ms)
            ctx.log_info(f"延时完成: {delay_ms}ms")
            
            # 构建结果数据
            result_data = {
                "delay_ms": delay_ms,
                "message": message,
                "show_countdown": show_countdown,
            }
            
            return self.create_success_result(result_data, f"延时完成: {delay_ms}ms")
            
        except Exception as e:
            ctx.log_error(f"延时执行异常: {e}")
            return self.create_failure_result(f"延时执行异常: {e}")
