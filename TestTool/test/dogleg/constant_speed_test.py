#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
狗腿模组匀速运行独立测试脚本（MPC 速度指令模式）

与产线步骤 ``pcan.move_with_torque_log`` / GUI ``pi_control_loop`` 不同：
本脚本在运控模式 (enable mode=1) 下以 200Hz 发送
    send_mpc_command(angle=0, speed=目标速度, torque=0)
由电机内部速度环跟踪目标角速度，实现真正的匀速运行。

用法（在 TestTool 目录或本脚本所在目录执行）::

    python test/dogleg/constant_speed_test.py --sn TEST001
    python test/dogleg/constant_speed_test.py --motor-id 3 --extend-speed 1.0 --kick-speed -1.0 --duration 8

依赖：PCAN-USB 驱动、PCANBasic.dll、同目录 tool.py
"""

from __future__ import annotations

import argparse
import csv
import queue
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from tool import CANCommunicator, data_queue  # noqa: E402

CONTROL_HZ = 200.0
DEFAULT_ALLOWED_IDS = (3, 6, 9, 12)
DEFAULT_EXTEND_SPEED = 1.0   # rad/s
DEFAULT_KICK_SPEED = -1.0    # rad/s
DEFAULT_DURATION_S = 8.0
DEFAULT_REPORT_HZ = 200
SPEED_TOLERANCE = 0.25     # |实测-目标| 允许偏差 (rad/s)
MIN_FEEDBACK = 20
SETTLE_RATIO = 0.25        # 舍弃前 25% 采样再统计稳态速度


@dataclass
class MotionStats:
    target_speed: float
    feedback_count: int = 0
    speeds: List[float] = field(default_factory=list)
    max_abs_torque: float = 0.0
    min_temperature_c: Optional[float] = None
    max_temperature_c: Optional[float] = None
    last_status: Optional[int] = None
    last_fault: Optional[int] = None
    motor_alarm: bool = False

    @property
    def steady_speeds(self) -> List[float]:
        if not self.speeds:
            return []
        skip = int(len(self.speeds) * SETTLE_RATIO)
        return self.speeds[skip:]

    @property
    def mean_speed(self) -> Optional[float]:
        ss = self.steady_speeds
        return statistics.mean(ss) if ss else None

    @property
    def speed_error(self) -> Optional[float]:
        m = self.mean_speed
        return abs(m - self.target_speed) if m is not None else None

    def passed(self, tolerance: float, min_feedback: int) -> Tuple[bool, str]:
        if self.feedback_count < min_feedback:
            return False, f"0x01 反馈不足: {self.feedback_count}/{min_feedback}"
        if self.motor_alarm:
            return False, (
                f"电机报警 status={self.last_status} fault=0x{int(self.last_fault or 0):02X}"
            )
        err = self.speed_error
        if err is None:
            return False, "无有效速度采样"
        if err > tolerance:
            m = self.mean_speed
            return False, (
                f"稳态速度偏差过大: 目标={self.target_speed:.3f}, "
                f"实测均值={m:.3f}, |误差|={err:.3f} > {tolerance:.3f} rad/s"
            )
        return True, (
            f"通过: 稳态均值={self.mean_speed:.3f} rad/s, "
            f"反馈={self.feedback_count}, max|扭矩|={self.max_abs_torque:.3f} Nm"
        )


def _drain_feedback(stats: MotionStats, max_items: int = 64) -> None:
    processed = 0
    while processed < max_items:
        try:
            fb = data_queue.get_nowait()
        except queue.Empty:
            break
        processed += 1
        stats.feedback_count += 1
        try:
            spd = float(fb.get("speed", 0.0))
            stats.speeds.append(spd)
        except (TypeError, ValueError):
            pass
        try:
            trq = float(fb.get("torque", 0.0))
            stats.max_abs_torque = max(stats.max_abs_torque, abs(trq))
        except (TypeError, ValueError):
            pass
        temp = fb.get("temperature")
        if temp is not None:
            try:
                t_c = float(temp)
                stats.min_temperature_c = (
                    t_c if stats.min_temperature_c is None
                    else min(stats.min_temperature_c, t_c)
                )
                stats.max_temperature_c = (
                    t_c if stats.max_temperature_c is None
                    else max(stats.max_temperature_c, t_c)
                )
            except (TypeError, ValueError):
                pass
        status = fb.get("status")
        if status is not None:
            stats.last_status = int(status)
            if int(status) == 2:
                stats.motor_alarm = True
        fault = fb.get("fault")
        if fault is not None:
            try:
                fault_i = int(fault) & 0xFF
            except (TypeError, ValueError):
                fault_i = 0
            stats.last_fault = fault_i
            if fault_i & 0x7F not in (0, 0x80):
                stats.motor_alarm = True


def _clear_feedback_queue() -> None:
    while True:
        try:
            data_queue.get_nowait()
        except queue.Empty:
            break


def _search_motor(comm: CANCommunicator, allowed: List[int], wait_s: float) -> Optional[int]:
    comm.discovered_motors.clear()
    comm.search_motors()
    time.sleep(wait_s)
    discovered = sorted({int(mid) for mid, _ in comm.discovered_motors})
    allowed_set = set(allowed)
    matched = [mid for mid in discovered if mid in allowed_set]
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        print(f"[WARN] 总线上多个允许 ID: {matched}，请只接一只电机")
        return None
    for candidate in allowed:
        comm.current_motor_id = candidate
        ok, err = comm.enable_motor(mode=1)
        if ok:
            print(f"[INFO] 使能探测成功: motor_id={candidate}")
            return candidate
        print(f"[INFO] ID={candidate} 使能失败: {err}")
    return None


def run_constant_speed(
    comm: CANCommunicator,
    target_speed: float,
    duration_s: float,
    log_path: Path,
    *,
    control_hz: float = CONTROL_HZ,
) -> MotionStats:
    """
    以固定目标角速度运行 duration_s 秒，记录 CSV 并统计稳态速度。
    """
    stats = MotionStats(target_speed=target_speed)
    _clear_feedback_queue()

    log_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not log_path.exists()
    interval = 1.0 / control_hz
    log_interval = 0.01  # 100Hz 写盘

    with open(log_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(
                ["time_ms", "target_speed", "actual_speed", "cmd_torque",
                 "temperature_c", "status", "fault"]
            )

        start = time.time()
        next_log = start
        while time.time() - start < duration_s:
            loop_start = time.time()
            _drain_feedback(stats)

            actual = stats.speeds[-1] if stats.speeds else 0.0
            # MPC 匀速：角度 0、速度=目标、扭矩 0（由电机速度环跟踪）
            comm.send_mpc_command(0.0, target_speed, 0.0)

            now = time.time()
            if now - next_log >= log_interval:
                temp = stats.max_temperature_c
                writer.writerow([
                    int(now * 1000),
                    f"{target_speed:.4f}",
                    f"{actual:.4f}",
                    "0",
                    "" if temp is None else f"{temp:.1f}",
                    stats.last_status if stats.last_status is not None else "",
                    stats.last_fault if stats.last_fault is not None else "",
                ])
                next_log = now

            elapsed = time.time() - loop_start
            sleep_t = interval - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)

    _drain_feedback(stats, max_items=128)
    # 停止后发送零指令
    comm.send_mpc_command(0.0, 0.0, 0.0)
    return stats


def _parse_id_list(raw: str) -> List[int]:
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    return [int(p) for p in parts] if parts else list(DEFAULT_ALLOWED_IDS)


def main() -> int:
    parser = argparse.ArgumentParser(description="狗腿模组匀速运行测试（MPC 速度指令）")
    parser.add_argument("--sn", default="CONST_SPEED_TEST", help="日志文件名前缀")
    parser.add_argument("--motor-id", type=int, default=None, help="指定电机 ID，跳过搜索")
    parser.add_argument("--allowed-ids", default="3,6,9,12", help="允许搜索的 ID 列表")
    parser.add_argument("--search-wait", type=float, default=0.8, help="搜索后等待秒数")
    parser.add_argument("--extend-speed", type=float, default=DEFAULT_EXTEND_SPEED)
    parser.add_argument("--kick-speed", type=float, default=DEFAULT_KICK_SPEED)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_S, help="每个动作时长(秒)")
    parser.add_argument("--report-hz", type=int, default=DEFAULT_REPORT_HZ, help="0x01 上报频率")
    parser.add_argument("--log-dir", type=Path, default=Path("Result/dogleg"))
    parser.add_argument("--skip-kick", action="store_true", help="只测伸腿，不测踢腿")
    parser.add_argument("--speed-tolerance", type=float, default=SPEED_TOLERANCE)
    parser.add_argument("--min-feedback", type=int, default=MIN_FEEDBACK)
    parser.add_argument("--extend-only", action="store_true", help="同 --skip-kick")
    args = parser.parse_args()

    if args.extend_only:
        args.skip_kick = True

    log_dir = args.log_dir
    allowed = _parse_id_list(args.allowed_ids)
    comm = CANCommunicator()

    print("[1/6] 初始化 PCAN …")
    if not comm.init_can():
        print("[FAIL] CAN 初始化失败，请检查 PCAN-USB 与驱动")
        return 1

    try:
        motor_id = args.motor_id
        if motor_id is None:
            print(f"[2/6] 搜索电机 allowed={allowed} …")
            motor_id = _search_motor(comm, allowed, args.search_wait)
            if motor_id is None:
                print("[FAIL] 未识别到电机")
                return 1
        else:
            comm.current_motor_id = motor_id

        print(f"[3/6] 使能电机 motor_id={motor_id} …")
        ok, err = comm.enable_motor(mode=1)
        if not ok:
            print(f"[FAIL] 使能失败: {err}")
            return 1

        print(f"[4/6] 开启 0x01 自动上报 {args.report_hz} Hz …")
        comm.toggle_auto_report(True, args.report_hz, motor_id)
        time.sleep(0.2)
        _clear_feedback_queue()

        results: List[Tuple[str, bool, str, Path]] = []
        actions: List[Tuple[str, float]] = [("extend", args.extend_speed)]
        if not args.skip_kick:
            actions.append(("kick", args.kick_speed))

        for idx, (action, speed) in enumerate(actions, start=5):
            log_path = log_dir / f"{args.sn}_{action}_const_speed.csv"
            print(f"[{idx}/6] 匀速 {action}: 目标速度={speed:.3f} rad/s, 时长={args.duration}s …")
            stats = run_constant_speed(comm, speed, args.duration, log_path)
            passed, msg = stats.passed(args.speed_tolerance, args.min_feedback)
            print(f"       日志: {log_path}")
            print(f"       结果: {'PASS' if passed else 'FAIL'} — {msg}")
            results.append((action, passed, msg, log_path))

        print("[6/6] 禁能并断开 …")
        comm.disable_motor()
        time.sleep(0.1)
        comm.send_mpc_command(0.0, 0.0, 0.0)

        all_ok = all(p for _, p, _, _ in results)
        print("\n======== 汇总 ========")
        for action, passed, msg, path in results:
            print(f"  {action}: {'PASS' if passed else 'FAIL'} — {msg}")
            print(f"         {path}")
        print(f"总体: {'PASS' if all_ok else 'FAIL'}")
        return 0 if all_ok else 2

    finally:
        try:
            comm.terminate()
        except Exception as e:
            print(f"[WARN] 终止 CAN 异常: {e}")


if __name__ == "__main__":
    sys.exit(main())
