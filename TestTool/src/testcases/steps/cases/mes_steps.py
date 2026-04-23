"""
MES related steps for registry-based runner.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from ...base import BaseStep, StepResult
from ...context import Context
from ....config.service import ConfigService
from ....mes.factory import MESFactory
from ....mes.models import MESConfig, TestResult as MESTestResult, TestResultStatus

logger = logging.getLogger(__name__)


class _MESMixin:
    _CTX_MES_CLIENT_KEY = "__mes_client_shared__"
    _CTX_MES_CONFIG_KEY = "__mes_config_shared__"

    def _load_mes_config(self) -> Optional[MESConfig]:
        candidates = [
            Path("Config/config.yaml"),
            Path(__file__).resolve().parents[4] / "Config" / "config.yaml",
        ]
        cfg_path = next((p for p in candidates if p.exists()), None)
        if cfg_path is None:
            return None

        root = ConfigService(str(cfg_path)).load()
        mes_model = root.mes
        if hasattr(mes_model, "model_dump"):
            data = mes_model.model_dump()
        else:
            data = mes_model.dict()
        return MESConfig(**data)

    @staticmethod
    def _run_async(coro):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # noqa: BLE001
                pass
            asyncio.set_event_loop(None)
            loop.close()

    def _get_or_create_mes_client(self, ctx: Context):
        existing_client = ctx.get_data(self._CTX_MES_CLIENT_KEY)
        existing_cfg = ctx.get_data(self._CTX_MES_CONFIG_KEY)
        if existing_client is not None and existing_cfg is not None:
            return existing_client, existing_cfg, None

        config = self._load_mes_config()
        if config is None:
            return None, None, "未找到 MES 配置文件: Config/config.yaml"
        if not config.enabled:
            return None, None, "MES 未启用，请在配置中将 mes.enabled 设为 true"

        factory = MESFactory()
        client = factory.create_client(config)
        ctx.set_data(self._CTX_MES_CLIENT_KEY, client)
        ctx.set_data(self._CTX_MES_CONFIG_KEY, config)
        return client, config, None

    def _with_mes_client(self, ctx: Context, fn):
        client, config, err = self._get_or_create_mes_client(ctx)
        if err:
            return None, err

        async def _runner():
            # 仅首次 connect/authenticate，后续步骤复用同一 client（含DLL句柄）
            if not getattr(client, "_is_authenticated", False):
                connected = await client.connect()
                if not connected:
                    conn_info = getattr(client, "connection_info", None)
                    err = str(getattr(conn_info, "last_error", "") or "").strip()
                    return False, f"MES 连接/认证失败{(': ' + err) if err else ''}"
            self._log_mes_handle(ctx, client)
            result = await fn(client, config)
            return True, result

        ok, result = self._run_async(_runner())
        if not ok:
            return None, result
        return result, None

    @staticmethod
    def _log_mes_handle(ctx: Context, client: Any) -> None:
        """记录当前复用的 MES 句柄值（DLL 模式）。"""
        try:
            adapter = getattr(client, "adapter", None)
            h_mes = getattr(adapter, "_h_mes", None)
            handle_val = int(getattr(h_mes, "value", 0) or 0)
            ctx.log_info(f"MES句柄(复用): value={handle_val}, hex={hex(handle_val)}")
        except Exception:  # noqa: BLE001
            # 非DLL模式或不支持句柄，忽略即可
            pass

    def _close_mes_client(self, ctx: Context) -> None:
        client = ctx.get_data(self._CTX_MES_CLIENT_KEY)
        if client is None:
            return

        async def _runner():
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass

        self._run_async(_runner())
        ctx.remove_state(self._CTX_MES_CLIENT_KEY)
        ctx.remove_state(self._CTX_MES_CONFIG_KEY)

    @staticmethod
    def _ctx_sn(ctx: Context, params: Dict[str, Any]) -> str:
        raw_sn = params.get("sn", "")
        sn = str(raw_sn or "").strip()
        # 支持序列变量表达式（如 ${sn} / ${debug_sn}）
        if sn.startswith("${") and sn.endswith("}"):
            key = sn[2:-1].strip()
            if key:
                resolved = ctx.get_data(key)
                if resolved is not None:
                    sn = str(resolved).strip()
        if sn:
            return sn
        if hasattr(ctx, "get_sn"):
            got = str(ctx.get_sn() or "").strip()
            if got and got != "NULL":
                return got
        return str(getattr(ctx, "sn", "") or "").strip()

    def _mes_effective_station_label(self, mes_cfg: Optional[MESConfig]) -> str:
        """与 QMES 一致：ActionName 优先，否则用工位 station_id。"""
        if mes_cfg is None:
            return ""
        sid = str(getattr(mes_cfg, "station_id", "") or "").strip()
        cred = getattr(mes_cfg, "credentials", None)
        an = ""
        if isinstance(cred, dict):
            an = str(cred.get("action_name", "") or "").strip()
        elif cred is not None:
            an = str(getattr(cred, "action_name", "") or "").strip()
        return an or sid

    def _resolve_mes_placeholders(self, text: str, mes_cfg: Optional[MESConfig]) -> str:
        """解析序列里与 MES 配置相关的占位符（运行时从 Config/config.yaml 读取）。"""
        if not isinstance(text, str):
            return str(text or "")
        raw = text.strip()
        if not raw:
            return ""
        if mes_cfg is None:
            return raw
        sid = str(getattr(mes_cfg, "station_id", "") or "").strip()
        eff = self._mes_effective_station_label(mes_cfg)
        t = raw
        t = t.replace("${mes.effective_station}", eff)
        t = t.replace("${mes.action_name}", eff)
        t = t.replace("${mes.station_id}", sid)
        t = t.replace("${mes_station_id}", sid)
        if "${mes" in t or "${mes_" in t:
            return ""
        return t

    def _resolve_upload_station_id(self, ctx: Context, params: Dict[str, Any]) -> str:
        """上传结果中的 station_id：步骤参数 → 上下文/工单 → MES 配置（与过站 ActionName 一致）→ 默认 FT-1。"""
        mes_cfg = self._load_mes_config()
        raw = params.get("station_id")
        if raw is not None:
            s = str(raw).strip()
            if s:
                resolved = self._resolve_mes_placeholders(s, mes_cfg)
                if resolved and "${mes" not in resolved and "${mes_" not in resolved:
                    return resolved
        sid = str(getattr(ctx, "station", "") or "").strip()
        if sid:
            return sid
        wo = ctx.get_data("mes_work_order")
        if wo is not None:
            w = str(getattr(wo, "station_id", "") or "").strip()
            if w:
                return w
        if mes_cfg is not None:
            eff = self._mes_effective_station_label(mes_cfg)
            if eff:
                return eff
            fallback = str(getattr(mes_cfg, "station_id", "") or "").strip()
            if fallback:
                return fallback
        return "FT-1"

class MESHeartbeatStep(_MESMixin, BaseStep):
    """MES 心跳检测步骤。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        mes_cfg = self._load_mes_config()
        if mes_cfg is None or not bool(getattr(mes_cfg, "enabled", False)):
            return self.create_success_result(
                {"alive": True, "mode": "local_no_mes"},
                "MES未启用，按本地测试跳过心跳",
            )

        def _op(client, _config):
            return client.heartbeat()

        result, err = self._with_mes_client(ctx, _op)
        if err:
            return self.create_failure_result("MES心跳失败", error=err)
        if bool(result):
            return self.create_success_result({"alive": True}, "MES心跳成功")
        return self.create_failure_result("MES心跳失败", error="MES_HEARTBEAT_FAILED")


