# 电机控制程序打包说明

## 快速开始

### 方法一：使用批处理文件（推荐Windows用户）

1. 双击运行 `build.bat`
2. 等待打包完成
3. 在 `dist` 目录下找到 `电机控制程序.exe`

### 方法二：使用Python脚本

```bash
python build.py
```

### 方法三：手动打包

```bash
# 安装PyInstaller（如果未安装）
pip install pyinstaller

# 使用spec文件打包
pyinstaller build_exe.spec --clean
```

## 打包前准备

### 1. 安装Python依赖

```bash
pip install pyinstaller matplotlib pymodbus pyserial
```

### 2. 准备PCANBasic.dll

确保 `PCANBasic.dll` 文件在以下位置之一：
- 与 `tool.py` 同一目录
- 打包后与 `exe` 文件同一目录

### 3. 检查文件

确保以下文件存在：
- `tool.py` - 主程序文件
- `build_exe.spec` - PyInstaller配置文件
- `PCANBasic.dll` - PCAN驱动库（可选，但建议提供）

## 打包后的文件结构

```
dist/
└── 电机控制程序.exe    # 主程序（单文件，包含所有依赖）
```

## 分发程序

### 单文件分发

打包后的 `电机控制程序.exe` 是一个独立的可执行文件，包含所有Python依赖。

**需要一起分发的文件：**
- `电机控制程序.exe` - 主程序
- `PCANBasic.dll` - PCAN驱动库（如果使用PCAN功能）

### 安装说明（给最终用户）

1. 将 `电机控制程序.exe` 和 `PCANBasic.dll` 放在同一文件夹
2. 双击运行 `电机控制程序.exe`
3. 首次运行可能需要几秒钟加载时间

## 常见问题

### 1. 打包失败

**问题：** 提示缺少某个模块

**解决：**
```bash
pip install 缺少的模块名
```

### 2. 程序无法运行

**问题：** 双击exe没有反应或报错

**解决：**
- 检查是否有 `PCANBasic.dll` 文件
- 尝试在命令行运行exe查看错误信息
- 检查杀毒软件是否拦截

### 3. 文件太大

**问题：** 生成的exe文件很大（通常100-200MB）

**说明：** 这是正常的，因为包含了Python解释器和所有依赖库（matplotlib、pymodbus等）

**优化：**
- 使用 `--onefile` 模式（已在spec文件中配置）
- 使用UPX压缩（如果可用）

### 4. 缺少字体

**问题：** 图表中文显示为方框

**解决：** spec文件已自动包含matplotlib字体，如果仍有问题：
- 确保系统有中文字体（如SimHei）
- 或手动添加字体文件到打包配置

## 高级配置

### 修改程序图标

在 `build_exe.spec` 文件中找到：
```python
icon=None,  # 可以添加图标文件路径，如: 'icon.ico'
```

改为：
```python
icon='icon.ico',  # 你的图标文件路径
```

### 添加版本信息

在 `build_exe.spec` 的 `EXE` 部分添加：
```python
version='version_info.txt',  # 版本信息文件
```

### 排除不需要的模块

在 `build_exe.spec` 的 `excludes` 列表中添加要排除的模块：
```python
excludes=[
    'pytest',
    'unittest',
    'test',
    # 添加其他不需要的模块
],
```

## 技术说明

### 打包模式

- **单文件模式（onefile）**：所有依赖打包到一个exe文件
  - 优点：分发方便，只需一个文件
  - 缺点：启动稍慢（需要解压临时文件）

### 包含的库

- Python 3.x 解释器
- tkinter（GUI框架）
- matplotlib（图表库）
- pymodbus（Modbus通信）
- pyserial（串口通信）
- PCANBasic（CAN通信，需要DLL）

### 文件大小

- 基础exe：约100-150MB
- 包含所有依赖：约150-200MB

这是正常的，因为包含了完整的Python运行时环境。

## 联系支持

如果遇到打包问题，请检查：
1. Python版本（建议3.7+）
2. 所有依赖是否已安装
3. PCANBasic.dll是否存在
4. 错误日志信息
