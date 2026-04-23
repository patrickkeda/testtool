"""
PLC Modbus RTU 步骤（通过串口 COM 口）

说明：
- 与原来的電机用 `modbus_steps.py` 完全独立，避免互相影响
- 只支持 Modbus RTU 串口方式，用于通过 COM 口连接 PLC

提供的步骤类型（在 register_steps.py 中注册）：
- plc.modbus.connect        -> PlcModbusConnectStep
- plc.modbus.write_register -> PlcModbusWriteRegisterStep
- plc.modbus.read_register  -> PlcModbusReadRegisterStep
- plc.modbus.disconnect     -> PlcModbusDisconnectStep
"""

from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any
import json
import os
import sys

import time

try:
    # 与 plc-com-gui.py 保持一致：优先使用 pymodbus.client.serial
    from pymodbus.client.serial import ModbusSerialClient  # type: ignore
    PYMODBUS_AVAILABLE = True
except ImportError:  # pragma: no cover - 兼容新版本
    try:
        # 如果旧路径不存在，尝试新版本路径
        from pymodbus.client import ModbusSerialClient  # type: ignore
        PYMODBUS_AVAILABLE = True
    except ImportError:  # pragma: no cover
        try:
            # 最后尝试 sync 路径（旧版本）
            from pymodbus.client.sync import ModbusSerialClient  # type: ignore
            PYMODBUS_AVAILABLE = True
        except ImportError:  # pragma: no cover
            PYMODBUS_AVAILABLE = False
            ModbusSerialClient = None  # type: ignore


if PYMODBUS_AVAILABLE:

    class _PlcModbusSerialClient(ModbusSerialClient):
        """修复 pymodbus 同步串口「先 open 再设 inter_byte_timeout」导致的二次 _reconfigure。

        部分 Windows USB-RS485 在第二次 SetCommState 时返回 WinError 31（设备未正常工作）；
        在 serial_for_url 创建时即传入 inter_byte_timeout，与 pymodbus 内部算法一致，只配置一次端口。
        """

        def connect(self) -> bool:
            if self.socket:
                return True
            import serial
            from pymodbus.logging import Log

            try:
                self.socket = serial.serial_for_url(
                    self.comm_params.host,
                    timeout=self.comm_params.timeout_connect,
                    bytesize=self.comm_params.bytesize,
                    stopbits=self.comm_params.stopbits,
                    baudrate=self.comm_params.baudrate,
                    parity=self.comm_params.parity,
                    exclusive=True,
                    inter_byte_timeout=self.inter_byte_timeout,
                )
                self.last_frame_end = None
            except Exception as msg:
                Log.error("{}", msg)
                self.close()
            return self.socket is not None


def _debug_log(location: str, message: str, data: dict = None):
    """调试日志函数"""
    try:
        # 使用绝对路径：d:\b2test\TestTool-v0.4\.cursor\debug.log
        log_path = r'd:\b2test\TestTool-v0.4\.cursor\debug.log'
        # 确保目录存在
        log_dir = os.path.dirname(log_path)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        log_entry = {
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
            "sessionId": "debug-session",
            "runId": "run1"
        }
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            f.flush()  # 强制刷新，确保立即写入
    except Exception as e:
        # 如果日志写入失败，尝试打印到标准输出作为回退
        try:
            import sys
            print(f"[DEBUG_LOG_ERROR] {location}: {message} - {e}", file=sys.stderr)
            if data:
                print(f"[DEBUG_DATA] {data}", file=sys.stderr)
        except:
            pass  # 完全失败时静默

def _check_and_ensure_connection(client, ctx: Context) -> bool:
    """检查并确保 Modbus 客户端连接有效"""
    # #region agent log
    _debug_log("modbus_steps_com.py:_check_and_ensure_connection", "检查连接状态", {"client_type": str(type(client))})
    # #endregion
    try:
        # 检查连接状态的多种方式
        is_connected = False
        check_method = None
        if hasattr(client, 'is_socket_open'):
            is_connected = client.is_socket_open()
            check_method = "is_socket_open"
        elif hasattr(client, 'socket') and client.socket:
            is_connected = True
            check_method = "socket exists"
        elif hasattr(client, 'is_connected'):
            is_connected = client.is_connected()
            check_method = "is_connected"
        else:
            # 如果没有检查方法，假设已连接（由调用者处理）
            ctx.log_debug("[PLC] 无法检查连接状态，假设已连接")
            # #region agent log
            _debug_log("modbus_steps_com.py:_check_and_ensure_connection", "无法检查连接状态", {"assumed_connected": True})
            # #endregion
            return True
        
        # #region agent log
        _debug_log("modbus_steps_com.py:_check_and_ensure_connection", "连接状态检查结果", {"is_connected": is_connected, "check_method": check_method})
        # #endregion
        
        if not is_connected:
            ctx.log_warning("[PLC] 客户端连接已断开，尝试重新连接...")
            # #region agent log
            _debug_log("modbus_steps_com.py:_check_and_ensure_connection", "尝试重新连接", {})
            # #endregion
            reconnect_result = client.connect()
            # #region agent log
            _debug_log("modbus_steps_com.py:_check_and_ensure_connection", "重新连接结果", {"success": reconnect_result})
            # #endregion
            if not reconnect_result:
                ctx.log_error("[PLC] 重新连接失败")
                return False
            ctx.log_info("[PLC] 重新连接成功")
        return True
    except Exception as e:
        ctx.log_warning(f"[PLC] 检查连接状态时出现异常（继续尝试操作）: {e}")
        # #region agent log
        _debug_log("modbus_steps_com.py:_check_and_ensure_connection", "检查连接异常", {"error": str(e)})
        # #endregion
        return True  # 继续尝试，让实际操作来验证连接