class MESGetWorkOrderStep(_MESMixin, BaseStep):
    """MES 获取工单步骤。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        sn = self._ctx_sn(ctx, params)
        if not sn:
            return self.create_failure_result("SN为空，无法获取工单", error="SN_EMPTY")

        mes_cfg = self._load_mes_config()
        if mes_cfg is None or not bool(getattr(mes_cfg, "enabled", False)):
            return self.create_success_result(
                {"sn": sn, "mode": "local_no_mes"},
                "MES未启用，按本地测试跳过MesStart/工单获取",
            )

        def _resolve_expected(raw: Any) -> str:
            s = str(raw or "").strip()
            if not s:
                return ""
            return self._resolve_mes_placeholders(s, mes_cfg).strip()

        pre_exp = _resolve_expected(params.get("expected_station", ""))
        pre_sid = _resolve_expected(params.get("station_id", ""))
        expected_station = (pre_exp or pre_sid).strip()

        captured_cfg: Dict[str, Any] = {}

        def _op(client, mes_cfg_inner):
            captured_cfg["station_id"] = str(getattr(mes_cfg_inner, "station_id", "") or "").strip()
            captured_cfg["effective_station"] = self._mes_effective_station_label(mes_cfg_inner)
            return client.get_work_order(sn)

        work_order, err = self._with_mes_client(ctx, _op)
        if err:
            return self.create_failure_result("MES获取工单失败", error=err, data={"sn": sn})
        if work_order is None:
            return self.create_failure_result("MES未返回工单信息", error="WORK_ORDER_EMPTY", data={"sn": sn})

        if not expected_station:
            expected_station = str(
                captured_cfg.get("effective_station", "")
                or captured_cfg.get("station_id", "")
                or getattr(ctx, "station", "")
                or ""
            ).strip()
        else:
            expected_station = str(expected_station).strip()
        actual_station = str(getattr(work_order, "station_id", "") or "").strip()
        if expected_station and actual_station and expected_station != actual_station:
            return self.create_failure_result(
                "当前SN未到目标工站",
                error="STATION_MISMATCH",
                data={
                    "sn": sn,
                    "expected_station": expected_station,
                    "actual_station": actual_station,
                    "work_order": work_order.work_order,
                },
            )

        try:
            ctx.set_data("work_order", work_order.work_order)
            ctx.set_data("product_number", work_order.product_number)
            ctx.set_data("mes_work_order", work_order)
            if hasattr(ctx, "work_order"):
                ctx.work_order = work_order.work_order
            if hasattr(ctx, "product_number"):
                ctx.product_number = work_order.product_number
        except Exception:  # noqa: BLE001
            pass

        return self.create_success_result(
            {
                "sn": sn,
                "work_order": work_order.work_order,
                "product_number": work_order.product_number,
                "station_id": work_order.station_id,
                "parameters": work_order.parameters,
            },
            f"获取工单成功: {work_order.work_order}",
        )


class MESUploadResultStep(_MESMixin, BaseStep):
    """MES 上传结果步骤。"""

    @staticmethod
    def _is_failed_result_obj(value: Any) -> bool:
        """兼容不同结果模型，判断对象是否为失败结果。"""
        try:
            if hasattr(value, "passed"):
                passed = getattr(value, "passed")
                if isinstance(passed, bool):
                    return not passed
            if hasattr(value, "success"):
                success = getattr(value, "success")
                if isinstance(success, bool):
                    return not success
            if isinstance(value, dict):
                if "passed" in value and isinstance(value.get("passed"), bool):
                    return not bool(value.get("passed"))
                if "success" in value and isinstance(value.get("success"), bool):
                    return not bool(value.get("success"))
        except Exception:  # noqa: BLE001
            pass
        return False

    @staticmethod
    def _infer_overall_from_context(ctx: Context) -> str:
        """从上下文中的步骤结果推导总结果。"""
        try:
            state = getattr(ctx, "state", {}) or {}
            for value in state.values():
                if MESUploadResultStep._is_failed_result_obj(value):
                    return "FAIL"
        except Exception:  # noqa: BLE001
            pass
        return "PASS"

    @staticmethod
    def _infer_error_from_context(ctx: Context) -> str:
        """从上下文中的步骤结果提取首个失败原因。"""
        try:
            state = getattr(ctx, "state", {}) or {}
            for key, value in state.items():
                if MESUploadResultStep._is_failed_result_obj(value):
                    msg = str(getattr(value, "error", "") or getattr(value, "message", "") or "").strip()
                    if msg:
                        return f"{key}: {msg}"
        except Exception:  # noqa: BLE001
            pass
        return ""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        sn = self._ctx_sn(ctx, params)
        if not sn:
            return self.create_failure_result("SN为空，无法上传结果", error="SN_EMPTY")
        mes_cfg = self._load_mes_config()
        if mes_cfg is None or not bool(getattr(mes_cfg, "enabled", False)):
            overall_local = str(params.get("overall_result", "PASS") or "PASS").strip().upper()
            if overall_local not in {"PASS", "FAIL", "SKIP", "ERROR"}:
                overall_local = "PASS"
            return self.create_success_result(
                {"sn": sn, "overall_result": overall_local, "mode": "local_no_mes"},
                "MES未启用，按本地测试跳过结果上传",
            )

        if self.get_param_bool(params, "prompt_overall_result", False):
            try:
                from src.app.ui_invoker import invoke_in_gui_pass_fail_choice

                choice = invoke_in_gui_pass_fail_choice(
                    title=self.get_param_str(params, "choice_title", "MES上传结果"),
                    message=self.get_param_str(params, "choice_message", "请选择本次上传为测试通过或失败："),
                    pass_text=self.get_param_str(params, "pass_button_text", "上传成功(PASS)"),
                    fail_text=self.get_param_str(params, "fail_button_text", "上传失败(FAIL)"),
                    cancel_text=self.get_param_str(params, "cancel_button_text", "取消"),
                    allow_cancel=self.get_param_bool(params, "allow_cancel_choice", True),
                    port=str(getattr(ctx, "port", "") or "PortA"),
                )
            except Exception as exc:  # noqa: BLE001
                ctx.log_error(f"MES上传结果选择对话框失败: {exc}")
                return self.create_failure_result("选择上传结果失败", error=str(exc))
            if choice is None:
                ctx.log_warning("用户取消MES上传")
                return self.create_failure_result("已取消MES上传", error="USER_CANCELLED")
            overall = choice
        else:
            raw_overall = str(params.get("overall_result", "PASS") or "PASS").strip()
            if raw_overall in ("${context.result}", "${result}"):
                overall = self._infer_overall_from_context(ctx)
            else:
                overall = raw_overall.upper()

        if overall not in {"PASS", "FAIL", "SKIP", "ERROR"}:
            # 兼容未解析占位符等无效值，按上下文推导
            overall = self._infer_overall_from_context(ctx)
        elif overall == "PASS":
            # 防止误配导致失败结果被上报为 PASS：上下文存在失败时强制 FAIL
            inferred = self._infer_overall_from_context(ctx)
            if inferred == "FAIL":
                overall = "FAIL"

        station_id = self._resolve_upload_station_id(ctx, params)
        port = str(params.get("port", "") or getattr(ctx, "port", "") or "PortA")
        work_order = str(
            params.get("work_order", "")
            or getattr(ctx, "work_order", "")
            or ctx.get_data("work_order", "")
            or ""
        )
        product_number = str(
            params.get("product_number", "")
            or getattr(ctx, "product_number", "")
            or ctx.get_data("product_number", "")
            or ""
        )
        raw_error_message = str(params.get("error_message", "") or "").strip()
        if raw_error_message in ("${context.error_message}", "${error_message}"):
            error_message = self._infer_error_from_context(ctx)
        else:
            error_message = raw_error_message
        # FAIL/ERROR 未显式传入错误描述时，补默认失败原因，避免 MesEnd2 上传空错误信息。
        if not error_message and overall in {"FAIL", "ERROR"}:
            error_message = "测试失败（未提供具体错误信息）"
        use_mes_end = bool(params.get("use_mes_end", False))
        error_code = str(params.get("error_code", "") or "").strip()

        test_result = MESTestResult(
            sn=sn,
            station_id=station_id,
            port=port,
            work_order=work_order,
            product_number=product_number,
            overall_result=TestResultStatus[overall],
            error_message=error_message or None,
            metadata={
                "use_mes_end": use_mes_end,
                **({"error_code": error_code} if error_code else {}),
            },
        )

        def _op(client, _config):
            return client.upload_result(test_result)

        uploaded, err = self._with_mes_client(ctx, _op)
        if err:
            self._close_mes_client(ctx)
            return self.create_failure_result("MES上传结果失败", error=err, data={"sn": sn, "overall_result": overall})
        if bool(uploaded):
            result = self.create_success_result({"sn": sn, "overall_result": overall}, "MES上传结果成功")
            self._close_mes_client(ctx)
            return result
        result = self.create_failure_result(
            "MES上传结果失败",
            error="MES_UPLOAD_FAILED",
            data={"sn": sn, "overall_result": overall},
        )
        self._close_mes_client(ctx)
        return result
