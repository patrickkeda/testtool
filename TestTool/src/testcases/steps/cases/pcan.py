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
- pcan.move_with_torque_log  -> PcanMoveWithTorqueLogStep
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


class PcanMoveWithTorqueLogStep(BaseStep):
    """执行伸腿 / 踢腿动作，并记录扭矩日志（占位实现）

    参数：
    - action: 'extend' 或 'kick'
    - motor_id: 电机 ID
    - sn: 序列号（用于文件名）
    - log_dir: 日志目录（默认为 Result/dogleg）

    实际动作控制和扭矩采集逻辑需要参考现有 tool.py 中的实现，
    在此处补充 CAN 帧发送与扭矩采样/记录过程。
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

        ctx.log_info(
            f"[PCAN] 执行动作 action={action}, motor_id={motor_id}, 日志路径={log_path}"
        )

        try:
            import time
            import queue

            # 目标速度：默认 extend=+1.0 rad/s, kick=-1.0 rad/s，可通过参数覆盖
            default_target = 1.0 if action == "extend" else -1.0
            try:
                target_speed = float(params.get("target_speed", default_target))
            except Exception:
                target_speed = default_target
                ctx.log_warning(
                    f"[PCAN] target_speed 参数解析失败，使用默认值 {default_target}"
                )

            # 从 dogleg 工具模块获取数据队列，用于读取当前速度反馈
            from importlib import import_module

            feedback_queue = None
            try:
                # 确保 dogleg 路径已在 sys.path 中（_get_or_create_can_comm 已通过 _load_can_communicator 处理）
                dogleg_dir = _get_dogleg_dir()
                if dogleg_dir.is_dir() and str(dogleg_dir) not in sys.path:
                    sys.path.insert(0, str(dogleg_dir))
                dogleg_mod = import_module("tool")
                feedback_queue = getattr(dogleg_mod, "data_queue", None)
            except Exception as e:  # pragma: no cover
                ctx.log_warning(f"[PCAN] 无法导入 dogleg 工具模块用于读取反馈: {e}")

            new_file = not log_path.exists()
            with open(log_path, "a", encoding="utf-8") as f:
                if new_file:
                    f.write("time_ms,torque,position,velocity,raw\n")

                # PI 控制循环，尽量复用 tool.py 中的算法：
                # 200Hz 控制频率，tor = 0.1 * err + 0.05 * sumerror，限幅 [-3,3]
                control_interval = 1.0 / 200.0  # 5ms
                sumerror_spd = 0.0
                current_speed = 0.0
                start_time = time.time()
                next_log_time = start_time
                duration_s = max(0.1, duration_ms / 1000.0)

                while time.time() - start_time < duration_s:
                    loop_start = time.time()

                    # 更新当前速度：从反馈队列中取最新 speed
                    if feedback_queue is not None:
                        processed = 0
                        while processed < 10:
                            try:
                                fb = feedback_queue.get_nowait()
                            except queue.Empty:
                                break
                            try:
                                current_speed = float(fb.get("speed", current_speed))
                            except Exception:
                                pass
                            processed += 1

                    # PI 控制计算扭矩
                    errspd = target_speed - current_speed
                    sumerror_spd += 0.05 * errspd
                    torque = 0.1 * errspd + 0.05 * sumerror_spd

                    # 原算法扭矩限幅 [-3, 3]，再叠加外部 torque_limit 限幅
                    torque = max(-3.0, min(3.0, torque))
                    torque = max(-abs(torque_limit), min(abs(torque_limit), torque))

                    # 发送 MPC 命令
                    try:
                        comm.send_mpc_command(0.0, 0.0, torque)
                    except Exception as e:  # pragma: no cover
                        ctx.log_warning(f"[PCAN] 发送 MPC 命令失败（忽略继续）: {e}")

                    # 每 10ms 记录一次日志
                    now = time.time()
                    if now - next_log_time >= 0.01:
                        now_ms = int(now * 1000)
                        f.write(f"{now_ms},{torque},{0.0},{current_speed},\n")
                        next_log_time = now

                    # 保持控制周期接近 5ms
                    elapsed = time.time() - loop_start
                    sleep_time = control_interval - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)

        except Exception as e:  # pragma: no cover
            ctx.log_warning(f"[PCAN] 伸腿/踢腿控制执行异常（继续后续步骤）: {e}")

        return StepResult(
            passed=True,
            message=f"动作 {action} 执行占位步骤完成，日志文件: {log_path}",
            data={
                "action": action,
                "motor_id": motor_id,
                "sn": sn,
                "log_path": str(log_path),
            },
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

