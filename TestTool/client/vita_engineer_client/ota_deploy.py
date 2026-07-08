#!/usr/bin/env python3
"""VITA OTA / 文件同步主模块（核心逻辑 + 无头 CLI）。

图形界面见 ``ota_deploy_gui.py``（转发 ``main_gui``）。
产线序列可继续调用 ``ota_deploy_headless.py``（转发 ``main_cli``）。
兼容导入：``ota_deploy_core`` 转发本模块公开符号。
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    import paramiko
except ImportError as e:
    raise ImportError("缺少依赖库 paramiko。请执行: pip install paramiko") from e

# 默认扫描规则（兼容旧逻辑：目录内同时存在加解密包时可能匹配到任意一种）
PKG_RULES = {
    "S100 APP": "*app*s100*.zip",
    "S100 SYS": "*v*.zip",
    "X5 APP": "*app*x5*.zip",
    "X5 SYS": "all_in_one-LNX*.zip",
}

# lifecycle 0–3：未加密；>=4：已加密（与产线 provision 一致）
PKG_RULES_PLAIN: Dict[str, str | tuple[str, ...]] = {
    "S100 APP": "*app*s100*.zip",
    "S100 SYS": "*v*.zip",
    "X5 APP": "*app*x5*.zip",
    "X5 SYS": "all_in_one-LNX*.zip",
}
PKG_RULES_ENCRYPTED: Dict[str, str | tuple[str, ...]] = {
    "S100 APP": "*app*s100*.zip",
    "S100 SYS": ("all_in_one_signed*.zip", "*signed*v*.zip"),
    "X5 APP": "*app*x5*.zip",
    "X5 SYS": "all_in_one-LNX*.zip",
}

# 产线约定：仅 S100 SYS 包名含 signed 表示加密；APP / X5 SYS 无 signed 特征
_S100_SYS_ENCRYPTED_MARK = "signed"
_PLAIN_PKG_EXCLUDE = (_S100_SYS_ENCRYPTED_MARK,)
_ENCRYPTED_PKG_REQUIRE = (_S100_SYS_ENCRYPTED_MARK,)

PROVISION_TOOL = "/usr/hobot/bin/provision_tool"
LIFECYCLE_PROBE_CMD = (
    f"chmod 777 {PROVISION_TOOL} 2>/dev/null; "
    f"{PROVISION_TOOL} --get-lifecycle; "
    "echo __LIFECYCLE_RC__=$?"
)

# 版本校验 SSH 轮询默认上限（25 分钟）
OTA_DEFAULT_VERIFY_TIMEOUT_SEC = 25 * 60

DEFAULT_CONFIG: Dict[str, Any] = {
    "s100_ip": "192.168.126.2",
    "x5_ip": "192.168.127.10",
    "username": "root",
    "password": "root",
    "ota_dir": "/ota",
    "connect_timeout": 5,
    "use_identity_file": False,
    "identity_file": "",
    "ota_target_s100": True,
    "ota_target_x5": True,
    "use_tmux": True,
    "sync_items": [],
    "ota_manifest_encrypted": "",
    "ota_manifest_plain": "",
    # 换台 OTA：开始前清 ARP 并等待 S100 ping 通（产线同 IP 换设备）
    "ota_swap_clear_arp_on_start": True,
    "ota_swap_ping_wait_sec": 90,
    "ota_swap_ping_interval_sec": 3,
    # Hang 恢复：ping 不通或员工手动触发时，尝试 SSH reboot 并等待设备再起
    "ota_hang_recovery_on_ping_fail": True,
    "ota_hang_ssh_probe_sec": 15,
    "ota_hang_post_reboot_wait_sec": 180,
    # 版本校验：reboot 后须稳定再读，且连续多次一致才判通过（避免假阳性）
    "ota_version_stabilize_sec": 45,
    "ota_version_confirm_polls": 3,
    "ota_version_final_recheck_sec": 30,
    "ota_version_clear_arp_before_verify": True,
    # SSH 通过后，经工程服务 version=0 二次校验（与产线序列一致）
    "ota_version_engineer_verify": True,
    "ota_version_engineer_enter_fac": True,
    "ota_version_cross_check_ssh": True,
    "engineer_port": 3579,
    "ota_version_engineer_timeout_sec": 30,
    "ota_version_engineer_retries": 3,
    # 可选 tmux exit 轮询（秒）；0=不等待，直接 SSH 版本校验（推荐）
    "ota_tmux_max_wait_sec": 0,
    # 仅当 ota_tmux_max_wait_sec>0 时生效：读不到 exit 但版本已到位则提前进入校验
    "ota_tmux_version_fallback_sec": 120,
    "ota_tmux_version_fallback_confirm": 2,
    # tmux 非 0 时仍进入版本校验（125=抓 X5 超时，255=常见旧标记）
    "ota_trust_version_over_tmux_exit": True,
    "ota_tmux_suspect_exit_codes": (125, 255),
    # 双板 S100 tmux 内抓 X5 结果的最长秒数（设备侧，非 PC 等待）
    # 建议值：300（5分钟）。X5 reboot 后 S100 最多再等这么久就结束抓取，避免长时间卡住。
    "ota_s100_x5_fetch_max_sec": 300,
    # 非 tmux 前台 ota_tool 单命令超时（秒）
    "ota_foreground_timeout_sec": 3600,
    # 版本校验 SSH 轮询上限（秒）；ota_wait_timeout_sec 为产线序列别名
    "ota_verify_timeout_sec": OTA_DEFAULT_VERIFY_TIMEOUT_SEC,
    "ota_wait_timeout_sec": OTA_DEFAULT_VERIFY_TIMEOUT_SEC,
    # S100 刷写完成后不 SSH/tmux reboot，由产线员工人工上下电后再读版本
    "ota_s100_auto_reboot": False,
    # 版本校验未通过时，最多重新刷写几次（含首次）
    "ota_deploy_max_attempts": 3,
    # 无头模式：等员工关电后 ping 断开的最长秒数
    "ota_manual_power_down_wait_sec": 180,
    # 无头/GUI 确认后：等 S100 再次 ping 通的最长秒数
    "ota_manual_power_cycle_ping_wait_sec": 300,
    # 提示人工上下电前，等待 tmux 刷写写出结果文件的最长秒数
    "ota_wait_flash_before_power_cycle_sec": 3600,
    # ota result 读不到时，若 SSH/version=0 版本已与升级包一致则不再等 X5 result
    "ota_flash_complete_version_fallback": True,
}

CONFIG_FILE = os.path.expanduser("~/.ota_deploy_config.json")

REMOTE_APP_VERSION_FILE = "/app/version_info.txt"
REMOTE_SYS_VERSION_FILE = "/etc/version"
DEFAULT_OTA_VERSION_CONFIG = "Config/config.yaml"
# reboot 后 /tmp 会清空，结果码备份到 /app 供 PC 轮询
OTA_TMUX_RC_PERSIST_PREFIX = "/app/.ota_deploy_rc"

_PATH_KEYS = {
    "S100 APP": "s100_app_path",
    "S100 SYS": "s100_sys_path",
    "X5 APP": "x5_app_path",
    "X5 SYS": "x5_sys_path",
}

# manifest.yaml packages[] → cfg 路径键（domain + type）
_MANIFEST_PKG_KEYS = {
    ("s100", "s100-sys"): "s100_sys_path",
    ("s100", "s100-app"): "s100_app_path",
    ("x5", "x5-sys"): "x5_sys_path",
    ("x5", "x5-app"): "x5_app_path",
}

_REQUIRED_MANIFEST_KEYS = tuple(_MANIFEST_PKG_KEYS.values())


def ota_pkg_storage_key(base_key: str, encrypted: bool) -> str:
    """界面/配置中加密或未加密包路径键，如 s100_app_path_encrypted。"""
    suffix = "encrypted" if encrypted else "plain"
    return f"{base_key}_{suffix}"


def apply_stored_ota_packages(cfg: Dict[str, Any], encrypted: bool) -> bool:
    """将配置里加密/未加密四套路径写入当前 OTA 使用的 s100_app_path 等键。"""
    ok = True
    for base in _REQUIRED_MANIFEST_KEYS:
        stored = str(cfg.get(ota_pkg_storage_key(base, encrypted)) or "").strip()
        if stored and os.path.isfile(stored):
            cfg[base] = stored
        else:
            ok = False
    return ok


def ota_package_set_configured(cfg: Dict[str, Any], encrypted: bool) -> bool:
    """某一类（加密/未加密）升级包是否已配置 manifest 或四套 zip。"""
    if get_configured_ota_manifest(cfg, encrypted):
        return True
    return all(
        str(cfg.get(ota_pkg_storage_key(k, encrypted)) or "").strip()
        and os.path.isfile(str(cfg.get(ota_pkg_storage_key(k, encrypted))))
        for k in _REQUIRED_MANIFEST_KEYS
    )


def dual_board_ota_packages_configured(cfg: Dict[str, Any]) -> bool:
    """双板 OTA 是否已配置加密 + 未加密两套包（manifest 或四套 zip）。"""
    return ota_package_set_configured(cfg, True) and ota_package_set_configured(cfg, False)


def ota_emit_status(cfg: Dict[str, Any], message: str) -> None:
    """可选：GUI 通过 cfg['_status_callback'] 更新状态栏。"""
    cb = cfg.get("_status_callback")
    if not cb:
        return
    try:
        cb(message)
    except Exception:
        pass


def merge_cfg_with_defaults(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """UI/CLI 局部 cfg 与 DEFAULT_CONFIG 合并，保证 OTA 新参数生效。"""
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg or {})
    return merged


def resolve_ota_verify_timeout_sec(
    cfg: Dict[str, Any],
    wait_timeout_sec: Optional[int] = None,
) -> int:
    """版本校验轮询上限，默认 25 分钟。"""
    limit = int(
        cfg.get("ota_verify_timeout_sec")
        or cfg.get("ota_wait_timeout_sec")
        or OTA_DEFAULT_VERIFY_TIMEOUT_SEC
    )
    if wait_timeout_sec is not None:
        limit = min(limit, int(wait_timeout_sec))
    return max(60, limit)


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg.update(saved)
            # 旧版默认阻塞等 tmux 7200s；现以 SSH 版本校验为准，不再长时间等 exit
            if int(cfg.get("ota_tmux_max_wait_sec") or 0) == 7200:
                cfg["ota_tmux_max_wait_sec"] = DEFAULT_CONFIG["ota_tmux_max_wait_sec"]
        except Exception:
            pass
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    import json

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"保存配置失败: {e}")


def _pkg_patterns(rule: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if isinstance(rule, str):
        return (rule,)
    return tuple(rule)


def _zip_name_matches_tokens(name: str, *, exclude: tuple[str, ...], require: tuple[str, ...]) -> bool:
    low = name.lower()
    if exclude and any(tok in low for tok in exclude):
        return False
    if require and not any(tok in low for tok in require):
        return False
    return True


def scan_package_dir(
    directory: str,
    *,
    rules: Optional[Dict[str, str | tuple[str, ...]]] = None,
    exclude_name_tokens: tuple[str, ...] = (),
    require_name_tokens: tuple[str, ...] = (),
    encrypted: Optional[bool] = None,
) -> Dict[str, str]:
    """按规则在目录中选取最新匹配的 zip，返回 cfg 路径键。

    encrypted=True/False 时仅对 S100 SYS 按文件名是否含 signed 过滤；
    其他包（S100 APP / X5）不按 signed 判断。
    """
    out: Dict[str, str] = {}
    if not directory or not os.path.isdir(directory):
        return out
    rule_map = rules or PKG_RULES
    for label, rule in rule_map.items():
        key = _PATH_KEYS[label]
        if encrypted is not None and label == "S100 SYS":
            exclude = () if encrypted else (_S100_SYS_ENCRYPTED_MARK,)
            require = (_S100_SYS_ENCRYPTED_MARK,) if encrypted else ()
        else:
            exclude = exclude_name_tokens if encrypted is None else ()
            require = require_name_tokens if encrypted is None else ()
        matches: List[str] = []
        for pattern in _pkg_patterns(rule):
            for f in os.listdir(directory):
                if not fnmatch.fnmatch(f.lower(), pattern.lower()):
                    continue
                if not _zip_name_matches_tokens(
                    f,
                    exclude=exclude,
                    require=require,
                ):
                    continue
                matches.append(os.path.join(directory, f))
        if matches:
            out[key] = max(set(matches), key=os.path.getmtime)
    return out


def _is_manifest_filename(name: str) -> bool:
    low = name.lower()
    return low == "manifest.yaml" or (
        low.startswith("manifest") and low.endswith((".yaml", ".yml"))
    )


def _yaml_install_hint() -> str:
    exe = getattr(sys, "executable", "python")
    req = Path(__file__).resolve().parent.parent.parent / "requirements.txt"
    if req.is_file():
        return (
            f"{exe} -m pip install pyyaml>=6.0\n"
            f"或: {exe} -m pip install -r {req}"
        )
    return f"{exe} -m pip install pyyaml>=6.0"


def parse_yaml_file(path: str) -> Any:
    """解析 YAML 文件；优先 PyYAML，回退 ruamel.yaml。"""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise RuntimeError(f"无法打开文件: {path} ({exc})") from exc

    try:
        import yaml

        return yaml.safe_load(text) or {}
    except ImportError:
        pass
    except Exception as exc:
        raise RuntimeError(f"YAML 解析失败: {path} ({exc})") from exc

    try:
        from ruamel.yaml import YAML

        loader = YAML(typ="safe")
        return loader.load(text) or {}
    except ImportError as exc:
        raise RuntimeError(
            "未安装 YAML 解析库（PyYAML / ruamel.yaml），无法读取 manifest。\n"
            "请在本机执行:\n"
            f"  {_yaml_install_hint()}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"YAML 解析失败: {path} ({exc})") from exc


def load_ota_manifest(manifest_path: str) -> Dict[str, Any]:
    try:
        doc = parse_yaml_file(manifest_path)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"YAML 解析失败: {manifest_path} ({exc})") from exc
    if not isinstance(doc, dict):
        raise RuntimeError(f"manifest 根节点必须是对象(dict): {manifest_path}")
    if not isinstance(doc.get("packages"), list):
        raise RuntimeError(
            f"manifest 缺少 packages 列表: {manifest_path}；"
            f"请使用与产线一致的 manifest.yaml 格式"
        )
    return doc


def s100_sys_filename_is_encrypted(filename: str) -> bool:
    """仅 S100 SYS 包名含 signed 视为加密包。"""
    return _S100_SYS_ENCRYPTED_MARK in (filename or "").lower()


def manifest_is_encrypted(manifest: Dict[str, Any]) -> bool:
    """根据 manifest 中 type=s100-sys 的 filename 是否含 signed 判断整套是否加密。"""
    packages = manifest.get("packages")
    if not isinstance(packages, list):
        return False
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        ptype = str(pkg.get("type", "") or "").strip().lower()
        if ptype == "s100-sys":
            return s100_sys_filename_is_encrypted(str(pkg.get("filename", "") or ""))
    return False


def discover_ota_manifests(package_dir: str) -> List[str]:
    """在目录及一级子目录中查找 manifest*.yaml。"""
    found: List[str] = []
    if not package_dir or not os.path.isdir(package_dir):
        return found
    root = os.path.abspath(package_dir)

    def _scan_dir(folder: str) -> None:
        try:
            names = os.listdir(folder)
        except OSError:
            return
        for name in names:
            full = os.path.join(folder, name)
            if os.path.isfile(full) and _is_manifest_filename(name):
                found.append(os.path.abspath(full))

    _scan_dir(root)
    try:
        for name in os.listdir(root):
            sub = os.path.join(root, name)
            if os.path.isdir(sub):
                _scan_dir(sub)
    except OSError:
        pass
    return sorted(set(found))


def _search_dirs_for_zip(manifest_path: str, package_dir: str) -> List[str]:
    dirs: List[str] = []
    md = os.path.dirname(os.path.abspath(manifest_path))
    if md:
        dirs.append(md)
    if package_dir:
        root = os.path.abspath(package_dir)
        if root not in dirs:
            dirs.append(root)
        try:
            for name in os.listdir(root):
                sub = os.path.join(root, name)
                if os.path.isdir(sub) and sub not in dirs:
                    dirs.append(sub)
        except OSError:
            pass
    return dirs


def resolve_packages_from_manifest(
    manifest_path: str,
    package_dir: str = "",
) -> Dict[str, str]:
    """按 manifest 中的 filename 在目录中定位四个 zip 的绝对路径。"""
    manifest = load_ota_manifest(manifest_path)
    packages = manifest.get("packages")
    if not isinstance(packages, list):
        return {}

    search_dirs = _search_dirs_for_zip(manifest_path, package_dir)
    out: Dict[str, str] = {}
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        domain = str(pkg.get("domain", "") or "").strip().lower()
        ptype = str(pkg.get("type", "") or "").strip().lower()
        cfg_key = _MANIFEST_PKG_KEYS.get((domain, ptype))
        if not cfg_key:
            continue
        filename = str(pkg.get("filename", "") or "").strip()
        if not filename:
            continue
        resolved = ""
        for folder in search_dirs:
            candidate = os.path.join(folder, filename)
            if os.path.isfile(candidate):
                resolved = os.path.abspath(candidate)
                break
        if resolved:
            out[cfg_key] = resolved
    return out


def manifest_expected_filenames(manifest_path: str) -> Dict[str, str]:
    """manifest 中 packages[].filename → cfg 路径键（如 s100_app_path）。"""
    manifest = load_ota_manifest(manifest_path)
    packages = manifest.get("packages")
    if not isinstance(packages, list):
        return {}
    out: Dict[str, str] = {}
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        domain = str(pkg.get("domain", "") or "").strip().lower()
        ptype = str(pkg.get("type", "") or "").strip().lower()
        cfg_key = _MANIFEST_PKG_KEYS.get((domain, ptype))
        filename = str(pkg.get("filename", "") or "").strip()
        if cfg_key and filename:
            out[cfg_key] = filename
    return out


def md5_file_hex(path: str, chunk_size: int = 1 << 20) -> str:
    """计算文件 MD5（小写 hex）。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest().lower()


