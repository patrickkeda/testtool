# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

SPEC_ROOT = Path(SPECPATH).resolve().parent
_dll_candidates = [
    SPEC_ROOT / "bin" / "HQMES.dll",
    Path("C:/Users/VitaDynamics/Desktop/dll_v4.0.0.3/x64/HQMES.dll"),
    Path("D:/Mes/dll_v4.0.0.3/x64/HQMES.dll"),
    Path("D:/Mes/dll_v4.0.0.3/x86/HQMES.dll"),
    Path("_tmp_hqmes/dll_v4.0.0.3/x64/HQMES.dll"),
    Path("_tmp_hqmes/dll_v4.0.0.3/x86/HQMES.dll"),
]
_dll_datas = [(str(p.resolve()), "bin") for p in _dll_candidates if p.is_file()]

# 工程测试客户端（与 build/TestTool.spec 对齐，避免从仓库根误用本 spec 时漏打 client）
_client_datas = []
if (SPEC_ROOT / "client").is_dir():
    _client_datas.append((str(SPEC_ROOT / "client"), "client"))

# CAN vendor DLLs (ECanVci64 / ECANFDVCI64)
# Put these files in one of the candidate paths below, then rebuild.
_can_dll_candidates = [
    SPEC_ROOT / "build" / "can_dll" / "ECanVci64.dll",
    SPEC_ROOT / "build" / "can_dll" / "ECANFDVCI64.dll",
    SPEC_ROOT / "build" / "can_dll" / "CHUSBDLL64.dll",
    SPEC_ROOT / "test" / "canapp" / "ECanVci64.dll",
    SPEC_ROOT / "test" / "canapp" / "ECANFDVCI64.dll",
    SPEC_ROOT / "test" / "canapp" / "CHUSBDLL64.dll",
]
_can_dll_datas = [(str(p.resolve()), "test/canapp") for p in _can_dll_candidates if p.is_file()]

a = Analysis(
    ['src\\app\\main.py'],
    pathex=['.'],
    binaries=[],
    datas=[('Config', 'Config'), ('Seq', 'Seq')] + _client_datas + _dll_datas + _can_dll_datas,
    hiddenimports=[
        'vita_engineer_client',
        'vita_engineer_client.engineer_client',
        'vita_engineer_client.test_engineer_client',
        'vita_engineer_client.protocol',
        'vita_engineer_client.crypto_utils',
        'vita_engineer_client.response_handlers',
        'vita_engineer_client.pointcloud_processor',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TestTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TestTool',
)
