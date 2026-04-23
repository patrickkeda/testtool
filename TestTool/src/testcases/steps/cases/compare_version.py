"""
Compare version=0% result against Config/config.yaml versions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from ...base import BaseStep
from ...context import Context
from ..utility.version_payload import normalize_version_payload


class CompareVersionStep(BaseStep):
    """Compare the version payload from a previous step with configured versions."""

    DUAL_KEYS = ("S100", "X5")
    SINGLE_KEYS = ("MOTOR", "SERVO", "UWB", "LIDAR", "BMS")

    def run_once(self, ctx: Context, params: Dict[str, Any]):
        version_step_id = str(params.get("version_step_id", "step_read_version") or "step_read_version")
        config_path = str(params.get("config_path", "Config/config.yaml") or "Config/config.yaml")

        step_result = self._get_step_result(ctx, version_step_id)
        if step_result is None:
            return self.create_failure_result(
                f"未找到版本步骤结果: {version_step_id}",
                error="VERSION_STEP_RESULT_MISSING",
            )

        actual_payload = self._extract_version_payload(step_result)
        if actual_payload is None:
            return self.create_failure_result(
                f"无法解析步骤 {version_step_id} 的版本信息",
                error="VERSION_PAYLOAD_INVALID",
            )

        config_file = self._resolve_config_path(config_path)
        if config_file is None:
            return self.create_failure_result(
                f"未找到版本配置文件: {config_path}",
                error="CONFIG_FILE_MISSING",
            )

        try:
            with config_file.open("r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}
        except Exception as exc:  # noqa: BLE001
            return self.create_failure_result(
                f"读取版本配置失败: {exc}",
                error="CONFIG_LOAD_FAILED",
            )

        expected_versions = config_data.get("versions", {}) if isinstance(config_data, dict) else {}
        if not isinstance(expected_versions, dict):
            return self.create_failure_result(
                "配置文件中的 versions 节点无效",
                error="CONFIG_VERSIONS_INVALID",
            )

        mismatches = self._compare_versions(actual_payload, expected_versions)
        result_data = {
            "version_step_id": version_step_id,
            "config_path": str(config_file),
            "actual_version": actual_payload,
            "expected_version": expected_versions,
            "mismatches": mismatches,
        }

        if mismatches:
            message = "版本比对失败: " + "; ".join(mismatches)
            ctx.log_error(message)
            return self.create_failure_result(message, error="VERSION_MISMATCH", data=result_data)

        message = "版本比对通过"
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

    def _extract_version_payload(self, step_result: Any) -> Optional[Dict[str, Any]]:
        candidates = []
        if hasattr(step_result, "data"):
            candidates.append(step_result.data)
        if isinstance(step_result, dict):
            candidates.append(step_result)

        for item in candidates:
            normalized = self._normalize_with_client_helper(item)
            if normalized is not None:
                return normalized
            payload = self._extract_from_mapping(item)
            if payload is not None:
                return payload
        return None

    def _normalize_with_client_helper(self, raw: Any) -> Optional[Dict[str, Any]]:
        try:
            return normalize_version_payload(raw)
        except Exception:  # noqa: BLE001
            return None

    def _extract_from_mapping(self, data: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(data, dict):
            return self._parse_json_like(data)

        direct_payload = self._normalize_payload(data)
        if direct_payload is not None:
            return direct_payload

        response = data.get("response")
        if isinstance(response, dict):
            response_data = response.get("data")
            nested = self._normalize_payload(response_data)
            if nested is not None:
                return nested
            nested = self._normalize_payload(response)
            if nested is not None:
                return nested

        for key in ("response_data", "raw_response", "data"):
            nested = self._normalize_payload(data.get(key))
            if nested is not None:
                return nested

        return None

    def _normalize_payload(self, raw: Any) -> Optional[Dict[str, Any]]:
        if isinstance(raw, dict):
            if self._looks_like_version_payload(raw):
                return raw
            return None
        return self._parse_json_like(raw)

    def _parse_json_like(self, raw: Any) -> Optional[Dict[str, Any]]:
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except Exception:  # noqa: BLE001
                return None
        if not isinstance(raw, str):
            return None

        text = raw.strip()
        if not text or (not text.startswith("{") and not text.startswith("[")):
            return None

        try:
            parsed = json.loads(text)
        except Exception:  # noqa: BLE001
            return None

        if isinstance(parsed, dict) and self._looks_like_version_payload(parsed):
            return parsed
        return None

    def _looks_like_version_payload(self, data: Dict[str, Any]) -> bool:
        if any(key in data for key in self.DUAL_KEYS):
            return True
        devices = data.get("devices")
        return isinstance(devices, list)

    def _resolve_config_path(self, config_path: str) -> Optional[Path]:
        raw_path = Path(config_path)
        candidates = []
        if raw_path.is_absolute():
            candidates.append(raw_path)
        else:
            candidates.append(Path.cwd() / raw_path)
            candidates.append(Path(__file__).resolve().parents[4] / raw_path)

        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _compare_versions(self, actual: Dict[str, Any], expected: Dict[str, Any]) -> list[str]:
        mismatches: list[str] = []

        for key in self.DUAL_KEYS:
            expected_block = expected.get(key, {})
            actual_block = actual.get(key, {})
            if not isinstance(expected_block, dict):
                continue
            if not isinstance(actual_block, dict):
                actual_block = {}

            for field in ("app_version", "sys_version"):
                expected_value = str(expected_block.get(field, "") or "").strip()
                if not expected_value:
                    continue
                actual_value = str(actual_block.get(field, "") or "").strip()
                if actual_value != expected_value:
                    mismatches.append(
                        f"{key}.{field} 期望 '{expected_value}'，实际 '{actual_value or 'EMPTY'}'"
                    )

        for key in self.SINGLE_KEYS:
            expected_block = expected.get(key, {})
            if not isinstance(expected_block, dict):
                continue
            expected_value = str(expected_block.get("sw_version", "") or "").strip()
            if not expected_value:
                continue

            actual_instances = self._extract_device_instances(actual).get(key, [])
            if not actual_instances:
                mismatches.append(f"{key}.sw_version 期望 '{expected_value}'，实际 'EMPTY'")
                continue

            for inst in actual_instances:
                actual_value = str(inst.get("sw_version", "") or "").strip()
                if actual_value != expected_value:
                    device_id = str(inst.get("device_id", "") or "").strip()
                    name = str(inst.get("name", "") or "").strip()

                    suffix_parts: list[str] = []
                    if device_id:
                        suffix_parts.append(f"id{device_id}")
                    if name:
                        suffix_parts.append(name)

                    suffix = " ".join(suffix_parts)
                    label = f"{key}.sw_version[{suffix}]" if suffix else f"{key}.sw_version"
                    mismatches.append(
                        f"{label} 期望 '{expected_value}'，实际 '{actual_value or 'EMPTY'}'"
                    )

        return mismatches

    def _extract_device_instances(self, data: Dict[str, Any]) -> Dict[str, list[Dict[str, str]]]:
        """
        Extract per-device sw_version for MOTOR/SERVO/UWB/LIDAR/BMS.

        Expected payload structure (observed in logs):
        - data["devices"] is a list of wrappers
        - each wrapper has: { "device_type": "...", "versions": [ { "device_id": ..., "name": ..., "sw_version": ... }, ... ] }

        Important: the payload can contain multiple devices of the same type
        (e.g. 12 motors with different device_id). We must not overwrite them,
        and we must compare sw_version per device_id.
        """
        # result[type][device_id] -> record
        result: Dict[str, Dict[str, Dict[str, str]]] = {}
        devices = data.get("devices", [])
        if not isinstance(devices, list):
            return {}

        for device in devices:
            if not isinstance(device, dict):
                continue

            device_type = str(device.get("device_type", "") or "").upper().strip()
            if device_type not in self.SINGLE_KEYS:
                continue

            versions = device.get("versions", [])
            if not isinstance(versions, list):
                continue

            for item in versions:
                if not isinstance(item, dict):
                    continue
                device_id = str(item.get("device_id", "") or "").strip()
                if not device_id:
                    continue

                name = str(item.get("name", "") or "").strip()
                sw_version = str(item.get("sw_version", "") or "").strip()
                if not sw_version:
                    continue

                type_map = result.setdefault(device_type, {})
                rec = type_map.setdefault(
                    device_id,
                    {
                        "device_id": device_id,
                        "name": name,
                        # Keep an unknown-aware preferred value.
                        "fallback_value": "",
                        "preferred_value": "",
                    },
                )

                if not rec["fallback_value"]:
                    rec["fallback_value"] = sw_version
                if sw_version.lower() != "unknown" and not rec["preferred_value"]:
                    rec["preferred_value"] = sw_version

        # Convert to the expected output shape:
        # { device_type: [ {device_id, name, sw_version}, ... ] }
        out: Dict[str, list[Dict[str, str]]] = {}
        for device_type, type_map in result.items():
            out.setdefault(device_type, [])
            for _, rec in type_map.items():
                sw_version_final = rec["preferred_value"] or rec["fallback_value"]
                out[device_type].append(
                    {
                        "device_id": rec["device_id"],
                        "name": rec["name"],
                        "sw_version": sw_version_final,
                    }
                )

        return out
