"""
华勤 QMES 适配器实现。

参考《QMES接口规范之设备接口规范V4.0》：
- MesInit
- MesStart3
- MesEnd2
- MesUnInit
"""

from __future__ import annotations

import ctypes
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import aiohttp

from .base import MESAdapter
from ..models import MESConfig, MESResponse, TestResult, WorkOrder, WorkOrderStatus

logger = logging.getLogger(__name__)


class HuaqinQMESAdapter(MESAdapter):
    """华勤 QMES 适配器。"""

    def __init__(self) -> None:
        super().__init__("huaqin_qmes")
        self._dll: Optional[ctypes.CDLL] = None
        self._h_mes = ctypes.c_void_p(0)
        self._mes_callback = None
        self._dll_path_loaded: Optional[str] = None

    # ---------------- DLL mode (QMES 文档标准流程) ----------------
    def _resolve_dll_path(self, config: MESConfig) -> Optional[Path]:
        raw = str(self._value(config, "dll_path", "") or "").strip()
        if not raw:
            return None
        p = Path(raw)
        if p.is_absolute():
            return p if p.exists() else None
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            # PyInstaller 6+：数据文件在 exe 同级的 _internal 下，_MEIPASS 指向该目录
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                candidates.append(Path(meipass).resolve() / raw)
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / raw)
        candidates.extend(
            [
                Path.cwd() / raw,
                Path(__file__).resolve().parents[4] / raw,
            ]
        )
        for c in candidates:
            if c.exists():
                return c
        return None

    def _ensure_dll_loaded(self, config: MESConfig) -> Optional[str]:
        dll_path = self._resolve_dll_path(config)
        if dll_path is None:
            return "未找到 HQMES.dll，请检查 credentials.dll_path"
        dll_path_str = str(dll_path.resolve())
        if self._dll is not None and self._dll_path_loaded == dll_path_str:
            return None
        try:
            self._dll = ctypes.CDLL(dll_path_str)
            self._dll_path_loaded = dll_path_str

            # 按文档/C# demo：MESBackFunc(StringBuilder data)，回调约定为 Cdecl
            cb_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_char))

            def _cb(_data):
                return 0

            self._mes_callback = cb_t(_cb)

            self._dll.MesInit.argtypes = [
                cb_t,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_char),
                ctypes.POINTER(ctypes.c_int),
            ]
            self._dll.MesInit.restype = ctypes.c_int

            self._dll.MesStart.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_char),
                ctypes.POINTER(ctypes.c_int),
            ]
            self._dll.MesStart.restype = ctypes.c_int

            self._dll.MesStart2.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_char),
                ctypes.POINTER(ctypes.c_int),
            ]
            self._dll.MesStart2.restype = ctypes.c_int

            self._dll.MesStart3.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_char),
                ctypes.POINTER(ctypes.c_int),
            ]
            self._dll.MesStart3.restype = ctypes.c_int

            self._dll.MesEnd.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_char),
                ctypes.POINTER(ctypes.c_int),
            ]
            self._dll.MesEnd.restype = ctypes.c_int

            self._dll.MesEnd2.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_char),
                ctypes.POINTER(ctypes.c_int),
            ]
            self._dll.MesEnd2.restype = ctypes.c_int

            self._dll.MesUnInit.argtypes = [ctypes.c_void_p]
            self._dll.MesUnInit.restype = ctypes.c_int
            return None
        except Exception as exc:  # noqa: BLE001
            self._dll = None
            return f"加载HQMES.dll失败: {exc}"

    @staticmethod
    def _to_bytes(text: Any) -> bytes:
        return str(text or "").encode("utf-8", errors="ignore")

    @staticmethod
    def _decode_buf(raw: bytes) -> str:
        payload = raw.split(b"\x00", 1)[0]
        if not payload:
            return ""
        for enc in ("utf-8", "gb18030", "gbk", "latin1"):
            try:
                return payload.decode(enc)
            except Exception:  # noqa: BLE001
                continue
        return payload.decode("latin1", errors="ignore")

    def _dll_call(self, fn_name: str, *args, info_len: int = 102400) -> Tuple[int, str]:
        if self._dll is None:
            return -1, "DLL未加载"
        buf = ctypes.create_string_buffer(info_len)
        c_len = ctypes.c_int(info_len)
        fn = getattr(self._dll, fn_name)
        ret = int(fn(*args, buf, ctypes.byref(c_len)))
        text = self._decode_buf(bytes(buf))
        return ret, text

    def _dll_json_response(self, ret: int, s_info: str, op_name: str) -> MESResponse:
        parsed = self._parse_json_value(s_info)
        data = parsed if parsed is not None else {"raw": s_info}
        success, message, normalized_data = self._normalize_qmes_response(data)
        # DLL层返回0为函数调用成功；业务成功由 H_RET/code 判定
        final_success = (ret == 0) and success
        final_message = message or (f"{op_name}成功" if final_success else f"{op_name}失败")
        if not final_success:
            # 某些 DLL 会在失败时返回空/无效 JSON，避免误显示 "Success"
            if str(final_message).strip().lower() == "success":
                final_message = f"{op_name}失败"
            final_message = f"{final_message} (ret={ret})"
            if isinstance(normalized_data, dict) and s_info and "raw" not in normalized_data:
                normalized_data["raw"] = s_info
        return MESResponse(
            success=final_success,
            status_code=200 if final_success else 500,
            data=normalized_data,
            message=final_message,
            error_code=None if final_success else str(ret),
        )

    def _get_port_suffix(self, port: str) -> str:
        p = str(port or "").strip().lower()
        if p in {"porta", "a"}:
            return "porta"
        if p in {"portb", "b"}:
            return "portb"
        return ""

    def _value_by_port(self, config: MESConfig, base_key: str, port: str, default: Any) -> Any:
        suffix = self._get_port_suffix(port)
        if suffix:
            v = self._value(config, f"{base_key}_{suffix}", None)
            if v not in (None, ""):
                return v
        return self._value(config, base_key, default)

    def _is_helper_json_mode(self, config: MESConfig) -> bool:
        mode = str(self._value(config, "transport_mode", "") or "").strip().lower()
        return mode == "meshelper_json"

    def _action_name_start(self, config: MESConfig) -> str:
        raw = self._value(config, "action_name", "")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return str(config.station_id or "").strip()

    def _action_name_upload(self, config: MESConfig) -> str:
        raw = self._value(config, "upload_action_name", "")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return self._action_name_start(config)

    async def authenticate(self, config: MESConfig) -> MESResponse:
        """映射 QMES MesInit（严格文档流程：仅DLL）。"""
        dll_err = self._ensure_dll_loaded(config)
        if dll_err is not None or self._dll is None:
            return self._create_error_response(dll_err or "HQMES.dll未加载", "MES_DLL_UNAVAILABLE", 500)
        if int(self._h_mes.value or 0) != 0:
            return self._create_success_response(
                {"mes_handle": {"value": int(self._h_mes.value or 0), "hex": hex(int(self._h_mes.value or 0))}},
                "MesInit已完成，复用现有句柄",
            )
        info_len = ctypes.c_int(102400)
        buf = ctypes.create_string_buffer(info_len.value)
        ret = int(
            self._dll.MesInit(
                self._mes_callback,
                ctypes.byref(self._h_mes),
                buf,
                ctypes.byref(info_len),
            )
        )
        s_info = self._decode_buf(bytes(buf))
        rsp = self._dll_json_response(ret, s_info, "MesInit")
        if rsp.is_success():
            handle_val = int(self._h_mes.value or 0)
            body = rsp.data if isinstance(rsp.data, dict) else {}
            body["mes_handle"] = {"value": handle_val, "hex": hex(handle_val)}
            rsp.data = body
        return rsp

    async def get_work_order(self, config: MESConfig, sn: str) -> MESResponse:
        """映射 QMES MesStart/MesStart2/MesStart3（含 helper_json CheckFlow 兼容）。"""
        if not sn:
            return self._create_error_response("SN不能为空", "INVALID_SN", 400)
        if self._dll is None or int(self._h_mes.value or 0) == 0:
            return self._create_error_response("MesStart前需先MesInit成功并持有句柄", "MES_HANDLE_REQUIRED", 500)
        start_api = str(self._value(config, "start_api", "MesStart") or "MesStart").strip().lower()
        action_name = self._action_name_start(config)
        tools_name = self._value(config, "tools_name", "TestTool")
        tools_version = self._value(config, "tools_version", "V1.0")
        tools = f"{tools_name}_{tools_version}"
        sn_type = str(self._value(config, "sn_type", "1") or "1")
        if start_api == "messtart3":
            ext_info_obj = self._parse_json_value(self._value(config, "ext_info", {}))
            ext_info = json.dumps(ext_info_obj or {}, ensure_ascii=False)
            ret, s_info = self._dll_call(
                "MesStart3",
                self._h_mes,
                self._to_bytes(sn),
                self._to_bytes(sn_type),
                self._to_bytes(action_name),
                self._to_bytes(tools),
                self._to_bytes(ext_info),
            )
            return self._dll_json_response(ret, s_info, "MesStart3")
        if start_api == "messtart2":
            ret, s_info = self._dll_call(
                "MesStart2",
                self._h_mes,
                self._to_bytes(sn),
                self._to_bytes(sn_type),
                self._to_bytes(action_name),
                self._to_bytes(tools),
            )
            return self._dll_json_response(ret, s_info, "MesStart2")

        ret, s_info = self._dll_call(
            "MesStart",
            self._h_mes,
            self._to_bytes(sn),
            self._to_bytes(action_name),
            self._to_bytes(tools),
        )
        return self._dll_json_response(ret, s_info, "MesStart")

        start_api = str(self._value(config, "start_api", "MesStart3") or "MesStart3").strip().lower()
        use_start2 = start_api == "messtart2"
        use_start3 = start_api not in {"messtart", "messtart2"}
        helper_mode = self._is_helper_json_mode(config)
        endpoint = self._resolve_endpoint(
            config,
            ("mes_checkflow", "mes_start3", "work_order")
            if helper_mode
            else (("mes_start3", "work_order") if use_start3 else (("mes_start2", "work_order") if use_start2 else ("mes_start", "work_order"))),
            "/mes/checkflow" if helper_mode else ("/mes/start3" if use_start3 else ("/mes/start2" if use_start2 else "/mes/start")),
        )
        action_name = self._action_name_start(config)
        tools_name = self._value(config, "tools_name", "TestTool")
        tools_version = self._value(config, "tools_version", "V1.0")
        payload: Dict[str, Any] = {
            "SN": sn,
            "ActionName": action_name,
            "Tools": f"{tools_name}_{tools_version}",
            "InfoLen": 8192,
        }
        op_name = "MesStart"
        if use_start2 or use_start3:
            sn_type = self._value(config, "sn_type", "1")
            payload["SNType"] = str(sn_type)
            if use_start3:
                ext_info = self._parse_json_value(self._value(config, "ext_info", {}))
                payload["ExtInfo"] = ext_info
                op_name = "MesStart3"
            else:
                op_name = "MesStart2"
        if helper_mode:
            payload = self._build_helper_checkflow_payload(config, sn, payload)
            op_name = "MesCheckFlow"
        return await self._call_qmes(config, endpoint, payload, op_name)

    async def upload_result(self, config: MESConfig, test_result: TestResult) -> MESResponse:
        """映射 QMES MesEnd/MesEnd2（含 helper_json UpdateInfo 兼容）。"""
        if not test_result.sn:
            return self._create_error_response("SN不能为空", "INVALID_SN", 400)
        if self._dll is None or int(self._h_mes.value or 0) == 0:
            return self._create_error_response("MesEnd前需先MesInit成功并持有句柄", "MES_HANDLE_REQUIRED", 500)
        port = str(test_result.port or "")
        use_mes_end = self._should_use_mes_end(test_result)
        action_name = str(self._value_by_port(config, "upload_action_name", port, "") or "").strip()
        if not action_name:
            action_name = str(self._value_by_port(config, "action_name", port, config.station_id or "") or "").strip()
        tools_name = self._value_by_port(config, "tools_name", port, "TestTool")
        tools_version = self._value_by_port(config, "tools_version", port, "V1.0")
        tools = f"{tools_name}_{tools_version}"
        sn_type = str(self._value_by_port(config, "sn_type", port, "1") or "1")
        fail_default = str(self._value_by_port(config, "failure_error_code", port, "1") or "1").strip() or "1"
        if test_result.overall_result.value == "PASS":
            error_code = "0"
        else:
            raw_ec = test_result.metadata.get("error_code") if isinstance(test_result.metadata, dict) else None
            error_code = str(raw_ec).strip() if raw_ec is not None and str(raw_ec).strip() else fail_default

        if use_mes_end:
            err_desc = str(test_result.error_message or "")
            ret, s_info = self._dll_call(
                "MesEnd",
                self._h_mes,
                self._to_bytes(test_result.sn),
                self._to_bytes(action_name),
                self._to_bytes(tools),
                self._to_bytes(error_code),
                info_len=102400,
            )
            return self._dll_json_response(ret, s_info or err_desc, "MesEnd")

        all_data = self._build_all_data(test_result)
        all_data_s = json.dumps(all_data, ensure_ascii=False)
        ret, s_info = self._dll_call(
            "MesEnd2",
            self._h_mes,
            self._to_bytes(test_result.sn),
            self._to_bytes(sn_type),
            self._to_bytes(action_name),
            self._to_bytes(tools),
            self._to_bytes(error_code),
            self._to_bytes(all_data_s),
        )
        return self._dll_json_response(ret, s_info, "MesEnd2")

        use_mes_end = self._should_use_mes_end(test_result)
        helper_mode = self._is_helper_json_mode(config)
        endpoint = self._resolve_endpoint(
            config,
            ("mes_update_info", "mes_end2", "upload")
            if helper_mode
            else (("mes_end", "upload") if use_mes_end else ("mes_end2", "upload")),
            "/mes/update_info" if helper_mode else ("/mes/end" if use_mes_end else "/mes/end2"),
        )
        action_name = self._action_name_upload(config)
        tools_name = self._value(config, "tools_name", "TestTool")
        tools_version = self._value(config, "tools_version", "V1.0")
        fail_default = str(self._value(config, "failure_error_code", "1")).strip() or "1"
        if test_result.overall_result.value == "PASS":
            error_code = "0"
        else:
            raw_ec = test_result.metadata.get("error_code") if isinstance(test_result.metadata, dict) else None
            error_code = str(raw_ec).strip() if raw_ec is not None and str(raw_ec).strip() else fail_default
        error_desc = str(test_result.error_message or "").strip()

        payload: Dict[str, Any] = {
            "SN": test_result.sn,
            "ActionName": action_name,
            "Tools": f"{tools_name}_{tools_version}",
            "ErrorCode": str(error_code),
            "InfoLen": 8192,
        }
        op_name = "MesEnd"
        if not use_mes_end:
            sn_type = self._value(config, "sn_type", "1")
            payload["SNType"] = str(sn_type)
            if error_desc:
                payload["ErrorDesc"] = error_desc
            all_data = self._build_all_data(test_result)
            if error_desc and isinstance(all_data, dict) and not all_data.get("ERROR_MESSAGE"):
                all_data["ERROR_MESSAGE"] = error_desc
            payload["AllData"] = all_data
            op_name = "MesEnd2"
        if helper_mode:
            payload = self._build_helper_update_payload(config, test_result, payload)
            op_name = "MesUpdateInfo"
        return await self._call_qmes(config, endpoint, payload, op_name)

    async def heartbeat(self, config: MESConfig) -> MESResponse:
        """QMES 规范无专用心跳接口，优先使用可配置心跳端点。"""
        heartbeat_endpoint = self._resolve_endpoint(config, ("heartbeat",), "")
        if not heartbeat_endpoint:
            return self._create_success_response(
                {"status": "alive", "mode": "local"},
                "QMES未配置心跳端点，使用本地存活状态",
            )

        try:
            response = await self._post_json(config, heartbeat_endpoint, {})
            self._log_response(response)
            if response.is_success():
                return response
            # QMES 通常无标准 heartbeat 接口；端点失败时降级为本地存活，避免误判阻断测试
            self.logger.warning("心跳端点返回失败，降级为本地存活: %s", response.message)
            return self._create_success_response(
                {"status": "alive", "mode": "fallback_local", "detail": response.message},
                "心跳端点不可用，已降级为本地存活",
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("心跳请求异常，降级为本地存活: %s", exc)
            return self._create_success_response(
                {"status": "alive", "mode": "fallback_local", "detail": str(exc)},
                "心跳请求异常，已降级为本地存活",
            )

    async def get_product_params(self, config: MESConfig, product_number: str) -> MESResponse:
        """产品参数查询。若配置了端点则调用，否则返回空结果。"""
        endpoint = self._resolve_endpoint(config, ("product_params",), "")
        if not endpoint:
            return self._create_success_response({}, "未配置产品参数端点")

        payload = {"ProductNumber": product_number}
        try:
            response = await self._post_json(config, endpoint, payload)
            self._log_response(response)
            return response
        except Exception as exc:  # noqa: BLE001
            self.logger.error("获取产品参数异常: %s", exc)
            return self._create_error_response(f"获取产品参数异常: {exc}", "GET_PRODUCT_PARAMS_EXCEPTION", 500)

    async def uninitialize(self, config: MESConfig) -> MESResponse:
        if self._dll is not None and int(self._h_mes.value or 0) != 0:
            try:
                ret = int(self._dll.MesUnInit(self._h_mes))
                self._h_mes = ctypes.c_void_p(0)
                if ret == 0:
                    return self._create_success_response({"status": "released"}, "MesUnInit成功")
                return self._create_error_response("MesUnInit失败", "MES_UNINIT_FAILED", 500)
            except Exception as exc:  # noqa: BLE001
                return self._create_error_response(f"MesUnInit异常: {exc}", "MES_UNINIT_EXCEPTION", 500)
        endpoint = self._resolve_endpoint(config, ("mes_uninit", "uninit"), "")
        if not endpoint:
            return self._create_success_response({"status": "noop"}, "未配置 MesUnInit 端点")
        try:
            response = await self._post_json(config, endpoint, {})
            self._log_response(response)
            return response
        except Exception as exc:  # noqa: BLE001
            self.logger.error("MesUnInit请求异常: %s", exc)
            return self._create_error_response(f"MesUnInit请求异常: {exc}", "MES_UNINIT_EXCEPTION", 500)

    def parse_work_order(self, response_data: Any) -> Optional[WorkOrder]:
        """解析 MesStart3 返回。"""
        if not isinstance(response_data, dict):
            return None

        data = response_data.get("DATA", {})
        if not isinstance(data, dict):
            data = {}

        station_id = self._pick_first_non_empty(data, ("ActionName", "G_STATION", "Station")) or ""
        wo = self._pick_first_non_empty(data, ("G_CHECKFLOWID", "WorkOrder")) or ""
        product_number = self._pick_first_non_empty(data, ("SettingName", "ProductNumber")) or ""

        return WorkOrder(
            work_order=wo,
            product_number=product_number,
            revision="",
            batch="",
            quantity=1,
            station_id=station_id,
            status=WorkOrderStatus.ACTIVE,
            parameters=data,
            description=response_data.get("H_MSG", ""),
        )

    def parse_product_params(self, response_data: Any) -> Dict[str, Any]:
        """解析产品参数返回。"""
        if isinstance(response_data, dict):
            data = response_data.get("DATA", response_data)
            return data if isinstance(data, dict) else {}
        return {}

    async def _call_qmes(
        self,
        config: MESConfig,
        endpoint: str,
        payload: Dict[str, Any],
        op_name: str,
    ) -> MESResponse:
        self._log_request("POST", endpoint, payload)
        try:
            response = await self._post_json(config, endpoint, payload)
            self._log_response(response)
            if response.is_success():
                return response
            return response
        except Exception as exc:  # noqa: BLE001
            self.logger.error("%s请求异常: %s", op_name, exc)
            return self._create_error_response(f"{op_name}请求异常: {exc}", f"{op_name}_EXCEPTION", 500)

    async def _post_json(self, config: MESConfig, endpoint: str, payload: Dict[str, Any]) -> MESResponse:
        url = self._build_url(config.base_url, endpoint)
        headers = {"Content-Type": "application/json"}
        headers.update(config.headers or {})

        timeout = aiohttp.ClientTimeout(total=max(config.timeout_ms, 100) / 1000.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                body: Any
                try:
                    body = await resp.json(content_type=None)
                except Exception:  # noqa: BLE001
                    body = await resp.text()

                success, message, data = self._normalize_qmes_response(body)
                return MESResponse(
                    success=success and (resp.status < 400),
                    status_code=resp.status,
                    data=data,
                    message=message,
                    request_id=resp.headers.get("X-Request-ID"),
                )

    def _normalize_qmes_response(self, body: Any) -> Tuple[bool, str, Any]:
        """
        兼容多种 QMES/MESHelper 返回格式。

        常见形态：
        - {"ret": 0, "sInfo": {...}}
        - {"code": 0, "data": {...}, "msg": "..."}
        - 直接返回 sInfo JSON
        """
        if isinstance(body, str):
            parsed = self._parse_json_value(body)
            body = parsed if parsed is not None else {"raw": body}

        if not isinstance(body, dict):
            return True, "Success", body

        result_code = self._pick_first_non_empty(body, ("ret", "code", "returnCode", "Result", "result"))
        info = body.get("sInfo", body.get("data", body))
        if isinstance(info, str):
            parsed_info = self._parse_json_value(info)
            if parsed_info is not None:
                info = parsed_info

        message = ""
        if isinstance(info, dict):
            message = self._pick_first_non_empty(info, ("H_MSG", "msg", "message")) or ""
            if result_code is None:
                # QMES规范示例返回体：HEAD.H_RET / HEAD.H_MSG
                head = info.get("HEAD")
                if isinstance(head, dict):
                    result_code = self._pick_first_non_empty(head, ("H_RET",))
                    if not message:
                        message = self._pick_first_non_empty(head, ("H_MSG",)) or ""
        if not message:
            message = self._pick_first_non_empty(body, ("msg", "message")) or "Success"

        if result_code is None:
            return True, message, info

        code_text = str(result_code).strip()
        # QMES常见成功码：00001；兼容部分网关返回0/OK/SUCCESS
        if code_text in {"00001", "1", "01"}:
            return True, message or "Success", info

        try:
            rc = int(code_text)
        except Exception:  # noqa: BLE001
            rc = 0 if code_text.upper() in {"OK", "SUCCESS"} else 1

        return rc == 0, message, info

    def _build_all_data(self, test_result: TestResult) -> Dict[str, Any]:
        all_data: Dict[str, Any] = {
            "OVERALL_RESULT": test_result.overall_result.value,
            "TOTAL_DURATION_MS": test_result.total_duration_ms,
            "STATION_ID": test_result.station_id,
            "PORT": test_result.port,
            "WORK_ORDER": test_result.work_order,
            "PRODUCT_NUMBER": test_result.product_number,
        }

        if test_result.error_message:
            all_data["ERROR_MESSAGE"] = test_result.error_message

        for idx, step in enumerate(test_result.test_steps, start=1):
            key_prefix = f"STEP_{idx}_{step.step_id or 'UNKNOWN'}"
            all_data[f"{key_prefix}_NAME"] = step.step_name
            all_data[f"{key_prefix}_RESULT"] = step.result.value
            if step.actual_value is not None:
                all_data[f"{key_prefix}_ACTUAL"] = step.actual_value
            if step.expected_value is not None:
                all_data[f"{key_prefix}_EXPECTED"] = step.expected_value
            if step.error_message:
                all_data[f"{key_prefix}_ERROR"] = step.error_message

        return all_data

    def _should_use_mes_end(self, test_result: TestResult) -> bool:
        if not isinstance(test_result.metadata, dict):
            return False
        raw = test_result.metadata.get("use_mes_end")
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def _build_helper_checkflow_payload(self, config: MESConfig, sn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        ws = str(payload.get("ActionName", "") or self._action_name_start(config))
        return {
            "HEAD": {
                "H_TOKEN": str(self._value(config, "h_token", "") or ""),
                "H_ACTION": str(self._value(config, "h_action", "") or ""),
            },
            "MAIN": {
                "G_SN": sn,
                "G_SN_TYPE": payload.get("SNType", str(self._value(config, "sn_type", "1"))),
                "G_WS": ws,
                "G_ASSIGN_METHOD": 0,
                "G_ASSIGN_SN": "",
                "G_WOID": "",
                "G_GROUP": str(self._value(config, "op_group", "") or ""),
                "G_OP_LINE": str(self._value(config, "op_line", "") or ""),
                "G_OP_PC": str(self._value(config, "op_pc", "") or ""),
                "G_OP_SHIFT": str(self._value(config, "op_shift", "") or ""),
            },
        }

    def _build_helper_update_payload(self, config: MESConfig, test_result: TestResult, payload: Dict[str, Any]) -> Dict[str, Any]:
        all_data = payload.get("AllData", {})
        if not isinstance(all_data, dict):
            all_data = {}
        ws = str(payload.get("ActionName", "") or self._action_name_upload(config))
        err_code = str(payload.get("ErrorCode", "1") or "1")
        err_desc = str(payload.get("ErrorDesc", test_result.error_message or "") or "")
        return {
            "HEAD": {
                "H_TOKEN": str(self._value(config, "h_token", "") or ""),
                "H_ACTION": str(self._value(config, "h_action", "") or ""),
            },
            "MAIN": {
                "G_SN": test_result.sn,
                "G_SN_TYPE": str(self._value(config, "sn_type", "1")),
                "G_WS": ws,
                "G_WOID": "",
                "G_CHECKID": str(test_result.work_order or ""),
                "G_GROUP": str(self._value(config, "op_group", "") or ""),
                "G_OP_LINE": str(self._value(config, "op_line", "") or ""),
                "G_OP_PC": str(self._value(config, "op_pc", "") or ""),
                "G_OP_SHIFT": str(self._value(config, "op_shift", "") or ""),
                "G_ERROR": [{"G_CODE": err_code, "G_DESC": err_desc}],
                "G_ALL_DATA": all_data,
            },
        }

    def _resolve_endpoint(self, config: MESConfig, keys: Tuple[str, ...], default: str) -> str:
        for key in keys:
            endpoint = (config.endpoints or {}).get(key)
            if endpoint:
                return endpoint
        return default

    def _value(self, config: MESConfig, key: str, default: Any) -> Any:
        if isinstance(config.credentials, dict):
            return config.credentials.get(key, default)
        if hasattr(config.credentials, key):
            value = getattr(config.credentials, key)
            return default if value is None else value
        return default

    @staticmethod
    def _build_url(base_url: str, endpoint: str) -> str:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        return f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    @staticmethod
    def _parse_json_value(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _pick_first_non_empty(source: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[str]:
        for key in keys:
            value = source.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None
