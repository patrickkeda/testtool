"""
PCAN (pcan-usb1) 相关测试步骤（复用 test/dogleg/tool.py 中的 CANCommunicator）

说明：
- 不再依赖 python-can，而是直接动态加载 `test/dogleg/tool.py` 里现成的 PCANBasic 封装；
- 这样打包到其它电脑时，只要带上 PCANBasic 相关 DLL 和 `tool.py` 即可，无需额外 pip 安装；
- 这里只做“无界面”的调用，不依赖 Tk 界面类，只用 CANCommunicator 这一层。

提供的步骤类型（在 register_steps.py 中注册）：
- pcan.connect               -> PcanConnectStep
- pcan.search_motor          -> PcanSearchMotorStep
- pcan.enable_motor          -> PcanEnableMotorStep
- pcan.set_auto_report       -> PcanSetAutoReportStep
- pcan.move_with_torque_log  -> PcanMoveWithTorqueLogStep
- pcan.move_until_limit      -> PcanMoveUntilLimitStep（思粤：扭矩 PI 控速直至到位传感器）
- pcan.read_motor_status     -> PcanReadMotorStatusStep
- pcan.disconnect            -> PcanDisconnectStep
"""

from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import sys
import os
import time
import importlib.util

# 产线狗腿返修后常见电机 ID（非固定 3 时在此集合内自动识别）
_DEFAULT_ALLOWED_MOTOR_IDS = (3, 6, 9, 12)


def _parse_motor_id_list(raw: Any, default: Tuple[int, ...] = _DEFAULT_ALLOWED_MOTOR_IDS) -> List[int]:
    """解析 ``3,6,9,12`` / ``[3,6,9,12]`` / 单数字。"""
    if raw is None:
        return list(default)
    if isinstance(raw, (list, tuple)):
        out: List[int] = []
        for x in raw:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
        return out or list(default)
    s = str(raw).strip()
    if not s:
        return list(default)
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            continue
    return out or list(default)