def manifest_expected_md5sums(manifest_path: str) -> Dict[str, str]:
    """manifest 中 packages[].md5sum → cfg 路径键（如 s100_app_path）。"""
    manifest = load_ota_manifest(manifest_path)
    packages = manifest.get("packages")
    if not isinstance(packages, list):
        return {}
    out: Dict[str, str] = {}
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        domain = str(pkg.get("domain", "") or "").strip().lower()
        ptype = str(pkg.get("type", "") or "").strip().lower()
        cfg_key = _MANIFEST_PKG_KEYS.get((domain, ptype))
        md5 = str(pkg.get("md5sum", "") or "").strip().lower()
        if cfg_key and md5:
            out[cfg_key] = md5
    return out


_PKG_KEY_LABELS = {
    "s100_sys_path": "S100 SYS",
    "s100_app_path": "S100 APP",
    "x5_sys_path": "X5 SYS",
    "x5_app_path": "X5 APP",
}


def resolve_active_manifest_path(cfg: Dict[str, Any], encrypted: bool) -> str:
    """本次 OTA 使用的 manifest 绝对路径（无则返回空）。"""
    explicit = get_configured_ota_manifest(cfg, encrypted)
    if explicit:
        return explicit
    active = str(cfg.get("ota_manifest_path") or "").strip()
    if not active or not os.path.isfile(active):
        return ""
    try:
        if manifest_is_encrypted(load_ota_manifest(active)) == encrypted:
            return os.path.abspath(active)
    except Exception:
        return ""
    return ""


def resolve_manifest_check_encryption(cfg: Dict[str, Any]) -> Optional[bool]:
    """推断本次应对照的 manifest 是加密还是未加密；无法推断则返回 None（跳过校验）。"""
    if cfg.get("ota_pkg_encrypted") is not None:
        return bool(cfg["ota_pkg_encrypted"])
    active = str(cfg.get("ota_manifest_path") or "").strip()
    if active and os.path.isfile(active):
        try:
            return manifest_is_encrypted(load_ota_manifest(active))
        except Exception:
            pass
    sys_p = str(cfg.get("s100_sys_path") or "").strip()
    if sys_p:
        return s100_sys_filename_is_encrypted(os.path.basename(sys_p))
    has_enc_mp = bool(get_configured_ota_manifest(cfg, True))
    has_plain_mp = bool(get_configured_ota_manifest(cfg, False))
    if has_enc_mp and not has_plain_mp:
        return True
    if has_plain_mp and not has_enc_mp:
        return False
    return None


def _resolved_ota_zip_path(cfg: Dict[str, Any], cfg_key: str, encrypted: bool) -> str:
    stored = str(cfg.get(ota_pkg_storage_key(cfg_key, encrypted)) or "").strip()
    if stored:
        return stored
    return str(cfg.get(cfg_key) or "").strip()


def validate_ota_packages_match_manifest(
    cfg: Dict[str, Any],
    *,
    encrypted: bool,
) -> Tuple[bool, str]:
    """OTA 开始前：校验所选 zip 文件名与 manifest 中 packages[].filename 完全一致。"""
    manifest_path = resolve_active_manifest_path(cfg, encrypted)
    if not manifest_path:
        return True, ""

    try:
        expected = manifest_expected_filenames(manifest_path)
    except Exception as exc:
        return False, f"无法读取 manifest: {manifest_path}\n{exc}"

    if not expected:
        return False, f"manifest 中未解析到有效 packages 条目: {manifest_path}"

    kind = "加密" if encrypted else "未加密"
    errors: List[str] = []
    checks = [
        ("S100", "ota_target_s100", "s100_app_path", "s100_sys_path"),
        ("X5", "ota_target_x5", "x5_app_path", "x5_sys_path"),
    ]
    for label, target_key, app_key, sys_key in checks:
        if not cfg.get(target_key):
            continue
        for key in (app_key, sys_key):
            exp_name = expected.get(key)
            if not exp_name:
                continue
            actual_path = _resolved_ota_zip_path(cfg, key, encrypted)
            if not actual_path:
                errors.append(f"[{label}] {key}: manifest 要求 {exp_name}，但未选择 zip")
                continue
            if not os.path.isfile(actual_path):
                errors.append(f"[{label}] {key}: 文件不存在\n  {actual_path}")
                continue
            actual_name = os.path.basename(actual_path)
            if actual_name != exp_name:
                errors.append(
                    f"[{label}] {key}: 与 manifest 不一致\n"
                    f"  manifest: {exp_name}\n"
                    f"  当前选择: {actual_name}"
                )

    if errors:
        return False, (
            f"【{kind}】升级包与 manifest 不一致（{os.path.basename(manifest_path)}）：\n"
            + "\n".join(errors)
        )
    return True, ""


def validate_ota_packages_md5_match_manifest(
    cfg: Dict[str, Any],
    *,
    encrypted: bool,
    check_all_packages: bool = False,
) -> Tuple[bool, str]:
    """校验烧录 zip 的 MD5 与 manifest packages[].md5sum 一致。"""
    manifest_path = resolve_active_manifest_path(cfg, encrypted)
    if not manifest_path:
        return True, ""

    try:
        expected_md5 = manifest_expected_md5sums(manifest_path)
    except Exception as exc:
        return False, f"无法读取 manifest: {manifest_path}\n{exc}"

    if not expected_md5:
        return False, (
            f"manifest 中未找到有效的 packages[].md5sum: "
            f"{os.path.basename(manifest_path)}"
        )

    kind = "加密" if encrypted else "未加密"
    errors: List[str] = []
    ok_lines: List[str] = []
    verified = 0
    checks = [
        ("S100", "ota_target_s100", "s100_app_path", "s100_sys_path"),
        ("X5", "ota_target_x5", "x5_app_path", "x5_sys_path"),
    ]
    for label, target_key, app_key, sys_key in checks:
        if not check_all_packages and not cfg.get(target_key):
            continue
        for key in (app_key, sys_key):
            exp_md5 = expected_md5.get(key)
            if not exp_md5:
                continue
            pkg_label = _PKG_KEY_LABELS.get(key, key)
            actual_path = _resolved_ota_zip_path(cfg, key, encrypted)
            if not actual_path:
                errors.append(f"[{label}] {pkg_label}: manifest 有 md5sum 但未选择 zip")
                continue
            if not os.path.isfile(actual_path):
                errors.append(f"[{label}] {pkg_label}: 文件不存在\n  {actual_path}")
                continue
            fname = os.path.basename(actual_path)
            try:
                actual_md5 = md5_file_hex(actual_path)
            except OSError as exc:
                errors.append(
                    f"[{label}] {pkg_label}: 无法读取文件\n  {actual_path}\n  {exc}"
                )
                continue
            if actual_md5 != exp_md5:
                errors.append(
                    f"[{label}] {pkg_label} ({fname}):\n"
                    f"  manifest: {exp_md5}\n"
                    f"  实际文件: {actual_md5}"
                )
            else:
                verified += 1
                ok_lines.append(f"  OK  {pkg_label}: {fname}")

    if errors:
        return False, (
            f"【{kind}】烧录包 MD5 与 manifest 不一致（{os.path.basename(manifest_path)}）：\n"
            + "\n".join(errors)
        )
    if verified == 0:
        return False, f"【{kind}】未核对任何烧录包（请确认已选择升级目标与 zip 路径）"

    summary = (
        f"【{kind}】{verified} 个烧录包 MD5 与 manifest 一致"
        f"（{os.path.basename(manifest_path)}）"
    )
    if ok_lines:
        summary += "\n" + "\n".join(ok_lines)
    return True, summary


def get_configured_ota_manifest(cfg: Dict[str, Any], encrypted: bool) -> str:
    """读取配置项 ota_manifest_encrypted / ota_manifest_plain（仅当文件存在时返回）。"""
    key = "ota_manifest_encrypted" if encrypted else "ota_manifest_plain"
    path = str(cfg.get(key) or "").strip()
    if not path:
        return ""
    if os.path.isfile(path):
        return os.path.abspath(path)
    return ""


def _classify_ota_manifest_files(manifests: List[str]) -> Tuple[List[Tuple[str, bool]], List[str]]:
    """解析 manifest 列表，返回 [(路径, 是否加密), ...] 与解析失败说明。"""
    classified: List[Tuple[str, bool]] = []
    errors: List[str] = []
    for mp in manifests:
        try:
            doc = load_ota_manifest(mp)
            classified.append((mp, manifest_is_encrypted(doc)))
        except Exception as exc:
            errors.append(f"  - {mp}: {exc}")
    return classified, errors


def select_packages_by_manifest(
    package_dir: str,
    *,
    encrypted: bool,
    cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, str], Optional[str]]:
    """
    优先使用 cfg 中配置的 manifest 路径；否则在 package_dir 下自动发现。
    返回 (paths, manifest_path)。
    """
    kind = "加密" if encrypted else "未加密"
    cfg = cfg or {}
    cfg_key = "ota_manifest_encrypted" if encrypted else "ota_manifest_plain"
    configured_raw = str(cfg.get(cfg_key) or "").strip()
    explicit = get_configured_ota_manifest(cfg, encrypted)
    stale_hint = ""
    if configured_raw and not explicit:
        stale_hint = (
            f"配置的 manifest 路径无效或文件不存在（将尝试在包目录自动发现）: {configured_raw}"
        )

    if explicit:
        try:
            doc = load_ota_manifest(explicit)
            if manifest_is_encrypted(doc) != encrypted:
                expect = "加密(S100 SYS 含 signed)" if encrypted else "未加密(S100 SYS 无 signed)"
                actual = "加密" if manifest_is_encrypted(doc) else "未加密"
                raise RuntimeError(
                    f"【{kind}】配置的 manifest 内容看起来像【{actual}】包，与期望【{expect}】不一致: {explicit}"
                )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"【{kind}】manifest 读取失败: {explicit} ({exc})") from exc

        paths = resolve_packages_from_manifest(explicit, package_dir)
        missing = [k for k in _REQUIRED_MANIFEST_KEYS if not paths.get(k)]
        if missing:
            raise RuntimeError(
                f"【{kind}】manifest {explicit} 已配置，但缺少 zip: {', '.join(missing)}；"
                f"请将 manifest 中的 filename 放到 manifest 同目录或 package_dir 下"
            )
        return paths, explicit

    manifests = discover_ota_manifests(package_dir)
    if not manifests:
        if configured_raw:
            raise RuntimeError(
                f"【{kind}】manifest 不存在: {configured_raw}；"
                f"且包目录内未发现 manifest*.yaml"
            )
        return {}, None

    classified, parse_errors = _classify_ota_manifest_files(manifests)

    # 仅选用与 encrypted 参数一致的 manifest
    if not classified:
        if configured_raw:
            raise RuntimeError(
                f"【{kind}】manifest 不存在: {configured_raw}；"
                f"且包目录内未发现 manifest*.yaml"
            )
        return {}, None

    matching = [mp for mp, enc in classified if enc == encrypted]

    if not matching:
        parts = [stale_hint] if stale_hint else []
        if parse_errors:
            parts.append(f"【{kind}】目录内 manifest 解析失败:")
            parts.extend(parse_errors)
        else:
            parts.append(f"【{kind}】包目录内无可用 manifest: {manifests}")
        if parts:
            raise RuntimeError("\n".join(p for p in parts if p))
        return {}, None

    manifest_path = max(matching, key=os.path.getmtime)
    paths = resolve_packages_from_manifest(manifest_path, package_dir)
    return paths, manifest_path


def scan_package_dir_for_lifecycle(
    directory: str,
    lifecycle: int,
    cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, str], Optional[str]]:
    """按 S100 lifecycle 选择未加密(0-3)或加密(>=4)包；优先配置的 manifest 路径。"""
    encrypted = lifecycle >= 4
    kind = "加密" if encrypted else "未加密"

    paths, manifest_path = select_packages_by_manifest(
        directory, encrypted=encrypted, cfg=cfg
    )

    if manifest_path and paths:
        missing = [k for k in _REQUIRED_MANIFEST_KEYS if not paths.get(k)]
        if not missing:
            return paths, manifest_path

    if encrypted:
        fallback = scan_package_dir(
            directory,
            rules=PKG_RULES_ENCRYPTED,
            encrypted=True,
        )
    else:
        fallback = scan_package_dir(
            directory,
            rules=PKG_RULES_PLAIN,
            encrypted=False,
        )

    if manifest_path:
        fallback.update({k: v for k, v in paths.items() if v})
        missing = [k for k in _REQUIRED_MANIFEST_KEYS if not fallback.get(k)]
        if missing:
            raise RuntimeError(
                f"【{kind}】manifest {manifest_path} 已匹配，但缺少 zip: {', '.join(missing)}；"
                f"请把 manifest 里的 filename 放到 manifest 同目录或 ota_package_dir 下"
            )
        return fallback, manifest_path

    if not fallback:
        manifests = discover_ota_manifests(directory)
        cfg_hint = ""
        if cfg:
            mk = "ota_manifest_encrypted" if encrypted else "ota_manifest_plain"
            if not get_configured_ota_manifest(cfg, encrypted):
                cfg_hint = f" 或在配置中设置 {mk} 指向 manifest 文件。"
        hint = (
            f"目录内 manifest 列表: {manifests or '(无)'}"
            if manifests
            else f"请配置 ota_manifest_{'encrypted' if encrypted else 'plain'}，或在目录下放置 manifest.yaml + zip"
        )
        raise RuntimeError(
            f"未找到【{kind}】OTA 包。{hint}{cfg_hint}"
        )
    return fallback, None


def parse_lifecycle_value(stdout: str, stderr: str, tool_exit: int) -> int:
    """解析 provision_tool --get-lifecycle 输出中的 lifecycle 数字。"""
    text = f"{stdout}\n{stderr}"
    for line in text.splitlines():
        m = re.search(r"lifecycle:\s*(\d+)", line, re.IGNORECASE)
        if m:
            return int(m.group(1))
        if "__LIFECYCLE_RC__=" in line:
            try:
                return int(line.rsplit("=", 1)[-1].strip())
            except ValueError:
                pass
    return tool_exit


def read_s100_lifecycle(ssh: SSHHelper) -> Tuple[int, str]:
    """在 S100 上执行 provision_tool --get-lifecycle，返回 (lifecycle, 原始输出摘要)。"""
    _, stdout, stderr = ssh.client.exec_command(LIFECYCLE_PROBE_CMD)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    tool_rc = stdout.channel.recv_exit_status()
    lifecycle = parse_lifecycle_value(out, err, tool_rc)
    summary = (out + err).strip()
    return lifecycle, summary


def resolve_ota_package_directory(cfg: Dict[str, Any]) -> str:
    pkg_dir = str(cfg.get("package_dir") or "").strip()
    if pkg_dir and os.path.isdir(pkg_dir):
        return pkg_dir
    paths = [
        str(cfg.get(k) or "").strip()
        for k in ("s100_app_path", "s100_sys_path", "x5_app_path", "x5_sys_path")
        if cfg.get(k)
    ]
    if not paths:
        return ""
    try:
        parent = os.path.commonpath([os.path.dirname(os.path.abspath(p)) for p in paths])
        return parent if os.path.isdir(parent) else ""
    except ValueError:
        return os.path.dirname(os.path.abspath(paths[0]))


def package_path_matches_encryption(
    path: str, encrypted: bool, *, cfg_key: str = ""
) -> bool:
    """加密/未加密仅校验 S100 SYS 是否含 signed；其他路径键不校验 signed。"""
    if not (path or "").strip():
        return True
    if cfg_key and cfg_key != "s100_sys_path":
        return True
    if not cfg_key:
        base = os.path.basename(path).lower()
        if "app" in base or "x5" in base or "lnx" in base:
            return True
        if "all_in_one" not in base and "s100" not in base:
            return True
    is_enc = s100_sys_filename_is_encrypted(path)
    return is_enc if encrypted else not is_enc


def validate_sn_packages(sn: str, cfg: Dict[str, Any]) -> Tuple[bool, str]:
    """校验 19 位 SN 与 APP 包名 edu/pro/max 特征。空 SN 且未要求时由调用方决定。"""
    sn = (sn or "").strip()
    if not sn:
        return True, ""
    if not re.match(r"^[A-Za-z0-9]{19}$", sn):
        return False, "SN 格式错误：必须是精确的 19 位字母或数字。"

    required_keyword: Optional[str] = None
    if "8010001" in sn or "8010002" in sn:
        required_keyword = "edu"
    elif "8010003" in sn or "8010004" in sn:
        required_keyword = "pro"
    elif "8010005" in sn or "8010006" in sn:
        required_keyword = "max"

    if not required_keyword:
        return True, ""

    errors: List[str] = []
    if cfg.get("ota_target_s100"):
        app = os.path.basename(str(cfg.get("s100_app_path") or "")).lower()
        if app and required_keyword not in app:
            errors.append(f"S100 APP ({app}) 未包含特征字 '{required_keyword}'")
    if cfg.get("ota_target_x5"):
        app = os.path.basename(str(cfg.get("x5_app_path") or "")).lower()
        if app and required_keyword not in app:
            errors.append(f"X5 APP ({app}) 未包含特征字 '{required_keyword}'")

    if errors:
        return False, (
            f"该 SN 对应需要【{required_keyword.upper()}】版本 APP 包，但检查不匹配：\n"
            + "\n".join(errors)
        )
    return True, ""


