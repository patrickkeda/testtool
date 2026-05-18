"""
Compare efuse=0,sn% readback against the scanned SN in context.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from ...base import BaseStep
from ...context import Context


class CompareEfuseSnStep(BaseStep):
    """Compare SN from a previous efuse read step with ctx SN (or expected_sn param)."""

    _SN_KEYS = ("sn", "SN", "pn", "PN", "serial", "serial_number")

    def run_once(self, ctx: Context, params: Dict[str, Any]):
        efuse_step_id = str(params.get("efuse_step_id", "step_22") or "step_22").strip()
        expected_sn = str(params.get("expected_sn") or ctx.get_sn() or "").strip()
        if not expected_sn:
            return self.create_failure_result(
                "无期望 SN：请先执行 scan.sn 或设置 expected_sn",
                error="EXPECTED_SN_MISSING",
            )

        step_result = self._get_step_result(ctx, efuse_step_id)
        if step_result is None:
            return self.create_failure_result(
                f"未找到 EFUSE 读取步骤结果: {efuse_step_id}",
                error="EFUSE_STEP_RESULT_MISSING",
            )

        actual_sn = self._extract_sn(step_result)
        if not actual_sn:
            return self.create_failure_result(
                f"无法从步骤 {efuse_step_id} 的响应中解析 SN",
                error="EFUSE_SN_PARSE_FAILED",
            )

        expected_norm = self._normalize_sn(expected_sn)
        actual_norm = self._normalize_sn(actual_sn)
        result_data = {
            "efuse_step_id": efuse_step_id,
            "expected_sn": expected_norm,
            "actual_sn": actual_norm,
        }

        if actual_norm != expected_norm:
            message = f"EFUSE SN 校验失败: 期望 {expected_norm}，读取 {actual_norm}"
            ctx.log_error(message)
            return self.create_failure_result(message, error="EFUSE_SN_MISMATCH", data=result_data)

        message = f"EFUSE SN 校验通过: {actual_norm}"
        ctx.log_info(message)
        return self.create_success_result(result_data, message)

    def _get_step_result(self, ctx: Context, step_id: str) -> Any:
        if hasattr(ctx, "get_result"):
            result = ctx.get_result(step_id)
            if result is not None:
                return result
        result = ctx.get_data(f"{step_id}_result")
        if result is not None:
            return result
        return ctx.get_data(step_id)

    def _normalize_sn(self, value: str) -> str:
        return "".join(str(value).split()).upper()

    def _extract_sn(self, step_result: Any) -> Optional[str]:
        for root in self._result_roots(step_result):
            found = self._find_sn_in_object(root)
            if found:
                return found
        return None

    def _result_roots(self, step_result: Any) -> list[Any]:
        roots: list[Any] = []
        if hasattr(step_result, "data"):
            roots.append(step_result.data)
        if isinstance(step_result, dict):
            roots.append(step_result)
        return roots

    def _find_sn_in_object(self, obj: Any, depth: int = 0) -> Optional[str]:
        if depth > 6 or obj is None:
            return None

        if isinstance(obj, str):
            text = obj.strip()
            if self._looks_like_sn(text):
                return text
            try:
                parsed = json.loads(text)
            except Exception:  # noqa: BLE001
                return self._match_sn_in_text(text)
            return self._find_sn_in_object(parsed, depth + 1)

        if isinstance(obj, dict):
            for key in self._SN_KEYS:
                if key in obj:
                    candidate = str(obj[key]).strip()
                    if self._looks_like_sn(candidate):
                        return candidate
            for key in ("data", "response", "response_data", "raw_response", "message"):
                if key in obj:
                    found = self._find_sn_in_object(obj[key], depth + 1)
                    if found:
                        return found
            for value in obj.values():
                found = self._find_sn_in_object(value, depth + 1)
                if found:
                    return found
            return None

        if isinstance(obj, (list, tuple)):
            for item in obj:
                found = self._find_sn_in_object(item, depth + 1)
                if found:
                    return found
        return None

    def _looks_like_sn(self, text: str) -> bool:
        s = self._normalize_sn(text)
        return len(s) == 19 and s.isalnum()

    def _match_sn_in_text(self, text: str) -> Optional[str]:
        for match in re.finditer(r"[A-Za-z0-9]{19}", text):
            candidate = match.group(0)
            if self._looks_like_sn(candidate):
                return candidate
        return None
