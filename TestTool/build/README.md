# TestTool 构建说明

本目录包含用于将 TestTool 打包成独立可执行文件的构建脚本和配置文件。

## 目录结构

```
build/
├── TestTool.spec      # PyInstaller 配置文件
├── build.bat          # Windows Batch 构建脚本
├── build.ps1          # PowerShell 构建脚本
└── README.md          # 本文件
```

## 前置要求

1. **Python 3.10+** - 确保已安装 Python 3.10 或更高版本
2. **依赖包** - 构建脚本会自动安装所需依赖，包括：
   - PyInstaller（用于打包）
   - 项目所需的所有依赖（从 `requirements.txt` 读取）

## 使用方法

### 方法 1: 使用 Batch 脚本（推荐）

1. 双击运行 `build.bat`
2. 等待构建完成
3. 构建产物位于 `../dist/TestTool.exe`

### 方法 2: 使用 PowerShell 脚本

1. 右键点击 `build.ps1`，选择"使用 PowerShell 运行"
2. 或者打开 PowerShell，执行：
   ```powershell
   cd build
   .\build.ps1
   ```
3. 等待构建完成
4. 构建产物位于 `../dist/TestTool.exe`

### 方法 3: 手动执行

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   pip install pyinstaller
   ```

2. 执行打包：
   ```bash
   cd build
   pyinstaller TestTool.spec --clean --noconfirm
   ```

## 构建输出

构建完成后，所有文件将输出到 `dist/` 目录：

```
dist/
├── TestTool.exe          # 主可执行文件
├── Config/               # 配置文件目录
├── Seq/                  # 测试序列文件目录
├── examples/             # 示例文件目录
└── [其他依赖文件]        # PyInstaller 生成的依赖文件
```

## 部署到其他电脑

1. **完整部署**（推荐）：
   - 将整个 `dist/` 目录复制到目标电脑
   - 确保目标电脑有相同的目录结构
   - 直接运行 `TestTool.exe`

2. **最小部署**：
   - 复制 `TestTool.exe` 和必要的配置文件（`Config/`、`Seq/`）
   - 注意：可能需要包含 PyInstaller 生成的依赖 DLL 文件

## 配置说明

### TestTool.spec 文件

这是 PyInstaller 的配置文件，包含以下主要配置：

- **主程序入口**: `src/app/main.py`
- **包含的数据文件**:
  - `Config/` - 配置文件目录
  - `Seq/` - 测试序列文件目录
  - `examples/` - 示例文件目录
  - `config_selfcheck.yaml` - 自检配置文件
- **包含的二进制文件**:
  - `test/canapp/CHUSBDLL64.dll`
  - `test/canapp/ECanVci64.dll`
- **隐藏导入**: 包含所有必要的 Python 模块

### 自定义配置

如果需要修改打包配置，可以编辑 `TestTool.spec` 文件：

- **添加图标**: 在 `EXE` 部分设置 `icon='path/to/icon.ico'`
- **添加更多数据文件**: 在 `datas` 列表中添加元组 `(源路径, 目标路径)`
- **添加更多二进制文件**: 在 `binaries` 列表中添加元组 `(源路径, 目标路径)`
- **排除模块**: 在 `excludes` 列表中添加不需要的模块名

## 常见问题

### 1. 构建失败：找不到模块

**解决方案**: 检查 `hiddenimports` 列表，添加缺失的模块。

### 2. 运行时缺少 DLL

**解决方案**: 确保 `binaries` 列表中包含了所有必要的 DLL 文件。

### 3. 配置文件找不到

**解决方案**: 检查 `datas` 列表，确保配置文件路径正确。

### 4. 打包后的文件太大

**解决方案**: 
- 在 `excludes` 中添加不需要的模块
- 使用 `--onefile` 模式（需要修改 spec 文件）

### 5. 控制台窗口出现

**解决方案**: 在 spec 文件中设置 `console=False`（已默认设置）。

## 注意事项

1. **首次构建时间较长**: PyInstaller 需要分析所有依赖，首次构建可能需要几分钟
2. **杀毒软件误报**: 某些杀毒软件可能会误报 PyInstaller 打包的程序，这是正常现象
3. **路径问题**: 打包后的程序使用相对路径，确保配置文件在正确的位置
4. **Python 版本**: 建议使用与开发环境相同的 Python 版本进行打包

## 更新日志

- **v1.0** (2026-01-05): 初始版本，支持基本的打包功能





