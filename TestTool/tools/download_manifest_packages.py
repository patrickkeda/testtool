#!/usr/bin/env python3
"""从 OTA manifest.yaml 读取 packages[].url 并下载到指定目录。

所有 zip 使用 manifest 中的 filename 原样保存到同一文件夹，不重命名、不建 version 子目录。
下载前会校验 s100/x5 的 sys、app 四个包是否存在，且 version 与 filename、url 一致。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST = Path(r"c:\Users\VitaDynamics\Downloads\manifest (13).yaml")

_REQUIRED_PACKAGES = (
    ("s100", "s100-sys"),
    ("s100", "s100-app"),
    ("x5", "x5-sys"),
    ("x5", "x5-app"),
)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("需要 PyYAML：pip install pyyaml>=6.0") from exc
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"manifest 根节点应为 mapping: {path}")
    return data


def _md5_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _download(url: str, dest: Path, timeout: float) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "TestTool-manifest-downloader/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as out:
        shutil.copyfileobj(resp, out, length=1 << 20)


def _package_label(pkg: dict[str, Any]) -> str:
    domain = pkg.get("domain", "?")
    ptype = pkg.get("type", "?")
    return f"{domain}/{ptype}"


def _normalize_pkg_key(pkg: dict[str, Any]) -> tuple[str, str] | None:
    domain = str(pkg.get("domain", "") or "").strip().lower()
    ptype = str(pkg.get("type", "") or "").strip().lower()
    if domain and ptype:
        return domain, ptype
    return None


def _version_in_text(version: str, text: str) -> bool:
    if not version or not text:
        return False
    if version in text:
        return True
    encoded = urllib.parse.quote(version, safe="")
    if encoded in text:
        return True
    # filename 里 + 保留，url 里可能是 %2B
    if "+" in version and version.replace("+", "%2B") in text:
        return True
    return False


def validate_manifest_packages(packages: list[Any]) -> list[str]:
    """校验四个必需包及 version 与 filename/url 一致性。"""
    errors: list[str] = []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for i, pkg in enumerate(packages, 1):
        if not isinstance(pkg, dict):
            errors.append(f"packages[{i}] 不是有效条目")
            continue
        key = _normalize_pkg_key(pkg)
        if not key:
            errors.append(f"packages[{i}] 缺少 domain 或 type")
            continue
        if key in by_key:
            errors.append(f"packages 中重复的 {key[0]}/{key[1]}")
        by_key[key] = pkg

    for domain, ptype in _REQUIRED_PACKAGES:
        key = (domain, ptype)
        label = f"{domain}/{ptype}"
        if key not in by_key:
            errors.append(f"缺少必需包: {label}")
            continue

        pkg = by_key[key]
        version = str(pkg.get("version") or "").strip()
        filename = str(pkg.get("filename") or "").strip()
        url = str(pkg.get("url") or "").strip()

        if not version:
            errors.append(f"{label}: 缺少 version")
        if not filename:
            errors.append(f"{label}: 缺少 filename")
        if not url:
            errors.append(f"{label}: 缺少 url")

        if version and filename and not _version_in_text(version, filename):
            errors.append(
                f"{label}: version={version!r} 未出现在 filename={filename!r}"
            )
        if version and url and not _version_in_text(version, url):
            errors.append(
                f"{label}: version={version!r} 未出现在 url 中"
            )

    return errors


def print_version_summary(packages: list[Any]) -> None:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        key = _normalize_pkg_key(pkg)
        if key:
            by_key[key] = pkg

    print("\n版本确认（与 manifest 一致）:")
    print(f"{'包':<16} {'version':<45} {'filename'}")
    print("-" * 110)
    for domain, ptype in _REQUIRED_PACKAGES:
        pkg = by_key.get((domain, ptype), {})
        label = f"{domain}/{ptype}"
        version = str(pkg.get("version") or "-")
        filename = str(pkg.get("filename") or "-")
        print(f"{label:<16} {version:<45} {filename}")


def download_from_manifest(
    manifest_path: Path,
    output_dir: Path,
    *,
    timeout: float = 300.0,
    dry_run: bool = False,
    skip_existing: bool = True,
    verify_md5: bool = True,
) -> int:
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest 不存在: {manifest_path}")

    data = _load_yaml(manifest_path)
    manifest_version = str(data.get("version") or "").strip()

    packages = data.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("manifest 缺少 packages 列表")

    validation_errors = validate_manifest_packages(packages)
    if validation_errors:
        msg = "manifest 校验失败:\n" + "\n".join(f"  - {e}" for e in validation_errors)
        raise ValueError(msg)

    pkg_dir = output_dir.resolve()
    pkg_dir.mkdir(parents=True, exist_ok=True)

    manifest_copy = pkg_dir / "manifest.yaml"
    if not dry_run:
        shutil.copy2(manifest_path, manifest_copy)

    if manifest_version:
        print(f"manifest version: {manifest_version}")
    print(f"输出目录: {pkg_dir}")
    print_version_summary(packages)
    print(f"\n待下载: {len(packages)} 个包")
    if dry_run:
        print("(dry-run，不实际下载)")

    failed = 0
    for i, pkg in enumerate(packages, 1):
        if not isinstance(pkg, dict):
            print(f"[{i}] 跳过：非 mapping 条目")
            failed += 1
            continue

        url = str(pkg.get("url") or "").strip()
        filename = str(pkg.get("filename") or "").strip()
        expected_md5 = str(pkg.get("md5sum") or "").strip().lower()
        pkg_version = str(pkg.get("version") or "").strip()
        label = _package_label(pkg)

        if not url or not filename:
            print(f"[{i}] {label} 缺少 url 或 filename")
            failed += 1
            continue

        dest = pkg_dir / filename
        print(f"[{i}/{len(packages)}] {label} (version={pkg_version}) -> {filename}")

        if skip_existing and dest.is_file():
            if verify_md5 and expected_md5:
                actual = _md5_file(dest)
                if actual == expected_md5:
                    print("  已存在且 MD5 一致，跳过")
                    continue
                print(f"  已存在但 MD5 不符，重新下载")
            else:
                print("  已存在，跳过")
                continue

        if dry_run:
            print(f"  url: {url[:90]}...")
            continue

        try:
            _download(url, dest, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"  下载失败: {exc}")
            failed += 1
            continue

        if dest.name != filename:
            print(f"  文件名异常: 期望 {filename!r}，实际 {dest.name!r}")
            failed += 1
            continue

        if verify_md5 and expected_md5:
            actual = _md5_file(dest)
            if actual != expected_md5:
                print(f"  MD5 校验失败: {actual} != {expected_md5}")
                failed += 1
            else:
                print("  完成，MD5 校验通过")
        else:
            print("  完成")

    if not dry_run and failed == 0:
        print("\n本地文件核对:")
        disk_ok = True
        for domain, ptype in _REQUIRED_PACKAGES:
            pkg = next(
                (
                    p
                    for p in packages
                    if isinstance(p, dict) and _normalize_pkg_key(p) == (domain, ptype)
                ),
                {},
            )
            expected_name = str(pkg.get("filename") or "")
            expected_ver = str(pkg.get("version") or "")
            path = pkg_dir / expected_name
            if path.is_file():
                print(f"  OK  {domain}/{ptype}: {expected_name} (version={expected_ver})")
            else:
                print(f"  缺失 {domain}/{ptype}: {expected_name}")
                disk_ok = False
                failed += 1
        if not disk_ok:
            print("部分文件未就绪")

    return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从 manifest.yaml 下载 OTA 包到指定文件夹（使用 manifest 原始 filename，不重命名）",
    )
    parser.add_argument(
        "-m",
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"manifest 路径（默认: {DEFAULT_MANIFEST}）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="下载目标文件夹，所有 zip 与 manifest.yaml 放在此目录",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="单个下载超时（秒），默认 300",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="已存在文件也重新下载",
    )
    parser.add_argument(
        "--no-md5",
        action="store_true",
        help="下载后不校验 md5sum",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验 manifest 并打印将要下载的内容",
    )
    args = parser.parse_args(argv)

    try:
        failed = download_from_manifest(
            args.manifest,
            args.output,
            timeout=args.timeout,
            dry_run=args.dry_run,
            skip_existing=not args.force,
            verify_md5=not args.no_md5,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if failed:
        print(f"\n完成，{failed} 个包失败", file=sys.stderr)
        return 1
    print("\n全部完成，四个包版本与 manifest 一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