def _replace_variables(text: str, ctx: Context) -> str:
    """简单的变量替换，支持 ${sn} / ${port} / ${xxx} (来自上下文数据)"""
    import re

    pattern = r"\$\{([^}]+)\}"

    def repl(m):
        name = m.group(1)
        if name == "sn":
            return ctx.get_sn() or ""
        if name == "port":
            return getattr(ctx, "port", "") or ""
        # 其他变量从上下文 data 里取（例如 plc_serial_port, plc_unit_id 等）
        v = ctx.get_data(name, "")
        if v is not None and v != "":
            ctx.log_debug(f"[PLC] 变量替换: ${{{name}}} = {v}")
            return str(v)
        else:
            ctx.log_warning(f"[PLC] 变量 ${{{name}}} 未找到，保持原样")
            return m.group(0)  # 保持原样，不替换

    return re.sub(pattern, repl, text)


def _temporary_modbus_timeout(client, timeout_sec: float):
    """临时拉长 pymodbus 客户端 I/O 超时（pymodbus 3.x 的 comm_params.timeout_connect 等）。"""
    from dataclasses import replace

    snapshots: list[tuple[str, Any]] = []

    try:
        if hasattr(client, "comm_params") and client.comm_params is not None:
            old_cp = client.comm_params
            try:
                client.comm_params = replace(old_cp, timeout_connect=float(timeout_sec))
                snapshots.append(("comm_params", old_cp))
            except Exception:
                pass
        if hasattr(client, "timeout"):
            try:
                old_t = getattr(client, "timeout")
                setattr(client, "timeout", float(timeout_sec))
                snapshots.append(("timeout_attr", old_t))
            except Exception:
                pass
    except Exception:
        pass

    def restore() -> None:
        for kind, old_val in reversed(snapshots):
            try:
                if kind == "comm_params":
                    client.comm_params = old_val
                elif kind == "timeout_attr":
                    setattr(client, "timeout", old_val)
            except Exception:
                pass

    return restore


