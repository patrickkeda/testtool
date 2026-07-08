"""
Background worker for test execution using the new testcases architecture.

Emits status and progress signals for UI binding.
"""

from __future__ import annotations

import sys
import time
import threading
import logging
from typing import Optional, List, Dict, Any

from PySide6.QtCore import QObject, Signal

# 导入新架构组件
from ..testcases.context import Context
# 先加载 register_steps：其模块尾部会执行 register_all_steps()，保证仅 import worker 时注册表也已填充
from ..testcases import register_steps as _register_steps  # noqa: F401
from ..testcases.registry import create_step
from ..testcases.base import StepResult
from ..testcases.config import TestSequenceConfig
from ..testcases.utils import resolve_placeholders_in_params, step_condition_should_run
from ..testcases.plc_safe_shutdown import (
    apply_plc_shutdown_writes,
    resolve_plc_shutdown_write_specs,
    sequence_uses_plc_modbus_rtu,
)
from ..testcases.steps.cases.pcan import _safe_shutdown_pcan_comm


class PortWorker(QObject):
    """Worker for one testing port, running in a separate thread.

    Uses the new testcases architecture to execute test steps.
    """

    sig_status = Signal(str)  # Idle/Preparing/Running/Paused/Completed/Alarm
    sig_progress = Signal(int)  # 0..100
    sig_step = Signal(str, str)  # step_id, status
    sig_step_result = Signal(str, object)  # step_id, StepResult

    def __init__(self, port: str, context: Optional[Context] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.port = port
        self.context = context or Context(port=port)
        self._sequence: Optional[TestSequenceConfig] = None
        self._lock = threading.RLock()
        self._should_stop = False
        self._is_paused = False
        self._running = False
        self._start_from_step = None  # 从指定步骤开始执行
        self._run_single_step_only = False  # 为 True 时只执行一条步骤后结束本轮
        self._test_mode = "production"  # 默认产线模式：'production' 或 'debug'
        self._retest_mode = False  # 复测模式：跳过SN扫描等前置步骤
        self._logger = logging.getLogger(f"{__name__}.{self.port}")

    # ---- control ---------------------------------------------------------
    def start_run(self) -> None:
        with self._lock:
            if self._running:
                return
            self._should_stop = False
            self._is_paused = False
            self._running = True
        self._logger.info("开始执行测试序列")
        self._run()

    def pause(self) -> None:
        with self._lock:
            self._is_paused = True
            self.sig_status.emit("Paused")
        self._logger.info("测试已暂停")

    def resume(self) -> None:
        with self._lock:
            self._is_paused = False
        self._logger.info("测试已恢复")

    def stop(self) -> None:
        with self._lock:
            self._should_stop = True
        self._logger.info("测试已停止")
    
    def set_sequence(self, sequence: TestSequenceConfig) -> None:
        """设置要执行的序列"""
        with self._lock:
            self._sequence = sequence
            self._logger.info(f"设置测试序列: {sequence.metadata.name if sequence else 'None'}")
    
    def set_context(self, context: Context) -> None:
        """设置测试上下文"""
        with self._lock:
            self.context = context
            self._logger.info(f"设置测试上下文: {context.port}")
    
    def set_start_from_step(self, step_id: str) -> None:
        """设置从指定步骤开始执行"""
        with self._lock:
            self._start_from_step = step_id

    def set_run_single_step_only(self, enabled: bool) -> None:
        """为 True 时本轮只执行一条步骤（需配合 set_start_from_step）。"""
        with self._lock:
            self._run_single_step_only = bool(enabled)
            self._logger.info("单步执行模式: %s", self._run_single_step_only)
    
    def set_test_mode(self, mode: str) -> None:
        """设置测试模式：'production' 或 'debug'。

        debug：MES 步骤（``mes.*``）默认关闭，不连服务器、不上报、不弹窗，自动判通过并继续。
        production：正常执行 MES；步骤失败时可 ``_run_mes_end_after_failure`` 上报 FAIL。
        """
        with self._lock:
            self._test_mode = mode
            self._logger.info(f"设置测试模式: {mode}")
    
    def set_retest_mode(self, enabled: bool) -> None:
        """设置是否为复测模式。
        
        复测模式下会跳过SN扫描步骤，直接使用上下文中已有的SN。
        """
        with self._lock:
            self._retest_mode = bool(enabled)
            self._logger.info("设置复测模式: %s", self._retest_mode)
    
    # ---- status queries ----------------------------------------------------
    def is_running(self) -> bool:
        """检查是否正在运行"""
        with self._lock:
            return self._running and not self._is_paused
    
    def is_paused(self) -> bool:
        """检查是否处于暂停状态"""
        with self._lock:
            return self._running and self._is_paused
    
    def is_idle(self) -> bool:
        """检查是否处于空闲状态"""
        with self._lock:
            return not self._running and not self._is_paused
    
    def is_completed(self) -> bool:
        """检查是否已完成"""
        with self._lock:
            return not self._running and not self._is_paused and not self._should_stop
    
    def reset(self) -> None:
        """重置worker状态，准备重新开始"""
        with self._lock:
            self._should_stop = False
            self._is_paused = False
            self._running = False
            self._start_from_step = None
            self._run_single_step_only = False

    # ---- internal --------------------------------------------------------
    def _run(self) -> None:
        """执行测试序列"""
        if not self._sequence:
            self._logger.error("没有设置测试序列")
            self.sig_status.emit("Idle")
            return

        with self._lock:
            _single_blocked = self._run_single_step_only and self._test_mode == "production"
        if _single_blocked:
            self._logger.warning("产线模式下禁止单步执行，已取消本轮")
            with self._lock:
                self._start_from_step = None
                self._run_single_step_only = False
                self._running = False
            self.sig_progress.emit(0)
            self.sig_status.emit("Idle")
            return
        
        self.sig_status.emit("Preparing")
        self._logger.info("准备执行测试...")
        time.sleep(0.1)
        
        self.sig_status.emit("Running")
        self._logger.info("测试执行中...")

        # 将序列变量注入上下文，便于 ${var} 替换
        try:
            if self._sequence.variables:
                for key, value in self._sequence.variables.items():
                    self.context.set_data(key, value)
                    self._logger.info(f"注入序列变量: {key} = {value}")
        except Exception as e:  # noqa: BLE001
            self._logger.warning(f"注入序列变量失败: {e}")

        with self._lock:
            _debug_mode = self._test_mode == "debug"
        if _debug_mode and self.context:
            self.context.set_data("mes_enabled", False)
            self._logger.info("调试模式：MES 默认关闭（mes_enabled=False）")

        # 配置「测试站 → 煲机脚本配置」(ssh.import_script_path) 非空时，覆盖序列变量 pvt_script_path
        try:
            _imp = self.context.get_data("ssh_import_script_path", "")
            if isinstance(_imp, str) and _imp.strip():
                from pathlib import Path

                self.context.set_data("pvt_script_path", _imp.strip())
                # PVT 序列：远端校验路径常用 /app/<basename>，与实际上传文件名对齐
                try:
                    self.context.set_data(
                        "pvt_remote_script_basename", Path(_imp.strip()).name
                    )
                except Exception:  # noqa: BLE001
                    pass
                self._logger.info(
                    "已使用配置 ssh.import_script_path 覆盖 pvt_script_path: %s",
                    _imp.strip(),
                )
        except Exception as e:  # noqa: BLE001
            self._logger.warning(f"应用 ssh.import_script_path 覆盖失败: {e}")

        # 配置「测试站 → 煲机数据保存目录」(ssh.burnin_data_save_dir) 非空时，覆盖 pvt_ota_pull_local_parent
        try:
            _save_dir = self.context.get_data("ssh_burnin_data_save_dir", "")
            if isinstance(_save_dir, str) and _save_dir.strip():
                self.context.set_data("pvt_ota_pull_local_parent", _save_dir.strip())
                self._logger.info(
                    "已使用配置 ssh.burnin_data_save_dir 覆盖 pvt_ota_pull_local_parent: %s",
                    _save_dir.strip(),
                )
        except Exception as e:  # noqa: BLE001
            self._logger.warning(f"应用 ssh.burnin_data_save_dir 覆盖失败: {e}")
        
        # 获取步骤列表
        steps = self._sequence.steps
        if not steps:
            self._logger.warning("测试序列为空")
            self.sig_status.emit("Completed")
            return
        
        # 确定开始执行的步骤索引
        start_idx = 0
        if self._start_from_step:
            for i, step in enumerate(steps):
                if step.id == self._start_from_step:
                    start_idx = i
                    self._logger.info(f"从步骤 {self._start_from_step} 开始执行")
                    break
            else:
                self._logger.warning(f"未找到起始步骤 {self._start_from_step}，从开始执行")
                start_idx = 0

        with self._lock:
            _single_intro = self._run_single_step_only
        if _single_intro:
            sid = steps[start_idx].id if start_idx < len(steps) else "?"
            self._logger.info("单步测试模式：仅执行步骤 %s（共 %s 步中的 1 步）", sid, len(steps))
        
        n = len(steps)
        self._logger.info(f"总共 {n} 个测试步骤")
        
        # 执行步骤
        for idx, step_config in enumerate(steps[start_idx:], start=start_idx + 1):
            if self._check_stop():
                # 用户停止测试：含 PLC 序列时先尝试下电再清理连接
                self._cleanup_connections(abnormal_exit=True)
                self._running = False
                self.sig_status.emit("Idle")
                self._logger.info("测试被用户停止")
                return
            
            # 暂停检查
            while self._is_paused and not self._should_stop:
                time.sleep(0.05)

            with self._lock:
                is_retest = self._retest_mode
                run_single = self._run_single_step_only
            
            # 复测模式下跳过 SN 扫描；单步调试指定跑 scan.sn 时不跳过
            if is_retest and not run_single and getattr(step_config, "type", "") == "scan.sn":
                self._logger.info(
                    "复测模式：跳过SN扫描步骤 %s (%s)，使用上下文中的已有SN",
                    step_config.id,
                    step_config.name,
                )
                self.sig_step.emit(step_config.id, "Skipped")
                self.sig_progress.emit(int(idx * 100 / n))
                continue

            # 步骤级 condition：为假时跳过本步（不创建实例、不计为失败）
            raw_cond = getattr(step_config, "condition", None)
            if not step_condition_should_run(raw_cond, self.context):
                self._logger.info(
                    "步骤 %s 条件不满足，跳过（condition=%r）",
                    step_config.id,
                    raw_cond,
                )
                self.sig_step.emit(step_config.id, "Skipped")
                self.sig_progress.emit(int(idx * 100 / n))
                if run_single:
                    break
                continue

            # 执行步骤
            self._logger.info(
                f"执行步骤 {step_config.id}（第 {idx}/{n} 步）: {step_config.name}"
            )
            self.sig_step.emit(step_config.id, "Running")
            
            try:
                # 调试模式：MES 默认关闭，自动跳过 mes.*，不弹窗、不连服务器
                _inner_type = str(getattr(step_config, "type", "") or "")
                with self._lock:
                    _dbg_mes_gate = self._test_mode == "debug"
                if _dbg_mes_gate and _inner_type.startswith("mes."):
                    self._logger.info(
                        "调试模式：MES 步骤 %s（%s）已自动跳过（MES 关闭）",
                        step_config.id,
                        step_config.name,
                    )
                    skip_res = StepResult(
                        passed=True,
                        message="调试模式：MES 已关闭，本步自动跳过",
                        data={"mes_skipped": True, "debug_mode": True},
                    )
                    try:
                        if hasattr(self.context, "set_result"):
                            self.context.set_result(step_config.id, skip_res)
                        else:
                            self.context.set_data(f"{step_config.id}_result", skip_res)
                            self.context.set_data(step_config.id, skip_res)
                        self.context.set_data(f"{step_config.id}_passed", True)
                    except Exception as persist_ex:  # noqa: BLE001
                        self._logger.warning("写入 MES 跳过结果到上下文失败: %s", persist_ex)
                    self.sig_step_result.emit(step_config.id, skip_res)
                    self.sig_progress.emit(int(idx * 100 / n))
                    self.sig_step.emit(step_config.id, "Pass")
                    if run_single:
                        break
                    continue

                # 创建步骤实例
                _st_timeout = getattr(step_config, "timeout", None)
                if _st_timeout is None:
                    _st_timeout = 30
                _retry_gap = getattr(step_config, "retry_interval_ms", None)
                if _retry_gap is None:
                    _retry_gap = 1000
                step_instance = create_step(
                    step_type=step_config.type,
                    step_id=step_config.id,
                    step_name=step_config.name,
                    timeout=_st_timeout,
                    retries=step_config.retries,
                    on_failure=step_config.on_failure,
                    retry_interval_ms=int(_retry_gap),
                )
                
                if not step_instance:
                    self._logger.error(f"无法创建步骤实例: {step_config.type}")
                    self.sig_step.emit(step_config.id, "Fail")
                    fail_res = StepResult(
                        passed=False,
                        message=f"无法创建步骤实例: {step_config.type}",
                        error=str(step_config.type),
                    )
                    try:
                        if hasattr(self.context, "set_result"):
                            self.context.set_result(step_config.id, fail_res)
                        else:
                            self.context.set_data(f"{step_config.id}_result", fail_res)
                            self.context.set_data(step_config.id, fail_res)
                        self.context.set_data(f"{step_config.id}_passed", False)
                    except Exception as persist_ex:  # noqa: BLE001
                        self._logger.warning("写入步骤失败结果到上下文失败: %s", persist_ex)
                    self.sig_step_result.emit(step_config.id, fail_res)
                    mes_uploaded = self._run_mes_end_after_failure(
                        steps=steps,
                        failed_step_id=step_config.id,
                        failed_step_name=step_config.name,
                        failed_result=fail_res,
                    )
                    if mes_uploaded:
                        self._logger.info("已执行 MesEnd 失败上报，停止后续步骤")
                    else:
                        with self._lock:
                            _tm = self._test_mode
                        if _tm == "debug":
                            self._logger.info("调试模式：不上报 MES，已停止后续步骤")
                        else:
                            self._logger.info(
                                "产线：已停止后续步骤（失败直跳 MesEnd 未执行、无 mes.upload_result 或为单步模式）"
                            )
                    self._cleanup_connections(abnormal_exit=True)
                    break
                
                # 执行步骤（${var} 与序列 variables / 上下文对齐）
                _params = resolve_placeholders_in_params(
                    dict(step_config.params or {}), self.context
                )
                result = step_instance.run(self.context, _params)

                # 将步骤结果写入上下文，供后续步骤引用（如 Step 7 读取 Step 6 的 SOC）
                try:
                    if hasattr(self.context, "set_result"):
                        self.context.set_result(step_config.id, result)
                    else:
                        # 兼容：至少写入 state
                        self.context.set_data(f"{step_config.id}_result", result)
                        self.context.set_data(step_config.id, result)
                    # 供 YAML condition: '${step_9_passed}' 等布尔判断（str(True/False) 展开后为 true/false）
                    self.context.set_data(f"{step_config.id}_passed", bool(result.passed))
                except Exception as e:  # noqa: BLE001
                    self._logger.warning(f"写入步骤结果到上下文失败: {e}")

                # 发送步骤结果信号
                self.sig_step_result.emit(step_config.id, result)
                
                # 更新进度
                self.sig_progress.emit(int(idx * 100 / n))
                
                # 记录结果
                if result.passed:
                    self._logger.info(
                        f"步骤 {step_config.id}（第 {idx}/{n} 步）: {step_config.name} - 通过"
                    )
                    self.sig_step.emit(step_config.id, "Pass")
                    if run_single:
                        break
                else:
                    self._logger.warning(
                        f"步骤 {step_config.id}（第 {idx}/{n} 步）: {step_config.name} - 失败: {result.message}"
                    )
                    err_detail = getattr(result, "error", None) or ""
                    if err_detail:
                        self._logger.warning("  失败详情: %s", err_detail)
                    ec = getattr(result, "error_code", None)
                    if ec:
                        self._logger.warning("  错误代码: %s", ec)
                    self.sig_step.emit(step_config.id, "Fail")

                    failure_policy = (getattr(step_config, "on_failure", None) or "fail").lower()
                    if failure_policy in ("continue", "skip"):
                        self._logger.warning(
                            "步骤失败且 YAML on_failure=%s：继续执行后续步骤（如 MesEnd）",
                            failure_policy,
                        )
                        continue

                    mes_uploaded = self._run_mes_end_after_failure(
                        steps=steps,
                        failed_step_id=step_config.id,
                        failed_step_name=step_config.name,
                        failed_result=result,
                    )
                    if mes_uploaded:
                        self._logger.info("已执行 MesEnd 失败上报，停止后续步骤")
                    else:
                        with self._lock:
                            _tm = self._test_mode
                        if _tm == "debug":
                            self._logger.info("调试模式：不上报 MES，已停止后续步骤")
                        else:
                            self._logger.info(
                                "产线：已停止后续步骤（失败直跳 MesEnd 未执行、无 mes.upload_result 或为单步模式）"
                            )
                    self._cleanup_connections(abnormal_exit=True)
                    break
                
            except Exception as e:
                self._logger.error(f"步骤执行异常: {e}")
                self.sig_step.emit(step_config.id, "Fail")

                ex_result = StepResult(
                    passed=False,
                    message=f"步骤执行异常: {step_config.name}",
                    error=str(e),
                )
                try:
                    if hasattr(self.context, "set_result"):
                        self.context.set_result(step_config.id, ex_result)
                    else:
                        self.context.set_data(f"{step_config.id}_result", ex_result)
                        self.context.set_data(step_config.id, ex_result)
                    self.context.set_data(f"{step_config.id}_passed", False)
                except Exception as persist_ex:  # noqa: BLE001
                    self._logger.warning("写入异常步骤结果到上下文失败: %s", persist_ex)
                self.sig_step_result.emit(step_config.id, ex_result)

                failure_policy = (getattr(step_config, "on_failure", None) or "fail").lower()
                if failure_policy in ("continue", "skip"):
                    self._logger.warning(
                        "步骤异常且 YAML on_failure=%s：继续执行后续步骤",
                        failure_policy,
                    )
                    continue

                mes_uploaded = self._run_mes_end_after_failure(
                    steps=steps,
                    failed_step_id=step_config.id,
                    failed_step_name=step_config.name,
                    failed_result=ex_result,
                )
                if mes_uploaded:
                    self._logger.info("已执行 MesEnd 失败上报，停止后续步骤")
                else:
                    with self._lock:
                        _tm = self._test_mode
                    if _tm == "debug":
                        self._logger.info("调试模式：不上报 MES，已停止后续步骤")
                    else:
                        self._logger.info(
                            "产线：步骤异常，已停止后续步骤（失败直跳 MesEnd 未执行、无 mes.upload_result 或为单步模式）"
                        )
                self._cleanup_connections(abnormal_exit=True)
                break
        
        # 测试完成，清理连接（正常跑完一轮，不做 PLC 失败下电写）
        self._cleanup_connections(abnormal_exit=False)

        # 结束一轮执行时进度拉满，避免失败提前退出时界面长期停在例如 92%
        self.sig_progress.emit(100)

        with self._lock:
            self._start_from_step = None
            self._run_single_step_only = False

        self.sig_status.emit("Completed")
        self._running = False
        self._logger.info("所有测试步骤执行完成")

    def _run_mes_end_after_failure(
        self,
        steps: List[Any],
        failed_step_id: str,
        failed_step_name: str,
        failed_result: StepResult,
    ) -> bool:
        """失败后立即执行 MesEnd 上传 FAIL（仅产线模式；调试模式不应调用本函数）。"""
        with self._lock:
            if self._test_mode == "debug":
                self._logger.info("调试模式：跳过失败直跳 MesEnd（不上报 MES）")
                return False
            if self._run_single_step_only:
                self._logger.info("单步模式：跳过失败直跳 MesEnd（不上报 MES）")
                return False
        try:
            mes_end_cfg = next((s for s in steps if getattr(s, "type", "") == "mes.upload_result"), None)
            if not mes_end_cfg:
                self._logger.warning("未找到 mes.upload_result 步骤，无法执行失败直跳上报")
                return False

            params = dict(getattr(mes_end_cfg, "params", {}) or {})
            params["prompt_overall_result"] = False
            err = getattr(failed_result, "error", None) or getattr(failed_result, "message", "") or "测试失败"
            err_line = f"{failed_step_id}({failed_step_name}) 失败: {err}"
            burnin_src = str(params.get("overall_result_source", "") or "").strip().lower()
            burnin_key = str(
                params.get("burnin_outcome_context_key", "pvt_hub_burnin_outcome") or "pvt_hub_burnin_outcome"
            ).strip()
            burnin_oc = str(self.context.get_data(burnin_key) or "").strip().lower() if self.context else ""
            raw_required = params.get("required_pass_step_ids") or params.get("must_pass_step_ids")
            required_ids: set[str] = set()
            if isinstance(raw_required, str):
                required_ids = {s.strip() for s in raw_required.split(",") if s.strip()}
            elif isinstance(raw_required, (list, tuple)):
                required_ids = {str(x).strip() for x in raw_required if str(x).strip()}
            required_failed = failed_step_id in required_ids if required_ids else False
            if burnin_src == "burnin" and burnin_oc == "ok" and not required_failed:
                params["overall_result"] = "PASS"
                params["error_message"] = f"煲机无异常；但 {err_line}"
                self._logger.info(
                    "失败直跳 MesEnd：煲机结果为 ok，按 PASS 上报并附带失败步骤说明"
                )
            else:
                params["overall_result"] = "FAIL"
                params["error_message"] = err_line

            self._logger.info(
                "失败直跳 MesEnd：step=%s(%s)，error=%s",
                failed_step_id,
                failed_step_name,
                err,
            )
            self.sig_step.emit(mes_end_cfg.id, "Running")
            _mes_gap = getattr(mes_end_cfg, "retry_interval_ms", None)
            if _mes_gap is None:
                _mes_gap = 1000
            mes_step = create_step(
                step_type=mes_end_cfg.type,
                step_id=mes_end_cfg.id,
                step_name=mes_end_cfg.name,
                timeout=mes_end_cfg.timeout,
                retries=mes_end_cfg.retries,
                on_failure=mes_end_cfg.on_failure,
                retry_interval_ms=int(_mes_gap),
            )
            if not mes_step:
                self._logger.error("失败直跳 MesEnd 失败：无法创建 mes.upload_result 实例")
                self.sig_step.emit(mes_end_cfg.id, "Fail")
                return False

            mes_result = mes_step.run(self.context, params)
            self.context.set_result(mes_end_cfg.id, mes_result)
            self.sig_step_result.emit(mes_end_cfg.id, mes_result)
            self.sig_step.emit(mes_end_cfg.id, "Pass" if mes_result.passed else "Fail")
            if mes_result.passed:
                self._logger.info("失败直跳 MesEnd 成功")
            else:
                self._logger.warning("失败直跳 MesEnd 失败: %s", getattr(mes_result, "error", ""))
            return True
        except Exception as ex:  # noqa: BLE001
            self._logger.error(f"失败直跳 MesEnd 异常: {ex}")
            return False

    def _check_stop(self) -> bool:
        with self._lock:
            return self._should_stop
    
    def _cleanup_connections(self, abnormal_exit: bool = False) -> None:
        """清理所有连接，包括 PCAN/CAN/PLC/Modbus 连接。

        abnormal_exit 为 True 时：若仍存在 plc_modbus 且本序列使用过 PLC 连接，则先按
        variables.plc_shutdown_on_failure 或 station 默认表写入下电，再断开。
        """
        try:
            if not self.context:
                return

            # PCAN（pcan_comm）：connect 失败时也可能已注册实例，必须 Uninitialize 并移除，否则下次 PCAN_ERR_CONNECT_FAILED
            pcan_comm = self.context.get_comm_driver("pcan_comm")
            if pcan_comm:
                try:
                    self._logger.info("测试失败或结束，正在断开PCAN连接...")
                    _safe_shutdown_pcan_comm(pcan_comm, self._logger.warning)
                    self.context.remove_comm_driver("pcan_comm")
                    self.context.set_state("pcan_connected", False)
                    self._logger.info("PCAN连接已断开")
                except Exception as e:
                    self._logger.warning(f"断开PCAN连接时出错: {e}")
                    self.context.remove_comm_driver("pcan_comm")
                    self.context.set_state("pcan_connected", False)

            # 检查是否有CAN连接
            can_sender = self.context.get_comm_driver("can_bus")
            if can_sender:
                try:
                    self._logger.info("测试失败或结束，正在断开CAN连接...")
                    can_sender.disconnect()
                    self.context.remove_comm_driver("can_bus")
                    self.context.set_state("can_connected", False)
                    self._logger.info("CAN连接已断开")
                except Exception as e:
                    self._logger.warning(f"断开CAN连接时出错: {e}")
                    # 即使出错也清理状态，避免下次误判为仍然已连接
                    self.context.remove_comm_driver("can_bus")
                    self.context.set_state("can_connected", False)
            
            # 检查是否有PLC Modbus连接
            plc_client = self.context.get_comm_driver("plc_modbus")
            if plc_client:
                try:
                    if (
                        abnormal_exit
                        and self._sequence
                        and sequence_uses_plc_modbus_rtu(self._sequence.steps)
                    ):
                        specs = resolve_plc_shutdown_write_specs(
                            self._sequence, self.context
                        )
                        if specs:
                            self._logger.info(
                                "异常退出：在断开 PLC 前执行安全下电写入（%s 项）",
                                len(specs),
                            )
                            apply_plc_shutdown_writes(
                                plc_client, self.context, specs
                            )
                        else:
                            self._logger.info(
                                "异常退出：序列含 PLC 但未解析到下电写入项"
                                "（可在 variables 中设置 plc_shutdown_on_failure，"
                                "或确认 metadata.station 是否匹配内置表）"
                            )
                    self._logger.info("测试失败或结束，正在断开PLC连接...")
                    plc_client.close()
                    self.context.remove_comm_driver("plc_modbus")
                    self.context.set_state("plc_modbus_connected", False)
                    self.context.remove_state("plc_modbus_port")
                    self._logger.info("PLC连接已断开")
                    # Windows USB 转串口常在 close 后需短暂时间才真正释放，立即再开易 WinError 31
                    if sys.platform == "win32":
                        time.sleep(0.35)
                except Exception as e:
                    self._logger.warning(f"断开PLC连接时出错: {e}")
                    # 即使出错也清理状态
                    self.context.remove_comm_driver("plc_modbus")
                    self.context.set_state("plc_modbus_connected", False)
                    self.context.remove_state("plc_modbus_port")
                    if sys.platform == "win32":
                        time.sleep(0.35)
            
            # 检查是否有其他Modbus连接（TCP方式）
            modbus_client = self.context.get_comm_driver("modbus")
            if modbus_client:
                try:
                    self._logger.info("测试失败或结束，正在断开Modbus连接...")
                    modbus_client.close()
                    self.context.remove_comm_driver("modbus")
                    self.context.set_state("modbus_connected", False)
                    self.context.remove_state("modbus_ip")
                    self.context.remove_state("modbus_port")
                    self._logger.info("Modbus连接已断开")
                except Exception as e:
                    self._logger.warning(f"断开Modbus连接时出错: {e}")
                    # 即使出错也清理状态
                    self.context.remove_comm_driver("modbus")
                    self.context.set_state("modbus_connected", False)
                    self.context.remove_state("modbus_ip")
                    self.context.remove_state("modbus_port")
                    
        except Exception as e:
            self._logger.error(f"清理连接时出错: {e}")


