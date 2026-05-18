"""
PLC 治具异常下电：在测试中途失败或用户停止、且仍存在 plc_modbus 连接时，按序写入安全线圈/寄存器后再断开。

优先级：
1. variables.plc_skip_auto_shutdown_on_failure 为真 → 不执行任何下电写。
2. variables.plc_shutdown_on_failure 为非空 list → 按条目写入（支持 address / value / use_coil / unit_id）。
3. 否则按 metadata.station 匹配内置默认（与现有 Seq 中正常下电步骤对齐）。
4. 无匹配且无自定义列表 → 跳过（仅断开连接）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .context import Context
from .utils import resolve_placeholders_in_params

def sequence_uses_plc_modbus_rtu(steps: Optional[List[Any]]) -> bool:
    if not steps:
        return False
    for s in steps:
        if getattr(s, "type", "") == "plc.modbus.connect":
            return True
    return False


def _truthy(val: Any) -> bool:
    if val is True:
        return True
    if val is False or val is None:
        return False
    if isinstance(val, (int, float)):
        return val != 0
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "on")


def _normalize_spec(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        addr = raw.get("address")
        val = raw.get("value")
        if addr is None or val is None:
            return None
        use_coil = bool(raw.get("use_coil", False))
        uid = raw.get("unit_id")
        return {
            "address": int(addr),
            "value": int(val),
            "use_coil": use_coil,
            "unit_id": uid,
            "description": str(raw.get("description", "plc_shutdown_on_failure")),
        }
    except (TypeError, ValueError):
        return None


def _station_builtin_shutdown_writes(station: str) -> List[Dict[str, Any]]:
    u = (station or "").strip().upper()
    if not u:
        return []
    # 狗腿：与 Seq「全部下电」一致（2050=1）
    if "DOGLEG" in u:
        return [{"address": 2050, "value": 1, "use_coil": True, "description": "DOGLEG fixture power-off"}]
    # X5 FCT：与 vita-fctx5 步骤 20/21 一致
    if "X5_FCT" in u or u == "X5FCT":
        return [
            {"address": 51, "value": 99, "use_coil": False, "description": "X5 FCT power off"},
            {"address": 53, "value": 99, "use_coil": False, "description": "S100 line off (X5 FCT)"},
        ]
    # S100 FCT：与 vita-fcts100 step_30 一致
    if "S100_FCT" in u or "S100FCT" in u or u == "S100_FCT":
        return [{"address": 84, "value": 99, "use_coil": False, "description": "S100 FCT power off"}]
    # 舵机类：与 vita-servo-id* step_7 一致（2053=0 线圈）
    if "SERVO" in u:
        return [{"address": 2053, "value": 0, "use_coil": True, "description": "Servo PLC power off"}]
    # 狗头治具：与 head 上电相反顺序拉低（2053/2052/2049=0）
    if "HEAD" in u:
        return [
            {"address": 2053, "value": 0, "use_coil": True, "description": "Head power off"},
            {"address": 2052, "value": 0, "use_coil": True, "description": "S100 relay off"},
            {"address": 2049, "value": 0, "use_coil": True, "description": "Cylinder drive release"},
        ]
    return []


def resolve_plc_shutdown_write_specs(sequence: Any, ctx: Context) -> List[Dict[str, Any]]:
    """返回待写入的规格列表（不含占位符解析）。"""
    variables = getattr(sequence, "variables", None) or {}
    if _truthy(variables.get("plc_skip_auto_shutdown_on_failure")):
        return []

    custom = variables.get("plc_shutdown_on_failure")
    if isinstance(custom, list) and custom:
        out: List[Dict[str, Any]] = []
        for item in custom:
            if isinstance(item, dict):
                spec = _normalize_spec(item)
                if spec:
                    out.append(spec)
        return out

    meta = getattr(sequence, "metadata", None)
    station = getattr(meta, "station", "") if meta else ""
    return _station_builtin_shutdown_writes(str(station))


def apply_plc_shutdown_writes(client: Any, ctx: Context, specs: List[Dict[str, Any]]) -> None:
    """在仍连接状态下尽力写入；失败只打日志，不抛异常。"""
    if not client or not specs:
        return

    from .steps.cases.modbus_steps_com import (  # noqa: WPS433 (runtime import avoids cycles at import)
        PYMODBUS_AVAILABLE,
        _check_and_ensure_connection,
    )

    if not PYMODBUS_AVAILABLE:
        ctx.log_warning("[PLC] 失败下电: pymodbus 不可用，跳过写入")
        return

    if not _check_and_ensure_connection(client, ctx):
        ctx.log_warning("[PLC] 失败下电: 连接不可用，跳过写入")
        return

    ctx.log_info(f"[PLC] 异常退出：尝试下电写入 {len(specs)} 项 …")

    for raw in specs:
        try:
            p = resolve_placeholders_in_params(dict(raw), ctx)
            spec = _normalize_spec(p)
            if not spec:
                continue
            address = spec["address"]
            value = spec["value"]
            use_coil = spec["use_coil"]
            uid_raw = spec.get("unit_id")
            if uid_raw is None or uid_raw == "":
                unit_id = int(ctx.get_data("plc_unit_id", 1) or 1)
            else:
                if isinstance(uid_raw, str) and "${" in uid_raw:
                    uid_raw = ctx.get_data("plc_unit_id", 1)
                unit_id = int(uid_raw) if uid_raw is not None else 1
            modbus_address = address - 1
            desc = spec.get("description", "")
            if use_coil:
                coil_val = bool(value) if value in (0, 1) else bool(value)
                try:
                    resp = client.write_coil(modbus_address, coil_val, device_id=unit_id)
                except TypeError:
                    try:
                        resp = client.write_coil(
                            address=modbus_address, value=coil_val, device_id=unit_id
                        )
                    except TypeError:
                        resp = client.write_coil(modbus_address, coil_val, slave=unit_id)
                ok = resp is not None and (not hasattr(resp, "isError") or not resp.isError())
                ctx.log_info(
                    f"[PLC] 失败下电 线圈 YAML地址={address} modbus={modbus_address} value={int(coil_val)} "
                    f"unit={unit_id} ok={ok} {desc}"
                )
            else:
                try:
                    resp = client.write_register(modbus_address, value, device_id=unit_id)
                except TypeError:
                    try:
                        resp = client.write_register(
                            address=modbus_address, value=value, device_id=unit_id
                        )
                    except TypeError:
                        resp = client.write_register(modbus_address, value, slave=unit_id)
                ok = resp is not None and (not hasattr(resp, "isError") or not resp.isError())
                ctx.log_info(
                    f"[PLC] 失败下电 保持寄存器 YAML地址={address} modbus={modbus_address} value={value} "
                    f"unit={unit_id} ok={ok} {desc}"
                )
            try:
                ctx.sleep_ms(80)
            except Exception:
                pass
        except Exception as ex:  # noqa: BLE001
            ctx.log_warning(f"[PLC] 失败下电单项写入异常（继续下一项）: {ex}")
