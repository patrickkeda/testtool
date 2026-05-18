"""
延时测试步骤

示例：简单的延时等待功能。
"""
from datetime import datetime
import time
from typing import Any, Dict

from ...base import BaseStep, StepResult
from ...context import Context


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
        - countdown_allow_interrupt: 倒计时是否允许关闭窗口中断（可选，默认 False；
          True 时用户关闭窗口则本步骤失败）
        - save_countdown_started_at_context_key: 非空时，在延时/倒计时**开始瞬间**将
          ``%Y%m%d_%H%M%S`` 时间戳写入上下文该键（供后续步骤目录命名等，例如 PVT Hub 倒计时）。
        - countdown_completion_buttons: 为真时显示「煲机无异常 / 煲机异常」。「煲机异常」可随时点击；
          「煲机无异常」须待倒计时结束方可点。两种选择均视为本步成功；结果写入 ``countdown_outcome_context_key``
          （值为 ``ok`` 或 ``abnormal``）。关闭窗口且未完成选择则本步失败。
        - countdown_ok_button_text / countdown_abnormal_button_text: 上述两按钮文案（可选）。
        - countdown_outcome_context_key: 煲机结果写入上下文的键名；与 ``countdown_completion_buttons``
          联用，默认 ``pvt_hub_burnin_outcome``。
        - 日志与成功结果中的耗时为**实际经过时间**（``elapsed_ms``），计划时长仍为 ``delay_ms`` / ``duration_ms``。
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
        countdown_allow_interrupt = self.get_param_bool(
            params, "countdown_allow_interrupt", False
        )
        save_at_key = self.get_param_str(
            params, "save_countdown_started_at_context_key", ""
        ).strip()
        completion_btns = self.get_param_bool(
            params, "countdown_completion_buttons", False
        )
        outcome_key = self.get_param_str(
            params, "countdown_outcome_context_key", "pvt_hub_burnin_outcome"
        ).strip()
        ok_btn_txt = self.get_param_str(
            params, "countdown_ok_button_text", "煲机无异常"
        )
        abnormal_btn_txt = self.get_param_str(
            params, "countdown_abnormal_button_text", "煲机异常"
        )
        if save_at_key:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            ctx.set_data(save_at_key, ts)
            ctx.log_info(f"延时/倒计时开始，已写入上下文 {save_at_key}={ts}")

        # 2) 执行延时
        try:
            ctx.log_info(f"开始延时: {message}")
            wait_start = time.monotonic()

            def _elapsed_ms() -> int:
                return max(0, int((time.monotonic() - wait_start) * 1000))

            if show_countdown:
                try:
                    from src.app.ui_invoker import invoke_in_gui_countdown

                    ok_cd, outcome_str = invoke_in_gui_countdown(
                        title=title,
                        message=message,
                        duration_ms=delay_ms,
                        port=ctx.port,
                        allow_interrupt=countdown_allow_interrupt,
                        completion_buttons=completion_btns,
                        ok_button_text=ok_btn_txt,
                        abnormal_button_text=abnormal_btn_txt,
                    )
                    if not ok_cd:
                        ctx.log_warning("倒计时未正常完成（被关闭或未选择煲机结果）")
                        return self.create_failure_result(
                            "倒计时被中断或未确认煲机结果",
                            error="COUNTDOWN_INTERRUPTED",
                            data={
                                "delay_ms": delay_ms,
                                "elapsed_ms": _elapsed_ms(),
                                "show_countdown": True,
                                "countdown_allow_interrupt": countdown_allow_interrupt,
                                "countdown_completion_buttons": completion_btns,
                            },
                        )
                    if completion_btns and outcome_key:
                        ctx.set_data(outcome_key, outcome_str)
                        ctx.log_info(
                            f"煲机结果已写入上下文 {outcome_key}={outcome_str!r}"
                        )
                except Exception as exc:
                    if completion_btns:
                        ctx.log_error(f"煲机倒计时 UI 失败: {exc}")
                        return self.create_failure_result(
                            "煲机倒计时界面异常，无法记录无异常/异常",
                            error=str(exc),
                            data={"delay_ms": delay_ms, "elapsed_ms": _elapsed_ms()},
                        )
                    ctx.log_warning(
                        f"倒计时弹窗显示失败，回退为普通延时: {exc}"
                    )
                    ctx.sleep_ms(delay_ms)
            else:
                ctx.sleep_ms(delay_ms)

            elapsed_ms = _elapsed_ms()
            ctx.log_info(
                f"延时完成: 实际经过 {elapsed_ms}ms（计划 {delay_ms}ms）"
            )

            # 构建结果数据
            result_data = {
                "delay_ms": delay_ms,
                "elapsed_ms": elapsed_ms,
                "message": message,
                "show_countdown": show_countdown,
            }
            if save_at_key:
                result_data["save_countdown_started_at_context_key"] = save_at_key
                result_data["countdown_started_at"] = ctx.get_data(save_at_key, "")
            if completion_btns and outcome_key:
                result_data["countdown_outcome_context_key"] = outcome_key
                result_data["burnin_outcome"] = ctx.get_data(outcome_key, "")

            return self.create_success_result(
                result_data,
                f"延时完成: 实际 {elapsed_ms}ms（计划 {delay_ms}ms）",
            )
            
        except Exception as e:
            ctx.log_error(f"延时执行异常: {e}")
            return self.create_failure_result(f"延时执行异常: {e}")
