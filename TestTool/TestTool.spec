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

a = Analysis(
    ['src\\app\\main.py'],
    pathex=['.'],
    binaries=[],
    datas=[('Config', 'Config'), ('Seq', 'Seq')] + _dll_datas,
    hiddenimports=[],
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
