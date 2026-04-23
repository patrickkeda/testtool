# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for TestTool application.
This file configures how PyInstaller packages the application into an executable.
"""

import os
import sys
from pathlib import Path

# PyInstaller 需要的变量
block_cipher = None

# 收集 cv2 的所有子模块和数据文件（如果需要）
try:
    from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all
    try:
        cv2_submodules = collect_submodules('cv2')
        cv2_datas = collect_data_files('cv2')
    except Exception:
        cv2_submodules = []
        cv2_datas = []
except ImportError:
    cv2_submodules = []
    cv2_datas = []
    collect_all = None

# test/dogleg/tool.py 会 import tkinter，动态加载时需提前打进包
_tk_datas = []
_tk_binaries = []
_tk_hidden = []
if collect_all is not None:
    try:
        _tk_all = collect_all('tkinter')
        _tk_datas = _tk_all[0]
        _tk_binaries = _tk_all[1]
        _tk_hidden = _tk_all[2]
    except Exception:
        pass
if not _tk_hidden:
    _tk_hidden = ['tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.filedialog']

# 获取项目根目录
# 构建脚本在 build/ 目录下运行 PyInstaller，所以项目根目录是当前目录的父目录
cwd = Path.cwd().resolve()

# 优先从当前工作目录推断
if cwd.name == 'build':
    # 当前在 build/ 目录
    project_root = cwd.parent
elif (cwd / 'src' / 'app' / 'main.py').exists():
    # 当前在项目根目录
    project_root = cwd
else:
    # 从 SPECPATH 推断（备用方法）
    try:
        spec_path = Path(SPECPATH).resolve()
        if spec_path.is_file() and spec_path.name == 'TestTool.spec':
            # SPECPATH 是文件: .../TestTool/build/TestTool.spec
            project_root = spec_path.parent.parent
        elif spec_path.is_dir() and spec_path.name == 'build':
            # SPECPATH 是目录: .../TestTool/build
            project_root = spec_path.parent
        else:
            # 尝试从 spec 路径的父目录推断
            project_root = spec_path.parent if spec_path.is_dir() else spec_path.parent.parent
    except Exception:
        # 如果 SPECPATH 解析失败，使用当前目录的父目录
        project_root = cwd.parent if cwd.name == 'build' else cwd

# 验证 main.py 是否存在
main_py = project_root / 'src' / 'app' / 'main.py'
if not main_py.exists():
    # 尝试其他可能的位置
    alt_paths = [
        cwd.parent / 'src' / 'app' / 'main.py' if cwd.name == 'build' else None,
        cwd / 'src' / 'app' / 'main.py',
    ]
    for alt_path in alt_paths:
        if alt_path and alt_path.exists():
            project_root = alt_path.parent.parent.parent
            main_py = alt_path
            break
    else:
        raise RuntimeError(
            f"Cannot find main.py\n"
            f"  Tried: {project_root / 'src' / 'app' / 'main.py'}\n"
            f"  Current working directory: {cwd}\n"
            f"  SPECPATH: {SPECPATH}\n"
            f"  Project root (calculated): {project_root}\n"
            f"  Please ensure:\n"
            f"    1. You run the build script (build.bat) from the TestTool directory\n"
            f"    2. The src/app/main.py file exists"
        )

# 构建打包数据列表（examples 仅当目录存在时包含，避免打包失败）
# test/dogleg 为 PCAN 狗腿测试步骤所需（pcan.py 动态加载 tool.py 中的 CANCommunicator）
datas = [
    (str(project_root / 'Config'), 'Config'),
    (str(project_root / 'config_selfcheck.yaml'), '.'),
    (str(project_root / 'Seq'), 'Seq'),
    (str(project_root / 'client'), 'client'),
    (str(project_root / 'test' / 'canapp'), 'test/canapp'),
]
if (project_root / 'test' / 'dogleg').is_dir():
    datas.append((str(project_root / 'test' / 'dogleg'), 'test/dogleg'))
if (project_root / 'examples').is_dir():
    datas.append((str(project_root / 'examples'), 'examples'))
datas = datas + cv2_datas + _tk_datas

# PCAN 狗腿步骤依赖 test/dogleg/tool.py -> PCANBasic，需把 PCANBasic.dll 打进包
_pcan_binaries = []
_search_dirs = [
    project_root,
    project_root / 'test' / 'dogleg',
    project_root / 'build',
    Path(os.environ.get('SystemRoot', 'C:\\Windows')) / 'System32',
]
try:
    import PCANBasic
    _search_dirs.insert(0, Path(PCANBasic.__file__).resolve().parent)
except Exception:
    pass
for _d in _search_dirs:
    for _dll_name in ('PCANBasic64.dll', 'PCANBasic.dll'):
        _p = _d / _dll_name
        if _p.exists():
            _pcan_binaries.append((str(_p), '.'))
            break
    if _pcan_binaries:
        break

# 允许外部指定输出目录名（默认 TestTool）
output_name = os.environ.get('TESTTOOL_OUTPUT_NAME', 'TestTool')

# 分析主程序
a = Analysis(
    [str(project_root / 'src' / 'app' / 'main.py')],
    pathex=[
        str(project_root),
        str(project_root / 'src'),
    ],
    binaries=[
        (str(project_root / 'test' / 'canapp' / dll), 'test/canapp')
        for dll in ['CHUSBDLL64.dll', 'ECanVci64.dll']
        if (project_root / 'test' / 'canapp' / dll).exists()
    ] + _pcan_binaries + _tk_binaries,
    datas=datas,
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'pymodbus',
        'pymodbus.client',
        'pymodbus.client.serial',
        'pymodbus.client.tcp',
        'pymodbus.client.sync',
        'pyserial',
        'serial',
        'websockets',
        'requests',
        'httpx',
        'pandas',
        'matplotlib',
        'matplotlib.backends',
        'matplotlib.backends.backend_pdf',
        'matplotlib.pyplot',
        'numpy',
        'cryptography',
        'pyvisa',
        'yaml',
        'pydantic',
        'asyncio',
        'threading',
        # OpenCV (cv2) - 用于图像处理
        'cv2',
        'cv2.cv2',
    ] + cv2_submodules + [
        # PIL/Pillow - 用于图像处理
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        # 项目内部模块
        'src',
        'src.app',
        'src.app.views',
        'src.app.tools',
        'src.config',
        'src.core',
        'src.app_logging',
        'src.app_logging.config',
        'src.drivers',
        'src.drivers.comm',
        'src.drivers.instruments',
        'src.instruments',
        'src.mes',
        'src.mes.adapters',
        'src.security',
        'src.selfcheck',
        'src.testcases',
        'src.testcases.steps',
        'src.testcases.steps.cases',
        'src.testcases.steps.utility',
        'src.testcases.steps.common',
        'src.uut',
        # CAN 相关模块（动态导入需要）
        'can_sender',
        'test.canapp.can_sender',
        # test/dogleg/tool.py 动态 import 依赖（狗腿 PcanConnect 步骤）
        'PCANBasic',
        'matplotlib.backends.backend_tkagg',
        'matplotlib.backends._backend_tk',
        'matplotlib.backend_bases',
        'matplotlib.figure',
    ] + _tk_hidden + [
        # client 模块（工程测试客户端）
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
    excludes=[
        'matplotlib.tests',
        'numpy.tests',
        'pandas.tests',
        'pytest',
        # 注意：不要排除 unittest，因为某些库（如 matplotlib）可能需要它
        # 'unittest',  # 注释掉，确保 unittest 被包含
        'test',
        'tests',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 收集所有依赖
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 创建可执行文件 - 使用 onedir 模式（目录结构）
# 这样配置文件会包含在 _internal 目录中，方便修改和维护
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # 不将二进制文件打包进 exe，而是放在目录中
    name='TestTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,  # 不显示控制台窗口（GUI应用）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可以在这里指定图标文件路径
)

# 创建目录结构（onedir 模式）
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=output_name,
)