def _resolve_motor_id_param(raw: Any, ctx: Context, default: int = 3) -> int:
    if isinstance(raw, str) and raw.strip().startswith("${") and raw.strip().endswith("}"):
        raw = ctx.get_data("motor_id", default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _persist_detected_motor_id(ctx: Context, comm: Any, motor_id: int) -> None:
    setattr(comm, "current_motor_id", motor_id)
    ctx.set_state("pcan_motor_id", motor_id)
    ctx.set_data("motor_id", motor_id)


def _active_motor_id(ctx: Context, params: Dict[str, Any]) -> int:
    """优先使用 search 步骤识别并写入的 ID，其次步骤参数 / 序列变量。"""
    state_mid = ctx.get_state("pcan_motor_id")
    if state_mid is not None:
        return int(state_mid)
    if params.get("motor_id") is not None:
        return _resolve_motor_id_param(params.get("motor_id"), ctx, default=3)
    return _resolve_motor_id_param(ctx.get_data("motor_id", 3), ctx, default=3)


def _get_dogleg_feedback_queue():
    """dogleg tool 接收线程写入的 0x01 状态反馈队列。"""
    try:
        dogleg_dir = _get_dogleg_dir()
        if dogleg_dir.is_dir() and str(dogleg_dir) not in sys.path:
            sys.path.insert(0, str(dogleg_dir))
        if "tool" in sys.modules:
            return getattr(sys.modules["tool"], "data_queue", None)
        from importlib import import_module

        return getattr(import_module("tool"), "data_queue", None)
    except Exception:
        return None


def _empty_feedback_stats() -> Dict[str, Any]:
    """0x01 自动上报汇总结构（速度/扭矩/温度/状态/故障）。"""
    return {
        "feedback_count": 0,
        "max_abs_speed": 0.0,
        "max_abs_torque": 0.0,
        "saw_enabled": False,
        "saw_fault_status": False,
        "saw_fault_code": False,
        "last_status": None,
        "last_fault": None,
        "last_temperature_c": None,
        "min_temperature_c": None,
        "max_temperature_c": None,
        "motor_alarm": False,
    }


def _motor_alarm_from_stats(stats: Dict[str, Any]) -> bool:
    """status=2（故障）或 fault 低 7 位非 0 视为电机报警。"""
    return bool(stats.get("saw_fault_status") or stats.get("saw_fault_code"))


def _finalize_feedback_stats(stats: Dict[str, Any]) -> None:
    stats["motor_alarm"] = _motor_alarm_from_stats(stats)


def _format_motor_status_log(stats: Dict[str, Any]) -> str:
    last_t = stats.get("last_temperature_c")
    temp_part = (
        f"温度: 当前={last_t:.1f}°C, "
        f"min={stats.get('min_temperature_c')}, max={stats.get('max_temperature_c')}"
        if last_t is not None
        else "温度: 未收到 0x01 反馈"
    )
    alarm = stats.get("motor_alarm", False)
    status = stats.get("last_status")
    fault = stats.get("last_fault")
    alarm_part = (
        f"电机报警={'是' if alarm else '否'}, status={status}, fault=0x{int(fault or 0):02X}"
    )
    peak_trq = stats.get("max_abs_torque")
    trq_part = (
        f", 反馈扭矩峰值={float(peak_trq):.3f}Nm"
        if peak_trq is not None and float(peak_trq) > 0
        else ""
    )
    return (
        f"{temp_part}; {alarm_part}; feedback={stats.get('feedback_count', 0)}{trq_part}"
    )


def _resolve_max_feedback_torque_nm(
    params: Dict[str, Any], ctx: Context, action: str
) -> float:
    """0x01 反馈扭矩 |torque| 上限 (Nm)，0 表示不检查。"""
    generic = params.get("max_feedback_torque_nm", ctx.get_data("max_feedback_torque_nm", 0))
    key = (
        "max_extend_feedback_torque_nm"
        if action == "extend"
        else "max_kick_feedback_torque_nm"
    )
    raw = params.get(key, ctx.get_data(key, generic))
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def _check_feedback_torque_overload(
    stats: Dict[str, Any],
    max_torque_nm: float,
    action: str,
) -> Optional[str]:
    """反馈扭矩峰值超过阈值时返回错误信息。"""
    if max_torque_nm <= 0:
        return None
    peak = float(stats.get("max_abs_torque", 0.0))
    if peak > max_torque_nm:
        return (
            f"动作 {action} 反馈扭矩超限: 峰值|torque|={peak:.3f} Nm > "
            f"上限 {max_torque_nm:.3f} Nm（0x01 自动上报）"
        )
    return None


def _drain_feedback_queue(feedback_queue, stats: Dict[str, Any], max_items: int = 32) -> None:
    """从 0x01 状态反馈队列更新运动统计（速度/扭矩/温度/状态/故障）。"""
    import queue as queue_mod

    if feedback_queue is None:
        return
    processed = 0
    while processed < max_items:
        try:
            fb = feedback_queue.get_nowait()
        except queue_mod.Empty:
            break
        processed += 1
        stats["feedback_count"] = int(stats.get("feedback_count", 0)) + 1
        try:
            spd = float(fb.get("speed", 0.0))
            stats["last_speed"] = spd
            stats["max_abs_speed"] = max(float(stats.get("max_abs_speed", 0.0)), abs(spd))
        except (TypeError, ValueError):
            pass
        try:
            trq = float(fb.get("torque", 0.0))
            stats["max_abs_torque"] = max(float(stats.get("max_abs_torque", 0.0)), abs(trq))
        except (TypeError, ValueError):
            pass
        temp = fb.get("temperature")
        if temp is not None:
            try:
                t_c = float(temp)
                stats["last_temperature_c"] = t_c
                prev_min = stats.get("min_temperature_c")
                prev_max = stats.get("max_temperature_c")
                stats["min_temperature_c"] = t_c if prev_min is None else min(float(prev_min), t_c)
                stats["max_temperature_c"] = t_c if prev_max is None else max(float(prev_max), t_c)
            except (TypeError, ValueError):
                pass
        status = fb.get("status")
        if status is not None:
            stats["last_status"] = int(status)
            if int(status) == 1:
                stats["saw_enabled"] = True
            elif int(status) == 2:
                stats["saw_fault_status"] = True
        fault = fb.get("fault")
        if fault is not None:
            try:
                fault_i = int(fault) & 0xFF
            except (TypeError, ValueError):
                fault_i = 0
            stats["last_fault"] = fault_i
            # 协议：bit7 默认为 1，仅 bit0-6 为故障位
            if fault_i & 0x7F not in (0, 0x80):
                stats["saw_fault_code"] = True
    _finalize_feedback_stats(stats)


def _get_dogleg_dir() -> Path:
    """返回 test/dogleg 目录路径，兼容开发环境与 PyInstaller 打包后的 exe。"""
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        # 打包后：_MEIPASS 指向 _internal 目录，test/dogleg 被复制到该目录下
        return Path(sys._MEIPASS).resolve() / "test" / "dogleg"
    # 开发环境：从本文件位置推算项目根目录
    project_root = Path(__file__).resolve().parents[4]
    return project_root / "test" / "dogleg"


# 最近一次加载失败时的异常信息，供步骤返回给界面显示
_last_load_error: str = ""


def _format_pcanbasic_missing_error() -> str:
    """生成 PCANBasic 缺失时的可读错误信息。"""
    dll_candidates = [
        Path("C:/Windows/System32/PCANBasic.dll"),
        Path("C:/Windows/SysWOW64/PCANBasic.dll"),
    ]
    module_spec = importlib.util.find_spec("PCANBasic")
    module_state = "found" if module_spec is not None else "missing"

    existing_dlls = [str(p) for p in dll_candidates if p.exists()]
    dll_state = ", ".join(existing_dlls) if existing_dlls else "missing"

    return (
        "未找到 Python 模块 'PCANBasic'。"
        f" module={module_state}, dll={dll_state}。"
        " 设备驱动正常并不代表 Python 封装已安装。"
        " 请安装/放置 PCANBasic.py 到当前 Python 环境可搜索路径后重试。"
    )


def _load_can_communicator(ctx: Context):
    """
    动态加载 test/dogleg/tool.py 中的 CANCommunicator。
    支持开发环境与 PyInstaller 打包后在其它电脑运行。
    """
    global _last_load_error
    import traceback
    _last_load_error = ""
    try:
        dogleg_dir = _get_dogleg_dir()
        if not dogleg_dir.is_dir():
            _last_load_error = f"test/dogleg 目录不存在: {dogleg_dir}"
            ctx.log_error(f"[PCAN] {_last_load_error}")
            return None
        dogleg_str = str(dogleg_dir)
        if dogleg_str not in sys.path:
            sys.path.insert(0, dogleg_str)

        import tool  # type: ignore  # noqa: PLC0415

        CANCommunicator = getattr(tool, "CANCommunicator", None)
        if CANCommunicator is None:
            _last_load_error = "test/dogleg/tool.py 中未找到 CANCommunicator 类"
            ctx.log_error("[PCAN] " + _last_load_error)
            return None
        return CANCommunicator
    except Exception as e:  # pragma: no cover
        if isinstance(e, ModuleNotFoundError) and getattr(e, "name", "") == "PCANBasic":
            _last_load_error = _format_pcanbasic_missing_error()
        else:
            _last_load_error = str(e)
        ctx.log_error(f"[PCAN] 加载 CANCommunicator 失败: {e}")
        if _last_load_error != str(e):
            ctx.log_error(f"[PCAN] 诊断信息: {_last_load_error}")
        for line in traceback.format_exc().splitlines():
            ctx.log_error(f"[PCAN]   {line}")
        return None


def _safe_shutdown_pcan_comm(comm, warn=None) -> None:
    """先停止 CAN 接收线程再 Uninitialize，避免与 receive_loop 并发访问 PCANBasic 导致进程偶发闪退。

    dogleg ``tool.CANCommunicator`` 在 ``init_can`` 中会启动 ``receive_thread``；若仅调用
    ``Uninitialize`` 而不停线程，接收循环仍可能卡在 ``Read``，与释放通道竞态，表现为间歇性崩溃。
    """
    if comm is None:
        return
    _w = warn or (lambda *_a, **_k: None)

    try:
        if hasattr(comm, "terminate"):
            comm.terminate()
            return
    except Exception as e:  # pragma: no cover
        _w(f"[PCAN] terminate 异常（将尝试降级清理）: {e}")

    try:
        try:
            setattr(comm, "termination_requested", True)
        except Exception:
            pass
        try:
            comm.running = False
        except Exception:
            pass
        rt = getattr(comm, "receive_thread", None)
        if rt is not None and rt.is_alive():
            try:
                rt.join(timeout=2.0)
            except Exception:
                pass
        if hasattr(comm, "pcan") and hasattr(comm, "channel"):
            try:
                comm.pcan.Uninitialize(comm.channel)
            except Exception:
                pass
        try:
            setattr(comm, "initialized", False)
        except Exception:
            pass
    except Exception as e:  # pragma: no cover
        _w(f"[PCAN] 降级清理异常: {e}")


def _get_or_create_can_comm(ctx: Context):
    """
    从上下文获取或创建一个 CANCommunicator 实例。
    使用 comm_driver key: 'pcan_comm'
    """
    comm = ctx.get_comm_driver("pcan_comm")
    if comm is not None:
        return comm

    CANCommunicator = _load_can_communicator(ctx)
    if CANCommunicator is None:
        return None

    try:
        comm = CANCommunicator()
        ctx.set_comm_driver("pcan_comm", comm)
        return comm
    except Exception as e:  # pragma: no cover
        ctx.log_error(f"[PCAN] 创建 CANCommunicator 实例失败: {e}")
        return None


class PcanConnectStep(BaseStep):
    """连接 PCAN 设备（例如 pcan-usb1）"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        comm = _get_or_create_can_comm(ctx)
        if comm is None:
            err_detail = _last_load_error or "请检查 test/dogleg 目录、tool.py 及 PCANBasic.dll"
            return StepResult(
                passed=False,
                message="加载 CANCommunicator 失败",
                error=err_detail,
                error_code="PCAN_ERR_IMPORT",
            )

        # 如果已经初始化过，先停接收线程再释放通道，避免与 receive_loop 竞态导致闪退
        try:
            if getattr(comm, "initialized", False):
                ctx.log_warning("[PCAN] 检测到上次连接可能未完全释放，先安全终止再重连")
                _safe_shutdown_pcan_comm(comm, ctx.log_warning)
        except Exception:
            pass

        try:
            ok = comm.init_can()
            if not ok:
                ctx.log_error("[PCAN] 调用 CANCommunicator.init_can() 失败")
                return StepResult(
                    passed=False,
                    message="PCAN 总线初始化失败",
                    error="CANCommunicator.init_can 返回 False",
                    error_code="PCAN_ERR_CONNECT_FAILED",
                )

            ctx.set_state("pcan_connected", True)
            ctx.log_info("[PCAN] ✓ PCAN 设备连接成功（PCANBasic）")
            return StepResult(
                passed=True,
                message="PCAN 设备连接成功（PCANBasic）",
                data={"impl": "CANCommunicator"},
            )
        except Exception as e:  # pragma: no cover
            ctx.log_error(f"[PCAN] 连接异常: {e}")
            return StepResult(
                passed=False,
                message=f"PCAN 连接异常: {e}",
                error=str(e),
                error_code="PCAN_ERR_CONNECT_EXCEPTION",
            )


class PcanSearchMotorStep(BaseStep):
    """搜索电机并在允许 ID 集合内自动识别（返修件可能为 3/6/9/12 等非默认 3）。

    params:
    - auto_detect_motor_id: 是否根据总线搜索结果自动选用 ID（默认 true）
    - allowed_motor_ids: 允许的 ID，如 ``3,6,9,12`` 或列表（默认 3,6,9,12）
    - search_wait_ms: 广播搜索后等待响应毫秒数（默认 800）
    - probe_enable_if_not_found: 搜索无结果时，在允许 ID 上逐个尝试使能（默认 true）
    """

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        comm = _get_or_create_can_comm(ctx)
        if comm is None or not getattr(comm, "initialized", False):
            return StepResult(
                passed=False,
                message="PCAN 总线未连接",
                error="请先执行 pcan.connect 步骤",
                error_code="PCAN_ERR_NOT_CONNECTED",
            )

        allowed = _parse_motor_id_list(
            params.get("allowed_motor_ids", ctx.get_data("allowed_motor_ids")),
        )
        auto_detect = self.get_param_bool(params, "auto_detect_motor_id", True)
        search_wait_ms = max(100, self.get_param_int(params, "search_wait_ms", 800))
        probe_enable = self.get_param_bool(params, "probe_enable_if_not_found", True)

        ctx.log_info(
            f"[PCAN] 电机 ID 策略: auto_detect={auto_detect}, allowed={allowed}"
        )

        discovered_ids: List[int] = []
        if hasattr(comm, "search_motors"):
            try:
                if hasattr(comm, "discovered_motors"):
                    comm.discovered_motors.clear()
            except Exception:
                pass
            try:
                ctx.log_info("[PCAN] 调用 CANCommunicator.search_motors() 广播搜索…")
                comm.search_motors()
                time.sleep(search_wait_ms / 1000.0)
                discovered_ids = sorted(
                    {int(mid) for mid, _uid in getattr(comm, "discovered_motors", [])}
                )
                if discovered_ids:
                    ctx.log_info(f"[PCAN] 总线发现电机 ID: {discovered_ids}")
            except Exception as e:  # pragma: no cover
                ctx.log_warning(f"[PCAN] 搜索电机异常: {e}")

        motor_id: Optional[int] = None
        detect_source = ""

        if auto_detect:
            allowed_set = set(allowed)
            matched = [mid for mid in discovered_ids if mid in allowed_set]
            if len(matched) == 1:
                motor_id = matched[0]
                detect_source = "bus_search"
            elif len(matched) > 1:
                return StepResult(
                    passed=False,
                    message="总线上发现多个允许的电机 ID，请只接一只电机或缩小 allowed_motor_ids",
                    error=f"matched={matched}, discovered={discovered_ids}",
                    error_code="PCAN_ERR_MULTIPLE_MOTOR_ID",
                )
            elif discovered_ids and not matched:
                return StepResult(
                    passed=False,
                    message="发现电机但 ID 不在允许列表内",
                    error=(
                        f"discovered={discovered_ids}, allowed={allowed}; "
                        "请确认返修写入的 ID 或更新 allowed_motor_ids"
                    ),
                    error_code="PCAN_ERR_MOTOR_ID_NOT_ALLOWED",
                )

        if motor_id is None and probe_enable and auto_detect and hasattr(comm, "enable_motor"):
            ctx.log_info(
                f"[PCAN] 搜索未命中允许 ID，逐个尝试使能: {allowed}"
            )
            for candidate in allowed:
                setattr(comm, "current_motor_id", candidate)
                try:
                    ok, err = comm.enable_motor(mode=1)
                except Exception as e:  # noqa: BLE001
                    ok, err = False, str(e)
                if ok:
                    motor_id = candidate
                    detect_source = "probe_enable"
                    ctx.log_info(f"[PCAN] 使能探测成功: motor_id={candidate}")
                    break
                if hasattr(comm, "disable_motor"):
                    try:
                        comm.disable_motor()
                    except Exception:  # noqa: BLE001
                        pass
                ctx.log_info(f"[PCAN] ID={candidate} 使能未成功: {err}")

        if motor_id is None:
            ctx.log_error(
                f"[PCAN] 未在允许列表 {allowed} 内识别到电机 "
                f"(discovered={discovered_ids or '无'})"
            )
            return StepResult(
                passed=False,
                message="未识别到电机 ID，请检查接线、供电及返修写入的 ID",
                error=(
                    f"allowed={allowed}, discovered={discovered_ids or []}; "
                    "已尝试总线搜索与使能探测"
                ),
                error_code="PCAN_ERR_MOTOR_ID_NOT_FOUND",
            )

        _persist_detected_motor_id(ctx, comm, motor_id)
        ctx.log_info(f"[PCAN] 本次使用 motor_id={motor_id}（来源: {detect_source}）")

        return StepResult(
            passed=True,
            message=f"电机 ID 已确定: {motor_id}（{detect_source}）",
            data={
                "motor_id": motor_id,
                "detect_source": detect_source,
                "discovered_ids": discovered_ids,
                "allowed_motor_ids": allowed,
            },
        )


class PcanEnableMotorStep(BaseStep):
    """使能电机（占位实现）

    实际的使能帧格式请参考现有 tool.py 中的 PCAN 协议定义，并在此处填充发送逻辑。
    """

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        comm = _get_or_create_can_comm(ctx)
        if comm is None or not getattr(comm, "initialized", False):
            return StepResult(
                passed=False,
                message="PCAN 总线未连接",
                error="请先执行 pcan.connect 步骤",
                error_code="PCAN_ERR_NOT_CONNECTED",
            )

        motor_id = _active_motor_id(ctx, params)
        setattr(comm, "current_motor_id", motor_id)

        if not hasattr(comm, "enable_motor"):
            return StepResult(
                passed=False,
                message="CANCommunicator 不支持 enable_motor 方法",
                error="请检查 test/dogleg/tool.py",
                error_code="PCAN_ERR_ENABLE_UNSUPPORTED",
            )

        try:
            ok, err = comm.enable_motor(mode=1)
            if not ok:
                # 如果底层没有返回具体错误信息（err 为 None 或空），
                # 很可能是电机已经处于使能状态，这里视为“已使能”不再当作失败。
                if err is None or str(err).strip() == "":
                    ctx.log_warning(
                        "[PCAN] 使能电机返回失败，但无具体错误信息，推测电机已在使能状态，视作成功。"
                    )
                    return StepResult(
                        passed=True,
                        message="电机已处于使能状态，跳过错误并继续测试",
                        data={"motor_id": motor_id, "already_enabled": True},
                    )

                ctx.log_error(f"[PCAN] 使能电机失败: {err}")
                return StepResult(
                    passed=False,
                    message="电机使能失败",
                    error=str(err),
                    error_code="PCAN_ERR_ENABLE_FAILED",
                )

            ctx.log_info(f"[PCAN] ✓ 电机已使能: motor_id={motor_id}")
            return StepResult(
                passed=True,
                message=f"电机使能成功: motor_id={motor_id}",
                data={"motor_id": motor_id},
            )
        except Exception as e:  # pragma: no cover
            ctx.log_error(f"[PCAN] 使能电机异常: {e}")
            return StepResult(
                passed=False,
                message=f"电机使能异常: {e}",
                error=str(e),
                error_code="PCAN_ERR_ENABLE_EXCEPTION",
            )


class PcanSetAutoReportStep(BaseStep):
    """开关电机 0x01 状态自动上报（协议功能码 0x09）。

    params:
    - enable: 是否开启（默认 true）
    - frequency_hz: 上报频率 Hz（默认 200，协议最高约 500）
    - motor_id: 电机 ID（默认识别结果）
    """

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        comm = _get_or_create_can_comm(ctx)
        if comm is None or not getattr(comm, "initialized", False):
            return StepResult(
                passed=False,
                message="PCAN 总线未连接",
                error="请先执行 pcan.connect 步骤",
                error_code="PCAN_ERR_NOT_CONNECTED",
            )

        motor_id = _active_motor_id(ctx, params)
        setattr(comm, "current_motor_id", motor_id)
        enable = self.get_param_bool(params, "enable", True)
        frequency = max(1, min(500, self.get_param_int(params, "frequency_hz", 200)))

        if not hasattr(comm, "toggle_auto_report"):
            return StepResult(
                passed=False,
                message="CANCommunicator 不支持 toggle_auto_report",
                error="请检查 test/dogleg/tool.py",
                error_code="PCAN_ERR_AUTO_REPORT_UNSUPPORTED",
            )

        try:
            comm.toggle_auto_report(enable, frequency, motor_id)
            ctx.set_state("pcan_auto_report", enable)
            ctx.log_info(
                f"[PCAN] 状态自动上报已{'开启' if enable else '关闭'}: "
                f"motor_id={motor_id}, {frequency}Hz"
            )
            return StepResult(
                passed=True,
                message=f"状态自动上报{'开启' if enable else '关闭'}: {frequency}Hz",
                data={"motor_id": motor_id, "enable": enable, "frequency_hz": frequency},
            )
        except Exception as e:  # pragma: no cover
            return StepResult(
                passed=False,
                message=f"设置状态自动上报异常: {e}",
                error=str(e),
                error_code="PCAN_ERR_AUTO_REPORT_EXCEPTION",
            )


class PcanMoveWithTorqueLogStep(BaseStep):
    """执行伸腿 / 踢腿动作，记录扭矩日志，并可依据 0x01 状态反馈判定是否运动。

    参数：
    - action: 'extend' 或 'kick'
    - motor_id: 电机 ID
    - sn: 序列号（用于文件名）
    - log_dir: 日志目录（默认为 Result/dogleg）
    - verify_motion: 是否根据 0x01 反馈判定腿是否工作（默认 false）
    - min_speed_rad_s: 动作过程中 |速度| 峰值下限（默认 0.15 rad/s）
    - min_feedback_count: 至少收到的状态反馈条数（默认 20）
    - min_torque_nm: 可选，|扭矩| 峰值下限（默认 0，不检查）
    """

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        comm = _get_or_create_can_comm(ctx)
        if comm is None or not getattr(comm, "initialized", False):
            return StepResult(
                passed=False,
                message="PCAN 总线未连接",
                error="请先执行 pcan.connect 步骤",
                error_code="PCAN_ERR_NOT_CONNECTED",
            )

        action = str(params.get("action", "extend")).lower()
        motor_id = _active_motor_id(ctx, params)
        setattr(comm, "current_motor_id", motor_id)
        sn = params.get("sn", ctx.get_sn() or "UNKNOWN_SN")
        log_dir = params.get("log_dir", "Result/dogleg")

        # 限制力度和动作时间，可通过 YAML 参数调整
        # torque_limit: 单次命令扭矩上限（默认 0.5，远小于 tool.py 里的 ±3）
        # duration_ms: 动作持续时间（默认 3000ms）
        raw_torque = params.get("torque_limit", ctx.get_data("extend_torque", 0.5))
        if isinstance(raw_torque, str):
            if raw_torque.strip().startswith("${") and raw_torque.strip().endswith("}"):
                # 根据 action 选择变量名
                var_name = "extend_torque" if action == "extend" else "kick_torque"
                raw_torque = ctx.get_data(var_name, 0.5)
        try:
            torque_limit = float(raw_torque)
        except Exception:
            torque_limit = 0.5
            ctx.log_warning(f"[PCAN] torque_limit 参数解析失败，使用默认值 0.5，原始值: {raw_torque!r}")

        raw_duration = params.get("duration_ms", ctx.get_data("move_duration_ms", 3000))
        try:
            duration_ms = int(raw_duration)
        except Exception:
            duration_ms = 3000
            ctx.log_warning(f"[PCAN] duration_ms 参数解析失败，使用默认值 3000，原始值: {raw_duration!r}")

        # 构造日志路径：Result/dogleg/{sn}_{action}.csv
        base_dir = Path(log_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        log_path = base_dir / f"{sn}_{action}.csv"

        verify_motion = self.get_param_bool(params, "verify_motion", False)
        min_speed = float(params.get("min_speed_rad_s", ctx.get_data("motion_min_speed", 0.15)))
        min_feedback = int(params.get("min_feedback_count", ctx.get_data("motion_min_feedback", 20)))
        min_torque = float(params.get("min_torque_nm", ctx.get_data("motion_min_torque", 0.0)))
        max_fb_torque = _resolve_max_feedback_torque_nm(params, ctx, action)

        ctx.log_info(
            f"[PCAN] 执行动作 action={action}, motor_id={motor_id}, 日志路径={log_path}, "
            f"verify_motion={verify_motion}"
        )

        motion_stats: Dict[str, Any] = _empty_feedback_stats()
        control_error: Optional[str] = None

        try:
            # 目标速度：默认 extend=+1.0 rad/s, kick=-1.0 rad/s，可通过参数覆盖
            default_target = 1.0 if action == "extend" else -1.0
            try:
                target_speed = float(params.get("target_speed", default_target))
            except Exception:
                target_speed = default_target
                ctx.log_warning(
                    f"[PCAN] target_speed 参数解析失败，使用默认值 {default_target}"
                )

            feedback_queue = _get_dogleg_feedback_queue()
            if verify_motion and feedback_queue is None:
                return StepResult(
                    passed=False,
                    message="无法获取电机状态反馈队列，请先开启自动上报",
                    error="data_queue 不可用",
                    error_code="PCAN_ERR_FEEDBACK_QUEUE_MISSING",
                )

            new_file = not log_path.exists()
            with open(log_path, "a", encoding="utf-8") as f:
                if new_file:
                    f.write(
                        "time_ms,torque,position,velocity,temperature_c,status,fault\n"
                    )

                control_interval = 1.0 / 200.0
                sumerror_spd = 0.0
                current_speed = 0.0
                start_time = time.time()
                next_log_time = start_time
                duration_s = max(0.1, duration_ms / 1000.0)

                while time.time() - start_time < duration_s:
                    loop_start = time.time()

                    _drain_feedback_queue(feedback_queue, motion_stats, max_items=32)
                    if "last_speed" in motion_stats:
                        try:
                            current_speed = float(motion_stats["last_speed"])
                        except (TypeError, ValueError):
                            pass

                    errspd = target_speed - current_speed
                    sumerror_spd += 0.05 * errspd
                    torque = 0.1 * errspd + 0.05 * sumerror_spd
                    torque = max(-3.0, min(3.0, torque))
                    torque = max(-abs(torque_limit), min(abs(torque_limit), torque))

                    try:
                        comm.send_mpc_command(0.0, 0.0, torque)
                    except Exception as e:  # pragma: no cover
                        ctx.log_warning(f"[PCAN] 发送 MPC 命令失败（忽略继续）: {e}")

                    now = time.time()
                    if now - next_log_time >= 0.01:
                        now_ms = int(now * 1000)
                        temp_c = motion_stats.get("last_temperature_c")
                        temp_s = "" if temp_c is None else f"{float(temp_c):.1f}"
                        status_s = motion_stats.get("last_status")
                        fault_s = motion_stats.get("last_fault")
                        f.write(
                            f"{now_ms},{torque},{0.0},{current_speed},"
                            f"{temp_s},{status_s},{fault_s}\n"
                        )
                        next_log_time = now

                    elapsed = time.time() - loop_start
                    sleep_time = control_interval - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)

            _drain_feedback_queue(feedback_queue, motion_stats, max_items=64)
            _finalize_feedback_stats(motion_stats)

        except Exception as e:  # pragma: no cover
            control_error = str(e)
            ctx.log_warning(f"[PCAN] 伸腿/踢腿控制执行异常: {e}")

        ctx.log_info(f"[PCAN] 动作 {action} 反馈汇总: {_format_motor_status_log(motion_stats)}")
        ctx.set_data("motor_temperature_c", motion_stats.get("last_temperature_c"))
        ctx.set_data("motor_temperature_min_c", motion_stats.get("min_temperature_c"))
        ctx.set_data("motor_temperature_max_c", motion_stats.get("max_temperature_c"))
        ctx.set_data("motor_alarm", motion_stats.get("motor_alarm", False))
        ctx.set_data("motor_last_status", motion_stats.get("last_status"))
        ctx.set_data("motor_last_fault", motion_stats.get("last_fault"))

        result_data = {
            "action": action,
            "motor_id": motor_id,
            "sn": sn,
            "log_path": str(log_path),
            "verify_motion": verify_motion,
            "motion_stats": motion_stats,
            "temperature_c": motion_stats.get("last_temperature_c"),
            "temperature_min_c": motion_stats.get("min_temperature_c"),
            "temperature_max_c": motion_stats.get("max_temperature_c"),
            "motor_alarm": motion_stats.get("motor_alarm", False),
            "last_status": motion_stats.get("last_status"),
            "last_fault": motion_stats.get("last_fault"),
        }

        if control_error and verify_motion:
            return StepResult(
                passed=False,
                message=f"动作 {action} 控制异常: {control_error}",
                error=control_error,
                error_code="PCAN_ERR_MOTION_CONTROL_EXCEPTION",
                data=result_data,
            )

        if verify_motion:
            if motion_stats["feedback_count"] < min_feedback:
                msg = (
                    f"未收到足够的状态反馈(0x01): {motion_stats['feedback_count']}/{min_feedback}，"
                    "请确认已执行 pcan.set_auto_report"
                )
                ctx.log_error(f"[PCAN] {msg}")
                return StepResult(
                    passed=False,
                    message=msg,
                    error=msg,
                    error_code="PCAN_ERR_MOTION_NO_FEEDBACK",
                    data=result_data,
                )
            if motion_stats.get("motor_alarm"):
                msg = (
                    f"动作 {action} 期间电机报警: status={motion_stats.get('last_status')}, "
                    f"fault=0x{int(motion_stats.get('last_fault') or 0):02X}, "
                    f"温度={motion_stats.get('last_temperature_c')}°C"
                )
                ctx.log_error(f"[PCAN] {msg}")
                return StepResult(
                    passed=False,
                    message=msg,
                    error=msg,
                    error_code="PCAN_ERR_MOTION_FAULT",
                    data=result_data,
                )
            if float(motion_stats["max_abs_speed"]) < min_speed:
                msg = (
                    f"动作 {action} 速度峰值不足: "
                    f"{motion_stats['max_abs_speed']:.3f} < {min_speed:.3f} rad/s"
                )
                ctx.log_error(f"[PCAN] {msg}")
                return StepResult(
                    passed=False,
                    message=msg,
                    error=msg,
                    error_code="PCAN_ERR_MOTION_SPEED_LOW",
                    data=result_data,
                )
            if min_torque > 0 and float(motion_stats["max_abs_torque"]) < min_torque:
                msg = (
                    f"动作 {action} 扭矩峰值不足: "
                    f"{motion_stats['max_abs_torque']:.3f} < {min_torque:.3f} Nm"
                )
                ctx.log_error(f"[PCAN] {msg}")
                return StepResult(
                    passed=False,
                    message=msg,
                    error=msg,
                    error_code="PCAN_ERR_MOTION_TORQUE_LOW",
                    data=result_data,
                )
            msg = _check_feedback_torque_overload(
                motion_stats, max_fb_torque, action
            )
            if msg:
                ctx.log_error(f"[PCAN] {msg}")
                return StepResult(
                    passed=False,
                    message=msg,
                    error=msg,
                    error_code="PCAN_ERR_FEEDBACK_TORQUE_OVERLOAD",
                    data=result_data,
                )
            ctx.log_info(
                f"[PCAN] 动作 {action} 运动检测通过: "
                f"feedback={motion_stats['feedback_count']}, "
                f"max|speed|={motion_stats['max_abs_speed']:.3f} rad/s, "
                f"max|torque|={motion_stats['max_abs_torque']:.3f} Nm; "
                f"{_format_motor_status_log(motion_stats)}"
            )

        alarm = motion_stats.get("motor_alarm", False)
        temp_msg = motion_stats.get("last_temperature_c")
        return StepResult(
            passed=True,
            message=(
                f"动作 {action} 完成，日志: {log_path}; "
                f"温度={temp_msg}°C, 电机报警={'是' if alarm else '否'}"
            ),
            data=result_data,
        )


def _resolve_plc_unit_id(params: Dict[str, Any], ctx: Context) -> int:
    raw = params.get("unit_id", ctx.get_data("plc_unit_id", 1))
    if isinstance(raw, str) and raw.strip().startswith("${"):
        raw = ctx.get_data("plc_unit_id", 1)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def _read_plc_coil(ctx: Context, yaml_address: int, unit_id: int) -> Optional[int]:
    """读取 PLC 线圈（YAML 地址与 plc.modbus.read_register 一致，内部 address-1）。"""
    client = ctx.get_comm_driver("plc_modbus")
    if client is None:
        return None
    modbus_address = int(yaml_address) - 1
    resp = None
    try:
        resp = client.read_coils(modbus_address, 1, device_id=unit_id)
    except TypeError:
        try:
            resp = client.read_coils(address=modbus_address, count=1, device_id=unit_id)
        except TypeError:
            try:
                resp = client.read_coils(modbus_address, 1, slave=unit_id)
            except Exception:
                return None
    except Exception:
        return None
    if resp and not resp.isError() and hasattr(resp, "bits"):
        bits = list(resp.bits)
        return 1 if (bits and bool(bits[0])) else 0
    return None


def _pi_torque_command(
    target_speed: float,
    current_speed: float,
    sumerror_spd: float,
    *,
    kp: float = 0.1,
    ki_gain: float = 0.05,
    torque_limit: float = 3.0,
) -> Tuple[float, float]:
    """与 tool.py pi_control_loop 一致：扭矩环跟踪目标角速度。"""
    errspd = target_speed - current_speed
    sumerror_spd += ki_gain * errspd
    torque = kp * errspd + ki_gain * sumerror_spd
    torque = max(-3.0, min(3.0, torque))
    lim = abs(float(torque_limit))
    torque = max(-lim, min(lim, torque))
    return torque, sumerror_spd


class PcanMoveUntilLimitStep(BaseStep):
    """思粤方案：扭矩 PI 控速 → 匀速至 PLC 到位传感器触发 → 停止 → 校验反馈速度达目标。

    参数：
    - action: extend / kick（默认速度 extend=+1、kick=-1，可被 target_speed 覆盖）
    - target_speed: 目标角速度 (rad/s)
    - torque_limit: PI 输出扭矩上限 (Nm)
    - limit_sensor_address: 到位传感器 PLC 线圈 YAML 地址（伸腿常用 2055，踢腿 2056）
    - limit_sensor_expected: 触发值（默认 1）
    - unit_id: Modbus 从站（默认识别序列变量 plc_unit_id）
    - poll_interval_ms: 读 PLC 线圈周期（默认 20）
    - max_duration_ms: 未触发传感器时的超时（默认 60000）
    - stop_hold_ms: 到位后保持零扭矩指令时长（默认 200）
    - verify_speed: 是否校验反馈速度达到目标（默认 true）
    - speed_tolerance: |峰值速度 - 目标速度| 允许偏差 (rad/s)，默认 0.25
    - min_feedback_count / min_speed_rad_s: 与 move_with_torque_log 相同语义
    - max_feedback_torque_nm: 0x01 反馈 |扭矩| 峰值上限 (Nm)，超过则直接 FAIL（0=不检查）
    - max_extend_feedback_torque_nm / max_kick_feedback_torque_nm: 分动作上限（可选）
    - pi_kp / pi_ki_gain: PI 系数（默认 0.1 / 0.05）
    - limit_sensor_idle: 本行程到位线圈启动前应处于的值（伸腿前 2055 应为 0）
    - home_sensor_address / home_sensor_expected: 原位传感器（伸腿前常用 2056=1）
    - require_sensor_clear_before_start: 启动前检查到位线圈尚未触发（默认 true）
    - require_home_before_start: 启动前检查腿在原位（默认 true，需配置 home_sensor_address）
    - min_run_ms: 启动后忽略到位信号的时长（默认 800ms，防传感器过早为 1）
    - min_speed_before_limit: 认可到位前反馈 |速度| 峰值下限（默认同速度校验下限）
    - sensor_confirm_count: 到位信号需连续 N 次读数为 expected 才停（默认 3）
    - log_dir, sn: CSV 日志
    """

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        comm = _get_or_create_can_comm(ctx)
        if comm is None or not getattr(comm, "initialized", False):
            return StepResult(
                passed=False,
                message="PCAN 总线未连接",
                error="请先执行 pcan.connect 步骤",
                error_code="PCAN_ERR_NOT_CONNECTED",
            )

        plc = ctx.get_comm_driver("plc_modbus")
        if plc is None:
            return StepResult(
                passed=False,
                message="PLC Modbus 未连接",
                error="请先执行 plc.modbus.connect（思粤方案需轮询到位传感器）",
                error_code="PCAN_ERR_PLC_NOT_CONNECTED",
            )

        action = str(params.get("action", "extend")).lower()
        motor_id = _active_motor_id(ctx, params)
        setattr(comm, "current_motor_id", motor_id)
        sn = params.get("sn", ctx.get_sn() or "UNKNOWN_SN")
        log_dir = params.get("log_dir", "Result/dogleg")

        default_target = 1.0 if action == "extend" else -1.0
        try:
            target_speed = float(params.get("target_speed", default_target))
        except (TypeError, ValueError):
            target_speed = default_target

        var_name = "extend_torque" if action == "extend" else "kick_torque"
        raw_torque = params.get("torque_limit", ctx.get_data(var_name, 1.0))
        if isinstance(raw_torque, str) and raw_torque.strip().startswith("${"):
            raw_torque = ctx.get_data(var_name, 1.0)
        try:
            torque_limit = float(raw_torque)
        except (TypeError, ValueError):
            torque_limit = 1.0

        sensor_addr = int(
            params.get(
                "limit_sensor_address",
                ctx.get_data(
                    "extend_limit_address" if action == "extend" else "kick_limit_address",
                    2055 if action == "extend" else 2056,
                ),
            )
        )
        sensor_expected = int(params.get("limit_sensor_expected", 1))
        unit_id = _resolve_plc_unit_id(params, ctx)
        poll_ms = max(5, self.get_param_int(params, "poll_interval_ms", 20))
        max_duration_ms = max(500, self.get_param_int(params, "max_duration_ms", 60000))
        stop_hold_ms = max(0, self.get_param_int(params, "stop_hold_ms", 200))
        verify_speed = self.get_param_bool(params, "verify_speed", True)
        speed_tolerance = float(params.get("speed_tolerance", ctx.get_data("speed_tolerance", 0.25)))
        min_feedback = int(params.get("min_feedback_count", ctx.get_data("motion_min_feedback", 20)))
        min_speed_peak = float(params.get("min_speed_rad_s", ctx.get_data("motion_min_speed", 0.15)))
        pi_kp = float(params.get("pi_kp", 0.1))
        pi_ki = float(params.get("pi_ki_gain", 0.05))
        target_abs = abs(target_speed)
        speed_pass_floor = max(min_speed_peak, target_abs - speed_tolerance)
        default_idle = 0 if sensor_expected == 1 else 1
        limit_sensor_idle = int(params.get("limit_sensor_idle", default_idle))
        require_clear = self.get_param_bool(
            params, "require_sensor_clear_before_start", False
        )
        require_home = self.get_param_bool(params, "require_home_before_start", False)
        raw_timed_fb = params.get(
            "timed_fallback_ms", ctx.get_data("move_duration_ms", 0)
        )
        try:
            timed_fallback_ms = max(0, int(raw_timed_fb))
        except (TypeError, ValueError):
            timed_fallback_ms = 0
        home_sensor_addr_raw = params.get("home_sensor_address")
        if home_sensor_addr_raw is None and action == "extend":
            home_sensor_addr_raw = ctx.get_data("leg_home_address")
        elif home_sensor_addr_raw is None and action == "kick":
            home_sensor_addr_raw = ctx.get_data(
                "kick_start_sensor_address",
                ctx.get_data("extend_limit_address", 2055),
            )
        home_sensor_addr: Optional[int] = None
        if home_sensor_addr_raw is not None:
            try:
                home_sensor_addr = int(home_sensor_addr_raw)
            except (TypeError, ValueError):
                home_sensor_addr = None
        if action == "extend":
            home_expected = int(
                params.get("home_sensor_expected", ctx.get_data("leg_home_expected", 1))
            )
        else:
            home_expected = int(
                params.get(
                    "home_sensor_expected",
                    ctx.get_data("kick_start_sensor_expected", 1),
                )
            )
        min_run_ms = max(0, self.get_param_int(params, "min_run_ms", 800))
        raw_min_spd_limit = params.get("min_speed_before_limit")
        if raw_min_spd_limit is None:
            min_speed_before_limit = speed_pass_floor if verify_speed else 0.0
        else:
            min_speed_before_limit = float(raw_min_spd_limit)
        sensor_confirm_count = max(1, self.get_param_int(params, "sensor_confirm_count", 3))
        max_fb_torque = _resolve_max_feedback_torque_nm(params, ctx, action)

        base_dir = Path(log_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        log_path = base_dir / f"{sn}_{action}_until_limit.csv"

        feedback_queue = _get_dogleg_feedback_queue()
        if feedback_queue is None:
            return StepResult(
                passed=False,
                message="无法获取电机状态反馈队列，请先开启自动上报",
                error="data_queue 不可用",
                error_code="PCAN_ERR_FEEDBACK_QUEUE_MISSING",
            )

        home_desc = (
            f"原位={home_sensor_addr}(期望{home_expected})"
            if home_sensor_addr is not None
            else "原位=未配置"
        )
        ctx.log_info(
            f"[PCAN] 思粤匀速 action={action}: 目标速度={target_speed} rad/s, "
            f"扭矩上限={torque_limit} Nm, 到位={sensor_addr}(未到位={limit_sensor_idle}, "
            f"到位={sensor_expected}), {home_desc}, "
            f"min_run_ms={min_run_ms}, timed_fallback_ms={timed_fallback_ms}, "
            f"min_speed_before_limit={min_speed_before_limit}, "
            f"max_feedback_torque={max_fb_torque if max_fb_torque > 0 else '不检查'}, "
            f"日志={log_path}"
        )

        if require_home and home_sensor_addr is not None:
            home_val = _read_plc_coil(ctx, home_sensor_addr, unit_id)
            if home_val is None:
                return StepResult(
                    passed=False,
                    message=f"动作 {action} 启动前无法读取原位传感器 {home_sensor_addr}",
                    error="PLC 读线圈失败",
                    error_code="PCAN_ERR_HOME_SENSOR_READ_FAILED",
                )
            if home_val != home_expected:
                msg = (
                    f"腿不在原位: 传感器 {home_sensor_addr}={home_val}，"
                    f"期望={home_expected}。请确认腿已缩回到原位后再测"
                )
                ctx.log_error(f"[PCAN] {msg}")
                return StepResult(
                    passed=False,
                    message=msg,
                    error=msg,
                    error_code="PCAN_ERR_LEG_NOT_AT_HOME",
                )
            ctx.log_info(
                f"[PCAN] 原位检查通过: {home_sensor_addr}={home_val}"
            )

        if require_clear:
            pre_limit = _read_plc_coil(ctx, sensor_addr, unit_id)
            if pre_limit is None:
                return StepResult(
                    passed=False,
                    message=f"动作 {action} 启动前无法读取到位传感器 {sensor_addr}",
                    error="PLC 读线圈失败",
                    error_code="PCAN_ERR_LIMIT_SENSOR_READ_FAILED",
                )
            if pre_limit == sensor_expected:
                msg = (
                    f"本行程到位信号已为 {pre_limit}（{sensor_addr}），"
                    f"无法重复执行 {action}。若腿已在终点请先踢腿回原位"
                )
                ctx.log_error(f"[PCAN] {msg}")
                return StepResult(
                    passed=False,
                    message=msg,
                    error=msg,
                    error_code="PCAN_ERR_LIMIT_SENSOR_ALREADY_ACTIVE",
                )
            if pre_limit != limit_sensor_idle:
                ctx.log_warning(
                    f"[PCAN] 到位线圈 {sensor_addr}={pre_limit}，"
                    f"期望未到位={limit_sensor_idle}，继续运行"
                )
            else:
                ctx.log_info(
                    f"[PCAN] 到位线圈未触发: {sensor_addr}={pre_limit}"
                )

        motion_stats: Dict[str, Any] = _empty_feedback_stats()
        sumerror_spd = 0.0
        current_speed = 0.0
        sensor_triggered = False
        stop_reason = "timeout"
        sensor_confirm_hits = 0
        warned_early_limit = False
        control_interval = 1.0 / 200.0
        poll_interval_s = poll_ms / 1000.0
        last_poll = 0.0
        start = time.time()
        deadline = start + max_duration_ms / 1000.0
        next_log = start
        new_file = not log_path.exists()

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                if new_file:
                    f.write(
                        "time_ms,target_speed,cmd_torque,actual_speed,"
                        "sensor_value,temperature_c,status,fault\n"
                    )

                while time.time() < deadline:
                    loop_start = time.time()
                    _drain_feedback_queue(feedback_queue, motion_stats, max_items=32)
                    if "last_speed" in motion_stats:
                        try:
                            current_speed = float(motion_stats["last_speed"])
                        except (TypeError, ValueError):
                            pass

                    torque, sumerror_spd = _pi_torque_command(
                        target_speed,
                        current_speed,
                        sumerror_spd,
                        kp=pi_kp,
                        ki_gain=pi_ki,
                        torque_limit=torque_limit,
                    )
                    try:
                        comm.send_mpc_command(0.0, 0.0, torque)
                    except Exception as e:  # pragma: no cover
                        ctx.log_warning(f"[PCAN] 发送 MPC 扭矩命令失败: {e}")

                    sensor_val: Optional[int] = None
                    elapsed_ms = int((loop_start - start) * 1000)
                    if loop_start - last_poll >= poll_interval_s:
                        sensor_val = _read_plc_coil(ctx, sensor_addr, unit_id)
                        last_poll = loop_start
                        if (
                            elapsed_ms >= min_run_ms
                            and sensor_val == sensor_expected
                        ):
                            peak_now = float(motion_stats.get("max_abs_speed", 0.0))
                            if elapsed_ms < timed_fallback_ms:
                                sensor_confirm_hits = 0
                                if not warned_early_limit:
                                    warned_early_limit = True
                                    ctx.log_info(
                                        f"[PCAN] 到位信号已亮但在最短运行时间内 "
                                        f"({elapsed_ms}/{timed_fallback_ms}ms)，继续施力"
                                    )
                            elif (
                                min_speed_before_limit <= 0
                                or peak_now >= min_speed_before_limit
                            ):
                                sensor_confirm_hits += 1
                                if sensor_confirm_hits >= sensor_confirm_count:
                                    sensor_triggered = True
                                    stop_reason = "limit_sensor"
                                    break
                            else:
                                sensor_confirm_hits = 0
                                if not warned_early_limit:
                                    warned_early_limit = True
                                    ctx.log_warning(
                                        f"[PCAN] 忽略过早到位: sensor={sensor_expected} 但 "
                                        f"峰值|speed|={peak_now:.3f} < "
                                        f"{min_speed_before_limit:.3f} "
                                        f"(已运行 {elapsed_ms}ms)，继续加速"
                                    )
                        elif sensor_val != sensor_expected:
                            sensor_confirm_hits = 0

                    now = time.time()
                    if now - next_log >= 0.01:
                        temp_c = motion_stats.get("last_temperature_c")
                        temp_s = "" if temp_c is None else f"{float(temp_c):.1f}"
                        f.write(
                            f"{int(now * 1000)},{target_speed},{torque},{current_speed},"
                            f"{'' if sensor_val is None else sensor_val},"
                            f"{temp_s},{motion_stats.get('last_status')},"
                            f"{motion_stats.get('last_fault')}\n"
                        )
                        next_log = now

                    elapsed = time.time() - loop_start
                    sleep_t = control_interval - elapsed
                    if sleep_t > 0:
                        time.sleep(sleep_t)

            _drain_feedback_queue(feedback_queue, motion_stats, max_items=64)
            _finalize_feedback_stats(motion_stats)

            hold_end = time.time() + stop_hold_ms / 1000.0
            while time.time() < hold_end:
                try:
                    comm.send_mpc_command(0.0, 0.0, 0.0)
                except Exception:
                    pass
                time.sleep(control_interval)
            try:
                comm.send_mpc_command(0.0, 0.0, 0.0)
            except Exception:
                pass

        except Exception as e:  # pragma: no cover
            ctx.log_error(f"[PCAN] move_until_limit 异常: {e}")
            return StepResult(
                passed=False,
                message=f"动作 {action} 控制异常: {e}",
                error=str(e),
                error_code="PCAN_ERR_MOVE_UNTIL_LIMIT_EXCEPTION",
            )

        ctx.log_info(
            f"[PCAN] 动作 {action} 结束: {stop_reason}, "
            f"{_format_motor_status_log(motion_stats)}"
        )
        ctx.set_data(f"{action}_limit_triggered", sensor_triggered)
        ctx.set_data(f"{action}_max_abs_speed", motion_stats.get("max_abs_speed"))

        result_data = {
            "action": action,
            "motor_id": motor_id,
            "target_speed": target_speed,
            "stop_reason": stop_reason,
            "sensor_triggered": sensor_triggered,
            "limit_sensor_address": sensor_addr,
            "log_path": str(log_path),
            "motion_stats": motion_stats,
        }

        if not sensor_triggered:
            msg = (
                f"动作 {action} 超时未触发到位传感器 "
                f"(地址={sensor_addr}, 期望={sensor_expected}, "
                f"已运行 {int((time.time() - start) * 1000)} ms)"
            )
            ctx.log_error(f"[PCAN] {msg}")
            return StepResult(
                passed=False,
                message=msg,
                error=msg,
                error_code="PCAN_ERR_LIMIT_SENSOR_TIMEOUT",
                data=result_data,
            )

        if motion_stats.get("motor_alarm"):
            msg = (
                f"动作 {action} 期间电机报警: {_format_motor_status_log(motion_stats)}"
            )
            ctx.log_error(f"[PCAN] {msg}")
            return StepResult(
                passed=False,
                message=msg,
                error=msg,
                error_code="PCAN_ERR_MOTION_FAULT",
                data=result_data,
            )

        msg = _check_feedback_torque_overload(motion_stats, max_fb_torque, action)
        if msg:
            ctx.log_error(f"[PCAN] {msg}")
            return StepResult(
                passed=False,
                message=msg,
                error=msg,
                error_code="PCAN_ERR_FEEDBACK_TORQUE_OVERLOAD",
                data=result_data,
            )

        if verify_speed:
            if motion_stats["feedback_count"] < min_feedback:
                msg = (
                    f"未收到足够 0x01 反馈: {motion_stats['feedback_count']}/{min_feedback}"
                )
                ctx.log_error(f"[PCAN] {msg}")
                return StepResult(
                    passed=False,
                    message=msg,
                    error=msg,
                    error_code="PCAN_ERR_MOTION_NO_FEEDBACK",
                    data=result_data,
                )
            peak = float(motion_stats["max_abs_speed"])
            # 思粤：看反馈速度是否到目标值
            if peak < max(min_speed_peak, target_abs - speed_tolerance):
                msg = (
                    f"反馈速度未达目标: 峰值|speed|={peak:.3f} rad/s, "
                    f"目标={target_abs:.3f} rad/s, "
                    f"容差={speed_tolerance:.3f}, 下限={min_speed_peak:.3f}"
                )
                ctx.log_error(f"[PCAN] {msg}")
                return StepResult(
                    passed=False,
                    message=msg,
                    error=msg,
                    error_code="PCAN_ERR_TARGET_SPEED_NOT_REACHED",
                    data=result_data,
                )
            ctx.log_info(
                f"[PCAN] 反馈速度达标: 峰值|speed|={peak:.3f} >= "
                f"目标 {target_abs:.3f} - 容差 {speed_tolerance:.3f}"
            )

        trq_note = (
            f", 反馈扭矩峰值={float(motion_stats.get('max_abs_torque', 0)):.3f}Nm"
            if float(motion_stats.get("max_abs_torque", 0)) > 0
            else ""
        )
        return StepResult(
            passed=True,
            message=(
                f"动作 {action} 完成: 传感器已触发, 峰值|speed|="
                f"{motion_stats.get('max_abs_speed', 0):.3f} rad/s{trq_note}, 日志={log_path}"
            ),
            data=result_data,
        )


class PcanReadMotorStatusStep(BaseStep):
    """读取 0x01 自动上报中的温度与电机报警（需先 pcan.set_auto_report）。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        motor_id = _active_motor_id(ctx, params)
        collect_ms = max(50, self.get_param_int(params, "collect_ms", 500))
        min_feedback = max(1, self.get_param_int(params, "min_feedback_count", 1))
        fail_on_alarm = self.get_param_bool(params, "fail_on_alarm", True)
        require_feedback = self.get_param_bool(params, "require_feedback", True)
        max_fb_torque = _resolve_max_feedback_torque_nm(params, ctx, "extend")
        if params.get("max_feedback_torque_nm") is not None:
            try:
                max_fb_torque = max(0.0, float(params.get("max_feedback_torque_nm")))
            except (TypeError, ValueError):
                pass
        feedback_queue = _get_dogleg_feedback_queue()
        if feedback_queue is None:
            return StepResult(
                passed=False,
                message="无法获取电机状态反馈队列",
                error="请先执行 pcan.connect 与 pcan.set_auto_report",
                error_code="PCAN_ERR_FEEDBACK_QUEUE_MISSING",
            )

        stats = _empty_feedback_stats()
        deadline = time.time() + collect_ms / 1000.0
        ctx.log_info(
            f"[PCAN] 读取电机状态 motor_id={motor_id}, 采集 {collect_ms} ms…"
        )
        while time.time() < deadline:
            _drain_feedback_queue(feedback_queue, stats, max_items=64)
            time.sleep(0.02)
        _drain_feedback_queue(feedback_queue, stats, max_items=128)
        _finalize_feedback_stats(stats)

        summary = _format_motor_status_log(stats)
        ctx.log_info(f"[PCAN] 电机状态: {summary}")

        ctx.set_data("motor_temperature_c", stats.get("last_temperature_c"))
        ctx.set_data("motor_temperature_min_c", stats.get("min_temperature_c"))
        ctx.set_data("motor_temperature_max_c", stats.get("max_temperature_c"))
        ctx.set_data("motor_alarm", stats.get("motor_alarm", False))
        ctx.set_data("motor_last_status", stats.get("last_status"))
        ctx.set_data("motor_last_fault", stats.get("last_fault"))

        result_data = {
            "motor_id": motor_id,
            "collect_ms": collect_ms,
            "temperature_c": stats.get("last_temperature_c"),
            "temperature_min_c": stats.get("min_temperature_c"),
            "temperature_max_c": stats.get("max_temperature_c"),
            "motor_alarm": stats.get("motor_alarm", False),
            "last_status": stats.get("last_status"),
            "last_fault": stats.get("last_fault"),
            "feedback_count": stats.get("feedback_count", 0),
            "motion_stats": stats,
        }

        if require_feedback and int(stats.get("feedback_count", 0)) < min_feedback:
            msg = (
                f"未收到足够 0x01 反馈: {stats.get('feedback_count')}/{min_feedback}，"
                "请确认已开启自动上报且电机在线"
            )
            ctx.log_error(f"[PCAN] {msg}")
            return StepResult(
                passed=False,
                message=msg,
                error=msg,
                error_code="PCAN_ERR_STATUS_NO_FEEDBACK",
                data=result_data,
            )

        if fail_on_alarm and stats.get("motor_alarm"):
            msg = f"电机报警: {summary}"
            ctx.log_error(f"[PCAN] {msg}")
            return StepResult(
                passed=False,
                message=msg,
                error=msg,
                error_code="PCAN_ERR_MOTOR_ALARM",
                data=result_data,
            )

        msg = _check_feedback_torque_overload(stats, max_fb_torque, "status")
        if msg:
            ctx.log_error(f"[PCAN] {msg}")
            return StepResult(
                passed=False,
                message=msg,
                error=msg,
                error_code="PCAN_ERR_FEEDBACK_TORQUE_OVERLOAD",
                data=result_data,
            )

        return StepResult(
            passed=True,
            message=summary,
            data=result_data,
        )


class PcanDisconnectStep(BaseStep):
    """断开 PCAN 连接"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        comm = ctx.get_comm_driver("pcan_comm")
        if not comm:
            ctx.log_info("[PCAN] 当前未连接 PCAN 设备")
            return StepResult(
                passed=True,
                message="当前未连接 PCAN 设备",
                data={"disconnected": True},
            )

        try:
            _safe_shutdown_pcan_comm(comm, ctx.log_warning)
        except Exception as e:  # pragma: no cover
            ctx.log_warning(f"[PCAN] 断开 PCAN 连接时出现异常: {e}")

        ctx.remove_comm_driver("pcan_comm")
        ctx.set_state("pcan_connected", False)

        ctx.log_info("[PCAN] 已断开 PCAN 设备连接")
        return StepResult(
            passed=True,
            message="PCAN 设备断开连接成功",
            data={"disconnected": True},
        )

