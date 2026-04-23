# Git 仓库快速设置脚本
# 使用方法：在PowerShell中运行 .\setup_git.ps1

Write-Host "=== TestTool Git 仓库设置 ===" -ForegroundColor Green
Write-Host ""

# 检查是否已配置用户信息
$userName = git config user.name
$userEmail = git config user.email

if (-not $userName -or -not $userEmail) {
    Write-Host "检测到未配置Git用户信息，请先配置：" -ForegroundColor Yellow
    Write-Host ""
    
    $name = Read-Host "请输入您的姓名"
    $email = Read-Host "请输入您的邮箱"
    
    if ($name -and $email) {
        git config user.name $name
        git config user.email $email
        Write-Host "✓ 用户信息配置成功" -ForegroundColor Green
    } else {
        Write-Host "✗ 用户信息未配置，请手动运行：" -ForegroundColor Red
        Write-Host "  git config user.name `"Your Name`"" -ForegroundColor Yellow
        Write-Host "  git config user.email `"your.email@example.com`"" -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "✓ Git用户信息已配置：" -ForegroundColor Green
    Write-Host "  姓名: $userName" -ForegroundColor Cyan
    Write-Host "  邮箱: $userEmail" -ForegroundColor Cyan
    Write-Host ""
}

# 检查是否有未提交的文件
$status = git status --short
if ($status) {
    Write-Host "检测到未提交的文件，准备进行初始提交..." -ForegroundColor Yellow
    Write-Host ""
    
    $confirm = Read-Host "是否现在进行初始提交？(Y/N)"
    if ($confirm -eq "Y" -or $confirm -eq "y") {
        git commit -m "Initial commit: TestTool v0.4 - 生产线测试工具完整代码库

- 完整的测试框架和UI界面
- Modbus电机控制步骤实现
- 测试序列配置和运行器
- MES集成和安全模块
- 日志和配置管理
- 文档和示例"
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "✓ 初始提交成功！" -ForegroundColor Green
            Write-Host ""
            Write-Host "下一步：创建远程仓库并推送代码" -ForegroundColor Cyan
            Write-Host "1. 在 GitHub/GitLab/Gitee 上创建新仓库" -ForegroundColor Yellow
            Write-Host "2. 运行: git remote add origin <仓库地址>" -ForegroundColor Yellow
            Write-Host "3. 运行: git push -u origin master" -ForegroundColor Yellow
        } else {
            Write-Host "✗ 提交失败，请检查错误信息" -ForegroundColor Red
        }
    } else {
        Write-Host "已取消提交" -ForegroundColor Yellow
    }
} else {
    Write-Host "✓ 没有未提交的文件" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== 设置完成 ===" -ForegroundColor Green















