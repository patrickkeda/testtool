"""
确认对话框步骤

在执行流程中弹出一个阻塞确认对话框，用户点击“确认”后流程继续。
"""
from typing import Dict, Any

from ...base import BaseStep, StepResult
from ...context import Context


class ConfirmStep(BaseStep):
    """显示确认提示，等待用户确认"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        参数示例：
        - title: 对话框标题（默认 “操作确认”）
        - message: 对话框内容
        - confirm_text: 确认按钮文字（默认 “确认”）
        - cancel_text: 取消按钮文字（默认 “取消”）
        - allow_cancel: 是否允许取消（默认 True; False 时不显示取消按钮）
        """
        title = self.get_param_str(params, "title", "操作确认")
        message = self.get_param_str(params, "message", "请确认是否继续")
        confirm_text = self.get_param_str(params, "confirm_text", "确认")
        allow_cancel = self.get_param_bool(params, "allow_cancel", True)
        cancel_text = self.get_param_str(params, "cancel_text", "取消") if allow_cancel else ""

        ctx.log_info(f"显示确认对话框: {message}")

        try:
            from src.app.ui_invoker import invoke_in_gui_confirmation

            accepted = invoke_in_gui_confirmation(
                title=title,
                message=message,
                confirm_text=confirm_text,
                cancel_text=cancel_text,
                port=ctx.port,
                allow_cancel=allow_cancel,
            )
        except Exception as exc:
            ctx.log_error(f"确认对话框显示失败: {exc}")
            return self.create_failure_result("确认对话框显示失败", error=str(exc))

        if accepted:
            ctx.log_info("用户已确认，继续执行")
            return self.create_success_result(
                data={"confirmed": True},
                message="用户确认完成"
            )

        ctx.log_warning("用户取消了测试流程")
        return self.create_failure_result("用户取消确认", data={"confirmed": False})