def merge_ota_cfg(
    base: Optional[Dict[str, Any]] = None,
    *,
    s100_ip: str = "",
    x5_ip: str = "",
    username: str = "",
    password: str = "",
    ota_dir: str = "",
    connect_timeout: int = 0,
    use_identity_file: bool = False,
    identity_file: str = "",
    ota_target_s100: Optional[bool] = None,
    ota_target_x5: Optional[bool] = None,
    use_tmux: Optional[bool] = None,
    s100_app_path: str = "",
    s100_sys_path: str = "",
    x5_app_path: str = "",
    x5_sys_path: str = "",
    package_dir: str = "",
    ota_manifest_encrypted: str = "",
    ota_manifest_plain: str = "",
) -> Dict[str, Any]:
    cfg = dict(base or DEFAULT_CONFIG)
    if s100_ip:
        cfg["s100_ip"] = s100_ip
    if x5_ip:
        cfg["x5_ip"] = x5_ip
    if username:
        cfg["username"] = username
    if password:
        cfg["password"] = password
    if ota_dir:
        cfg["ota_dir"] = ota_dir
    if connect_timeout > 0:
        cfg["connect_timeout"] = connect_timeout
    if use_identity_file or identity_file:
        cfg["use_identity_file"] = bool(use_identity_file or identity_file)
    if identity_file:
        cfg["identity_file"] = identity_file
    if ota_target_s100 is not None:
        cfg["ota_target_s100"] = ota_target_s100
    if ota_target_x5 is not None:
        cfg["ota_target_x5"] = ota_target_x5
    if use_tmux is not None:
        cfg["use_tmux"] = use_tmux

    if package_dir:
        cfg["package_dir"] = package_dir
    if ota_manifest_encrypted:
        cfg["ota_manifest_encrypted"] = ota_manifest_encrypted
    if ota_manifest_plain:
        cfg["ota_manifest_plain"] = ota_manifest_plain
    scanned = scan_package_dir(package_dir) if package_dir else {}
    for key, val in (
        ("s100_app_path", s100_app_path),
        ("s100_sys_path", s100_sys_path),
        ("x5_app_path", x5_app_path),
        ("x5_sys_path", x5_sys_path),
    ):
        if val:
            cfg[key] = val
        elif key in scanned:
            cfg[key] = scanned[key]
    return cfg


def _expected_ota_block(expected: Dict[str, Any], label: str) -> Tuple[str, str]:
    block = expected.get(label, {}) if isinstance(expected, dict) else {}
    if not isinstance(block, dict):
        block = {}
    app_ver = str(block.get("app_version", "") or "").strip()
    sys_ver = str(block.get("sys_version", "") or "").strip()
    return app_ver, sys_ver


def resolve_ota_version_config_path(config_path: str = "") -> Optional[Path]:
    """解析 TestTool Config/config.yaml（或用户指定路径）。"""
    raw = (config_path or DEFAULT_OTA_VERSION_CONFIG).strip()
    candidates: List[Path] = []
    p = Path(raw).expanduser()
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append(Path.cwd() / raw)
        core_dir = Path(__file__).resolve().parent
        tt_root = core_dir.parent.parent
        candidates.append(tt_root / raw)
        candidates.append(core_dir / raw)
    for c in candidates:
        try:
            if c.is_file():
                return c.resolve()
        except OSError:
            continue
    return None


def load_ota_version_expected(config_path: str = "") -> Dict[str, Any]:
    """从 config.yaml 读取 ota_version（与导入包/菜单「OTA 版本」一致）。"""
    cfg_file = resolve_ota_version_config_path(config_path)
    if cfg_file is None:
        return {}
    try:
        doc = parse_yaml_file(str(cfg_file))
        block = doc.get("ota_version", {}) if isinstance(doc, dict) else {}
        return block if isinstance(block, dict) else {}
    except Exception:
        return {}


def parse_app_version_from_remote(content: str) -> str:
    for line in (content or "").splitlines():
        line = line.strip()
        if line.startswith("VERSION="):
            return line.split("=", 1)[1].strip()
    return ""


_APP_ZIP_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+-\d+(?:\+git[a-f0-9]+)?)", re.I)


def app_version_from_zip_path(path: str) -> str:
    """从 APP 升级包文件名提取 VERSION= 对应特征串。"""
    name = os.path.basename(path or "")
    m = _APP_ZIP_VERSION_RE.search(name)
    return m.group(1) if m else ""


def sys_version_from_zip_path(path: str) -> str:
    """从 SYS 升级包文件名提取 /etc/version 对应特征串。"""
    name = os.path.basename(path or "")
    if name.lower().endswith(".zip"):
        name = name[:-4]
    low = name.lower()
    if low.startswith("all_in_one_signed-"):
        return name[len("all_in_one_signed-") :]
    if low.startswith("all_in_one-"):
        return name[len("all_in_one-") :]
    return name


