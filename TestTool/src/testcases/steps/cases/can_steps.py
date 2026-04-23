"""
CAN 总线相关测试步骤

基于 TestTool/test/canapp/can_sender.py 中的 CANProtocolSender 实现：
- can.connect        -> CanConnectStep
- can.send_frame     -> CanSendFrameStep
- can.disconnect     -> CanDisconnectStep
"""

from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any

import sys
from pathlib import Path


def _load_can_sender(ctx: Context):
    """
    动态加载 test/canapp/can_sender.py 中的 CANProtocolSender。
    这样可以复用现有 DLL 封装，而不复制代码。
    """
    try:
        # src/testcases/steps/cases/ -> TestTool 根目录
        project_root = Path(__file__).resolve().parents[4]
        canapp_dir = project_root / "test" / "canapp"
        if str(canapp_dir) not in sys.path:
            sys.path.insert(0, str(canapp_dir))

        from can_sender import CANProtocolSender  # type: ignore

        return CANProtocolSender
    except Exception as e:  # pragma: no cover
        ctx.log_error(f"[CAN] 加载 CANProtocolSender 失败: {e}")
        return None


class CanConnectStep(BaseStep):
    """连接 CAN 设备并启动总线"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        参数：
        - device_type: 设备类型（默认 4，即 USBCAN2）
        - device_index: 设备索引（默认 0）
        - channel: 通道号（默认 0）
        - baudrate: 波特率，默认 500000
        """
        CANProtocolSender = _load_can_sender(ctx)
        if CANProtocolSender is None:
            return StepResult(
                passed=False,
                message="CANProtocolSender 加载失败",
                error="请检查 test/canapp/can_sender.py 是否存在且可导入",
                error_code="CAN_ERR_IMPORT",
            )

        try:
            # 优先从上下文中读取由测试序列 variables 注入的 CAN 相关变量，
            # 这样 YAML 中可以只在 variables 里配置一次。
            def _to_int(val, default: int) -> int:
                try:
                    return int(val)
                except Exception:
                    return default

            device_type = _to_int(
                ctx.get_data("can_device_type", params.get("device_type", 4)),
                4,
            )
            device_index = _to_int(
                ctx.get_data("can_device_index", params.get("device_index", 0)),
                0,
            )
            channel = _to_int(
                ctx.get_data("can_channel", params.get("channel", 0)),
                0,
            )
            baudrate = _to_int(
                ctx.get_data("can_baudrate", params.get("baudrate", 500000)),
                500000,
            )

            ctx.log_info(
                f"[CAN] 准备连接设备: type={device_type}, index={device_index}, "
                f"channel={channel}, baudrate={baudrate}"
            )

            sender = CANProtocolSender(device_type, device_index, channel)
            try:
                if not sender.connect(baudrate):
                    ctx.log_error("[CAN] 连接设备失败")
                    return StepResult(
                        passed=False,
                        message="CAN 设备连接失败",
                        error="调用 CANProtocolSender.connect 返回 False。请检查：1) CAN设备是否连接并安装驱动；2) DLL文件是否正确打包；3) Visual C++运行库是否安装",
                        error_code="CAN_ERR_CONNECT_FAILED",
                    )
            except RuntimeError as e:
                ctx.log_error(f"[CAN] DLL加载失败: {e}")
                return StepResult(
                    passed=False,
                    message="CAN DLL加载失败",
                    error=str(e),
                    error_code="CAN_ERR_DLL_LOAD_FAILED",
                )
            except Exception as e:
                ctx.log_error(f"[CAN] 连接异常: {e}")
                import traceback
                ctx.log_error(f"[CAN] 异常堆栈: {traceback.format_exc()}")
                return StepResult(
                    passed=False,
                    message=f"CAN 连接异常: {e}",
                    error=str(e),
                    error_code="CAN_ERR_CONNECT_EXCEPTION",
                )

            ctx.set_comm_driver("can_bus", sender)
            ctx.set_state("can_connected", True)

            ctx.log_info("[CAN] ✓ CAN 设备连接成功")
            return StepResult(
                passed=True,
                message="CAN 设备连接成功",
                data={
                    "device_type": device_type,
                    "device_index": device_index,
                    "channel": channel,
                    "baudrate": baudrate,
                },
            )
        except Exception as e:  # pragma: no cover
            ctx.log_error(f"[CAN] 连接异常: {e}")
            return StepResult(
                passed=False,
                message=f"CAN 连接异常: {e}",
                error=str(e),
                error_code="CAN_ERR_CONNECT_EXCEPTION",
            )


class CanSendFrameStep(BaseStep):
    """发送单帧 CAN 消息"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        参数：
        - frame_id: 帧 ID（支持 "0x00000601" 或 "00 00 06 01"）
        - data: 数据，十六进制字符串（如 "23 00 61 2A 00 00 01 00"）
        - description: 描述（可选）
        """
        sender = ctx.get_comm_driver("can_bus")
        if not sender:
            return StepResult(
                passed=False,
                message="CAN 设备未连接",
                error="请先执行 can.connect 步骤",
                error_code="CAN_ERR_NOT_CONNECTED",
            )

        try:
            frame_id = str(params.get("frame_id", "0x00000601"))
            data = str(params.get("data", "")).strip()
            description = str(params.get("description", ""))

            ctx.log_info(
                f"[CAN] 发送帧: ID={frame_id}, data={data}, desc={description}"
            )

            ok = sender.send(frame_id, data)
            if ok:
                ctx.log_info("[CAN] ✓ 帧发送成功")
                return StepResult(
                    passed=True,
                    message="CAN 帧发送成功",
                    data={
                        "frame_id": frame_id,
                        "data": data,
                        "description": description,
                    },
                )

            ctx.log_error("[CAN] ✗ 帧发送失败")
            return StepResult(
                passed=False,
                message="CAN 帧发送失败",
                error="CANProtocolSender.send 返回 False",
                error_code="CAN_ERR_SEND_FAILED",
            )
        except Exception as e:  # pragma: no cover
            ctx.log_error(f"[CAN] 发送异常: {e}")
            return StepResult(
                passed=False,
                message=f"CAN 帧发送异常: {e}",
                error=str(e),
                error_code="CAN_ERR_SEND_EXCEPTION",
            )


class CanDisconnectStep(BaseStep):
    """断开 CAN 设备"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        try:
            sender = ctx.get_comm_driver("can_bus")
            if not sender:
                ctx.log_info("[CAN] 当前未连接 CAN 设备")
                return StepResult(
                    passed=True,
                    message="当前未连接 CAN 设备",
                    data={"disconnected": True},
                )

            try:
                sender.disconnect()
            except Exception as e:  # pragma: no cover
                ctx.log_warning(f"[CAN] 调用 disconnect 出现异常: {e}")

            ctx.remove_comm_driver("can_bus")
            ctx.set_state("can_connected", False)

            ctx.log_info("[CAN] 已断开 CAN 设备连接")
            return StepResult(
                passed=True,
                message="CAN 设备断开连接成功",
                data={"disconnected": True},
            )
        except Exception as e:  # pragma: no cover
            ctx.log_error(f"[CAN] 断开连接异常: {e}")
            ctx.remove_comm_driver("can_bus")
            ctx.set_state("can_connected", False)
            return StepResult(
                passed=True,
                message="CAN 设备断开连接（可能有异常）",
                data={"disconnected": True},
            )






