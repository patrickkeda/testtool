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
import time

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
            def _to_bool(val: Any, default: bool = False) -> bool:
                if isinstance(val, bool):
                    return val
                if val is None:
                    return default
                text = str(val).strip().lower()
                if text in ("1", "true", "yes", "y", "on"):
                    return True
                if text in ("0", "false", "no", "n", "off"):
                    return False
                return default

            def _to_int(val: Any, default: int) -> int:
                try:
                    return int(val)
                except Exception:
                    return default

            def _parse_frame_id(frame_id_text: str) -> int:
                text = frame_id_text.strip().replace(" ", "").replace("0x", "").replace("0X", "")
                return int(text, 16)

            def _parse_data_bytes(data_text: str) -> list[int]:
                text = data_text.strip().replace(" ", "")
                if not text:
                    return []
                if len(text) % 2 != 0:
                    text = "0" + text
                return [int(text[i:i + 2], 16) for i in range(0, len(text), 2)]

            frame_id = str(params.get("frame_id", "0x00000601"))
            data = str(params.get("data", "")).strip()
            description = str(params.get("description", ""))
            wait_response = _to_bool(params.get("wait_response", False), False)
            response_timeout_ms = _to_int(params.get("response_timeout_ms", 300), 300)
            response_max_count = _to_int(params.get("response_max_count", 30), 30)
            decode_servo_version = _to_bool(params.get("decode_servo_version", False), False)
            version_required = _to_bool(params.get("version_required", False), False)
            log_all_responses = _to_bool(params.get("log_all_responses", False), False)
            response_log_limit = _to_int(params.get("response_log_limit", 20), 20)

            ctx.log_info(
                f"[CAN] 发送帧: ID={frame_id}, data={data}, desc={description}"
            )

            # 版本读取场景下先清空一次接收缓存，避免历史周期帧干扰匹配
            if wait_response:
                drained = 0
                for _ in range(10):
                    old_batch = sender.receive_messages(timeout_ms=0, max_count=response_max_count)
                    if not old_batch:
                        break
                    drained += len(old_batch)
                if drained > 0:
                    ctx.log_info(f"[CAN] 发送前已清空接收缓存: {drained} 帧")

            ok = sender.send(frame_id, data)
            if ok:
                extra_data: Dict[str, Any] = {}
                if wait_response:
                    req_id = _parse_frame_id(frame_id)
                    req_data = _parse_data_bytes(data)
                    node_id = req_id & 0xFF
                    expected_resp_id = 0x580 + node_id
                    # 一些设备会使用 0x50x 回传，保留兼容匹配
                    alt_resp_id = 0x500 + node_id

                    # 轮询接收直到超时，避免“发送后立即读一次”导致错过应答帧
                    deadline = time.time() + max(1, response_timeout_ms) / 1000.0
                    recv_msgs = []
                    version_msg = None
                    while time.time() < deadline:
                        left_ms = int(max(1, (deadline - time.time()) * 1000))
                        batch = sender.receive_messages(
                            timeout_ms=min(50, left_ms),
                            max_count=response_max_count,
                        )
                        if batch:
                            recv_msgs.extend(batch)
                            if decode_servo_version:
                                for msg in batch:
                                    if msg.frame_id not in (expected_resp_id, alt_resp_id):
                                        continue
                                    if len(msg.data) < 8:
                                        continue
                                    # 标准读 4 字节应答: CS=0x43，索引=00 61，子索引=0x01
                                    if msg.data[0] != 0x43:
                                        continue
                                    if msg.data[1] != req_data[1] or msg.data[2] != req_data[2] or msg.data[3] != 0x01:
                                        continue
                                    version_msg = msg
                                    break
                                if version_msg is not None:
                                    break
                            # 已收到后再短暂等待一个时间片，尽量收齐同批应答
                            time.sleep(0.01)
                        else:
                            time.sleep(0.005)
                    recv_dump = []
                    for msg in recv_msgs:
                        recv_dump.append(
                            {
                                "frame_id": f"0x{msg.frame_id:08X}",
                                "data": " ".join(f"{b:02X}" for b in msg.data),
                            }
                        )
                    extra_data["responses"] = recv_dump
                    if recv_dump:
                        # 默认不刷屏，仅打印摘要；需要排查时可显式打开 log_all_responses
                        if log_all_responses:
                            show_count = min(len(recv_dump), max(1, response_log_limit))
                            for idx, one in enumerate(recv_dump[:show_count], start=1):
                                ctx.log_info(
                                    f"[CAN] 接收应答[{idx}]: ID={one['frame_id']}, data={one['data']}"
                                )
                            if len(recv_dump) > show_count:
                                ctx.log_info(
                                    f"[CAN] 其余应答省略: {len(recv_dump) - show_count} 帧"
                                )
                        else:
                            id_counter: Dict[str, int] = {}
                            for one in recv_dump:
                                id_counter[one["frame_id"]] = id_counter.get(one["frame_id"], 0) + 1
                            top_ids = ", ".join(
                                f"{k}x{v}" for k, v in sorted(id_counter.items(), key=lambda kv: kv[1], reverse=True)[:5]
                            )
                            ctx.log_info(
                                f"[CAN] 接收应答共 {len(recv_dump)} 帧，主要ID: {top_ids}"
                            )
                    else:
                        ctx.log_warning(
                            f"[CAN] 在 {response_timeout_ms}ms 内未收到应答帧"
                        )

                    # 舵机软件版本读取日志（0x6100/0x01）
                    if decode_servo_version:
                        try:
                            if version_msg is not None:
                                b4, b5, b6, b7 = version_msg.data[4:8]
                                # 协议文档中的展示按应答数据后32位原序拼接：
                                # data[4..7] = 00 6D 10 01 -> v006D1001
                                version_u32 = (b4 << 24) | (b5 << 16) | (b6 << 8) | b7
                                version_hex = f"0x{version_u32:08X}"
                                # 按协议文档定义：
                                # bit16-31: 软件项目版本号（如 0x006D -> 109）
                                # bit12-15: 软件主版本号 A
                                # bit8-11 : 软件次版本号 B
                                # bit0-7  : 软件修正版本号 C
                                project_code = (version_u32 >> 16) & 0xFFFF
                                main_version = (version_u32 >> 12) & 0x0F
                                minor_version = (version_u32 >> 8) & 0x0F
                                patch_version = version_u32 & 0xFF
                                version_text = f"V{project_code}.{main_version}.{minor_version}.{patch_version}"
                                version_protocol_text = f"v{version_u32:08X}"
                                extra_data["servo_version"] = {
                                    "frame_id": f"0x{version_msg.frame_id:08X}",
                                    "raw_data": " ".join(f"{b:02X}" for b in version_msg.data),
                                    "version_u32_hex": version_hex,
                                    "version_text": version_text,
                                    "version_protocol_text": version_protocol_text,
                                    "project_code": project_code,
                                    "project_code_hex": f"0x{project_code:04X}",
                                    "main_version": main_version,
                                    "minor_version": minor_version,
                                    "patch_version": patch_version,
                                }
                                ctx.log_info(
                                    f"[CAN] 舵机软件版本: {version_text} "
                                    f"(协议格式: {version_protocol_text}, raw={version_hex}, project={project_code}, "
                                    f"A={main_version}, B={minor_version}, C={patch_version})"
                                )
                            else:
                                miss_msg = (
                                    f"[CAN] 未匹配到版本应答帧(期望ID=0x{expected_resp_id:08X}，"
                                    f"兼容ID=0x{alt_resp_id:08X}，CS=0x43, sub-index=0x01)"
                                )
                                # 诊断输出：打印候选版本应答帧（同ID，索引00 61）
                                candidates = []
                                for msg in recv_msgs:
                                    if msg.frame_id not in (expected_resp_id, alt_resp_id):
                                        continue
                                    if len(msg.data) < 4:
                                        continue
                                    if msg.data[1] == req_data[1] and msg.data[2] == req_data[2]:
                                        candidates.append(msg)

                                # 兼容某些固件按 0x01~0x04 四个子索引分别回 1 字节（CS=0x4F）
                                if candidates:
                                    byte_map = {}
                                    for c in candidates:
                                        if len(c.data) >= 5 and c.data[0] == 0x4F and 0x01 <= c.data[3] <= 0x04:
                                            byte_map[c.data[3]] = c.data[4]
                                    if all(k in byte_map for k in (1, 2, 3, 4)):
                                        b1 = byte_map[1]
                                        b2 = byte_map[2]
                                        b3 = byte_map[3]
                                        b4 = byte_map[4]
                                        version_u32 = (b1 << 24) | (b2 << 16) | (b3 << 8) | b4
                                        version_hex = f"0x{version_u32:08X}"
                                        project_code = (version_u32 >> 16) & 0xFFFF
                                        main_version = (version_u32 >> 12) & 0x0F
                                        minor_version = (version_u32 >> 8) & 0x0F
                                        patch_version = version_u32 & 0xFF
                                        version_text = f"V{project_code}.{main_version}.{minor_version}.{patch_version}"
                                        version_protocol_text = f"v{version_u32:08X}"
                                        extra_data["servo_version"] = {
                                            "frame_id": f"0x{expected_resp_id:08X}",
                                            "raw_data": f"{b1:02X} {b2:02X} {b3:02X} {b4:02X}",
                                            "version_u32_hex": version_hex,
                                            "version_text": version_text,
                                            "version_protocol_text": version_protocol_text,
                                            "project_code": project_code,
                                            "project_code_hex": f"0x{project_code:04X}",
                                            "main_version": main_version,
                                            "minor_version": minor_version,
                                            "patch_version": patch_version,
                                        }
                                        ctx.log_info(
                                            f"[CAN] 舵机软件版本(分段回包): {version_text} "
                                            f"(协议格式: {version_protocol_text}, raw={version_hex})"
                                        )
                                        candidates = []

                                if candidates:
                                    show_n = min(len(candidates), 5)
                                    for i in range(show_n):
                                        c = candidates[i]
                                        raw = " ".join(f"{b:02X}" for b in c.data)
                                        ctx.log_info(
                                            f"[CAN] 版本候选帧[{i+1}]: ID=0x{c.frame_id:08X}, data={raw}"
                                        )
                                    if len(candidates) > show_n:
                                        ctx.log_info(
                                            f"[CAN] 版本候选帧其余省略: {len(candidates) - show_n} 帧"
                                        )

                                if version_required:
                                    ctx.log_warning(miss_msg)
                                else:
                                    ctx.log_info(
                                        miss_msg + "，本步骤按非强制模式继续。"
                                    )
                        except Exception as parse_err:
                            ctx.log_warning(f"[CAN] 版本应答解析失败: {parse_err}")

                ctx.log_info("[CAN] ✓ 帧发送成功")
                return StepResult(
                    passed=True,
                    message="CAN 帧发送成功",
                    data={
                        "frame_id": frame_id,
                        "data": data,
                        "description": description,
                        **extra_data,
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