class PlcModbusConnectStep(BaseStep):
    """通过串口连接 PLC (Modbus RTU)"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """连接 PLC

        参数：
        - port: 串口号，例如 "COM3"
        - baudrate: 波特率，默认 115200（符合治具要求）
        - parity: 校验位，"N"/"E"/"O"，默认 "O" (ODD)
        - stopbits: 停止位，默认 1
        - bytesize: 数据位，默认 8
        - timeout: 超时时间（秒），默认 5
        """
        if not PYMODBUS_AVAILABLE:
            return StepResult(
                passed=False,
                message="pymodbus 库未安装",
                error="请安装 pymodbus: pip install pymodbus",
                error_code="PLC_MODBUS_ERR_LIB_NOT_FOUND",
            )

        try:
            # 上一轮测试若异常退出，或同一进程内重复跑序列，可能仍挂着客户端；不先关掉则 COM 会被占用导致“第二次连不上”
            old = ctx.get_comm_driver("plc_modbus")
            if old is not None:
                ctx.log_info("[PLC] 检测到未释放的 Modbus 连接，先关闭后再建立新连接")
                try:
                    old.close()
                except Exception:
                    pass
                ctx.remove_comm_driver("plc_modbus")
                ctx.set_state("plc_modbus_connected", False)
                ctx.remove_state("plc_modbus_port")
                time.sleep(0.15)

            # 优先从上下文中读取 PLC 相关变量（由测试序列 variables 注入），
            # 避免直接使用形如 "${plc_baudrate}" 的字符串
            port = str(ctx.get_data("plc_serial_port", params.get("port", "COM3")))
            # 默认波特率改为 115200，满足“115200 8O1”的需求
            # 关键：必须优先使用 YAML 序列中的配置，确保与 plc-com-gui.py 一致（115200 8O1）
            plc_baudrate_from_ctx = ctx.get_data("plc_baudrate", None)
            if plc_baudrate_from_ctx is not None:
                baudrate = int(plc_baudrate_from_ctx)
                ctx.log_info(f"[PLC] 使用YAML序列中的波特率: {baudrate}")
            else:
                baudrate = int(params.get("baudrate", 115200))
                ctx.log_warning(f"[PLC] YAML序列中未找到plc_baudrate，使用默认/参数中的波特率: {baudrate}")
            # #region agent log
            _debug_log("modbus_steps_com.py:PlcModbusConnectStep", "读取波特率", {
                "plc_baudrate_from_ctx": plc_baudrate_from_ctx,
                "params_baudrate": params.get("baudrate"),
                "final_baudrate": baudrate
            })
            # #endregion
            parity = str(ctx.get_data("plc_parity", params.get("parity", "O"))).upper()
            stopbits = int(ctx.get_data("plc_stopbits", params.get("stopbits", 1)))
            bytesize = int(ctx.get_data("plc_bytesize", params.get("bytesize", 8)))
            timeout = int(ctx.get_data("plc_timeout", params.get("timeout", 5)))

            # 如果端口配置中启用了“治具通讯”，优先使用治具串口作为 PLC 串口，
            # 这样用户只需在端口配置界面选择 COM 口即可，无需修改 YAML。
            try:
                port_cfg = ctx.get_port_config()
                if isinstance(port_cfg, dict):
                    fixture_cfg = port_cfg.get("fixture") or {}
                    if fixture_cfg.get("enabled"):
                        serial_cfg = fixture_cfg.get("serial") or {}
                        cfg_port = serial_cfg.get("port")
                        if cfg_port:
                            port = str(cfg_port)
                            ctx.log_info(f"[PLC] 使用治具串口作为 PLC 串口: {port} (注意：波特率等参数使用YAML配置，不覆盖)")
                        # 关键修复：不覆盖波特率、校验位等参数，优先使用 YAML 序列中的配置
                        # 这样确保与 plc-com-gui.py 的配置一致（115200 8O1）
                        # 重要：即使治具串口配置中有 baudrate，也不使用，确保使用 YAML 序列中的配置
                        # cfg_baud = serial_cfg.get("baudrate")
                        # if cfg_baud:
                        #     baudrate = int(cfg_baud)  # 已注释掉，不覆盖 YAML 配置
                        # #region agent log
                        _debug_log("modbus_steps_com.py:PlcModbusConnectStep", "治具串口配置", {
                            "cfg_port": cfg_port,
                            "cfg_baudrate": serial_cfg.get("baudrate"),
                            "current_baudrate": baudrate,
                            "note": "不覆盖波特率，使用YAML配置"
                        })
                        # #endregion
                        cfg_timeout_ms = serial_cfg.get("timeout_ms")
                        if cfg_timeout_ms is not None:
                            timeout = max(1, int(cfg_timeout_ms / 1000))
            except Exception as e:  # pragma: no cover
                ctx.log_warning(f"[PLC] 从端口配置读取治具串口失败: {e}")

            # #region agent log
            _debug_log("modbus_steps_com.py:PlcModbusConnectStep", "最终连接参数", {
                "port": port, "baudrate": baudrate, "bytesize": bytesize, 
                "parity": parity, "stopbits": stopbits, "timeout": 1,
                "plc_baudrate_from_ctx": ctx.get_data("plc_baudrate", None),
                "plc_parity_from_ctx": ctx.get_data("plc_parity", None)
            })
            # #endregion
            ctx.log_info(
                f"[PLC] 正在连接 Modbus RTU: {port}, {baudrate},{bytesize}{parity}{stopbits}, 超时={timeout}s"
            )

            # 完全按照 plc-com-gui.py 的方式创建客户端
            # plc-com-gui.py 中：ModbusSerialClient(port=..., baudrate=..., bytesize=..., parity=..., stopbits=..., timeout=1)
            # 关键：plc-com-gui.py 使用 timeout=1，我们也使用 timeout=1 保持一致
            # #region agent log
            _debug_log("modbus_steps_com.py:PlcModbusConnectStep", "创建客户端前", {
                "port": port, "baudrate": baudrate, "bytesize": bytesize, 
                "parity": parity, "stopbits": stopbits, "timeout": 1
            })
            # #endregion
            # Windows：close 后驱动释放慢；WinError 31 时加长退避，避免连续重试把 USB 转串口打挂
            max_attempts = 4
            backoff_after_fail = (0.5, 1.0, 2.0) if sys.platform == "win32" else (0.25, 0.35, 0.5)
            client = None
            connect_result = False
            for attempt in range(1, max_attempts + 1):
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
                    client = None
                    if attempt > 1:
                        time.sleep(backoff_after_fail[attempt - 2])
                client = _PlcModbusSerialClient(
                    port=port,
                    baudrate=baudrate,
                    bytesize=bytesize,
                    parity=parity,
                    stopbits=stopbits,
                    timeout=1,  # 与 plc-com-gui.py 完全一致：使用 timeout=1
                )
                # #region agent log
                _debug_log(
                    "modbus_steps_com.py:PlcModbusConnectStep",
                    "客户端创建完成",
                    {"client_type": str(type(client)), "attempt": attempt},
                )
                # #endregion

                connect_result = client.connect()
                # #region agent log
                _debug_log(
                    "modbus_steps_com.py:PlcModbusConnectStep",
                    "连接结果",
                    {"success": connect_result, "attempt": attempt},
                )
                # #endregion
                if connect_result:
                    break
                ctx.log_warning(
                    f"[PLC] Modbus RTU 连接 {port} 第 {attempt}/{max_attempts} 次失败，"
                    + ("将重试…" if attempt < max_attempts else "不再重试")
                )

            if connect_result:
                ctx.log_info(f"[PLC] ✓ Modbus RTU 连接成功: {port}")
                ctx.set_comm_driver("plc_modbus", client)
                ctx.set_state("plc_modbus_connected", True)
                ctx.set_state("plc_modbus_port", port)
                return StepResult(
                    passed=True,
                    message=f"PLC Modbus RTU 连接成功: {port}",
                    data={
                        "port": port,
                        "baudrate": baudrate,
                        "parity": parity,
                        "stopbits": stopbits,
                        "bytesize": bytesize,
                        "timeout": timeout,
                        "connected": True,
                    },
                )

            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            ctx.log_error(f"[PLC] ✗ Modbus RTU 连接失败: {port}")
            ctx.log_error(
                "[PLC] 若日志含 WinError 31 / “设备没有发挥作用”：多为 USB 转串口或驱动异常，"
                "请拔掉重插、在设备管理器中检查 COM 口、并关闭其它占用该串口的程序。"
            )
            return StepResult(
                passed=False,
                message=f"PLC Modbus RTU 连接失败: {port}",
                error="连接失败",
                error_code="PLC_MODBUS_ERR_CONNECT_FAILED",
            )

        except Exception as e:  # pragma: no cover
            ctx.log_error(f"[PLC] Modbus RTU 连接异常: {e}")
            return StepResult(
                passed=False,
                message=f"PLC Modbus RTU 连接异常: {e}",
                error=str(e),
                error_code="PLC_MODBUS_ERR_CONNECT_EXCEPTION",
            )


class PlcModbusWriteRegisterStep(BaseStep):
    """PLC: 写单个保持寄存器 / 线圈控制"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """写寄存器或线圈

        参数：
        - address: PLC 中看到的地址（例如 2049、2050），内部会做必要偏移
        - value: 写入的值（整数或 0/1）
        - unit_id: 从站地址（默认 1）
        - description: 描述（可选）
        - use_coil: 为 True 时走 write_coil / read_coils 风格（与 plc-com-gui 一致）
        - 注意：地址会做 address - 1 的偏移（与 plc-com-gui.py 完全一致）
        - tolerate_no_modbus_response: 为 True 时仅尽力写入；在 modbus_response_timeout_sec 内无有效应答仍判步骤通过并继续（不读回校验）
        - modbus_response_timeout_sec: 与 tolerate 配合，单次写等待应答的最长时间（秒），默认 10
        """
        if not PYMODBUS_AVAILABLE:
            return StepResult(
                passed=False,
                message="pymodbus 库未安装",
                error="请安装 pymodbus: pip install pymodbus",
                error_code="PLC_MODBUS_ERR_LIB_NOT_FOUND",
            )

        try:
            client = ctx.get_comm_driver("plc_modbus")
            if not client:
                return StepResult(
                    passed=False,
                    message="PLC Modbus 未连接",
                    error="请先执行 plc.modbus.connect 步骤",
                    error_code="PLC_MODBUS_ERR_NOT_CONNECTED",
                )
            
            # 验证并确保客户端连接有效
            if not _check_and_ensure_connection(client, ctx):
                return StepResult(
                    passed=False,
                    message="PLC Modbus 连接已断开，重新连接失败",
                    error="PLC连接已断开",
                    error_code="PLC_MODBUS_ERR_NOT_CONNECTED",
                )

            # #region agent log
            _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "开始写入步骤", {
                "step_id": self.step_id, "step_name": self.step_name, "params": str(params)
            })
            # #endregion
            
            # 获取参数，支持变量替换
            address_val = params.get("address", 0)
            if isinstance(address_val, str):
                address_val = _replace_variables(address_val, ctx)
            address = int(address_val) if address_val else 0
            
            value_val = params.get("value", 0)
            if isinstance(value_val, str):
                value_val = _replace_variables(value_val, ctx)
            value = int(value_val) if value_val else 0
            
            # unit_id 支持变量替换（重要！）
            unit_id_val = params.get("unit_id", ctx.get_data("plc_unit_id", 1))
            if isinstance(unit_id_val, str):
                unit_id_val = _replace_variables(unit_id_val, ctx)
            # 如果变量替换后还是字符串，尝试从上下文获取
            if isinstance(unit_id_val, str) and unit_id_val.startswith("${"):
                unit_id_val = ctx.get_data("plc_unit_id", 1)
            unit_id = int(unit_id_val) if unit_id_val else 1
            
            # #region agent log
            _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "参数解析完成", {
                "address": address, "value": value, "unit_id": unit_id
            })
            # #endregion
            
            description = self.get_param_str(params, "description", "")

            # 是否按线圈方式写入（勿用 bool(str)，否则 "false" 也会被当成 True）
            use_coil = self.get_param_bool(params, "use_coil", False)
            tolerate_no_modbus_response = self.get_param_bool(params, "tolerate_no_modbus_response", False)
            modbus_response_timeout_sec = float(params.get("modbus_response_timeout_sec", 10))
            if tolerate_no_modbus_response:
                ctx.log_info(
                    f"[PLC] tolerate_no_modbus_response 已启用，最长等待 {modbus_response_timeout_sec}s；"
                    f"无 Modbus 应答时仍继续（与 PLC 程序是否已执行动作无必然对应）"
                )

            if use_coil:
                restore_timeout = (
                    _temporary_modbus_timeout(client, modbus_response_timeout_sec)
                    if tolerate_no_modbus_response
                    else (lambda: None)
                )
                try:
                    # 完全按照 plc-com-gui.py 的方式：转换为 Modbus 地址（从 0 开始）
                    # plc-com-gui.py 中：modbus_address = address - 1
                    modbus_address = address - 1
                    coil_val = bool(value)

                    # #region agent log
                    _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "写线圈开始", {
                        "yaml_address": address, "modbus_address": modbus_address, 
                        "value": coil_val, "unit_id": unit_id, "client_type": str(type(client))
                    })
                    # #endregion

                    ctx.log_info(
                        f"[PLC] 写线圈: addr={modbus_address} (YAML地址={address}), value={coil_val}, "
                        f"unit_id={unit_id}, desc={description}"
                    )

                    resp = None
                    last_error = None
                    # 完全按照 plc-com-gui.py 的方式：使用 device_id 参数
                    # plc-com-gui.py 中：result = self.modbus_client.write_coil(modbus_address, value, device_id=node)
                    try:
                        # 方法1：使用 device_id 参数（与 plc-com-gui.py 完全一致）
                        # #region agent log
                        _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "调用write_coil前", {
                            "modbus_address": modbus_address, "coil_val": coil_val, "unit_id": unit_id
                        })
                        # #endregion
                        resp = client.write_coil(modbus_address, coil_val, device_id=unit_id)
                        # #region agent log
                        _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "write_coil调用完成", {
                            "resp": str(resp) if resp else None, "is_error": resp.isError() if resp else None
                        })
                        # #endregion
                    except TypeError as e1:
                        # #region agent log
                        _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "write_coil TypeError", {"error": str(e1)})
                        # #endregion
                        try:
                            # 方法2：尝试使用命名参数 device_id
                            resp = client.write_coil(address=modbus_address, value=coil_val, device_id=unit_id)
                            # #region agent log
                            _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "方法2成功", {"resp": str(resp) if resp else None})
                            # #endregion
                        except TypeError as e2:
                            # #region agent log
                            _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "方法2也失败", {"error": str(e2)})
                            # #endregion
                            try:
                                # 方法3：尝试使用 slave 参数（某些版本可能使用此参数）
                                resp = client.write_coil(modbus_address, coil_val, slave=unit_id)
                                # #region agent log
                                _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "方法3结果", {"resp": str(resp) if resp else None})
                                # #endregion
                            except Exception as e3:
                                last_error = str(e3)
                                resp = None
                                # #region agent log
                                _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "所有方法都失败", {"error": str(e3)})
                                # #endregion
                    except Exception as e:
                        # 捕获所有其他异常（如 ModbusException, ConnectionException 等）
                        last_error = str(e)
                        if tolerate_no_modbus_response:
                            ctx.log_warning(
                                f"[PLC] 写线圈未收到应答（将按 tolerate 继续）: {e}"
                            )
                        else:
                            ctx.log_error(f"[PLC] 写线圈异常: {e}")
                        # #region agent log
                        _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "写线圈异常", {"error": str(e), "error_type": str(type(e))})
                        # #endregion
                        # tolerate 模式下不再二次 write，避免再等一轮超时；直接走下方“未确认也通过”
                        if not tolerate_no_modbus_response:
                            try:
                                resp = client.write_coil(modbus_address, coil_val, device_id=unit_id)
                                # #region agent log
                                _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "重试write_coil", {"resp": str(resp) if resp else None})
                                # #endregion
                            except Exception as e2:
                                last_error = str(e2)
                                resp = None
                                # #region agent log
                                _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "重试也失败", {"error": str(e2)})
                                # #endregion

                    # #region agent log
                    _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "检查响应", {
                        "resp_exists": resp is not None, 
                        "is_error": resp.isError() if resp else None,
                        "resp_str": str(resp) if resp else None
                    })
                    # #endregion
                    if resp and not resp.isError():
                        ctx.log_info(f"[PLC] ✓ 线圈写入成功: Modbus地址={modbus_address} (YAML地址={address}) = {int(coil_val)}")
                        # #region agent log
                        _debug_log("modbus_steps_com.py:PlcModbusWriteRegisterStep", "写入成功", {
                            "modbus_address": modbus_address, "yaml_address": address, "value": int(coil_val)
                        })
                        # #endregion
                        # PLC写入成功后等待一小段时间，确保PLC有足够时间处理命令
                        ctx.sleep_ms(100)
                        return StepResult(
                            passed=True,
                            message=f"PLC 线圈写入成功: {address} = {int(coil_val)}",
                            data={
                                "address": address,
                                "modbus_address": modbus_address,
                                "value": int(coil_val),
                                "unit_id": unit_id,
                                "description": description,
                            },
                        )

                    # tolerate：除“明确成功”外一律放行（超时异常、无 resp、或 pymodbus 返回错误帧但不抛异常）
                    if tolerate_no_modbus_response:
                        ctx.log_warning(
                            f"[PLC] 写线圈未确认成功，按 tolerate_no_modbus_response 继续下一项 "
                            f"(最长等待 {modbus_response_timeout_sec}s, last_error={last_error!r}, resp={resp!r})"
                        )
                        return StepResult(
                            passed=True,
                            message=f"PLC 线圈写入已尝试（未确认应答）: {address} = {int(coil_val)}",
                            data={
                                "address": address,
                                "modbus_address": modbus_address,
                                "value": int(coil_val),
                                "unit_id": unit_id,
                                "description": description,
                                "unacknowledged": True,
                                "last_error": last_error,
                            },
                        )

                    # 提供详细的错误信息
                    if last_error:
                        ctx.log_error(
                            f"[PLC] ⚠ 线圈写入异常: Modbus地址={modbus_address} (YAML地址={address}), value={int(coil_val)}, unit_id={unit_id}, "
                            f"异常={last_error}"
                        )
                        ctx.log_error(
                            f"[PLC] 诊断建议: "
                            f"1) 检查串口连接是否正常 (COM口、波特率115200、校验位O、数据位8、停止位1); "
                            f"2) 检查unit_id={unit_id}是否正确（ModScan32中的Slave ID）; "
                            f"3) 检查YAML地址={address}是否正确（实际Modbus地址={modbus_address}）; "
                            f"4) 检查PLC是否在线并响应; "
                            f"5) 尝试增加timeout时间或重试次数"
                        )
                        return StepResult(
                            passed=False,
                            message=f"PLC 线圈写入失败: {address}",
                            error=f"Modbus Error: {last_error}",
                            error_code="PLC_MODBUS_ERR_WRITE_COIL_FAILED",
                        )
                    else:
                        ctx.log_error(
                            f"[PLC] ⚠ 线圈写入失败: Modbus地址={modbus_address} (YAML地址={address}), value={int(coil_val)}, "
                            f"unit_id={unit_id}, resp={resp}"
                        )
                        ctx.log_error(
                            f"[PLC] 诊断建议: "
                            f"1) 检查串口连接是否正常 (COM口、波特率115200、校验位O、数据位8、停止位1); "
                            f"2) 检查unit_id={unit_id}是否正确; "
                            f"3) 检查PLC是否在线; "
                            f"4) 尝试增加timeout时间"
                        )
                        return StepResult(
                            passed=False,
                            message=f"PLC 线圈写入失败: {address}",
                            error="线圈写入响应异常",
                            error_code="PLC_MODBUS_ERR_WRITE_COIL_FAILED",
                        )
                finally:
                    try:
                        restore_timeout()
                    except Exception as ex:  # noqa: BLE001
                        ctx.log_warning(f"[PLC] 恢复串口超时设置时异常（忽略）: {ex}")

            # 默认仍然是保持寄存器写入（兼容其他场景）
            # 完全按照 plc-com-gui.py 的方式：转换为 Modbus 地址（从 0 开始）
            # plc-com-gui.py 中：modbus_address = address - 1
            modbus_address = address - 1
            ctx.log_info(
                f"[PLC] 写保持寄存器: Modbus地址={modbus_address} (YAML地址={address}), value={value}, unit_id={unit_id}, desc={description}"
            )

            restore_reg = (
                _temporary_modbus_timeout(client, modbus_response_timeout_sec)
                if tolerate_no_modbus_response
                else (lambda: None)
            )
            try:
                # 完全按照 plc-com-gui.py 的方式：使用 device_id 参数
                # plc-com-gui.py 中：result = self.modbus_client.write_register(modbus_address, value, device_id=node)
                resp = None
                last_reg_err = None
                try:
                    try:
                        # 方法1：使用 device_id 参数（与 plc-com-gui.py 完全一致）
                        resp = client.write_register(modbus_address, value, device_id=unit_id)
                    except TypeError:
                        try:
                            # 方法2：尝试使用命名参数 device_id
                            resp = client.write_register(address=modbus_address, value=value, device_id=unit_id)
                        except TypeError:
                            try:
                                # 方法3：尝试使用 slave 参数（某些版本可能使用此参数）
                                resp = client.write_register(modbus_address, value, slave=unit_id)
                            except Exception:
                                resp = None
                except Exception as e:
                    last_reg_err = str(e)
                    resp = None
                    if tolerate_no_modbus_response:
                        ctx.log_warning(
                            f"[PLC] 写保持寄存器异常（将按 tolerate 继续）: {e}"
                        )
                        return StepResult(
                            passed=True,
                            message=f"PLC 寄存器写入已尝试（异常/未确认）: {address} = {value}",
                            data={
                                "address": address,
                                "modbus_address": modbus_address,
                                "value": value,
                                "unit_id": unit_id,
                                "description": description,
                                "unacknowledged": True,
                                "last_error": last_reg_err,
                            },
                        )
                    ctx.log_error(f"[PLC] 写保持寄存器异常: {e}")
                    return StepResult(
                        passed=False,
                        message=f"PLC 寄存器写入失败: {address}",
                        error=str(e),
                        error_code="PLC_MODBUS_ERR_WRITE_REG_EXCEPTION",
                    )

                if resp and not resp.isError():
                    ctx.log_info(f"[PLC] ✓ 寄存器写入成功: Modbus地址={modbus_address} (YAML地址={address}) = {value}")
                    # PLC写入成功后等待一小段时间，确保PLC有足够时间处理命令
                    ctx.sleep_ms(100)
                    return StepResult(
                        passed=True,
                        message=f"PLC 寄存器写入成功: {address} = {value}",
                        data={
                            "address": address,
                            "modbus_address": modbus_address,
                            "value": value,
                            "unit_id": unit_id,
                            "description": description,
                        },
                    )

                if tolerate_no_modbus_response:
                    ctx.log_warning(
                        f"[PLC] 写保持寄存器未确认成功，按 tolerate_no_modbus_response 继续下一项 "
                        f"(最长等待 {modbus_response_timeout_sec}s, resp={resp!r})"
                    )
                    return StepResult(
                        passed=True,
                        message=f"PLC 寄存器写入已尝试（未确认应答）: {address} = {value}",
                        data={
                            "address": address,
                            "modbus_address": modbus_address,
                            "value": value,
                            "unit_id": unit_id,
                            "description": description,
                            "unacknowledged": True,
                        },
                    )

                # 这里记录更多调试信息，查看 PLC 返回的 Modbus 异常码
                if resp is not None:
                    fc = getattr(resp, "function_code", None)
                    exc_code = getattr(resp, "exception_code", None)

                    # 详细的异常码说明
                    exc_msg = ""
                    if exc_code == 0x01:
                        exc_msg = " (非法功能码)"
                    elif exc_code == 0x02:
                        exc_msg = " (非法数据地址 - 检查address是否正确)"
                    elif exc_code == 0x03:
                        exc_msg = " (非法数据值 - 检查value范围)"
                    elif exc_code == 0x04:
                        exc_msg = " (从站设备故障)"
                    elif exc_code == 0x06:
                        exc_msg = " (从站设备忙)"
                    elif exc_code == 0x0A:
                        exc_msg = " (网关路径不可用)"
                    elif exc_code == 0x0B:
                        exc_msg = " (网关目标设备无响应 - 检查unit_id是否正确)"

                    ctx.log_error(
                        f"[PLC] ⚠ 寄存器写入失败: Modbus地址={modbus_address} (YAML地址={address}), value={value}, "
                        f"unit_id={unit_id}, function_code={fc}, exception_code=0x{exc_code:02X}{exc_msg}, "
                        f"raw_resp={resp}"
                    )
                    ctx.log_error(
                        f"[PLC] 诊断建议: "
                        f"1) 检查串口连接是否正常 (COM口、波特率115200、校验位O、数据位8、停止位1); "
                        f"2) 检查unit_id={unit_id}是否正确（ModScan32中的Slave ID）; "
                        f"3) 检查YAML地址={address}是否正确（实际Modbus地址={modbus_address}）; "
                        f"4) 检查串口参数是否与ModScan32一致"
                    )
                else:
                    ctx.log_error(f"[PLC] ⚠ 寄存器写入失败: Modbus地址={modbus_address} (YAML地址={address}), 未收到有效响应")
                    ctx.log_error(
                        f"[PLC] 诊断建议: "
                        f"1) 检查串口连接是否正常 (COM口、波特率115200、校验位O、数据位8、停止位1); "
                        f"2) 检查unit_id={unit_id}是否正确; "
                        f"3) 检查PLC是否在线; "
                        f"4) 尝试增加timeout时间"
                    )
                return StepResult(
                    passed=False,
                    message=f"PLC 寄存器写入失败: {address}",
                    error="写入响应异常",
                    error_code="PLC_MODBUS_ERR_WRITE_REG_FAILED",
                )
            finally:
                try:
                    restore_reg()
                except Exception as ex:  # noqa: BLE001
                    ctx.log_warning(f"[PLC] 恢复串口超时设置时异常（忽略）: {ex}")

        except Exception as e:  # pragma: no cover
            ctx.log_error(f"[PLC] 寄存器写入异常: {e}")
            return StepResult(
                passed=False,
                message=f"PLC 寄存器写入异常: {e}",
                error=str(e),
                error_code="PLC_MODBUS_ERR_WRITE_REG_EXCEPTION",
            )


class PlcModbusReadRegisterStep(BaseStep):
    """PLC: 读取保持寄存器 / 线圈，并在结果中提供 value"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """读寄存器或线圈

        参数：
        - address: 寄存器地址（去掉 40000 偏移后的值，例如 40101 -> 101）
        - count: 读取数量（默认 1）
        - unit_id: 从站地址（默认 1）
        - description: 描述（可选）
        """
        if not PYMODBUS_AVAILABLE:
            return StepResult(
                passed=False,
                message="pymodbus 库未安装",
                error="请安装 pymodbus: pip install pymodbus",
                error_code="PLC_MODBUS_ERR_LIB_NOT_FOUND",
            )

        try:
            client = ctx.get_comm_driver("plc_modbus")
            if not client:
                return StepResult(
                    passed=False,
                    message="PLC Modbus 未连接",
                    error="请先执行 plc.modbus.connect 步骤",
                    error_code="PLC_MODBUS_ERR_NOT_CONNECTED",
                )
            
            # 验证并确保客户端连接有效
            if not _check_and_ensure_connection(client, ctx):
                return StepResult(
                    passed=False,
                    message="PLC Modbus 连接已断开，重新连接失败",
                    error="PLC连接已断开",
                    error_code="PLC_MODBUS_ERR_NOT_CONNECTED",
                )

            # 获取参数，支持变量替换
            address_val = params.get("address", 0)
            if isinstance(address_val, str):
                address_val = _replace_variables(address_val, ctx)
            address = int(address_val) if address_val else 0
            
            count_val = params.get("count", 1)
            if isinstance(count_val, str):
                count_val = _replace_variables(count_val, ctx)
            count = int(count_val) if count_val else 1
            
            # unit_id 支持变量替换（重要！）
            unit_id_val = params.get("unit_id", ctx.get_data("plc_unit_id", 1))
            if isinstance(unit_id_val, str):
                original_val = unit_id_val
                unit_id_val = _replace_variables(unit_id_val, ctx)
                if original_val != unit_id_val:
                    ctx.log_info(f"[PLC] 变量替换: {original_val} -> {unit_id_val}")
            # 如果变量替换后还是字符串，尝试从上下文获取
            if isinstance(unit_id_val, str) and unit_id_val.startswith("${"):
                ctx.log_warning(f"[PLC] 变量 {unit_id_val} 未找到，尝试从上下文获取")
                unit_id_val = ctx.get_data("plc_unit_id", 1)
                ctx.log_info(f"[PLC] 从上下文获取 plc_unit_id = {unit_id_val}")
            unit_id = int(unit_id_val) if unit_id_val else 1
            ctx.log_debug(f"[PLC] 最终 unit_id = {unit_id} (原始值: {params.get('unit_id', '未指定')})")
            
            description = self.get_param_str(params, "description", "")

            # 是否按线圈方式读取
            use_coil = bool(params.get("use_coil", False))

            if use_coil:
                # 完全按照 plc-com-gui.py 的方式：转换为 Modbus 地址（从 0 开始）
                # plc-com-gui.py 中：modbus_address = address - 1
                modbus_address = address - 1
                ctx.log_info(
                    f"[PLC] 读取线圈: Modbus地址={modbus_address} (YAML地址={address}), count={count}, "
                    f"unit_id={unit_id}, desc={description}"
                )

                # 完全按照 plc-com-gui.py 的方式：使用 device_id 参数
                # plc-com-gui.py 中：result = self.modbus_client.read_coils(modbus_address, count=length, device_id=device_id)
                resp = None
                try:
                    # 方法1：使用 device_id 参数（与 plc-com-gui.py 完全一致）
                    resp = client.read_coils(modbus_address, count, device_id=unit_id)
                except TypeError:
                    try:
                        # 方法2：尝试使用命名参数 device_id
                        resp = client.read_coils(address=modbus_address, count=count, device_id=unit_id)
                    except TypeError:
                        try:
                            # 方法3：尝试使用 slave 参数（某些版本可能使用此参数）
                            resp = client.read_coils(modbus_address, count, slave=unit_id)
                        except Exception:
                            resp = None

                if resp and not resp.isError() and hasattr(resp, "bits"):
                    bits = list(resp.bits)[:count]
                    value = 1 if (bits and bool(bits[0])) else 0

                    expected_raw = params.get("expected_value", params.get("expect_value"))
                    expected_int = None
                    passed = True
                    extra_msg = ""
                    if expected_raw is not None:
                        if isinstance(expected_raw, str):
                            expected_raw = _replace_variables(expected_raw, ctx)
                        try:
                            expected_int = int(expected_raw)
                            passed = value == expected_int
                            extra_msg = f" (期望值={expected_int}, 实际值={value})"
                        except (TypeError, ValueError):
                            ctx.log_warning(f"[PLC] expected_value 解析失败: {expected_raw}")

                    ctx.log_info(
                        f"[PLC] ✓ 线圈读取成功: Modbus地址={modbus_address} (YAML地址={address}) => {value}{extra_msg}"
                    )
                    return StepResult(
                        passed=passed,
                        message=f"PLC 线圈读取成功: {address} => {value}{extra_msg}",
                        data={
                            "address": address,
                            "modbus_address": modbus_address,
                            "count": count,
                            "values": bits,
                            "value": value,
                            "unit_id": unit_id,
                            "description": description,
                            "expected_value": expected_int,
                            "matched": passed if expected_int is not None else None,
                        },
                    )

                ctx.log_warning(f"[PLC] ⚠ 线圈读取失败: Modbus地址={modbus_address} (YAML地址={address})")
                return StepResult(
                    passed=False,
                    message=f"PLC 线圈读取失败: {address}",
                    error="读取响应异常",
                    error_code="PLC_MODBUS_ERR_READ_COIL_FAILED",
                )

            # 默认仍然是保持寄存器读取
            # 完全按照 plc-com-gui.py 的方式：转换为 Modbus 地址（从 0 开始）
            # plc-com-gui.py 中：modbus_address = address - 1
            modbus_address = address - 1
            ctx.log_info(
                f"[PLC] 读取保持寄存器: Modbus地址={modbus_address} (YAML地址={address}), count={count}, unit_id={unit_id}, desc={description}"
            )

            # 完全按照 plc-com-gui.py 的方式：使用 device_id 参数
            # plc-com-gui.py 中：result = self.modbus_client.read_holding_registers(modbus_address, count=length, device_id=device_id)
            resp = None
            try:
                # 方法1：使用 device_id 参数（与 plc-com-gui.py 完全一致）
                resp = client.read_holding_registers(modbus_address, count, device_id=unit_id)
            except TypeError:
                try:
                    # 方法2：尝试使用命名参数 device_id
                    resp = client.read_holding_registers(address=modbus_address, count=count, device_id=unit_id)
                except TypeError:
                    try:
                        # 方法3：尝试使用 slave 参数（某些版本可能使用此参数）
                        resp = client.read_holding_registers(modbus_address, count, slave=unit_id)
                    except Exception:
                        resp = None

            if resp and not resp.isError() and hasattr(resp, "registers"):
                regs = list(resp.registers)
                value = regs[0] if regs else 0

                # 支持两种判定：
                # 1) expected_value / expect_value：精确匹配
                # 2) expected_low(expected_min)/expected_high(expected_max)：范围拦截（闭区间）
                expected_raw = params.get("expected_value", params.get("expect_value"))
                expected_int = None

                expected_low_raw = params.get(
                    "expected_low",
                    params.get("expected_min", params.get("low", params.get("min"))),
                )
                expected_high_raw = params.get(
                    "expected_high",
                    params.get("expected_max", params.get("high", params.get("max"))),
                )
                expected_low = None
                expected_high = None

                passed = True
                extra_msg = ""

                if expected_raw is not None:
                    if isinstance(expected_raw, str):
                        expected_raw = _replace_variables(expected_raw, ctx)
                    try:
                        expected_int = int(expected_raw)
                        passed = value == expected_int
                        extra_msg = f" (期望值={expected_int}, 实际值={value})"
                    except (TypeError, ValueError):
                        ctx.log_warning(f"[PLC] expected_value 解析失败: {expected_raw}")

                # 范围拦截优先级更高：只要配置了上下限，就用范围来判定（满足你的“要报fail”需求）
                if expected_low_raw is not None or expected_high_raw is not None:
                    if isinstance(expected_low_raw, str):
                        expected_low_raw = _replace_variables(expected_low_raw, ctx)
                    if isinstance(expected_high_raw, str):
                        expected_high_raw = _replace_variables(expected_high_raw, ctx)
                    try:
                        expected_low = float(expected_low_raw) if expected_low_raw is not None else None
                        expected_high = float(expected_high_raw) if expected_high_raw is not None else None
                    except (TypeError, ValueError):
                        ctx.log_warning(
                            f"[PLC] expected_low/high 解析失败: low={expected_low_raw!r}, high={expected_high_raw!r}"
                        )
                        expected_low = None
                        expected_high = None

                    if expected_low is not None and expected_high is not None:
                        passed = expected_low <= float(value) <= expected_high
                        extra_msg = f" (期望范围=[{expected_low:g}, {expected_high:g}], 实际值={value})"
                    elif expected_low is not None:
                        passed = float(value) >= expected_low
                        extra_msg = f" (期望下限>={expected_low:g}, 实际值={value})"
                    elif expected_high is not None:
                        passed = float(value) <= expected_high
                        extra_msg = f" (期望上限<={expected_high:g}, 实际值={value})"
                    # 额外调试日志：确认是否执行了范围拦截
                    try:
                        _debug_log(
                            "modbus_steps_com.py:PlcModbusReadRegisterStep",
                            "range intercept evaluated",
                            {
                                "step_id": self.step_id,
                                "step_name": self.step_name,
                                "value": value,
                                "expected_low": expected_low,
                                "expected_high": expected_high,
                                "passed": passed,
                            },
                        )
                    except Exception:
                        pass

                ctx.log_info(f"[PLC] ✓ 寄存器读取成功: Modbus地址={modbus_address} (YAML地址={address}) => {value}{extra_msg}")
                return StepResult(
                    passed=passed,
                    message=f"PLC 寄存器读取成功: {address} => {value}{extra_msg}",
                    data={
                        "address": address,
                        "modbus_address": modbus_address,
                        "count": count,
                        "values": regs,
                        "value": value,
                        "unit_id": unit_id,
                        "description": description,
                        "expected_value": expected_int,
                        # 兼容 UI：PortPanel 优先读 data['low'/'high'] 来显示上下限
                        "low": expected_low,
                        "high": expected_high,
                        "expected_low": expected_low,
                        "expected_high": expected_high,
                        "matched": passed if (expected_int is not None or expected_low is not None or expected_high is not None) else None,
                    },
                )

            ctx.log_warning(f"[PLC] ⚠ 寄存器读取失败: Modbus地址={modbus_address} (YAML地址={address})")
            return StepResult(
                passed=False,
                message=f"PLC 寄存器读取失败: {address}",
                error="读取响应异常",
                error_code="PLC_MODBUS_ERR_READ_REG_FAILED",
            )

        except Exception as e:  # pragma: no cover
            ctx.log_error(f"[PLC] 寄存器读取异常: {e}")
            return StepResult(
                passed=False,
                message=f"PLC 寄存器读取异常: {e}",
                error=str(e),
                error_code="PLC_MODBUS_ERR_READ_REG_EXCEPTION",
            )


class PlcModbusDisconnectStep(BaseStep):
    """PLC: 断开 Modbus RTU 连接"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        try:
            client = ctx.get_comm_driver("plc_modbus")
            if not client:
                ctx.log_info("[PLC] 当前未连接到 PLC Modbus")
                return StepResult(
                    passed=True,
                    message="PLC Modbus 当前未连接",
                    data={"disconnected": True},
                )

            client.close()
            ctx.remove_comm_driver("plc_modbus")
            ctx.set_state("plc_modbus_connected", False)
            ctx.remove_state("plc_modbus_port")
            if sys.platform == "win32":
                time.sleep(0.35)

            ctx.log_info("[PLC] 已断开 PLC Modbus 连接")
            return StepResult(
                passed=True,
                message="PLC Modbus 断开连接成功",
                data={"disconnected": True},
            )

        except Exception as e:  # pragma: no cover
            ctx.log_error(f"[PLC] 断开 PLC Modbus 连接异常: {e}")
            # 即使异常也尽量标记为已断开
            ctx.remove_comm_driver("plc_modbus")
            ctx.set_state("plc_modbus_connected", False)
            ctx.remove_state("plc_modbus_port")
            if sys.platform == "win32":
                time.sleep(0.35)
            return StepResult(
                passed=True,
                message="PLC Modbus 断开连接（可能有异常）",
                data={"disconnected": True},
            )

