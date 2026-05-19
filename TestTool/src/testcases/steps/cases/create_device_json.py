"""
创建 device.json 文件测试用例

功能：
1. 从前面步骤的结果中提取数据（imei, sn）
2. 从 Config/config.yaml device_json 读取出厂版本（可被步骤参数覆盖；不参与版本比对）
3. 生成 device.json 文件
4. 保存到 Result/upload/${sn}/device.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ...base import BaseStep, StepResult
from ...context import Context


def _resolve_config_path(config_path: str) -> Optional[Path]:
    candidates = [
        Path(config_path),
        Path(__file__).resolve().parents[4] / config_path,
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _load_factory_versions_from_config(
    config_path: str = "Config/config.yaml",
) -> Tuple[str, str]:
    """从 config.yaml 的 device_json 节点读取出厂版本（非 versions，不参与 compare_version）。"""
    cfg_file = _resolve_config_path(config_path)
    if cfg_file is None:
        return "", ""

    try:
        from ....config.service import ConfigService

        root = ConfigService(str(cfg_file)).load()
        device_json_cfg = getattr(root, "device_json", None)
        if device_json_cfg is None:
            return "", ""
        download = str(getattr(device_json_cfg, "factory_download_version", "") or "").strip()
        install = str(getattr(device_json_cfg, "factory_install_version", "") or "").strip()
        return download, install
    except Exception:
        return "", ""


class CreateDeviceJsonStep(BaseStep):
    """创建 device.json 文件测试用例"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行创建 device.json 文件

        参数：
        - imei_step_id: 读取 IMEI 的步骤ID（默认 "step_4"）
        - output_dir: 输出目录（默认 "Result/upload"）
        - config_path: 版本配置文件（默认 "Config/config.yaml"）
        - factory_download_version: 覆盖 config 中 device_json.factory_download_version
        - factory_install_version: 覆盖 config 中 device_json.factory_install_version

        从前面步骤提取的数据：
        - imei: 从读取 IMEI 的步骤响应中提取
        - sn: 从上下文获取（通过 ctx.get_sn()）
        """
        try:
            imei_step_id = params.get("imei_step_id", "step_4")
            output_dir = params.get("output_dir", "Result/upload")
            config_path = str(params.get("config_path", "Config/config.yaml") or "Config/config.yaml")

            ctx.log_info("开始创建 device.json 文件")

            sn = ctx.get_sn()
            if not sn or sn == "NULL":
                return self.create_failure_result(
                    "无法获取SN，请确保已执行扫描SN步骤",
                    error="SN为空",
                )

            ctx.log_info(f"获取SN: {sn}")

            factory_download, factory_install = _load_factory_versions_from_config(config_path)
            param_dl = params.get("factory_download_version")
            param_in = params.get("factory_install_version")
            if param_dl is not None and str(param_dl).strip():
                factory_download = str(param_dl).strip()
            if param_in is not None and str(param_in).strip():
                factory_install = str(param_in).strip()

            if not factory_download or not factory_install:
                return self.create_failure_result(
                    "出厂版本未配置：请在「配置 → 版本配置」中填写 device.json 的 "
                    "出厂下载/安装版本，"
                    "或在步骤参数中指定 factory_download_version / factory_install_version",
                    error="FACTORY_VERSION_MISSING",
                )

            ctx.log_info(
                f"出厂版本: factoryDownloadVersion={factory_download}, "
                f"factoryInstallVersion={factory_install}"
            )

            imei_step_result = None
            imei_step_data: Dict[str, Any] = {}

            try:
                if hasattr(ctx, "get_result"):
                    imei_step_result = ctx.get_result(imei_step_id)

                if not imei_step_result:
                    imei_step_result = ctx.get_data(f"{imei_step_id}_result")

                if not imei_step_result:
                    imei_step_result = ctx.get_data(imei_step_id)

                if not imei_step_result and hasattr(ctx, "state"):
                    imei_step_result = ctx.state.get(f"{imei_step_id}_result") or ctx.state.get(
                        imei_step_id
                    )

                if imei_step_result:
                    if hasattr(imei_step_result, "data"):
                        imei_step_data = imei_step_result.data or {}
                    elif isinstance(imei_step_result, dict):
                        imei_step_data = imei_step_result
            except Exception as e:  # noqa: BLE001
                ctx.log_warning(f"获取步骤结果时发生异常: {e}", exc_info=True)

            imei = ""
            if imei_step_data and isinstance(imei_step_data, dict):
                imei = (
                    imei_step_data.get("imei", "")
                    or imei_step_data.get("imeiNumber", "")
                )
                if not imei:
                    response_obj = imei_step_data.get("response", {})
                    if isinstance(response_obj, dict):
                        data_value = response_obj.get("data")
                        if isinstance(data_value, dict):
                            imei = data_value.get("imei", "") or data_value.get("imeiNumber", "")
                        elif isinstance(data_value, str):
                            try:
                                parsed_data = json.loads(data_value)
                                if isinstance(parsed_data, dict):
                                    imei = parsed_data.get("imei", "") or parsed_data.get(
                                        "imeiNumber", ""
                                    )
                            except Exception:
                                pass
                if not imei:
                    response_data = imei_step_data.get("response_data", "")
                    if isinstance(response_data, str):
                        try:
                            parsed_data = json.loads(response_data)
                            if isinstance(parsed_data, dict):
                                imei = parsed_data.get("imei", "") or parsed_data.get(
                                    "imeiNumber", ""
                                )
                        except Exception:
                            if response_data.strip():
                                imei = response_data.strip()

            if not imei:
                ctx.log_warning("无法从步骤结果中提取 IMEI，使用 UNKNOWN")
                imei = "UNKNOWN"

            ctx.set_data("imei", imei)
            ctx.log_info(f"已写入上下文变量 context.imei={imei}")

            if len(sn) < 7:
                return self.create_failure_result(
                    f"SN长度不足，无法按规则生成name: {sn}",
                    error="SN长度必须至少为7位",
                )

            alias_name = f"大头{sn[6]}{sn[-7:]}"

            device_data = [
                {
                    "snNumber": sn,
                    "imeiNumber": imei,
                    "name": f"pvt{sn[6]}{sn[-7:]}",
                    "parentId": "vbotPVTsample",
                    "deviceType": "direct",
                    "alias": alias_name,
                    "factoryDownloadVersion": factory_download,
                    "factoryInstallVersion": factory_install,
                    "description": f"Vita robot pvt no.{sn}",
                    "status": "1",
                    "linkStatus": "offline",
                }
            ]

            output_path = Path(output_dir) / sn
            output_path.mkdir(parents=True, exist_ok=True)

            json_file_path = output_path / "device.json"
            with open(json_file_path, "w", encoding="utf-8") as f:
                json.dump(device_data, f, ensure_ascii=False, indent=2)

            ctx.log_info(f"device.json 文件已创建: {json_file_path}")

            result_data = {
                "file_path": str(json_file_path),
                "imei": imei,
                "sn": sn,
                "factoryDownloadVersion": factory_download,
                "factoryInstallVersion": factory_install,
            }

            return self.create_success_result(
                result_data,
                f"device.json 文件创建成功: {json_file_path}",
            )

        except Exception as e:  # noqa: BLE001
            ctx.log_error(f"创建 device.json 文件异常: {e}", exc_info=True)
            return self.create_failure_result(
                f"创建 device.json 文件异常: {e}",
                error=str(e),
            )
