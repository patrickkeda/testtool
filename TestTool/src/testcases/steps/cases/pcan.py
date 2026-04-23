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
from typing import Dict, Any
from pathlib import Path
import sys
import os
import importlib.util


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

        # 如果已经初始化过，先尝试优雅关闭再重连，避免上一次失败残留导致本次 Initialize 失败
        try:
            if getattr(comm, "initialized", False) and hasattr(comm, "pcan") and hasattr(comm, "channel"):
                ctx.log_warning("[PCAN] 检测到上次连接可能未完全释放，先执行 Uninitialize 再重连")
                try:
                    comm.pcan.Uninitialize(comm.channel)
                except Exception:
                    # 忽略底层异常，继续尝试重新初始化
                    pass
                # 标记为未初始化，方便后续逻辑判断
                try:
                    setattr(comm, "initialized", False)
                except Exception:
                    pass
        except Exception:
            # 任何清理异常都不影响后续重连尝试
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
    """搜索并“连接”指定 ID 的电机

    说明：
    - 这里提供一个简单占位实现，仅验证总线可用并记录 motor_id
    - 实际搜索/握手逻辑可参考现有 tool.py 中的实现，在此处补充
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

        # motor_id 支持直接数字或 "${motor_id}" 形式，从上下文 variables 解析
        raw_motor_id = params.get("motor_id", ctx.get_data("motor_id", 3))
        if isinstance(raw_motor_id, str):
            # 如果是占位符，优先从上下文取数字
            if raw_motor_id.strip().startswith("${") and raw_motor_id.strip().endswith("}"):
                raw_motor_id = ctx.get_data("motor_id", 3)
        try:
            motor_id = int(raw_motor_id)
        except Exception:
            motor_id = 3
            ctx.log_warning(f"[PCAN] motor_id 参数解析失败，使用默认值 3，原始值: {raw_motor_id!r}")
        # 无 UI 环境：直接设置 current_motor_id，并调用 search_motors 进行一次广播
        try:
            setattr(comm, "current_motor_id", motor_id)
            if hasattr(comm, "search_motors"):
                ctx.log_info("[PCAN] 调用 CANCommunicator.search_motors() 搜索电机")
                comm.search_motors()
        except Exception as e:  # pragma: no cover
            ctx.log_warning(f"[PCAN] 搜索电机时出现异常（忽略，仅记录）: {e}")

        ctx.set_state("pcan_motor_id", motor_id)
        ctx.log_info(f"[PCAN] 已记录 motor_id={motor_id}")

        return StepResult(
            passed=True,
            message=f"记录电机 ID 成功（占位实现）: motor_id={motor_id}",
            data={"motor_id": motor_id},
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

        raw_motor_id = params.get(
            "motor_id", ctx.get_state("pcan_motor_id", default=ctx.get_data("motor_id", 3))
        )
        if isinstance(raw_motor_id, str):
            if raw_motor_id.strip().startswith("${") and raw_motor_id.strip().endswith("}"):
                raw_motor_id = ctx.get_data("motor_id", 3)
        try:
            motor_id = int(raw_motor_id)
        except Exception:
            motor_id = 3
            ctx.log_warning(f"[PCAN] motor_id 参数解析失败，使用默认值 3，原始值: {raw_motor_id!r}")
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
        raw_motor_id = params.get(
            "motor_id", ctx.get_state("pcan_motor_id", default=ctx.get_data("motor_id", 3))
        )
        if isinstance(raw_motor_id, str):
            if raw_motor_id.strip().startswith("${") and raw_motor_id.strip().endswith("}"):
                raw_motor_id = ctx.get_data("motor_id", 3)
        try:
            motor_id = int(raw_motor_id)
        except Exception:
            motor_id = 3
            ctx.log_warning(f"[PCAN] motor_id 参数解析失败，使用默认值 3，原始值: {raw_motor_id!r}")
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
            if hasattr(comm, "pcan") and hasattr(comm, "channel"):
                try:
                    comm.pcan.Uninitialize(comm.channel)
                except Exception:
                    pass
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