def build_expected_ota_version_from_packages(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """从本次 OTA 实际选用的 zip 路径推导 SSH 版本校验期望值。"""
    result: Dict[str, Any] = {}
    for label, target_key, app_key, sys_key in (
        ("S100", "ota_target_s100", "s100_app_path", "s100_sys_path"),
        ("X5", "ota_target_x5", "x5_app_path", "x5_sys_path"),
    ):
        if not cfg.get(target_key):
            continue
        app_path = str(cfg.get(app_key) or "").strip()
        sys_path = str(cfg.get(sys_key) or "").strip()
        app_ver = app_version_from_zip_path(app_path) if app_path else ""
        sys_ver = sys_version_from_zip_path(sys_path) if sys_path else ""
        if app_ver or sys_ver:
            result[label] = {"app_version": app_ver, "sys_version": sys_ver}
    return result


def resolve_expected_ota_version(cfg: Dict[str, Any], logger: Callable[[str], None]) -> bool:
    """刷包完成后解析期望版本：优先本次选用的 zip，否则回退 config.yaml。"""
    existing = cfg.get("expected_ota_version")
    if isinstance(existing, dict) and existing:
        logger(f"[版本校验] 期望版本（OTA 选包阶段已解析）: {existing}")
        return True

    pkg_expected = build_expected_ota_version_from_packages(cfg)
    if pkg_expected:
        cfg["expected_ota_version"] = pkg_expected
        logger(f"[版本校验] 期望版本来自本次选用的升级包: {pkg_expected}")
        return True

    config_path = str(cfg.get("ota_version_config_path") or DEFAULT_OTA_VERSION_CONFIG)
    expected = load_ota_version_expected(config_path)
    if expected:
        cfg["expected_ota_version"] = expected
        logger(f"[版本校验] 期望版本来自 config.yaml ota_version: {expected}")
        return True

    logger(
        "❌ 无法获取期望版本：请在界面选择升级包，或在 config.yaml 配置 ota_version"
    )
    return False


def version_strings_match(expected: str, actual: str) -> bool:
    """设备读到的版本须与期望一致（忽略大小写；SYS 允许 v 前缀差异）。"""
    expected = (expected or "").strip()
    actual = (actual or "").strip()
    if not expected:
        return True
    if not actual:
        return False

    def _norm(v: str) -> str:
        low = v.lower()
        if low.startswith("v") and len(low) > 1 and low[1].isdigit():
            return low[1:]
        return low

    return _norm(expected) == _norm(actual)


def read_remote_versions(ssh: "SSHHelper") -> Tuple[str, str]:
    """SSH 读取 APP(/app/version_info.txt) 与 SYS(/etc/version)。"""
    rc_app, app_raw, _ = _ssh_exec_read(ssh, f"cat '{REMOTE_APP_VERSION_FILE}' 2>/dev/null")
    rc_sys, sys_raw, _ = _ssh_exec_read(ssh, f"cat '{REMOTE_SYS_VERSION_FILE}' 2>/dev/null")
    app_ver = parse_app_version_from_remote(app_raw) if rc_app == 0 else ""
    sys_ver = sys_raw.strip() if rc_sys == 0 else ""
    return app_ver, sys_ver


def read_remote_versions_verbose(
    ssh: "SSHHelper",
) -> Tuple[str, str, str]:
    """同 read_remote_versions，额外返回诊断说明（读不到时）。"""
    rc_app, app_raw, _ = _ssh_exec_read(ssh, f"cat '{REMOTE_APP_VERSION_FILE}' 2>/dev/null")
    rc_sys, sys_raw, _ = _ssh_exec_read(ssh, f"cat '{REMOTE_SYS_VERSION_FILE}' 2>/dev/null")
    app_ver = parse_app_version_from_remote(app_raw) if rc_app == 0 else ""
    sys_ver = sys_raw.strip() if rc_sys == 0 else ""
    notes: List[str] = []
    if rc_app != 0:
        notes.append(f"{REMOTE_APP_VERSION_FILE} 读取失败(rc={rc_app})")
    elif not app_ver:
        notes.append(f"{REMOTE_APP_VERSION_FILE} 无 VERSION= 行")
    if rc_sys != 0:
        notes.append(f"{REMOTE_SYS_VERSION_FILE} 读取失败(rc={rc_sys})")
    elif not sys_ver:
        notes.append(f"{REMOTE_SYS_VERSION_FILE} 为空")
    return app_ver, sys_ver, "; ".join(notes)


def _looks_like_engineer_version_payload(data: Dict[str, Any]) -> bool:
    if any(key in data for key in ("S100", "X5")):
        return True
    devices = data.get("devices")
    return isinstance(devices, list)


def normalize_engineer_version_payload(raw: Any) -> Optional[Dict[str, Any]]:
    """解析工程模式 version=0 响应为 {S100: {app_version, sys_version}, ...}。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text.startswith("{"):
            return None
        try:
            return normalize_engineer_version_payload(json.loads(text))
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    if not isinstance(raw, dict):
        return None
    if _looks_like_engineer_version_payload(raw):
        return raw
    for key in ("data", "payload", "result", "body"):
        inner = raw.get(key)
        if inner is None:
            continue
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        nested = normalize_engineer_version_payload(inner)
        if nested is not None:
            return nested
    resp = raw.get("response")
    if isinstance(resp, dict):
        nested = normalize_engineer_version_payload(resp)
        if nested is not None:
            return nested
    return None


def engineer_service_post(
    host: str,
    port: int,
    command: str,
    params: Dict[str, Any],
    *,
    timeout_sec: float = 30.0,
) -> Dict[str, Any]:
    """同步 POST 工程服务 /command（与 test_engineer_client 报文格式一致）。"""
    url = f"http://{host}:{port}/command"
    body = json.dumps(
        {
            "command": command,
            "params": params,
            "timestamp": int(time.time() * 1000),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Connection": "close",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def _ssh_exec_read(ssh: "SSHHelper", cmd: str) -> Tuple[int, str, str]:
    _, stdout, stderr = ssh.client.exec_command(cmd)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    return code, out, err


def validate_ota_package_filenames(
    cfg: Dict[str, Any],
    expected: Dict[str, Any],
) -> Tuple[bool, str]:
    """检查升级包 zip 文件名是否包含 config 中 ota_version 配置的版本特征串。"""
    errors: List[str] = []
    checks = [
        ("S100", "ota_target_s100", "s100_app_path", "s100_sys_path"),
        ("X5", "ota_target_x5", "x5_app_path", "x5_sys_path"),
    ]
    for label, target_key, app_key, sys_key in checks:
        if not cfg.get(target_key):
            continue
        app_ver, sys_ver = _expected_ota_block(expected, label)
        app_path = str(cfg.get(app_key) or "").strip()
        sys_path = str(cfg.get(sys_key) or "").strip()

        if not app_path or not os.path.isfile(app_path):
            errors.append(f"{label} APP 包路径无效或文件不存在: {app_path or '(未设置)'}")
        elif app_ver:
            name = os.path.basename(app_path)
            if app_ver.lower() not in name.lower():
                errors.append(
                    f"{label} APP 包名未包含期望版本 '{app_ver}': {name}"
                )

        if not sys_path or not os.path.isfile(sys_path):
            errors.append(f"{label} SYS 包路径无效或文件不存在: {sys_path or '(未设置)'}")
        elif sys_ver:
            name = os.path.basename(sys_path)
            if sys_ver.lower() not in name.lower():
                errors.append(
                    f"{label} SYS 包名未包含期望版本 '{sys_ver}': {name}"
                )

    if errors:
        return False, "\n".join(errors)
    return True, ""


def validate_ota_cfg(cfg: Dict[str, Any]) -> Tuple[bool, str]:
    if not (cfg.get("ota_target_s100") or cfg.get("ota_target_x5")):
        return False, "未选择任何 OTA 升级目标（S100 / X5）。"
    if cfg.get("ota_target_s100") and cfg.get("ota_target_x5"):
        missing = []
        for label, app_k, sys_k in (
            ("S100", "s100_app_path", "s100_sys_path"),
            ("X5", "x5_app_path", "x5_sys_path"),
        ):
            if not cfg.get(app_k) or not cfg.get(sys_k):
                missing.append(f"{label} APP/SYS")
            else:
                for p in (cfg[app_k], cfg[sys_k]):
                    if not os.path.isfile(p):
                        return False, f"升级包不存在: {p}"
        if missing:
            return False, f"双板 OTA 缺少路径: {', '.join(missing)}（请先确认加密类型并选包）"
        return True, ""
    if cfg.get("ota_target_s100"):
        if not cfg.get("s100_app_path") or not cfg.get("s100_sys_path"):
            hint = _missing_pkg_hint("S100", ("s100_app_path", "s100_sys_path"), cfg)
            return False, f"已启用 S100 OTA，但缺少 S100 APP 或 SYS 包路径。{hint}"
        for p in (cfg["s100_app_path"], cfg["s100_sys_path"]):
            if not os.path.isfile(p):
                return False, f"S100 包不存在: {p}"
    if cfg.get("ota_target_x5"):
        if not cfg.get("x5_app_path") or not cfg.get("x5_sys_path"):
            hint = _missing_pkg_hint("X5", ("x5_app_path", "x5_sys_path"), cfg)
            return False, f"已启用 X5 OTA，但缺少 X5 APP 或 SYS 包路径。{hint}"
        for p in (cfg["x5_app_path"], cfg["x5_sys_path"]):
            if not os.path.isfile(p):
                return False, f"X5 包不存在: {p}"
    return True, ""


def _missing_pkg_hint(label: str, path_keys: tuple[str, str], cfg: Dict[str, Any]) -> str:
    """扫描失败时附带目录内容与匹配规则，便于产线排查。"""
    pkg_dir = str(cfg.get("package_dir") or "").strip()
    rules = {k: v for k, v in PKG_RULES.items() if label in k}
    parts = [f" 匹配规则: {rules}"]
    if pkg_dir:
        scanned = scan_package_dir(pkg_dir)
        parts.append(f" 目录 {pkg_dir} 已扫描到: {scanned or '(无匹配 zip)'}")
        if os.path.isdir(pkg_dir):
            names = sorted(os.listdir(pkg_dir))
            parts.append(f" 目录内文件: {names}")
    return " " + " | ".join(parts)


def clear_windows_arp_for_ips(ips: Iterable[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
    """清除本机 ARP 缓存（Windows: arp -d <ip>）。返回 (成功 IP 列表, [(失败 IP, 原因), ...])。"""
    cleared: List[str] = []
    failed: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for raw in ips:
        ip = str(raw or "").strip()
        if not ip or ip in seen:
            continue
        seen.add(ip)
        if sys.platform != "win32":
            failed.append((ip, "仅 Windows 支持 arp -d"))
            continue
        try:
            proc = subprocess.run(
                ["arp", "-d", ip],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                cleared.append(ip)
            else:
                err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
                failed.append((ip, err))
        except Exception as exc:
            failed.append((ip, str(exc)))
    return cleared, failed


def ping_host_reachable(ip: str, *, timeout_sec: float = 2.0) -> bool:
    """单次 ping 探测（Windows / Linux）。"""
    host = str(ip or "").strip()
    if not host:
        return False
    try:
        if sys.platform == "win32":
            proc = subprocess.run(
                ["ping", "-n", "1", "-w", str(max(500, int(timeout_sec * 1000))), host],
                capture_output=True,
                timeout=max(3.0, timeout_sec + 2.0),
            )
        else:
            proc = subprocess.run(
                ["ping", "-c", "1", "-W", str(max(1, int(timeout_sec))), host],
                capture_output=True,
                timeout=max(3.0, timeout_sec + 2.0),
            )
        return proc.returncode == 0
    except Exception:
        return False


def wait_for_ping(
    ip: str,
    *,
    total_timeout_sec: float = 90.0,
    interval_sec: float = 3.0,
    ping_timeout_sec: float = 2.0,
    on_tick: Optional[Callable[[float, float], None]] = None,
) -> Tuple[bool, float]:
    """等待 host ping 通。on_tick(elapsed, total_timeout_sec) 可选。返回 (是否成功, 已等待秒数)。"""
    host = str(ip or "").strip()
    if not host:
        return False, 0.0
    total = max(1.0, float(total_timeout_sec))
    interval = max(0.5, float(interval_sec))
    deadline = time.monotonic() + total
    elapsed = 0.0
    while time.monotonic() < deadline:
        if ping_host_reachable(host, timeout_sec=ping_timeout_sec):
            return True, elapsed
        elapsed = total - max(0.0, deadline - time.monotonic())
        if on_tick:
            on_tick(elapsed, total)
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
    return False, total


def prepare_pc_network_for_device_swap(
    s100_ip: str,
    x5_ip: str = "",
    *,
    wait_ping_s100: bool = True,
    ping_wait_sec: float = 90.0,
    ping_interval_sec: float = 3.0,
    log: Optional[Callable[[str], None]] = None,
    on_ping_tick: Optional[Callable[[float, float], None]] = None,
) -> Tuple[bool, str]:
    """换台后准备 PC 网络：清 ARP，可选等待 S100 ping 通。"""
    _log = log or (lambda _msg: None)
    ips = [ip for ip in (s100_ip, x5_ip) if str(ip or "").strip()]
    if not ips:
        return False, "未配置 S100/X5 IP"

    _log("换台准备：清除本机 ARP 缓存（避免同 IP 换设备后 ping/SSH 仍指向上一台）…")
    cleared, failed = clear_windows_arp_for_ips(ips)
    for ip in cleared:
        _log(f"  已清除 ARP: {ip}")
    for ip, err in failed:
        _log(f"  清除 ARP 跳过/失败 ({ip}): {err}")

    s100 = str(s100_ip or "").strip()
    if not wait_ping_s100 or not s100:
        return True, "ARP 已处理（未等待 ping）"

    _log(f"等待 S100 上线: ping {s100}（最长 {int(ping_wait_sec)}s，每 {ping_interval_sec}s 一次）…")
    ok, waited = wait_for_ping(
        s100,
        total_timeout_sec=ping_wait_sec,
        interval_sec=ping_interval_sec,
        on_tick=on_ping_tick,
    )
    if ok:
        _log(f"  S100 已响应 ping（约 {waited:.0f}s）")
        return True, f"S100 {s100} ping 通"
    _log(f"  超时：{int(ping_wait_sec)}s 内 ping 不通 {s100}")
    return False, f"{int(ping_wait_sec)}s 内 ping 不通 S100 ({s100})"


def _ssh_connect_kwargs_from_cfg(cfg: Dict[str, Any], *, connect_timeout: float) -> Dict[str, Any]:
    return {
        "hostname": str(cfg.get("s100_ip") or "").strip(),
        "username": str(cfg.get("username") or "root"),
        "password": cfg.get("password"),
        "identity_file": cfg.get("identity_file") if cfg.get("use_identity_file") else None,
        "use_key": bool(cfg.get("use_identity_file")),
        "timeout": connect_timeout,
    }


def attempt_ssh_reboot_s100(
    cfg: Dict[str, Any],
    *,
    connect_timeout: float = 15.0,
    log: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """SSH 可达时对 S100 下发 sync; reboot（用于 hang 恢复）。"""
    ip = str(cfg.get("s100_ip") or "").strip()
    if not ip:
        return False, "未配置 s100_ip"
    _log = log or (lambda _msg: None)
    kw = _ssh_connect_kwargs_from_cfg(cfg, connect_timeout=connect_timeout)
    ssh = SSHHelper(logger=_log, **kw)
    try:
        _log(f"尝试 SSH 连接 {ip}（超时 {int(connect_timeout)}s）…")
        ssh.connect()
        _log("SSH 已连接，下发 sync; reboot …")
        _, stdout, stderr = ssh.client.exec_command("sync; reboot", timeout=30)
        try:
            stdout.channel.recv_exit_status()
        except Exception:
            pass
        err = (stderr.read().decode("utf-8", errors="replace") or "").strip()
        if err:
            _log(f"  reboot stderr: {err[:200]}")
        _log("已下发远程 reboot，设备即将重启…")
        return True, f"已对 S100 ({ip}) 下发 reboot"
    except Exception as exc:
        hint = _ssh_connect_hint(str(exc))
        return False, f"无法 SSH 远程 reboot: {exc}{hint}"
    finally:
        try:
            ssh.close()
        except Exception:
            pass


def wait_for_ping_down(
    ip: str,
    *,
    total_timeout_sec: float = 60.0,
    interval_sec: float = 2.0,
    ping_timeout_sec: float = 2.0,
    log: Optional[Callable[[str], None]] = None,
) -> bool:
    """等待 ping 从通变为不通（设备开始 reboot）。"""
    host = str(ip or "").strip()
    if not host:
        return False
    _log = log or (lambda _msg: None)
    deadline = time.monotonic() + max(5.0, float(total_timeout_sec))
    while time.monotonic() < deadline:
        if not ping_host_reachable(host, timeout_sec=ping_timeout_sec):
            _log("  设备 ping 已断开（正在重启）")
            return True
        time.sleep(max(0.5, float(interval_sec)))
    _log("  未观察到 ping 断开（可能 reboot 很快或命令未生效）")
    return False


def recover_hung_s100_device(
    cfg: Dict[str, Any],
    x5_ip: str = "",
    *,
    clear_arp: bool = True,
    post_reboot_wait_sec: float = 180.0,
    ping_interval_sec: float = 3.0,
    ssh_connect_timeout: float = 15.0,
    log: Optional[Callable[[str], None]] = None,
    on_ping_tick: Optional[Callable[[float, float], None]] = None,
) -> Tuple[bool, str]:
    """Hang 恢复：清 ARP → SSH reboot → 等待 S100 再次 ping 通。"""
    _log = log or (lambda _msg: None)
    s100 = str(cfg.get("s100_ip") or "").strip()
    if not s100:
        return False, "未配置 S100 IP"

    _log("Hang 恢复：尝试清除设备假死状态（远程 reboot）…")
    if clear_arp:
        ips = [ip for ip in (s100, x5_ip) if str(ip or "").strip()]
        cleared, failed = clear_windows_arp_for_ips(ips)
        for ip in cleared:
            _log(f"  已清除 ARP: {ip}")
        for ip, err in failed:
            _log(f"  清除 ARP 跳过/失败 ({ip}): {err}")

    reboot_ok, reboot_msg = attempt_ssh_reboot_s100(
        cfg,
        connect_timeout=ssh_connect_timeout,
        log=_log,
    )
    if not reboot_ok:
        _log(f"  {reboot_msg}")
        _log(
            "  无法远程 reboot：设备可能网络/sshd 均已 hang，请关电 10 秒后重新上电再试"
        )
        return False, (
            f"{reboot_msg}\n\n"
            "无法远程恢复。请对该设备：关电 10 秒 → 重新上电 → 等待 1～2 分钟后再连接。"
        )

    _log(reboot_msg)
    wait_for_ping_down(s100, log=_log)
    _log(f"等待 S100 reboot 完成后再次 ping 通（最长 {int(post_reboot_wait_sec)}s）…")
    ok, waited = wait_for_ping(
        s100,
        total_timeout_sec=post_reboot_wait_sec,
        interval_sec=ping_interval_sec,
        on_tick=on_ping_tick,
    )
    if ok:
        _log(f"  Hang 恢复成功：S100 已再次 ping 通（约 {waited:.0f}s）")
        return True, f"Hang 恢复成功，S100 {s100} 已 ping 通"

    _log(f"  reboot 后 {int(post_reboot_wait_sec)}s 内仍 ping 不通")
    return False, (
        f"已下发 reboot，但 {int(post_reboot_wait_sec)}s 内 S100 ({s100}) 仍未 ping 通。\n"
        "请检查是否正在 boot，或手动关电再上电。"
    )


def prompt_s100_manual_power_cycle(
    cfg: Dict[str, Any],
    logger: Callable[[str], None],
) -> bool:
    """提示产线人工上下电，并检测到 ping 先断后通，才允许进入版本校验。"""
    if cfg.get("_s100_manual_power_cycle_done"):
        return True
    if cfg.get("ota_s100_auto_reboot", False) or not cfg.get("ota_target_s100"):
        return True

    s100 = str(cfg.get("s100_ip") or "").strip()
    if not s100:
        logger("❌ 未配置 s100_ip，无法等待人工上下电")
        return False

    down_wait = float(cfg.get("ota_manual_power_down_wait_sec") or 180)
    up_wait = float(cfg.get("ota_manual_power_cycle_ping_wait_sec") or 300)
    ping_interval = float(cfg.get("ota_swap_ping_interval_sec") or 3)

    cb = cfg.get("_manual_power_cycle_callback")
    if cb:
        logger("⏸ 请查看弹窗：先点「确定」，再关电 → 上电（工具将自动检测）…")
        ota_emit_status(cfg, "⏸ 请人工上下电 S100…")
        try:
            confirmed = bool(cb())
        except Exception as exc:
            logger(f"❌ 人工上下电确认异常: {exc}")
            return False
        if not confirmed:
            logger("❌ 产线员工取消人工上下电")
            return False
        logger("✅ 已确认，等待检测到关电（ping 断开）…")
    else:
        logger("=" * 52)
        logger("【人工上下电】设备刷写完成后，请产线员工：")
        logger("  1. 关电")
        logger("  2. 等待约 10 秒")
        logger("  3. 重新上电，等待 1～2 分钟")
        logger("  工具将自动检测 ping 断开后再通，然后才读版本")
        logger("=" * 52)
        ota_emit_status(cfg, "⏸ 等待产线人工上下电…")

    # 必须观察到 ping 断开（证明已关电）；未关电则不进入版本校验，避免空等 25min
    if ping_host_reachable(s100):
        logger(f"等待关电：ping {s100} 断开（最长 {int(down_wait)}s）…")
        if not wait_for_ping_down(
            s100,
            total_timeout_sec=down_wait,
            interval_sec=ping_interval,
            log=logger,
        ):
            logger(
                "❌ 超时：ping 一直通，未检测到关电。"
                "请先关电再上电；未上下电时版本不会变，不能进入读版本。"
            )
            return False
    else:
        logger("  已检测到 ping 断开（设备可能已关电）")

    if cfg.get("ota_version_clear_arp_before_verify", True):
        cleared, failed = clear_windows_arp_for_ips([s100])
        for ip in cleared:
            logger(f"  重新上电前已清除 ARP: {ip}")
        for ip, err in failed:
            logger(f"  清除 ARP 跳过/失败 ({ip}): {err}")

    logger(f"等待重新上电：ping {s100} 恢复（最长 {int(up_wait)}s）…")
    ok, waited = wait_for_ping(
        s100,
        total_timeout_sec=up_wait,
        interval_sec=ping_interval,
    )
    if ok:
        logger(f"  S100 已 ping 通（约 {waited:.0f}s），上下电完成，开始读版本")
        ota_emit_status(cfg, "✅ S100 已上线，开始读版本…")
        cfg["_s100_manual_power_cycle_done"] = True
        return True

    logger(f"❌ 关电后 {int(up_wait)}s 内 S100 仍 ping 不通，请检查上电")
    return False


def _ssh_connect_hint(err: str) -> str:
    low = err.lower()
    if "no route to host" in low:
        return (
            "\n  → 网络不可达 (No route to host)：PC 与设备不在同一网段或路由不通。"
            "请检查网线、网卡 IP、设备是否开机；本机可试: ping <设备IP>"
        )
    if "connect failed" in low:
        return (
            "\n  → 连接被拒绝或不可达：请确认 IP 正确、设备 SSH 已启动、防火墙未拦截 22 端口"
        )
    if "timed out" in low or "timeout" in low:
        return "\n  → 连接超时：请检查 IP/网络或增大 connect_timeout"
    if "authentication" in low or "auth failed" in low:
        return "\n  → 认证失败：请检查用户名/密码或私钥"
    return ""


class SSHHelper:
    def __init__(
        self,
        hostname,
        username,
        password=None,
        identity_file=None,
        use_key=False,
        timeout=5,
        jump_client=None,
        logger=None,
    ):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.identity_file = identity_file
        self.use_key = use_key
        self.timeout = timeout
        self.jump_client = jump_client
        self.logger = logger or (lambda msg: None)
        self.client = None

    def connect(self):
        sock = None
        via = ""
        if self.jump_client:
            via = f"（经 S100 隧道 → {self.hostname}:22）"
            try:
                transport = self.jump_client.get_transport()
                if transport is None or not transport.is_active():
                    raise RuntimeError("S100 跳板 SSH 会话已断开")
                sock = transport.open_channel(
                    "direct-tcpip", (self.hostname, 22), ("127.0.0.1", 0)
                )
            except Exception as exc:
                hint = _ssh_connect_hint(str(exc))
                raise RuntimeError(
                    f"经 S100 隧道连接 {self.hostname}:22 失败: {exc}{hint}"
                ) from exc

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kwargs = {
            "hostname": self.hostname,
            "username": self.username,
            "timeout": self.timeout,
            "sock": sock,
        }
        if self.use_key and self.identity_file:
            kwargs["key_filename"] = self.identity_file
            if self.password:
                kwargs["password"] = self.password
        else:
            kwargs["password"] = self.password
        try:
            self.client.connect(**kwargs)
        except Exception as exc:
            hint = _ssh_connect_hint(str(exc))
            target = f"{self.username}@{self.hostname}:22{via}"
            raise RuntimeError(f"SSH 连接失败 {target}: {exc}{hint}") from exc

    def upload_file(self, local_src, remote_dst, progress_cb=None):
        if remote_dst.endswith("/"):
            remote_dir = remote_dst.rstrip("/")
            remote_path = remote_dir + "/" + os.path.basename(local_src)
        else:
            remote_dir = os.path.dirname(remote_dst)
            remote_path = remote_dst

        _, stdout_mk, _ = self.client.exec_command(f"mkdir -p '{remote_dir}'")
        stdout_mk.channel.recv_exit_status()
        sftp = self.client.open_sftp()
        try:
            sftp.put(local_src, remote_path, callback=progress_cb)
        finally:
            sftp.close()

    def close(self):
        if self.client:
            self.client.close()


class DeployExecutor:
    def __init__(self, cfg: Dict[str, Any], logger: Callable[[str], None]):
        self.cfg = merge_cfg_with_defaults(cfg)
        self.log = logger

    def _status(self, message: str) -> None:
        ota_emit_status(self.cfg, message)

    def run_sync(self) -> bool:
        self.log("🚀 开始【独立文件同步】任务...")
        return self._run_task(mode="sync")

    def run_ota(self) -> bool:
        self.log("🚀 开始【独立 OTA 升级】任务...")
        return self._run_task(mode="ota")

    def _run_task(self, mode: str) -> bool:
        s100_ssh = None
        x5_ssh = None
        try:
            self.log(f">>> 连接 S100 @ {self.cfg['s100_ip']}")
            s100_ssh = SSHHelper(
                self.cfg["s100_ip"],
                self.cfg["username"],
                self.cfg["password"],
                identity_file=self.cfg["identity_file"],
                use_key=self.cfg["use_identity_file"],
                timeout=self.cfg["connect_timeout"],
                logger=self.log,
            )
            s100_ssh.connect()

            needs_x5 = False
            if mode == "ota":
                needs_x5 = self.cfg.get("ota_target_x5", False)
            else:
                needs_x5 = any(item.get("x5") for item in self.cfg.get("sync_items", []))

            if needs_x5:
                self.log(f">>> 连接 X5 @ {self.cfg['x5_ip']} (通过隧道)")
                x5_ssh = SSHHelper(
                    self.cfg["x5_ip"],
                    self.cfg["username"],
                    self.cfg["password"],
                    identity_file=self.cfg["identity_file"],
                    use_key=self.cfg["use_identity_file"],
                    jump_client=s100_ssh.client,
                    logger=self.log,
                )
                x5_ssh.connect()

            if mode == "sync":
                self._do_sync_work(s100_ssh, x5_ssh)
            else:
                # 单板/双板均按 S100 lifecycle 选加密或未加密包（GUI 手动选包时 auto_pkg=False 跳过探测）
                self._select_ota_packages_by_lifecycle(s100_ssh)
                ok_cfg, err = validate_ota_cfg(self.cfg)
                if not ok_cfg:
                    raise RuntimeError(err)
                enc_flag = resolve_manifest_check_encryption(self.cfg)
                if enc_flag is not None:
                    ok_manifest, err_manifest = validate_ota_packages_match_manifest(
                        self.cfg, encrypted=enc_flag
                    )
                    if not ok_manifest:
                        raise RuntimeError(err_manifest)
                    kind = "加密" if enc_flag else "未加密"
                    mp = resolve_active_manifest_path(self.cfg, enc_flag)
                    self.log(
                        f"✅ 【{kind}】升级包文件名与 manifest 一致: {os.path.basename(mp)}"
                    )
                    self.log("正在核对烧录包 MD5...")
                    ok_md5, md5_msg = validate_ota_packages_md5_match_manifest(
                        self.cfg, encrypted=enc_flag
                    )
                    if not ok_md5:
                        raise RuntimeError(md5_msg)
                    self.log(f"✅ {md5_msg.splitlines()[0]}")
                pkg_expected = build_expected_ota_version_from_packages(self.cfg)
                if pkg_expected:
                    self.cfg["expected_ota_version"] = pkg_expected
                self.capture_ota_baseline_versions()
                self._do_ota_work(s100_ssh, x5_ssh)

            if mode == "sync":
                self.log("🎉 文件同步任务执行完毕。")
            else:
                self.log("✅ OTA 上传与提交完成，等待版本校验…")
            return True
        except Exception as e:
            self.log(f"❌ 运行失败: {e}")
            return False
        finally:
            if x5_ssh:
                x5_ssh.close()
            if s100_ssh:
                s100_ssh.close()

    def _select_ota_packages_by_lifecycle(self, s100_ssh: SSHHelper) -> None:
        """按界面确认或 S100 lifecycle 选择加密/未加密升级包，并解析 manifest。"""
        encrypted: Optional[bool] = None

        if self.cfg.get("auto_pkg_by_lifecycle") is False:
            if self.cfg.get("ota_pkg_encrypted") is not None:
                encrypted = bool(self.cfg["ota_pkg_encrypted"])
                kind = "加密" if encrypted else "未加密"
                self.log(f"[双板 OTA] 使用界面确认的【{kind}】升级包")
            else:
                self.log("[双板 OTA] 未指定加密类型，保持当前路径")
                return
        else:
            self.log(">>> 双板 OTA：探测 S100 lifecycle（provision_tool --get-lifecycle）…")
            lifecycle, summary = read_s100_lifecycle(s100_ssh)
            encrypted = lifecycle >= 4
            kind = "加密" if encrypted else "未加密"
            self.log(f"[lifecycle] {summary.splitlines()[0] if summary else '(无输出)'}")
            self.log(
                f"[lifecycle] 解析值={lifecycle} → 选用【{kind}】升级包 "
                f"(>=4 加密，0-3 未加密)"
            )
            self.cfg["s100_lifecycle"] = lifecycle
            self.cfg["ota_pkg_encrypted"] = encrypted

        kind = "加密" if encrypted else "未加密"
        lifecycle = int(self.cfg.get("s100_lifecycle") or (4 if encrypted else 0))
        explicit_mp = get_configured_ota_manifest(self.cfg, encrypted)
        cfg_mk = "ota_manifest_encrypted" if encrypted else "ota_manifest_plain"
        configured_raw = str(self.cfg.get(cfg_mk) or "").strip()
        if configured_raw and not explicit_mp:
            self.log(
                f"[选包] ⚠️ 【{kind}】manifest 路径无效或文件不存在，将在包目录自动发现: "
                f"{configured_raw}"
            )
        pkg_dir = resolve_ota_package_directory(self.cfg)
        if explicit_mp and not pkg_dir:
            pkg_dir = os.path.dirname(explicit_mp)

        if explicit_mp or pkg_dir:
            scanned, manifest_path = scan_package_dir_for_lifecycle(
                pkg_dir or os.path.dirname(explicit_mp or "") or ".",
                lifecycle,
                cfg=self.cfg,
            )
            missing = [k for k in _REQUIRED_MANIFEST_KEYS if not scanned.get(k)]
            if not missing:
                if manifest_path:
                    self.log(f"[选包] 使用 manifest: {manifest_path}")
                    self.cfg["ota_manifest_path"] = manifest_path
                for key in _REQUIRED_MANIFEST_KEYS:
                    path = scanned[key]
                    self.cfg[key] = path
                    self.cfg[ota_pkg_storage_key(key, encrypted)] = path
                    self.log(f"[选包] {key}: {os.path.basename(path)}")
                return

        if apply_stored_ota_packages(self.cfg, encrypted):
            self.log(f"[选包] 使用界面配置的【{kind}】四套 zip 路径")
            for key in _REQUIRED_MANIFEST_KEYS:
                self.log(f"[选包] {key}: {os.path.basename(self.cfg[key])}")
            return

        raise RuntimeError(
            f"【{kind}】未配置 manifest 或四套 zip。"
            f"请在界面填写【{kind}】升级包（manifest 或四个 zip）。"
        )

    def _ssh_helper(self, hostname: str, jump_client=None) -> SSHHelper:
        return SSHHelper(
            hostname,
            self.cfg["username"],
            self.cfg["password"],
            identity_file=self.cfg.get("identity_file"),
            use_key=self.cfg.get("use_identity_file"),
            timeout=self.cfg.get("connect_timeout", 5),
            jump_client=jump_client,
            logger=self.log,
        )

    def _connect_ssh_for_label(self, label: str) -> Optional[SSHHelper]:
        """连接 S100 或经 S100 隧道连接 X5。"""
        try:
            if label == "S100":
                ssh = self._ssh_helper(self.cfg["s100_ip"])
                ssh.connect()
                return ssh
            if label == "X5":
                # X5 与刷包阶段一致：经 S100 跳板隧道连接（PC 通常无法直连 192.168.127.x）
                try:
                    s100_jump = self._ssh_helper(self.cfg["s100_ip"])
                    s100_jump.connect()
                except Exception as exc:
                    self.log(f"[X5 SSH] 连接 S100 跳板失败: {exc}")
                    return None
                x5 = self._ssh_helper(
                    self.cfg["x5_ip"],
                    jump_client=s100_jump.client,
                )
                x5.connect()
                x5._s100_jump = s100_jump  # type: ignore[attr-defined]
                return x5
        except Exception as exc:
            self.log(f"[{label} SSH] 连接失败: {exc}")
            return None
        return None

    def _close_ssh_chain(self, ssh: Optional[SSHHelper]) -> None:
        if ssh is None:
            return
        jump = getattr(ssh, "_s100_jump", None)
        try:
            ssh.close()
        except Exception:
            pass
        if jump is not None:
            try:
                jump.close()
            except Exception:
                pass

    def _tail_remote_log(self, ssh: SSHHelper, path: str, lines: int = 25) -> None:
        _, text, _ = _ssh_exec_read(ssh, f"tail -{lines} '{path}' 2>/dev/null")
        for line in (text or "").splitlines():
            line = line.rstrip()
            if line:
                self.log(f"  | {line}")

    def _clear_remote_ota_state(self, ssh: SSHHelper, label: str) -> None:
        """新一次 OTA 前清除上次 /tmp 与 /app 结果，避免第二次升级误读旧 255。"""
        low = label.lower()
        persist = f"{OTA_TMUX_RC_PERSIST_PREFIX}_{low}"
        paths = (
            f"/tmp/ota_{low}.result",
            f"/tmp/ota_{low}.log",
            persist,
        )
        if label == "S100":
            paths = paths + ("/tmp/ota_merge.detail",)
        joined = " ".join(f"'{p}'" for p in paths)
        self._exec_and_check(ssh, f"rm -f {joined}", f"{label} OTA", log_fail=False)
        self.log(f"[{label} OTA] 已清除上次 OTA 结果标记（/tmp 与 {persist}）")

    def _tmux_ota_session_running(self, ssh: SSHHelper, label: str) -> bool:
        session = f"ota_{label.lower()}"
        rc, _, _ = _ssh_exec_read(
            ssh, f"tmux has-session -t {session} 2>/dev/null"
        )
        return rc == 0

    def _read_tmux_ota_rc(self, ssh: SSHHelper, label: str) -> Optional[int]:
        """读取 tmux OTA 退出码：/tmp/result → 日志 →（会话已结束）/app 备份。"""
        low = label.lower()
        persist = f"{OTA_TMUX_RC_PERSIST_PREFIX}_{low}"
        _, rc_s, _ = _ssh_exec_read(ssh, f"cat /tmp/ota_{low}.result 2>/dev/null")
        rc_s = (rc_s or "").strip()
        if rc_s.isdigit():
            return int(rc_s)
        _, log_line, _ = _ssh_exec_read(
            ssh,
            f"grep -E 'tmux_done_{low}_rc=|^{low}_rc=' /tmp/ota_{low}.log 2>/dev/null | tail -1",
        )
        m = re.search(r"=(\d+)", log_line or "")
        if m:
            return int(m.group(1))
        tmux_running = self._tmux_ota_session_running(ssh, label)
        if not tmux_running:
            _, rc_p, _ = _ssh_exec_read(ssh, f"cat {persist} 2>/dev/null")
            rc_p = (rc_p or "").strip()
            if rc_p.isdigit():
                return int(rc_p)
        return None

    def _shell_quote(self, text: str) -> str:
        return shlex.quote(str(text))

    def _build_x5_remote_ssh_cmd(self, remote_shell: str, *, s100_ssh: Optional[SSHHelper] = None) -> str:
        """S100 上 ssh 到 X5 执行命令（优先密钥，否则 sshpass+密码）。"""
        x5_ip = self.cfg["x5_ip"]
        x5_auth, _ = (
            self._build_s100_to_x5_auth(s100_ssh) if s100_ssh else ("", "")
        )
        base = (
            "-o LogLevel=ERROR -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            "-o ConnectTimeout=8"
        )
        inner = self._shell_quote(remote_shell)
        if x5_auth and "IdentitiesOnly=yes" in x5_auth:
            return f"ssh {base} {x5_auth} root@{x5_ip} {inner}"
        password = str(self.cfg.get("password") or "")
        if password:
            pwd = password.replace("'", "'\\''")
            return (
                f"command -v sshpass >/dev/null 2>&1 && "
                f"sshpass -p '{pwd}' ssh {base} -o PreferredAuthentications=password "
                f"-o BatchMode=yes root@{x5_ip} {inner} || "
                f"ssh {base} {x5_auth or '-o BatchMode=yes'} root@{x5_ip} {inner}"
            )
        return f"ssh {base} {x5_auth or '-o BatchMode=yes'} root@{x5_ip} {inner}"

    def _exec_on_x5_via_s100(
        self, s100_ssh: SSHHelper, remote_shell: str
    ) -> Tuple[int, str, str]:
        """经 S100 在 X5 执行 shell，返回 (ssh外层rc, stdout, stderr)。"""
        cmd = self._build_x5_remote_ssh_cmd(remote_shell, s100_ssh=s100_ssh)
        return _ssh_exec_read(s100_ssh, cmd)

    def _read_x5_tmux_ota_rc_via_s100(self, s100_ssh: SSHHelper) -> Optional[int]:
        """经 S100 跳板读 X5 的 ota 结果（reboot 后读 /app 备份）。"""
        persist = f"{OTA_TMUX_RC_PERSIST_PREFIX}_x5"
        probe_rc, _, _ = self._exec_on_x5_via_s100(
            s100_ssh, "echo ota_x5_probe_ok"
        )
        if probe_rc == 255:
            fail_count = int(self.cfg.get("_x5_ssh_fail_count") or 0) + 1
            self.cfg["_x5_ssh_fail_count"] = fail_count
            if fail_count >= 3:
                self.log("[X5] 连续 3 次经 S100 连 X5 失败，判定为 reboot，刷写阶段结束")
                self.cfg["_x5_ssh_fail_count"] = 0
                return -2
            self.log(f"[X5] 经 S100 连 X5 失败（{fail_count}/3），暂不结束等待")
            return None

        self.cfg["_x5_ssh_fail_count"] = 0

        _, rc_s, _ = self._exec_on_x5_via_s100(
            s100_ssh, "cat /tmp/ota_x5.result 2>/dev/null"
        )
        rc_s = (rc_s or "").strip()
        if rc_s.isdigit():
            return int(rc_s)

        _, log_line, _ = self._exec_on_x5_via_s100(
            s100_ssh,
            "grep -E 'tmux_done_x5_rc=|^x5_rc=' /tmp/ota_x5.log 2>/dev/null | tail -1",
        )
        m = re.search(r"=(\d+)", log_line or "")
        if m:
            return int(m.group(1))

        rc_tmux, _, _ = self._exec_on_x5_via_s100(
            s100_ssh, "tmux has-session -t ota_x5 2>/dev/null"
        )
        tmux_running = rc_tmux == 0
        if not tmux_running:
            _, rc_p, _ = self._exec_on_x5_via_s100(
                s100_ssh, f"cat {persist} 2>/dev/null"
            )
            rc_p = (rc_p or "").strip()
            if rc_p.isdigit():
                return int(rc_p)
        return None

    def _diagnose_tmux_pending(
        self,
        s100_ssh: Optional[SSHHelper],
        targets: List[str],
        done: Dict[str, Optional[int]],
    ) -> None:
        """打印 tmux 仍「进行中」时的可读原因（便于排查）。"""
        for label in targets:
            if done.get(label) is not None:
                continue
            if label == "X5" and s100_ssh is not None:
                pr, _, _ = self._exec_on_x5_via_s100(s100_ssh, "echo ok")
                if pr == 255:
                    self.log(f"  [{label}] 经 S100 连 X5 失败（可能 reboot 中）")
                    continue
                tr, tout, _ = self._exec_on_x5_via_s100(
                    s100_ssh,
                    "tmux has-session -t ota_x5 2>/dev/null && echo running || echo stopped",
                )
                persist = f"{OTA_TMUX_RC_PERSIST_PREFIX}_x5"
                _, pv, _ = self._exec_on_x5_via_s100(
                    s100_ssh, f"cat {persist} 2>/dev/null || echo empty"
                )
                pv = (pv or "").strip()
                running = tr == 0 and "running" in (tout or "")
                self.log(
                    f"  [{label}] tmux={'运行' if running else '已结束'}"
                    f", {persist}={pv or '无'}"
                )
                continue
            ssh = self._connect_ssh_for_label(label)
            if ssh is None:
                self.log(f"  [{label}] SSH 不可用")
                continue
            try:
                running = self._tmux_ota_session_running(ssh, label)
                low = label.lower()
                persist = f"{OTA_TMUX_RC_PERSIST_PREFIX}_{low}"
                _, rv, _ = _ssh_exec_read(
                    ssh, f"cat /tmp/ota_{low}.result 2>/dev/null || cat {persist} 2>/dev/null"
                )
                rv = (rv or "").strip() or "无"
                self.log(
                    f"  [{label}] tmux={'运行' if running else '已结束'}"
                    f", result/persist={rv}"
                )
            finally:
                self._close_ssh_chain(ssh)

    def _try_tmux_version_fallback(self, targets: List[str]) -> bool:
        """tmux exit 读不到但设备版本已到位时，允许进入版本校验。"""
        expected = self.cfg.get("expected_ota_version") or {}
        if not expected:
            return False
        baseline = self.cfg.get("ota_baseline_versions") or {}
        ok_count = int(self.cfg.get("_tmux_fallback_ok_count") or 0)
        all_matched, _ = self._poll_ota_versions_once(targets, expected, baseline)
        if all_matched:
            ok_count += 1
            self.cfg["_tmux_fallback_ok_count"] = ok_count
            need = max(1, int(self.cfg.get("ota_tmux_version_fallback_confirm") or 2))
            self.log(
                f"  [兜底] 设备版本已与升级包一致 ({ok_count}/{need})"
                f"（tmux exit 码仍未齐）"
            )
            if ok_count >= need:
                self.log(
                    "⚠️ tmux exit 码未能全部读取，但设备版本已稳定匹配升级包；"
                    "跳过 tmux 等待，进入正式版本校验"
                )
                return True
        else:
            self.cfg["_tmux_fallback_ok_count"] = 0
        return False

    def capture_ota_baseline_versions(self) -> None:
        """OTA 开始前记录设备版本，便于日志排查（不能代替 ota_tool exit code）。"""
        baseline: Dict[str, Dict[str, str]] = {}
        for label, key in (("S100", "ota_target_s100"), ("X5", "ota_target_x5")):
            if not self.cfg.get(key):
                continue
            ssh = self._connect_ssh_for_label(label)
            if ssh is None:
                continue
            try:
                act_app, act_sys = read_remote_versions(ssh)
                baseline[label] = {"app_version": act_app, "sys_version": act_sys}
            finally:
                self._close_ssh_chain(ssh)
        self.cfg["ota_baseline_versions"] = baseline
        if baseline:
            self.log(f"[版本基线] OTA 开始前设备版本: {baseline}")
            expected = self.cfg.get("expected_ota_version") or {}
            for label, block in baseline.items():
                exp_app, exp_sys = _expected_ota_block(expected, label)
                if exp_app and version_strings_match(exp_app, block.get("app_version", "")):
                    if exp_sys and version_strings_match(exp_sys, block.get("sys_version", "")):
                        self.log(
                            f"[版本基线] ⚠️ {label} 读数已与升级包相同；"
                            f"仍须刷写完成且版本连续稳定一致才判通过"
                        )

    def _clear_arp_before_version_verify(self, labels: List[str]) -> None:
        if not self.cfg.get("ota_version_clear_arp_before_verify", True):
            return
        ips: List[str] = []
        if "S100" in labels and self.cfg.get("s100_ip"):
            ips.append(str(self.cfg["s100_ip"]))
        if "X5" in labels and self.cfg.get("x5_ip"):
            ips.append(str(self.cfg["x5_ip"]))
        if not ips:
            return
        self.log("版本校验前清除本机 ARP（避免 reboot 后 SSH 连错设备）…")
        cleared, failed = clear_windows_arp_for_ips(ips)
        for ip in cleared:
            self.log(f"  已清除 ARP: {ip}")
        for ip, err in failed:
            self.log(f"  清除 ARP 跳过/失败 ({ip}): {err}")

    def _poll_ota_versions_once(
        self,
        targets: List[str],
        expected: Dict[str, Any],
        baseline: Dict[str, Any],
    ) -> Tuple[bool, Dict[str, Tuple[str, str]]]:
        """单次读取各板版本并与期望比对。返回 (是否全部匹配, {label: (app, sys)})."""
        all_matched = True
        snapshot: Dict[str, Tuple[str, str]] = {}
        for label in targets:
            exp_app, exp_sys = _expected_ota_block(expected, label)
            if not exp_app and not exp_sys:
                self.log(f"[{label}] ❌ 配置中缺少 APP/SYS 期望版本")
                all_matched = False
                continue

            ssh = self._connect_ssh_for_label(label)
            if ssh is None:
                self.log(f"[{label}] ⚠️ SSH 未就绪，无法读版本（可能仍在 reboot）")
                all_matched = False
                continue
            try:
                act_app, act_sys, diag = read_remote_versions_verbose(ssh)
                snapshot[label] = (act_app, act_sys)
                ok_app = version_strings_match(exp_app, act_app)
                ok_sys = version_strings_match(exp_sys, act_sys)
                base = baseline.get(label) or {}
                base_app = base.get("app_version", "")
                base_sys = base.get("sys_version", "")
                unchanged = (
                    version_strings_match(act_app, base_app)
                    and version_strings_match(act_sys, base_sys)
                    if base_app or base_sys
                    else False
                )
                line = (
                    f"[{label}] APP 期望={exp_app!r} 实际={act_app!r} "
                    f"{'✓' if ok_app else '✗'} | "
                    f"SYS 期望={exp_sys!r} 实际={act_sys!r} {'✓' if ok_sys else '✗'}"
                )
                if diag:
                    line += f" | {diag}"
                if unchanged:
                    line += " | 与OTA前相同"
                self.log(line)
                if not ok_app or not ok_sys:
                    all_matched = False
            finally:
                self._close_ssh_chain(ssh)
        return all_matched, snapshot

    def _verify_engineer_version_after_ssh(
        self,
        targets: List[str],
        expected: Dict[str, Any],
        ssh_snapshot: Dict[str, Tuple[str, str]],
    ) -> bool:
        """SSH 终检通过后，用工程模式 version=0 再读一遍并与 SSH 交叉比对。"""
        if not self.cfg.get("ota_version_engineer_verify", True):
            return True

        host = str(self.cfg.get("s100_ip") or "").strip()
        if not host:
            self.log("❌ 未配置 s100_ip，无法进行 version=0 二次校验")
            return False

        port = int(self.cfg.get("engineer_port") or 3579)
        timeout = float(self.cfg.get("ota_version_engineer_timeout_sec") or 30)
        retries = max(1, int(self.cfg.get("ota_version_engineer_retries") or 3))
        enter_fac = bool(self.cfg.get("ota_version_engineer_enter_fac", True))
        cross_check = bool(self.cfg.get("ota_version_cross_check_ssh", True))

        self.log(
            f"⏳ 二次校验：工程模式 version=0 @ {host}:{port}"
            f"{'（先 enfac=1,1%）' if enter_fac else ''} …"
        )

        last_err = ""
        for attempt in range(1, retries + 1):
            if attempt > 1:
                time.sleep(5.0)
            try:
                if enter_fac:
                    fac_resp = engineer_service_post(
                        host,
                        port,
                        "enfac=1,1%",
                        {"op": "1", "en": "1"},
                        timeout_sec=timeout,
                    )
                    if str(fac_resp.get("status", "")).lower() not in (
                        "success",
                        "ok",
                    ):
                        self.log(
                            f"  [enfac] ⚠️ status={fac_resp.get('status')} "
                            f"message={fac_resp.get('message', '')}"
                        )
                resp = engineer_service_post(
                    host,
                    port,
                    "version=0%",
                    {"op": "0"},
                    timeout_sec=timeout,
                )
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_err = str(exc)
                self.log(f"  [version=0] 第 {attempt}/{retries} 次请求失败: {exc}")
                continue

            if str(resp.get("status", "")).lower() not in ("success", "ok"):
                last_err = str(resp.get("message") or resp.get("status") or "unknown")
                self.log(
                    f"  [version=0] 第 {attempt}/{retries} 次: "
                    f"status={resp.get('status')} message={last_err}"
                )
                continue

            payload = normalize_engineer_version_payload(resp)
            if payload is None:
                last_err = "响应无法解析为版本 JSON"
                self.log(f"  [version=0] 第 {attempt}/{retries} 次: {last_err}")
                continue

            all_ok = True
            eng_snap: Dict[str, Tuple[str, str]] = {}
            for label in targets:
                block = payload.get(label, {})
                if not isinstance(block, dict):
                    block = {}
                act_app = str(block.get("app_version", "") or "").strip()
                act_sys = str(block.get("sys_version", "") or "").strip()
                eng_snap[label] = (act_app, act_sys)
                exp_app, exp_sys = _expected_ota_block(expected, label)
                ok_app = version_strings_match(exp_app, act_app)
                ok_sys = version_strings_match(exp_sys, act_sys)
                self.log(
                    f"  [version=0][{label}] APP 期望={exp_app!r} 实际={act_app!r} "
                    f"{'✓' if ok_app else '✗'} | "
                    f"SYS 期望={exp_sys!r} 实际={act_sys!r} {'✓' if ok_sys else '✗'}"
                )
                if not ok_app or not ok_sys:
                    all_ok = False

            if not all_ok:
                last_err = "version=0 读到的版本与期望不一致"
                continue

            if cross_check:
                cross_ok = True
                for label in targets:
                    ssh_v = ssh_snapshot.get(label)
                    eng_v = eng_snap.get(label)
                    if not ssh_v or not eng_v:
                        continue
                    ssh_app, ssh_sys = ssh_v
                    eng_app, eng_sys = eng_v
                    app_same = version_strings_match(ssh_app, eng_app)
                    sys_same = version_strings_match(ssh_sys, eng_sys)
                    if app_same and sys_same:
                        self.log(f"  [{label}] SSH 与 version=0 一致 ✓")
                    else:
                        cross_ok = False
                        self.log(
                            f"  ❌ [{label}] SSH 与 version=0 不一致: "
                            f"SSH APP/SYS=({ssh_app!r}, {ssh_sys!r}) vs "
                            f"version=0=({eng_app!r}, {eng_sys!r})"
                        )
                if not cross_ok:
                    last_err = "SSH 与 version=0 读数不一致（可能存在假通过）"
                    continue

            self.log("✅ 工程模式 version=0 二次校验通过")
            return True

        self.log(f"❌ 工程模式 version=0 二次校验失败: {last_err}")
        return False

    def _tmux_exit_suspect(self, code: int) -> bool:
        raw = self.cfg.get("ota_tmux_suspect_exit_codes") or (125, 255)
        try:
            suspects = {int(x) for x in raw}
        except (TypeError, ValueError):
            suspects = {125, 255}
        return int(code) in suspects

    def wait_tmux_ota_complete(self, timeout_sec: int = 7200, poll_interval: int = 10) -> bool:
        """可选：轮询 tmux exit 码；超时或非可疑 exit 时仍进入 SSH 版本校验（最终判定）。"""
        targets: List[str] = []
        if self.cfg.get("ota_target_s100"):
            targets.append("S100")
        if self.cfg.get("ota_target_x5"):
            targets.append("X5")
        if not targets:
            return True

        self.log(
            f"⏳ 轮询 tmux exit 码（最多 {timeout_sec}s，每 {poll_interval}s；"
            f"最终以版本校验为准）…"
        )
        self._status(f"⏳ tmux OTA 进行中（最多等 {timeout_sec}s）…")
        fallback_after = float(self.cfg.get("ota_tmux_version_fallback_sec") or 120)
        if fallback_after > 0:
            self.log(
                f"  ≥{int(fallback_after)}s 后若版本已与升级包一致，提前进入版本校验"
            )
        elapsed = 0
        dual = "S100" in targets and "X5" in targets

        while elapsed < timeout_sec:
            done: Dict[str, Optional[int]] = {t: None for t in targets}
            s100_ssh: Optional[SSHHelper] = None
            if "S100" in targets or (dual and "X5" in targets):
                s100_ssh = self._connect_ssh_for_label("S100")

            try:
                if s100_ssh and "S100" in targets:
                    done["S100"] = self._read_tmux_ota_rc(s100_ssh, "S100")

                if dual and s100_ssh and done.get("X5") is None:
                    _, detail, _ = _ssh_exec_read(
                        s100_ssh, "cat /tmp/ota_merge.detail 2>/dev/null"
                    )
                    xm = re.search(r"x5_rc=(\d+)", detail or "")
                    if xm:
                        done["X5"] = int(xm.group(1))
                    if done.get("X5") is None:
                        x5_rc = self._read_x5_tmux_ota_rc_via_s100(s100_ssh)
                        if x5_rc is not None:
                            done["X5"] = x5_rc
            finally:
                self._close_ssh_chain(s100_ssh)

            if "X5" in targets and done.get("X5") is None:
                x5 = self._connect_ssh_for_label("X5")
                if x5:
                    try:
                        done["X5"] = self._read_tmux_ota_rc(x5, "X5")
                    finally:
                        self._close_ssh_chain(x5)

            if all(done[t] is not None for t in targets):
                failed = [t for t in targets if done[t] != 0]
                if not failed:
                    self.log(
                        "✅ tmux OTA 已全部完成: "
                        + ", ".join(f"{t}=exit 0" for t in targets)
                    )
                    return True
                suspect_only = failed and all(
                    self._tmux_exit_suspect(int(done[t] or 0)) for t in failed
                )
                for label in failed:
                    code = int(done[label] or 0)
                    if self._tmux_exit_suspect(code):
                        self.log(
                            f"⚠️ [{label} tmux] exit={code} "
                            f"（多为抓结果超时/旧标记，不代表 ota_tool 失败）"
                        )
                    else:
                        self.log(f"❌ [{label} tmux] ota_tool 失败 exit={code}")
                    log_path = f"/tmp/ota_{label.lower()}.log"
                    ssh = self._connect_ssh_for_label(label)
                    if ssh:
                        try:
                            self.log(f"[{label} tmux] 日志尾部 {log_path}:")
                            self._tail_remote_log(ssh, log_path)
                        finally:
                            self._close_ssh_chain(ssh)
                if suspect_only or self.cfg.get("ota_trust_version_over_tmux_exit", True):
                    self.log(
                        "⚠️ tmux exit 未全为 0，改以 SSH + version=0 版本校验为最终判定"
                    )
                    return True
                return False

            if fallback_after > 0 and elapsed >= fallback_after:
                s100_diag = self._connect_ssh_for_label("S100")
                try:
                    if self._try_tmux_version_fallback(targets):
                        return True
                finally:
                    self._close_ssh_chain(s100_diag)

            if elapsed > 0 and elapsed % 60 == 0:
                known = [
                    f"{t}={'进行中' if done[t] is None else done[t]}"
                    for t in targets
                ]
                extra = ""
                if dual and done.get("X5") is None and elapsed >= 120:
                    extra = "（X5 reboot 后请经 S100+sshpass 读 /app 备份）"
                self.log(
                    f"… tmux OTA 进行中，已等待 {elapsed}s（"
                    + "; ".join(known)
                    + f"）{extra}…"
                )
                self._status(
                    f"⏳ tmux OTA 进行中，已等待 {elapsed}s（"
                    + "; ".join(known)
                    + "）"
                )
                s100_diag = self._connect_ssh_for_label("S100")
                try:
                    self._diagnose_tmux_pending(s100_diag, targets, done)
                finally:
                    self._close_ssh_chain(s100_diag)

            time.sleep(poll_interval)
            elapsed += poll_interval

        self.log(
            f"⚠️ tmux exit 轮询已达 {timeout_sec}s 上限（可能仍在「进行中」），"
            f"进入 SSH + version=0 版本校验（以此为准）"
        )
        self._status("🔍 进入版本校验（SSH + version=0）…")
        return True

    def _ota_verify_targets(self) -> List[str]:
        targets: List[str] = []
        if self.cfg.get("ota_target_s100"):
            targets.append("S100")
        if self.cfg.get("ota_target_x5"):
            targets.append("X5")
        return targets

    def _try_engineer_version_match_once(
        self,
        targets: List[str],
        expected: Dict[str, Any],
        *,
        log: bool = False,
    ) -> bool:
        """经 S100 工程服务 version=0 读各板版本并与期望比对（单次）。"""
        host = str(self.cfg.get("s100_ip") or "").strip()
        if not host:
            return False
        port = int(self.cfg.get("engineer_port") or 3579)
        timeout = float(self.cfg.get("ota_version_engineer_timeout_sec") or 30)
        enter_fac = bool(self.cfg.get("ota_version_engineer_enter_fac", True))
        try:
            if enter_fac:
                engineer_service_post(
                    host,
                    port,
                    "enfac=1,1%",
                    {"op": "1", "en": "1"},
                    timeout_sec=timeout,
                )
            resp = engineer_service_post(
                host,
                port,
                "version=0%",
                {"op": "0"},
                timeout_sec=timeout,
            )
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return False
        if str(resp.get("status", "")).lower() not in ("success", "ok"):
            return False
        payload = normalize_engineer_version_payload(resp)
        if payload is None:
            return False
        all_ok = True
        for label in targets:
            block = payload.get(label, {})
            if not isinstance(block, dict):
                block = {}
            act_app = str(block.get("app_version", "") or "").strip()
            act_sys = str(block.get("sys_version", "") or "").strip()
            exp_app, exp_sys = _expected_ota_block(expected, label)
            ok_app = version_strings_match(exp_app, act_app)
            ok_sys = version_strings_match(exp_sys, act_sys)
            if log:
                self.log(
                    f"  [version=0][{label}] APP 期望={exp_app!r} 实际={act_app!r} "
                    f"{'✓' if ok_app else '✗'} | "
                    f"SYS 期望={exp_sys!r} 实际={act_sys!r} {'✓' if ok_sys else '✗'}"
                )
            if not ok_app or not ok_sys:
                all_ok = False
        return all_ok

    def ota_versions_already_match(self, expected: Dict[str, Any]) -> bool:
        if not expected:
            return False
        targets = self._ota_verify_targets()
        if not targets:
            return False

        baseline = self.cfg.get("ota_baseline_versions") or {}

        ssh_ok, ssh_snapshot = self._poll_ota_versions_once(targets, expected, baseline)
        if ssh_ok:
            if self._is_different_from_baseline(ssh_snapshot, baseline):
                return True
            return False

        if not self.cfg.get("ota_flash_complete_version_fallback", True):
            return False

        eng_ok = self._try_engineer_version_match_once(targets, expected, log=False)
        if eng_ok:
            ssh_ok2, ssh_snapshot2 = self._poll_ota_versions_once(targets, expected, baseline)
            if ssh_ok2 and self._is_different_from_baseline(ssh_snapshot2, baseline):
                return True
        return False

    def _is_different_from_baseline(
        self, snapshot: Dict[str, Tuple[str, str]], baseline: Dict[str, Any]
    ) -> bool:
        for label, (act_app, act_sys) in snapshot.items():
            base = baseline.get(label) or {}
            base_app = base.get("app_version", "")
            base_sys = base.get("sys_version", "")
            if version_strings_match(act_app, base_app) and version_strings_match(act_sys, base_sys):
                return False
        return True

    def wait_for_ota_flash_complete(
        self, timeout_sec: int = 3600, poll_interval: int = 10
    ) -> bool:
        """tmux 模式：只等待 tmux 会话结束，不再依赖 result 文件。"""
        if not self.cfg.get("use_tmux"):
            return True

        targets: List[str] = []
        if self.cfg.get("ota_target_s100"):
            targets.append("S100")
        if self.cfg.get("ota_target_x5"):
            targets.append("X5")
        if not targets:
            return True

        cap = int(timeout_sec or self.cfg.get("ota_wait_flash_before_power_cycle_sec") or 3600)
        self.log(
            f"⏳ 等待设备刷写完成（只等 tmux 会话结束，最长 {cap}s）…"
        )
        self._status("⏳ 等待设备刷写完成…")
        elapsed = 0

        while elapsed < cap:
            all_done = True
            for label in targets:
                ssh = self._connect_ssh_for_label(label)
                if ssh is None:
                    all_done = False
                    continue
                try:
                    if self._tmux_ota_session_running(ssh, label):
                        all_done = False
                finally:
                    self._close_ssh_chain(ssh)

            if all_done:
                self.log("✅ 设备刷写已结束（tmux 会话已全部结束）")
                return True

            if elapsed > 0 and elapsed % 60 == 0:
                self.log(f"… 刷写进行中，已等待 {elapsed}s …")
            time.sleep(poll_interval)
            elapsed += poll_interval

        self.log(f"⚠️ 等待刷写结果已达 {cap}s 上限，仍将继续后续流程")
        return True

    def verify_ota_versions_via_ssh(
        self, timeout_sec: int = OTA_DEFAULT_VERIFY_TIMEOUT_SEC, poll_interval: int = 15
    ) -> bool:
        """OTA 完成后通过 SSH 读取设备版本，与 expected_ota_version（导入包配置）比对。"""
        expected = self.cfg.get("expected_ota_version") or {}
        if not expected:
            self.log("❌ 未配置 expected_ota_version，无法进行版本校验")
            return False

        targets: List[str] = []
        if self.cfg.get("ota_target_s100"):
            targets.append("S100")
        if self.cfg.get("ota_target_x5"):
            targets.append("X5")
        if not targets:
            self.log("❌ 未选择 OTA 目标，无法校验版本")
            return False

        self.log(f"⏳ 轮询设备版本（仅校验: {', '.join(targets)}）…")
        self._status("🔍 版本校验中（SSH 读版本 + version=0）…")
        self.log(f"  最长 {timeout_sec}s（约 {timeout_sec // 60}min），间隔 {poll_interval}s")
        if self.cfg.get("ota_version_engineer_verify", True):
            self.log(
                "  SSH 连续确认通过后，将再执行工程模式 version=0 二次校验"
            )
        self.log(f"  期望版本: {expected}")
        self.log(f"  APP: cat {REMOTE_APP_VERSION_FILE}  → VERSION=")
        self.log(f"  SYS: cat {REMOTE_SYS_VERSION_FILE}")
        baseline = self.cfg.get("ota_baseline_versions") or {}
        if baseline:
            self.log(f"  OTA 前基线: {baseline}")

        self._clear_arp_before_version_verify(targets)
        self._wait_for_ssh_ready_after_ota(targets)

        stabilize = float(self.cfg.get("ota_version_stabilize_sec") or 45)
        if stabilize > 0:
            self.log(
                f"  等待 {int(stabilize)}s 让 reboot 后版本文件稳定（避免读到过渡态）…"
            )
            time.sleep(stabilize)

        confirm_need = max(1, int(self.cfg.get("ota_version_confirm_polls") or 3))
        final_recheck = float(self.cfg.get("ota_version_final_recheck_sec") or 30)
        confirm_count = 0
        last_snapshot: Dict[str, Tuple[str, str]] = {}

        elapsed = 0
        while elapsed < timeout_sec:
            all_matched, snapshot = self._poll_ota_versions_once(
                targets, expected, baseline
            )

            if all_matched:
                volatile = False
                if confirm_count > 0 and last_snapshot:
                    for label in targets:
                        prev = last_snapshot.get(label)
                        cur = snapshot.get(label)
                        if prev is not None and cur is not None and prev != cur:
                            self.log(
                                f"[{label}] ⚠️ 版本读数波动 "
                                f"APP/SYS {prev} → {cur}，重新累计确认"
                            )
                            confirm_count = 0
                            last_snapshot = {}
                            volatile = True
                            break
                if not volatile:
                    confirm_count += 1
                    last_snapshot = dict(snapshot)
                    self.log(
                        f"  版本一致 ({confirm_count}/{confirm_need})，"
                        f"{'继续确认…' if confirm_count < confirm_need else '准备终检…'}"
                    )
                    if confirm_count >= confirm_need:
                        if final_recheck > 0:
                            self.log(
                                f"  终检前再等待 {int(final_recheck)}s，"
                                f"确认版本不会回退…"
                            )
                            time.sleep(final_recheck)
                        final_ok, final_snap = self._poll_ota_versions_once(
                            targets, expected, baseline
                        )
                        if final_ok:
                            summary = ", ".join(
                                f"{lb} APP={final_snap[lb][0]!r} SYS={final_snap[lb][1]!r}"
                                for lb in targets
                                if lb in final_snap
                            )
                            self.log("✅ SSH 终检版本与本次升级包一致")
                            self.log(f"  SSH 终检: {summary}")
                            if self._verify_engineer_version_after_ssh(
                                targets, expected, final_snap
                            ):
                                self.log(
                                    "✅ OTA 判定通过（SSH 连续确认 + 工程模式 version=0）"
                                )
                                self._status("✅ OTA 升级完成，版本校验通过")
                                return True
                            self.log(
                                "❌ SSH 已通过但工程模式 version=0 未通过，"
                                "OTA 判定失败（请人工 version=0% 复核）"
                            )
                            return False
                        self.log("  ❌ 终检版本不一致或读不到，继续轮询…")
                        confirm_count = 0
                        last_snapshot = {}
            else:
                if confirm_count > 0:
                    self.log("  版本未全部匹配，确认计数已清零")
                confirm_count = 0
                last_snapshot = {}

            time.sleep(poll_interval)
            elapsed += poll_interval
            if elapsed % 60 == 0:
                self.log(f"… 已等待 {elapsed}s，继续轮询版本…")

        self.log(f"❌ 版本校验超时（{timeout_sec}s），设备版本未与本次升级包稳定匹配")
        return False

    def _s100_post_success_shell(
        self, log_file: str, eng_cmd: str, grn_cmd: str, *, tag: str
    ) -> str:
        """S100 刷写成功后的 tmux 收尾：默认不 reboot，亮绿屏并写日志。"""
        if self.cfg.get("ota_s100_auto_reboot", False):
            return (
                f"{eng_cmd}; {grn_cmd}; "
                f"echo '[S100 OTA] {tag}, reboot' >> '{log_file}'; "
                f"sync; reboot; "
            )
        return (
            f"{eng_cmd}; {grn_cmd}; "
            f"echo '[S100 OTA] {tag}, await manual power cycle' >> '{log_file}'; "
        )

    def _exec_and_check(self, ssh, cmd, label="", log_fail=True):
        _, stdout, stderr = ssh.client.exec_command(cmd)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
        if log_fail and exit_code != 0 and err:
            self.log(f"[{label}] ⚠️ 命令失败 (exit {exit_code}): {err}")
        return exit_code, out, err

    def _start_tmux_session(self, ssh, session_name, inner_cmd, label):
        self._exec_and_check(ssh, f"tmux kill-session -t {session_name}", label, log_fail=False)

        rc, out, err = self._exec_and_check(
            ssh, f"tmux new-session -d -s {session_name}", label, log_fail=False
        )
        if rc != 0:
            reason = err or out or "未知错误"
            raise RuntimeError(f"[{label}] 启动 tmux 失败 (exit {rc}): {reason}")

        send_cmd = f"tmux send-keys -t {session_name} -- {shlex.quote(inner_cmd)} C-m"
        rc_send, out_send, err_send = self._exec_and_check(ssh, send_cmd, label, log_fail=False)
        if rc_send != 0:
            reason = err_send or out_send or "未知错误"
            raise RuntimeError(f"[{label}] 下发 tmux 命令失败 (exit {rc_send}): {reason}")

        rc2, _, err2 = self._exec_and_check(
            ssh, f"tmux has-session -t {session_name}", label, log_fail=False
        )
        if rc2 != 0:
            reason = (err2 or "").strip()
            if "no server running" in reason.lower() or "can't find session" in reason.lower():
                self.log(
                    f"[{label}] ℹ️ tmux 会话已快速结束，任务可能已完成或快速失败，请检查结果/日志文件"
                )
            else:
                self.log(f"[{label}] ⚠️ 无法确认 tmux 会话状态: {reason or '未知原因'}")

    def _build_s100_to_x5_auth(self, s100_ssh):
        s100_x5_key_path = "/tmp/ota_x5_fetch_id"
        use_key = self.cfg.get("use_identity_file") and self.cfg.get("identity_file")
        identity_file_local = self.cfg.get("identity_file", "")

        if use_key and os.path.exists(identity_file_local):
            try:
                s100_ssh.upload_file(identity_file_local, s100_x5_key_path)
                self._exec_and_check(
                    s100_ssh, f"chmod 600 '{s100_x5_key_path}'", "S100 OTA", log_fail=False
                )
                return (
                    f"-i '{s100_x5_key_path}' -o IdentitiesOnly=yes "
                    f"-o PreferredAuthentications=publickey -o BatchMode=yes",
                    f"rm -f '{s100_x5_key_path}'; ",
                )
            except Exception:
                pass

        return (
            "-o PreferredAuthentications=publickey,password,keyboard-interactive -o BatchMode=yes",
            "",
        )

    def _wait_for_ssh_ready_after_ota(self, labels: List[str]) -> None:
        """tmux OTA 结束后等待 reboot，再开始读版本。"""
        self.log("⏳ 等待设备 reboot 后 SSH 就绪（再读版本号）…")
        if "S100" in labels:
            ok, waited = wait_for_ping(
                self.cfg["s100_ip"],
                total_timeout_sec=180.0,
                interval_sec=3.0,
                on_tick=lambda e, t: None,
            )
            if ok:
                self.log(f"  S100 ping 已通（约 {waited:.0f}s）")
            else:
                self.log("  ⚠️ S100 ping 180s 内未通，仍将尝试 SSH 读版本")
        if "X5" in labels:
            deadline = time.monotonic() + 180.0
            x5_ready = False
            while time.monotonic() < deadline:
                ssh = self._connect_ssh_for_label("X5")
                if ssh:
                    self._close_ssh_chain(ssh)
                    x5_ready = True
                    break
                time.sleep(5.0)
            if x5_ready:
                self.log("  X5 经 S100 隧道 SSH 已就绪")
            else:
                self.log(
                    "  ⚠️ X5 SSH 180s 内未就绪（可能仍在 reboot）；"
                    "版本轮询会继续重试"
                )

    def _build_screen_cmds(self, ip):
        base_cmd = (
            f"curl -s -X POST 'http://{ip}:3579/command' -H 'Content-Type: application/json'"
        )
        eng_cmd = (
            f"{base_cmd} -d '{{\"command\":\"enfac=1,1%\",\"params\":{{\"op\":\"1\",\"en\":\"1\"}}}}'"
        )
        grn_cmd = (
            f"{base_cmd} -d '{{\"command\":\"lcd=1,green%\",\"params\":{{\"op\":\"1\",\"color\":\"green\"}}}}'"
        )
        red_cmd = (
            f"{base_cmd} -d '{{\"command\":\"lcd=1,red%\",\"params\":{{\"op\":\"1\",\"color\":\"red\"}}}}'"
        )
        return f"{eng_cmd} >/dev/null 2>&1 && sleep 1", f"{grn_cmd} >/dev/null 2>&1", f"{red_cmd} >/dev/null 2>&1"

    def _prepare_s100_vspi_for_ota(self, s100_ssh: SSHHelper) -> None:
        """S100 OTA 前切换 VSPI：卸载 debug 模块并加载正式 hobot_vspi。"""
        self.log(
            "[S100 OTA] OTA 前执行: rmmod hobot_vspi_debug; modprobe hobot_vspi"
        )
        rc, _, err = self._exec_and_check(
            s100_ssh,
            "rmmod hobot_vspi_debug > /dev/null 2>&1; modprobe hobot_vspi",
            "S100 OTA",
            log_fail=False,
        )
        if rc != 0 and err:
            self.log(f"[S100 OTA] ⚠️ VSPI 切换 exit={rc}: {err}")

    def _do_sync_work(self, s100_ssh, x5_ssh):
        items = self.cfg.get("sync_items", [])
        total = sum(
            1
            for item in items
            if item.get("src")
            and item.get("dst")
            and os.path.exists(item.get("src", ""))
            and (item.get("s100") or item.get("x5"))
        )
        done = 0
        for item in items:
            src, dst = item.get("src"), item.get("dst")
            if not (src and dst and os.path.exists(src)):
                continue
            file_size = os.path.getsize(src)
            size_str = (
                f"{file_size / 1024 / 1024:.1f}MB"
                if file_size > 1024 * 1024
                else f"{file_size / 1024:.1f}KB"
            )
            fname = os.path.basename(src)
            make_exec = item.get("executable", False)

            if item.get("s100") and s100_ssh:
                try:
                    rc, _, err = self._exec_and_check(
                        s100_ssh, "systemctl stop vita01.target", "stop robot"
                    )
                    if rc != 0:
                        self.log(f"[S100 Stop Robot] ⚠️ 停止机器人服务失败: {err}")
                    rc, _, err = self._exec_and_check(
                        s100_ssh, "mount -o remount,rw /app", "S100 Sync"
                    )
                    if rc != 0:
                        self.log(f"[S100 Sync] ⚠️ mount 失败: {err}")
                    self.log(f"[S100 Sync] 上传 {fname} ({size_str}) → {dst}")
                    s100_ssh.upload_file(
                        src,
                        dst,
                        progress_cb=self._make_progress_cb(f"S100 Sync", fname, file_size),
                    )
                    remote_path = dst + os.path.basename(src) if dst.endswith("/") else dst
                    if make_exec:
                        rc_chmod, _, err_chmod = self._exec_and_check(
                            s100_ssh, f"chmod +x '{remote_path}'", "S100 Sync"
                        )
                        if rc_chmod == 0:
                            self.log(f"[S100 Sync] 已赋予可执行权限: {remote_path}")
                        else:
                            self.log(f"[S100 Sync] ⚠️ chmod +x 失败: {err_chmod}")
                    rc, out, _ = self._exec_and_check(
                        s100_ssh, f"stat '{remote_path}' 2>&1", "S100 Sync"
                    )
                    if rc == 0:
                        self.log(f"[S100 Sync] ✅ {fname} 同步成功")
                    else:
                        self.log(f"[S100 Sync] ❌ {fname} 同步失败: {out}")
                except Exception as e:
                    self.log(f"[S100 Sync] ❌ {fname} 同步异常: {e}")

            if item.get("x5") and x5_ssh:
                try:
                    rc, _, err = self._exec_and_check(
                        x5_ssh, "systemctl stop vita01.target", "stop robot"
                    )
                    if rc != 0:
                        self.log(f"[X5 Stop Robot] ⚠️ 停止机器人服务失败: {err}")
                    rc, _, err = self._exec_and_check(
                        x5_ssh, "mount -o remount,rw /app", "X5 Sync"
                    )
                    if rc != 0:
                        self.log(f"[X5 Sync] ⚠️ mount /app 失败: {err}")
                    rc, _, err = self._exec_and_check(
                        x5_ssh, "mount -o remount,rw /usr/hobot", "X5 Sync"
                    )
                    if rc != 0:
                        self.log(f"[X5 Sync] ⚠️ mount /usr/hobot 失败: {err}")
                    self.log(f"[X5 Sync] 上传 {fname} ({size_str}) → {dst}")
                    x5_ssh.upload_file(
                        src,
                        dst,
                        progress_cb=self._make_progress_cb(f"X5 Sync", fname, file_size),
                    )
                    remote_path = dst + os.path.basename(src) if dst.endswith("/") else dst
                    if make_exec:
                        rc_chmod, _, err_chmod = self._exec_and_check(
                            x5_ssh, f"chmod +x '{remote_path}'", "X5 Sync"
                        )
                        if rc_chmod == 0:
                            self.log(f"[X5 Sync] 已赋予可执行权限: {remote_path}")
                        else:
                            self.log(f"[X5 Sync] ⚠️ chmod +x 失败: {err_chmod}")
                    rc, out, _ = self._exec_and_check(
                        x5_ssh, f"stat '{remote_path}' 2>&1", "X5 Sync"
                    )
                    if rc == 0:
                        self.log(f"[X5 Sync] ✅ {fname} 同步成功")
                    else:
                        self.log(f"[X5 Sync] ❌ {fname} 同步失败: {out}")
                except Exception as e:
                    self.log(f"[X5 Sync] ❌ {fname} 同步异常: {e}")

            done += 1
            self.log(f"--- 同步进度: {done}/{total} ---")

    def _make_progress_cb(self, label, filename, total_size):
        last_pct = [-1]

        def _cb(transferred, total):
            if total == 0:
                return
            pct = int(transferred * 100 / total)
            step = (pct // 10) * 10
            if step > last_pct[0]:
                last_pct[0] = step
                t_mb = transferred / 1024 / 1024
                total_mb = total / 1024 / 1024
                self.log(f"[{label}] 📦 {filename}: {t_mb:.1f}/{total_mb:.1f}MB ({pct}%)")

        return _cb

    def _do_ota_work(self, s100_ssh, x5_ssh):
        targets = [
            ("S100", s100_ssh, self.cfg.get("ota_target_s100")),
            ("X5", x5_ssh, self.cfg.get("ota_target_x5")),
        ]
        valid_targets = []
        for label, ssh, enabled in targets:
            if not (enabled and ssh):
                continue
            app_p = self.cfg.get(f"{label.lower()}_app_path")
            sys_p = self.cfg.get(f"{label.lower()}_sys_path")
            if not (app_p and sys_p):
                self.log(f"[{label} OTA] 缺少包路径，跳过。")
                continue
            valid_targets.append((label, ssh, app_p, sys_p))

        if not valid_targets:
            return

        for label, ssh, app_p, sys_p in valid_targets:
            ota_dir = self.cfg["ota_dir"]
            self.log(f"[{label} OTA] 上传升级包...")
            _, mk_out, _ = ssh.client.exec_command(
                f"mount -o remount,rw /app && mkdir -p {ota_dir} && rm -rf {ota_dir}/*"
            )
            mk_out.channel.recv_exit_status()
            sftp = ssh.client.open_sftp()
            app_name = os.path.basename(app_p)
            sys_name = os.path.basename(sys_p)
            sftp.put(
                app_p,
                f"{ota_dir}/{app_name}",
                callback=self._make_progress_cb(f"{label} OTA", app_name, os.path.getsize(app_p)),
            )
            sftp.put(
                sys_p,
                f"{ota_dir}/{sys_name}",
                callback=self._make_progress_cb(f"{label} OTA", sys_name, os.path.getsize(sys_p)),
            )
            sftp.close()
            self.log(f"[{label} OTA] 上传完成。")

        s100_ssh_ota = next((ssh for lb, ssh, _, _ in valid_targets if lb == "S100"), None)
        if s100_ssh_ota:
            self._prepare_s100_vspi_for_ota(s100_ssh_ota)

        if self.cfg["use_tmux"]:
            for label, ssh, _, _ in valid_targets:
                rc, _, _ = self._exec_and_check(
                    ssh, "command -v tmux >/dev/null 2>&1", f"{label} OTA", log_fail=False
                )
                if rc != 0:
                    raise RuntimeError(
                        f"[{label} OTA] 目标设备未安装 tmux，请安装 tmux 或关闭 tmux 后重试"
                    )

            target_map = {label: (ssh, app_p, sys_p) for label, ssh, app_p, sys_p in valid_targets}

            if "S100" in target_map and "X5" in target_map:
                x5_ssh, x5_app_p, x5_sys_p = target_map["X5"]
                x5_ota_cmd = (
                    f"cd {self.cfg['ota_dir']} && /usr/hobot/bin/ota_tool -n "
                    f"-p {os.path.basename(x5_app_p)} -p {os.path.basename(x5_sys_p)}"
                )
                x5_session = "ota_x5"
                x5_result_file = "/tmp/ota_x5.result"
                x5_log_file = "/tmp/ota_x5.log"
                self._clear_remote_ota_state(x5_ssh, "X5")
                x5_persist_rc = f"{OTA_TMUX_RC_PERSIST_PREFIX}_x5"
                x5_inner_cmd = (
                    f"{x5_ota_cmd} > '{x5_log_file}' 2>&1; "
                    f"x5_rc=$?; "
                    f"echo $x5_rc > '{x5_result_file}'; "
                    f"echo $x5_rc > '{x5_persist_rc}'; "
                    f"echo x5_rc=$x5_rc >> '{x5_log_file}'; "
                    f"rm -rf {self.cfg['ota_dir']}/*; "
                    f"if [ \"$x5_rc\" = \"0\" ]; then "
                    f"echo '[X5 OTA] ota success, reboot' >> '{x5_log_file}'; "
                    f"sync; reboot; "
                    f"fi; "
                    f"echo tmux_done_x5_rc=$x5_rc >> '{x5_log_file}'"
                )
                self._start_tmux_session(x5_ssh, x5_session, x5_inner_cmd, "X5 OTA")
                self.log(f"[X5 OTA] 已在 tmux 后台启动 (session: {x5_session})")

                s100_ssh, s100_app_p, s100_sys_p = target_map["S100"]
                s100_ota_cmd = (
                    f"cd {self.cfg['ota_dir']} && /usr/hobot/bin/ota_tool -n "
                    f"-p {os.path.basename(s100_app_p)} -p {os.path.basename(s100_sys_p)}"
                )
                s100_session = "ota_s100"
                s100_result_file = "/tmp/ota_s100.result"
                s100_log_file = "/tmp/ota_s100.log"
                merge_detail_file = "/tmp/ota_merge.detail"
                self._clear_remote_ota_state(s100_ssh, "S100")

                x5_ssh_auth, cleanup_key_cmd = self._build_s100_to_x5_auth(s100_ssh)
                x5_persist_on_x5 = f"{OTA_TMUX_RC_PERSIST_PREFIX}_x5"
                x5_fetch_inner = (
                    f"(cat /tmp/ota_x5.result 2>/dev/null || "
                    f"cat {x5_persist_on_x5} 2>/dev/null) | head -1"
                )
                x5_fetch_cmd = self._build_x5_remote_ssh_cmd(
                    x5_fetch_inner, s100_ssh=s100_ssh
                )
                x5_fetch_max = max(
                    60, int(self.cfg.get("ota_s100_x5_fetch_max_sec") or 300)
                )
                eng_cmd, grn_cmd, red_cmd = self._build_screen_cmds("localhost")
                s100_persist_rc = f"{OTA_TMUX_RC_PERSIST_PREFIX}_s100"
                s100_success = self._s100_post_success_shell(
                    s100_log_file, eng_cmd, grn_cmd, tag="dual ota success"
                )
                s100_inner_cmd = (
                    f"{s100_ota_cmd} > '{s100_log_file}' 2>&1; "
                    f"s100_rc=$?; "
                    f"echo $s100_rc > '{s100_result_file}'; "
                    f"echo $s100_rc > '{s100_persist_rc}'; "
                    f"echo s100_rc=$s100_rc >> '{s100_log_file}'; "
                    f"x5_rc=125; "
                    f"x5_fetch_status=timeout; "
                    f"for i in $(seq 1 {x5_fetch_max}); do "
                    f"x5_val=$({x5_fetch_cmd}); "
                    f"if [ -n \"$x5_val\" ]; then x5_rc=$x5_val; x5_fetch_status=ok; break; fi; "
                    f"sleep 1; "
                    f"done; "
                    f"if [ \"$x5_fetch_status\" = \"timeout\" ]; then "
                    f"echo '[S100] 抓 X5 结果超时（{x5_fetch_max}s），结束等待' >> '{s100_log_file}'; "
                    f"fi; "
                    f"echo s100_rc=$s100_rc > '{merge_detail_file}'; "
                    f"echo x5_rc=$x5_rc >> '{merge_detail_file}'; "
                    f"echo x5_fetch_status=$x5_fetch_status >> '{merge_detail_file}'; "
                    f"if [ \"$s100_rc\" = \"0\" ] && [ \"$x5_rc\" = \"0\" ]; then "
                    f"echo screen=green >> '{merge_detail_file}'; "
                    f"{s100_success}"
                    f"else "
                    f"echo screen=red >> '{merge_detail_file}'; "
                    f"{eng_cmd}; {red_cmd}; "
                    f"fi; "
                    f"{cleanup_key_cmd}"
                    f"rm -rf {self.cfg['ota_dir']}/*; "
                    f"echo tmux_done_s100_rc=$s100_rc >> '{s100_log_file}'"
                )
                self._start_tmux_session(s100_ssh, s100_session, s100_inner_cmd, "S100 OTA")
                self.log(
                    f"[S100 OTA] 已在 tmux 后台启动 (session: {s100_session})"
                    f"，抓 X5 结果最多 {x5_fetch_max}s"
                )
            else:
                label, ssh, app_p, sys_p = valid_targets[0]
                ota_dir = self.cfg["ota_dir"]
                cmd = (
                    f"cd {ota_dir} && /usr/hobot/bin/ota_tool -n "
                    f"-p {os.path.basename(app_p)} -p {os.path.basename(sys_p)}"
                )
                session_name = f"ota_{label.lower()}"
                result_file = f"/tmp/{session_name}.result"
                log_file = f"/tmp/{session_name}.log"
                persist_rc = f"{OTA_TMUX_RC_PERSIST_PREFIX}_{label.lower()}"
                self._clear_remote_ota_state(ssh, label)
                api_ip = "localhost" if label == "S100" else "192.168.127.2"
                eng_cmd, grn_cmd, red_cmd = self._build_screen_cmds(api_ip)
                if label == "S100":
                    success_tail = self._s100_post_success_shell(
                        log_file, eng_cmd, grn_cmd, tag=f"{label} OTA success"
                    )
                    fail_tail = (
                        f"echo screen=red >> '{log_file}'; {eng_cmd}; {red_cmd}; "
                    )
                else:
                    success_tail = (
                        f"echo screen=green >> '{log_file}'; {eng_cmd}; {grn_cmd}; "
                        f"echo '[{label} OTA] ota success, reboot' >> '{log_file}'; "
                        f"sync; reboot; "
                    )
                    fail_tail = (
                        f"echo screen=red >> '{log_file}'; {eng_cmd}; {red_cmd}; "
                    )
                tmux_inner_cmd = (
                    f"{cmd} > '{log_file}' 2>&1; "
                    f"ota_rc=$?; "
                    f"echo $ota_rc > '{result_file}'; "
                    f"echo $ota_rc > '{persist_rc}'; "
                    f"echo ota_rc=$ota_rc >> '{log_file}'; "
                    f"if [ \"$ota_rc\" = \"0\" ]; then "
                    f"{success_tail}"
                    f"else "
                    f"{fail_tail}"
                    f"fi; "
                    f"rm -rf {ota_dir}/*; "
                    f"echo tmux_done_ota_rc=$ota_rc >> '{log_file}'"
                )
                self._start_tmux_session(ssh, session_name, tmux_inner_cmd, f"{label} OTA")
                self.log(f"[{label} OTA] 已在 tmux 后台启动 (session: {session_name})")

            self.log("✅ tmux 任务已全部提交。")
            self._status("✅ OTA 包已提交（tmux 后台刷写中），即将开始版本校验…")
            return

        fail_labels: List[str] = []
        threads = []

        def _run_one(lbl: str, ssh_conn, app_path: str, sys_path: str) -> None:
            if not self._ota_exec_and_monitor(lbl, ssh_conn, app_path, sys_path):
                fail_labels.append(lbl)

        for label, ssh, app_p, sys_p in valid_targets:
            t = threading.Thread(
                target=_run_one,
                args=(label, ssh, app_p, sys_p),
                daemon=True,
            )
            threads.append(t)
            t.start()
            self.log(f"[{label} OTA] 前台执行中...")

        if len(threads) > 1:
            self.log("⏳ S100 与 X5 正在并行升级，请等待全部完成...")

        for t in threads:
            t.join()
        if fail_labels:
            raise RuntimeError(f"OTA 升级失败: {', '.join(fail_labels)}")

    def _ota_exec_and_monitor(self, label, ssh, app_p, sys_p) -> bool:
        ota_dir = self.cfg["ota_dir"]
        cmd = (
            f"cd {ota_dir} && /usr/hobot/bin/ota_tool -n "
            f"-p {os.path.basename(app_p)} -p {os.path.basename(sys_p)}"
        )
        timeout_sec = max(300, int(self.cfg.get("ota_foreground_timeout_sec") or 3600))
        try:
            _, stdout, stderr = ssh.client.exec_command(cmd, timeout=timeout_sec)
            for line in iter(stdout.readline, ""):
                line = line.rstrip("\n\r")
                if line:
                    self.log(f"[{label} OTA] {line}")
            err_output = stderr.read().decode("utf-8", errors="replace").strip()
            if err_output:
                for err_line in err_output.splitlines():
                    self.log(f"[{label} OTA ⚠️] {err_line}")
            exit_code = stdout.channel.recv_exit_status()
            if exit_code == 0:
                ssh.client.exec_command(f"rm -rf {ota_dir}/*")
                if label == "S100" and not self.cfg.get("ota_s100_auto_reboot", False):
                    self.log(
                        f"[{label} OTA] ota_tool 已结束 (exit 0)；"
                        f"请产线员工人工上下电后再校验版本"
                    )
                    return True
                self.log(f"[{label} OTA] ota_tool 已结束 (exit 0)，清理并重启…")
                ssh.client.exec_command("reboot")
                return True
            self.log(f"[{label} OTA] ❌ ota_tool 失败 (exit code: {exit_code})")
            return False
        except Exception as e:
            self.log(f"[{label} OTA] ❌ 执行异常: {e}")
            return False


def run_ota_deploy(
    cfg: Dict[str, Any],
    logger: Callable[[str], None],
    *,
    wait_tmux: bool = True,
    wait_timeout_sec: int = OTA_DEFAULT_VERIFY_TIMEOUT_SEC,
) -> bool:
    """上传并提交 OTA → 人工上下电（默认）→ 读版本；失败则重试刷写。"""
    cfg = merge_cfg_with_defaults(cfg)
    if not (cfg.get("ota_target_s100") or cfg.get("ota_target_x5")):
        logger("❌ 未选择任何 OTA 升级目标（S100 / X5）")
        return False
    # 双板时包路径在连接 S100 后按 lifecycle 再填充，此处不强制校验路径
    if not (cfg.get("ota_target_s100") and cfg.get("ota_target_x5")):
        ok_cfg, err = validate_ota_cfg(cfg)
        if not ok_cfg:
            logger(f"❌ 配置错误: {err}")
            return False

    verify_timeout = resolve_ota_verify_timeout_sec(cfg, wait_timeout_sec)
    max_attempts = max(1, int(cfg.get("ota_deploy_max_attempts") or 3))
    manual_s100 = (
        cfg.get("ota_target_s100") and not cfg.get("ota_s100_auto_reboot", False)
    )
    if manual_s100:
        logger(
            "S100 刷写完成后不自动 reboot，将由产线员工人工上下电后再读版本"
        )

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            logger(
                f"━━ 第 {attempt}/{max_attempts} 次升级"
                f"（上次版本校验未通过，重新刷写）━━"
            )

        cfg["_x5_ssh_fail_count"] = 0   # 重试前清零

        executor = DeployExecutor(cfg, logger)
        if not executor.run_ota():
            return False

        cfg = executor.cfg

        if not resolve_expected_ota_version(cfg, logger):
            return False

        if cfg.get("use_tmux"):
            if wait_tmux:
                tmux_cap = max(
                    0, min(int(cfg.get("ota_tmux_max_wait_sec") or 0), verify_timeout)
                )
                if tmux_cap > 0:
                    logger(
                        f"OTA 已提交 tmux，顺带轮询 exit 码 ≤{tmux_cap}s（最终以版本校验为准）"
                    )
                    ota_emit_status(cfg, f"⏳ tmux OTA 进行中（≤{tmux_cap}s）…")
                    executor.wait_tmux_ota_complete(timeout_sec=tmux_cap)
                else:
                    logger("OTA 已提交 tmux；跳过 exit 码等待")
            else:
                logger(
                    "⚠️ wait_tmux=false：tmux 已提交，立即进入后续流程"
                )

        if manual_s100:
            if cfg.get("use_tmux"):
                flash_wait = int(
                    cfg.get("ota_wait_flash_before_power_cycle_sec") or 3600
                )
                executor.wait_for_ota_flash_complete(timeout_sec=flash_wait)

            expected = cfg.get("expected_ota_version") or {}
            if expected and executor.ota_versions_already_match(expected):
                logger("✅ 设备版本已与升级包一致，跳过人工上下电")
                cfg["_s100_manual_power_cycle_done"] = True
            elif not prompt_s100_manual_power_cycle(cfg, logger):
                return False

        logger(
            f"开始版本校验（第 {attempt}/{max_attempts} 次，"
            f"最长 {verify_timeout}s / 约 {verify_timeout // 60}min）…"
        )
        ota_emit_status(cfg, "🔍 版本校验中（SSH + version=0）…")
        if executor.verify_ota_versions_via_ssh(timeout_sec=verify_timeout):
            return True

        if attempt < max_attempts:
            logger(
                f"版本校验未通过，{max_attempts - attempt} 次重试机会剩余，"
                f"即将重新刷写…"
            )
            time.sleep(2.0)

    logger(f"❌ 已尝试 {max_attempts} 次升级，版本仍未与本次升级包一致")
    return False


# ---------------------------------------------------------------------------
# CLI（原 ota_deploy_headless）
# ---------------------------------------------------------------------------

_PACKAGE_DIR = Path(__file__).resolve().parent


def _detach_console_when_stdio_piped() -> None:
    if sys.platform != "win32":
        return
    try:
        out = getattr(sys, "__stdout__", None) or sys.stdout
        if out is not None and hasattr(out, "isatty") and not out.isatty():
            import ctypes

            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass


def _cli_log(msg: str) -> None:
    text = (
        msg.replace("\u274c", "[FAIL]")
        .replace("\u2705", "[OK]")
        .replace("\u26a0\ufe0f", "[WARN]")
        .replace("\u26a0", "[WARN]")
    )
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"), flush=True)


def _default_config_path() -> str:
    root = _PACKAGE_DIR.parent.parent
    p = root / "Config" / "config.yaml"
    if p.is_file():
        return str(p.resolve())
    return "Config/config.yaml"


def _parse_bool_cli(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes", "on")


def main_cli(argv: list[str] | None = None) -> int:
    """无头 OTA 部署（供 TestTool 序列 utility.run_python_script 调用）。"""
    import argparse

    _detach_console_when_stdio_piped()

    p = argparse.ArgumentParser(description="VITA OTA 无头部署（S100 / X5）")
    p.add_argument("--sn", default="", help="19 位 SN，用于 edu/pro/max 包名校验")
    p.add_argument("--skip-sn-check", action="store_true", help="跳过 SN 与包名匹配校验")
    p.add_argument(
        "--config-path",
        default=_default_config_path(),
        help="读取 ota_version 用于升级包文件名校验",
    )
    p.add_argument(
        "--skip-package-version-check",
        action="store_true",
        help="跳过 ota_version 与 zip 文件名校验",
    )
    p.add_argument("--s100-ip", default="192.168.126.2")
    p.add_argument("--x5-ip", default="192.168.127.10")
    p.add_argument("--username", default="root")
    p.add_argument("--password", default="root")
    p.add_argument("--ota-dir", default="/ota")
    p.add_argument("--connect-timeout", type=int, default=30)
    p.add_argument("--identity-file", default="", help="SSH 私钥路径")
    p.add_argument(
        "--use-key-auth",
        default="false",
        help="是否私钥认证 true/false（序列可用 ${ota_use_key}）",
    )
    p.add_argument(
        "--target-s100",
        default="true",
        help="是否升级 S100 true/false（序列可用 ${ota_target_s100}）",
    )
    p.add_argument(
        "--target-x5",
        default="true",
        help="是否升级 X5 true/false（序列可用 ${ota_target_x5}）",
    )
    p.add_argument("--package-dir", default="", help="扫描目录并自动匹配 APP/SYS 包")
    p.add_argument(
        "--manifest-encrypted",
        default="",
        help="lifecycle>=4 时使用的 manifest.yaml 路径",
    )
    p.add_argument(
        "--manifest-plain",
        default="",
        help="lifecycle 0-3 时使用的 manifest.yaml 路径",
    )
    p.add_argument("--s100-app", default="")
    p.add_argument("--s100-sys", default="")
    p.add_argument("--x5-app", default="")
    p.add_argument("--x5-sys", default="")
    p.add_argument(
        "--use-tmux",
        default="true",
        help="tmux 后台 true/false（序列 ${ota_use_tmux}）",
    )
    p.add_argument(
        "--wait-tmux",
        default="true",
        help="tmux 后轮询结果 true/false（序列 ${ota_wait_tmux}）",
    )
    p.add_argument(
        "--wait-timeout-sec",
        type=int,
        default=OTA_DEFAULT_VERIFY_TIMEOUT_SEC,
        help="版本校验 SSH 轮询最长秒数（默认 25min）",
    )
    args = p.parse_args(argv)

    use_tmux = _parse_bool_cli(args.use_tmux)
    wait_tmux = _parse_bool_cli(args.wait_tmux)

    identity = (args.identity_file or "").strip()
    use_key = _parse_bool_cli(args.use_key_auth) or bool(identity)

    cfg = merge_ota_cfg(
        s100_ip=args.s100_ip,
        x5_ip=args.x5_ip,
        username=args.username,
        password=args.password,
        ota_dir=args.ota_dir,
        connect_timeout=args.connect_timeout,
        use_identity_file=use_key,
        identity_file=identity,
        ota_target_s100=_parse_bool_cli(args.target_s100),
        ota_target_x5=_parse_bool_cli(args.target_x5),
        use_tmux=use_tmux,
        package_dir=args.package_dir,
        s100_app_path=args.s100_app,
        s100_sys_path=args.s100_sys,
        x5_app_path=args.x5_app,
        x5_sys_path=args.x5_sys,
        ota_manifest_encrypted=args.manifest_encrypted,
        ota_manifest_plain=args.manifest_plain,
    )

    if not args.skip_sn_check and (args.sn or "").strip():
        ok_sn, err_sn = validate_sn_packages(args.sn.strip(), cfg)
        if not ok_sn:
            _cli_log(f"❌ SN 校验失败: {err_sn}")
            return 2

    ok_cfg, err_cfg = validate_ota_cfg(cfg)
    if not ok_cfg:
        _cli_log(f"❌ {err_cfg}")
        return 2

    expected: Dict[str, Any] = load_ota_version_expected(args.config_path)
    if not expected:
        _cli_log(f"❌ 未找到或无法读取 ota_version 配置: {args.config_path}")
        return 2
    cfg["expected_ota_version"] = expected
    cfg["ota_version_config_path"] = args.config_path

    if not args.skip_package_version_check:
        ok_pkg, err_pkg = validate_ota_package_filenames(cfg, expected)
        if not ok_pkg:
            _cli_log(f"❌ OTA 包版本校验失败:\n{err_pkg}")
            return 2
        _cli_log("OTA 包文件名与 ota_version 配置一致")

    _cli_log("=== OTA 无头部署开始 ===")
    _cli_log(
        f"目标: S100={cfg.get('ota_target_s100')} X5={cfg.get('ota_target_x5')} "
        f"tmux={cfg.get('use_tmux')} wait_tmux={wait_tmux}"
    )
    if cfg.get("s100_app_path"):
        _cli_log(f"S100 APP: {cfg['s100_app_path']}")
    if cfg.get("s100_sys_path"):
        _cli_log(f"S100 SYS: {cfg['s100_sys_path']}")
    if cfg.get("x5_app_path"):
        _cli_log(f"X5 APP: {cfg['x5_app_path']}")
    if cfg.get("x5_sys_path"):
        _cli_log(f"X5 SYS: {cfg['x5_sys_path']}")

    if cfg.get("use_tmux") and not wait_tmux:
        _cli_log("⚠️ wait_tmux=false：将跳过可选 tmux exit 轮询，直接版本校验")

    ok = run_ota_deploy(
        cfg,
        _cli_log,
        wait_tmux=wait_tmux,
        wait_timeout_sec=args.wait_timeout_sec,
    )
    if ok:
        _cli_log("=== OTA 部署成功 ===")
        return 0
    _cli_log("=== OTA 部署失败 ===")
    return 1


def main_gui() -> None:
    """启动图形界面（Tk 代码在 ota_deploy_gui，避免产线/无头环境 import tkinter）。"""
    from ota_deploy_gui import launch_gui

    launch_gui()


# 兼容旧 headless 脚本：main == main_cli
main = main_cli


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--gui", "-g", "gui"):
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        main_gui()
    else:
        raise SystemExit(main_cli())
