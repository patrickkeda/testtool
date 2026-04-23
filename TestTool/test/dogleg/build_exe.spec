# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller打包配置文件
用于将电机控制程序打包成独立的exe文件
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules
import os

# 收集所有必要的数据文件和二进制文件
datas = []
binaries = []
hiddenimports = []

# 收集matplotlib的所有资源（包括字体、样式等）
matplotlib_data = collect_all('matplotlib')
datas += matplotlib_data[0]
binaries += matplotlib_data[1]
hiddenimports += matplotlib_data[2]

# 收集pymodbus的所有资源
pymodbus_data = collect_all('pymodbus')
datas += pymodbus_data[0]
binaries += pymodbus_data[1]
hiddenimports += pymodbus_data[2]

# 收集serial.tools的所有资源
try:
    serial_data = collect_all('serial')
    datas += serial_data[0]
    binaries += serial_data[1]
    hiddenimports += serial_data[2]
except:
    pass

# 手动添加必要的隐藏导入
hiddenimports += [
    'matplotlib.backends.backend_tkagg',
    'matplotlib.figure',
    'matplotlib.backends._backend_tk',
    'pymodbus.client.serial',
    'pymodbus.exceptions',
    'serial.tools.list_ports',
    'PCANBasic',
    'tkinter',
    'tkinter.ttk',
    'queue',
    'threading',
    'struct',
    'unittest',  # matplotlib需要
    'unittest.mock',  # matplotlib可能需要
    'pkg_resources.py2_warn',  # 避免警告
]

# 尝试包含PCANBasic.dll（如果存在）
# 注意：在spec文件中不能使用__file__，使用当前工作目录
pcan_dll_paths = [
    'PCANBasic.dll',
    './PCANBasic.dll',
    '../PCANBasic.dll',
    os.path.join(os.getcwd(), 'PCANBasic.dll'),
]

for dll_path in pcan_dll_paths:
    abs_path = os.path.abspath(dll_path)
    if os.path.exists(abs_path):
        binaries.append((abs_path, '.'))
        print(f"找到PCANBasic.dll: {abs_path}")
        break
else:
    print("警告: 未找到PCANBasic.dll，请确保PCANBasic.dll在程序目录下")

# 添加matplotlib的字体配置
try:
    import matplotlib
    mpl_data_dir = os.path.dirname(matplotlib.__file__)
    # 包含matplotlib的字体目录
    font_dir = os.path.join(mpl_data_dir, 'fonts')
    if os.path.exists(font_dir):
        datas.append((font_dir, 'matplotlib/fonts'))
except:
    pass

# 分析主程序
a = Analysis(
    ['tool.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest',
        'test',
        'tests',
        # 注意：不要排除unittest和distutils，某些库需要它们
    ],
    noarchive=False,
    optimize=0,
)

# 创建PYZ文件
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# 创建目录模式exe（更稳定，便于分发）
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='电机控制程序',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # 使用UPX压缩（如果可用）
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可以添加图标文件路径，如: 'icon.ico'
)

# 收集所有文件到dist目录
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='电机控制程序',
)
