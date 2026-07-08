"""
校验本机 OTA 升级包 zip 文件名是否包含 config.yaml 中 ota_version 配置的版本特征串。

与 ota_deploy_gui 使用相同的目录扫描规则（PKG_RULES）；路径可由 package_dir 扫描或
步骤参数 / 序列变量显式指定。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from ...base import BaseStep, StepResult
from ...context import Context


def _ota_core_import():
    client_dir = Path(__file__).resolve().parents[4] / "client" / "vita_engineer_client"
    p = str(client_dir)
    if p not in sys.path:
        sys.path.insert(0, p)
    from ota_deploy_core import (  # noqa: WPS433
        merge_ota_cfg,
        validate_ota_package_filenames,
    )

    return merge_ota_cfg, validate_ota_package_filenames


def _parse_bool(raw: Any, default: bool = True) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _resolve_config_path(raw: str) -> Optional[Path]:
    s = (raw or "Config/config.yaml").strip()
    p = Path(s).expanduser()
    if p.is_file():
        return p.resolve()
    root = Path(__file__).resolve().parents[4]
    for c in (root / s, Path.cwd() / s):
        try:
            if c.is_file():
                return c.resolve()
        except OSError:
            continue
    return None


class CheckOtaPackagesStep(BaseStep):
    """检查 OTA 包文件名与配置中 ota_version 是否一致。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        merge_ota_cfg, validate_ota_package_filenames = _ota_core_import()

        config_path = str(params.get("config_path", "Config/config.yaml") or "Config/config.yaml")
        config_file = _resolve_config_path(config_path)
        if config_file is None:
            return self.create_failure_result(
                f"未找到配置文件: {config_path}",
                error="CONFIG_FILE_MISSING",
            )

        try:
            with config_file.open("r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}
        except Exception as exc:  # noqa: BLE001
            return self.create_failure_result(
                f"读取配置失败: {exc}",
                error="CONFIG_LOAD_FAILED",
            )

        expected = config_data.get("ota_version", {}) if isinstance(config_data, dict) else {}
        if not isinstance(expected, dict):
            return self.create_failure_result(
                "config.yaml 中 ota_version 节点无效",
                error="OTA_VERSION_CONFIG_INVALID",
            )

        package_dir = self.get_param_str(params, "package_dir", "").strip()
        cfg = merge_ota_cfg(
            package_dir=package_dir,
            s100_app_path=self.get_param_str(params, "s100_app_path", ""),
            s100_sys_path=self.get_param_str(params, "s100_sys_path", ""),
            x5_app_path=self.get_param_str(params, "x5_app_path", ""),
            x5_sys_path=self.get_param_str(params, "x5_sys_path", ""),
            ota_target_s100=_parse_bool(params.get("ota_target_s100"), True),
            ota_target_x5=_parse_bool(params.get("ota_target_x5"), True),
        )

        ok, err = validate_ota_package_filenames(cfg, expected)
        data = {
            "config_path": str(config_file),
            "expected_ota_version": expected,
            "resolved_packages": {
                k: cfg.get(k)
                for k in (
                    "s100_app_path",
                    "s100_sys_path",
                    "x5_app_path",
                    "x5_sys_path",
                )
                if cfg.get(k)
            },
        }

        if not ok:
            msg = "OTA 包版本校验失败:\n" + err
            ctx.log_error(msg)
            return self.create_failure_result(msg, error="OTA_PACKAGE_VERSION_MISMATCH", data=data)

        ctx.log_info("OTA 包文件名与 ota_version 配置一致")
        for k, v in data["resolved_packages"].items():
            ctx.log_info(f"  {k}: {v}")
        return self.create_success_result(data, "OTA 包版本校验通过")
