# 快速开始 - TestTool 构建指南

## 一键构建

### Windows 用户（推荐）

1. **双击运行** `build.bat`
2. 等待构建完成（首次构建可能需要 3-5 分钟）
3. 构建完成后，在 `dist/` 目录找到 `TestTool.exe`

### PowerShell 用户

```powershell
cd build
.\build.ps1
```

## 构建输出

构建完成后，所有文件将位于 `dist/` 目录：

```
dist/
├── TestTool.exe          # 主程序（可直接运行）
├── Config/               # 配置文件目录
│   └── config.yaml
├── Seq/                  # 测试序列文件目录
├── examples/             # 示例文件
└── [其他依赖文件]        # PyInstaller 自动生成的依赖
```

## 部署到其他电脑

### 方法 1: 完整部署（推荐）

1. 将整个 `dist/` 目录复制到目标电脑
2. 确保目录结构保持不变
3. 直接运行 `TestTool.exe`

### 方法 2: 最小部署

1. 复制以下文件/目录：
   - `TestTool.exe`
   - `Config/` 目录
   - `Seq/` 目录（如果需要）
   - PyInstaller 生成的依赖文件（通常以 `_internal` 结尾的目录）

## 常见问题

### Q: 构建失败，提示找不到模块？

**A:** 检查 `requirements.txt` 是否包含所有依赖，然后重新运行构建脚本。

### Q: 运行时报错找不到配置文件？

**A:** 确保 `Config/` 目录与 `TestTool.exe` 在同一目录下。

### Q: 打包后的文件太大？

**A:** 这是正常的，PyInstaller 会包含 Python 解释器和所有依赖。如果需要减小体积，可以：
- 使用虚拟环境只安装必要的包
- 在 spec 文件的 `excludes` 中添加不需要的模块

### Q: 杀毒软件报毒？

**A:** 这是误报，PyInstaller 打包的程序经常被误报。可以：
- 添加到杀毒软件白名单
- 使用代码签名证书签名（需要购买）

## 技术支持

如遇到问题，请检查：
1. Python 版本是否为 3.10+
2. 所有依赖是否已正确安装
3. 构建日志中的错误信息





