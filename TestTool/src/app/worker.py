"""
Background worker for test execution using the new testcases architecture.

Emits status and progress signals for UI binding.
"""

from __future__ import annotations

import sys
import time
import threading
import logging
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

from PySide6.QtCore import QObject, Signal

# 导入新架构组件
from ..testcases.context import Context
from ..testcases.registry import create_step
from ..testcases.base import StepResult
from ..testcases.simple_config import TestSequenceConfig

# #region agent log
try:
    Path(r"d:\b2test\TestTool-v0.4\.cursor").mkdir(parents=True, exist_ok=True)
    with open(r"d:\b2test\TestTool-v0.4\.cursor\debug.log", "a", encoding="utf-8") as _f:
        _f.write(json.dumps({
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": "H0",
            "location": "src/app/worker.py:module",
            "message": "worker module imported",
            "data": {},
            "timestamp": int(time.time() * 1000),
        }, ensure_ascii=False) + "\n")
except Exception as _e:
    logging.getLogger(__name__).warning("agent debug log write failed: %s", _e)
# #endregion


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
    
    def set_test_mode(self, mode: str) -> None:
        """设置测试模式：'production' 或 'debug'"""
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

    # ---- internal --------------------------------------------------------
    def _run(self) -> None:
        """执行测试序列"""
        if not self._sequence:
            self._logger.error("没有设置测试序列")
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
        
        n = len(steps)
        self._logger.info(f"总共 {n} 个测试步骤")
        
        # 执行步骤
        for idx, step_config in enumerate(steps[start_idx:], start=start_idx + 1):
            if self._check_stop():
                # 用户停止测试，清理连接
                self._cleanup_connections()
                self._running = False
                self.sig_status.emit("Idle")
                self._logger.info("测试被用户停止")
                return
            
            # 暂停检查
            while self._is_paused and not self._should_stop:
                time.sleep(0.05)
            
            # 复测模式下，跳过SN扫描步骤（例如 type 为 scan.sn）
            with self._lock:
                is_retest = self._retest_mode
            if is_retest and getattr(step_config, "type", "") == "scan.sn":
                self._logger.info(
                    "复测模式：跳过SN扫描步骤 %s (%s)，使用上下文中的已有SN",
                    step_config.id,
                    step_config.name,
                )
                self.sig_step.emit(step_config.id, "Skipped")
                self.sig_progress.emit(int(idx * 100 / n))
                continue

            # 执行步骤
            self._logger.info(
                f"执行步骤 {step_config.id}（第 {idx}/{n} 步）: {step_config.name}"
            )
            self.sig_step.emit(step_config.id, "Running")
            
            try:
                # 创建步骤实例
                step_instance = create_step(
                    step_type=step_config.type,
                    step_id=step_config.id,
                    step_name=step_config.name,
                    timeout=step_config.timeout,
                    retries=step_config.retries,
                    on_failure=step_config.on_failure
                )
                
                if not step_instance:
                    self._logger.error(f"无法创建步骤实例: {step_config.type}")
                    self.sig_step.emit(step_config.id, "Fail")
                    continue
                
                # 执行步骤
                result = step_instance.run(self.context, step_config.params)

                # #region agent log
                try:
                    with open(r"d:\b2test\TestTool-v0.4\.cursor\debug.log", "a", encoding="utf-8") as _f:
                        _f.write(json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "H1",
                            "location": "src/app/worker.py:_run",
                            "message": "step executed",
                            "data": {
                                "step_id": step_config.id,
                                "step_type": step_config.type,
                                "passed": getattr(result, "passed", None),
                                "has_set_result": hasattr(self.context, "set_result"),
                                "state_keys_count_before": len(getattr(self.context, "state", {}) or {}),
                            },
                            "timestamp": int(time.time() * 1000),
                        }, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                # #endregion

                # 将步骤结果写入上下文，供后续步骤引用（如 Step 7 读取 Step 6 的 SOC）
                try:
                    if hasattr(self.context, "set_result"):
                        self.context.set_result(step_config.id, result)
                    else:
                        # 兼容：至少写入 state
                        self.context.set_data(f"{step_config.id}_result", result)
                        self.context.set_data(step_config.id, result)
                except Exception as e:  # noqa: BLE001
                    self._logger.warning(f"写入步骤结果到上下文失败: {e}")

                # #region agent log
                try:
                    with open(r"d:\b2test\TestTool-v0.4\.cursor\debug.log", "a", encoding="utf-8") as _f:
                        _f.write(json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "H1",
                            "location": "src/app/worker.py:_run",
                            "message": "step result stored to context",
                            "data": {
                                "step_id": step_config.id,
                                "stored_key_1": f"{step_config.id}_result",
                                "stored_key_2": step_config.id,
                                "state_keys_count_after": len(getattr(self.context, "state", {}) or {}),
                            },
                            "timestamp": int(time.time() * 1000),
                        }, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                # #endregion
                
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
                else:
                    self._logger.warning(
                        f"步骤 {step_config.id}（第 {idx}/{n} 步）: {step_config.name} - 失败: {result.message}"
                    )
                    self.sig_step.emit(step_config.id, "Fail")

                    # 根据测试模式 + 步骤失败策略决定后续行为
                    with self._lock:
                        test_mode = self._test_mode
                    failure_policy = (getattr(step_config, "on_failure", None) or "fail").lower()

                    if test_mode == "production":
                        # 产线模式：步骤失败时优先直跳 MesEnd 上报 FAIL，然后结束本轮
                        mes_uploaded = self._run_mes_end_after_failure(
                            steps=steps,
                            failed_step_id=step_config.id,
                            failed_step_name=step_config.name,
                            failed_result=result,
                        )
                        if mes_uploaded:
                            self._logger.info("产线模式：已执行 MesEnd 失败上报，停止后续步骤")
                            self._cleanup_connections()
                            break

                        # 若未配置 MesEnd，则回退到 on_failure 策略
                        if failure_policy in ("continue", "skip"):
                            self._logger.info(
                                "产线模式：步骤失败但 on_failure=%s，继续执行后续步骤",
                                failure_policy
                            )
                            continue

                        self._logger.info(
                            "产线模式：步骤失败且 on_failure=%s，停止测试",
                            failure_policy
                        )
                        self._cleanup_connections()
                        break
                    else:
                        # Debug模式：继续执行完所有测试，忽略失败策略
                        self._logger.info("Debug模式：测试失败，继续执行后续步骤")
                        continue
                
            except Exception as e:
                self._logger.error(f"步骤执行异常: {e}")
                self.sig_step.emit(step_config.id, "Fail")

                # 根据测试模式 + 步骤失败策略决定异常时的行为
                with self._lock:
                    test_mode = self._test_mode
                failure_policy = (getattr(step_config, "on_failure", None) or "fail").lower()

                if test_mode == "production":
                    # 产线模式：步骤异常时同样优先直跳 MesEnd 上报 FAIL
                    ex_result = StepResult(
                        passed=False,
                        message=f"步骤执行异常: {step_config.name}",
                        error=str(e),
                    )
                    mes_uploaded = self._run_mes_end_after_failure(
                        steps=steps,
                        failed_step_id=step_config.id,
                        failed_step_name=step_config.name,
                        failed_result=ex_result,
                    )
                    if mes_uploaded:
                        self._logger.info("产线模式：已执行 MesEnd 失败上报，停止后续步骤")
                        self._cleanup_connections()
                        break

                    if failure_policy in ("continue", "skip"):
                        self._logger.info(
                            "产线模式：步骤异常但 on_failure=%s，继续执行后续步骤",
                            failure_policy
                        )
                        continue

                    self._logger.info(
                        "产线模式：步骤执行异常且 on_failure=%s，停止测试",
                        failure_policy
                    )
                    self._cleanup_connections()
                    break
                else:
                    # Debug模式：继续执行
                    self._logger.info("Debug模式：步骤执行异常，继续执行后续步骤")
                    continue
        
        # 测试完成，清理连接
        self._cleanup_connections()

        # 结束一轮执行时进度拉满，避免失败提前退出时界面长期停在例如 92%
        self.sig_progress.emit(100)

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
        """失败后立即执行 MesEnd 上传 FAIL。"""
        try:
            mes_end_cfg = next((s for s in steps if getattr(s, "type", "") == "mes.upload_result"), None)
            if not mes_end_cfg:
                self._logger.warning("未找到 mes.upload_result 步骤，无法执行失败直跳上报")
                return False

            params = dict(getattr(mes_end_cfg, "params", {}) or {})
            params["prompt_overall_result"] = False
            params["overall_result"] = "FAIL"
            err = getattr(failed_result, "error", None) or getattr(failed_result, "message", "") or "测试失败"
            params["error_message"] = f"{failed_step_id}({failed_step_name}) 失败: {err}"

            self._logger.info(
                "失败直跳 MesEnd：step=%s(%s)，error=%s",
                failed_step_id,
                failed_step_name,
                err,
            )
            self.sig_step.emit(mes_end_cfg.id, "Running")
            mes_step = create_step(
                step_type=mes_end_cfg.type,
                step_id=mes_end_cfg.id,
                step_name=mes_end_cfg.name,
                timeout=mes_end_cfg.timeout,
                retries=mes_end_cfg.retries,
                on_failure=mes_end_cfg.on_failure,
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
    
    def _cleanup_connections(self) -> None:
        """清理所有连接，包括 PCAN/CAN/PLC/Modbus 连接"""
        try:
            if not self.context:
                return

            # PCAN（pcan_comm）：connect 失败时也可能已注册实例，必须 Uninitialize 并移除，否则下次 PCAN_ERR_CONNECT_FAILED
            pcan_comm = self.context.get_comm_driver("pcan_comm")
            if pcan_comm:
                try:
                    self._logger.info("测试失败或结束，正在断开PCAN连接...")
                    if hasattr(pcan_comm, "pcan") and hasattr(pcan_comm, "channel"):
                        try:
                            pcan_comm.pcan.Uninitialize(pcan_comm.channel)
                        except Exception:
                            pass
                    try:
                        setattr(pcan_comm, "initialized", False)
                    except Exception:
                        pass
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


