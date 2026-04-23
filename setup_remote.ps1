# 远程仓库设置脚本
# 使用方法：在PowerShell中运行 .\setup_remote.ps1

Write-Host "=== TestTool 远程仓库设置 ===" -ForegroundColor Green
Write-Host ""

# 检查是否已有远程仓库
$remotes = git remote -v
if ($remotes) {
    Write-Host "当前已配置的远程仓库：" -ForegroundColor Yellow
    Write-Host $remotes
    Write-Host ""
    $overwrite = Read-Host "是否要添加新的远程仓库？(y/n)"
    if ($overwrite -ne "y" -and $overwrite -ne "Y") {
        Write-Host "已取消操作" -ForegroundColor Yellow
        exit 0
    }
}

Write-Host "请选择Git托管服务：" -ForegroundColor Cyan
Write-Host "1. GitHub"
Write-Host "2. GitLab"
Write-Host "3. Gitee (码云)"
Write-Host "4. 其他（手动输入）"
Write-Host ""

$choice = Read-Host "请输入选项 (1-4)"

$repoUrl = ""

switch ($choice) {
    "1" {
        Write-Host ""
        Write-Host "GitHub 设置步骤：" -ForegroundColor Yellow
        Write-Host "1. 访问 https://github.com/new 创建新仓库"
        Write-Host "2. 仓库名称建议：TestTool 或 TestTool-v0.4"
        Write-Host "3. 选择 Public 或 Private"
        Write-Host "4. 不要初始化 README、.gitignore 或 license（因为本地已有）"
        Write-Host "5. 创建后复制仓库地址"
        Write-Host ""
        $username = Read-Host "请输入您的GitHub用户名"
        $repoName = Read-Host "请输入仓库名称（默认：TestTool）"
        if (-not $repoName) { $repoName = "TestTool" }
        $repoUrl = "https://github.com/$username/$repoName.git"
        Write-Host ""
        Write-Host "仓库地址：$repoUrl" -ForegroundColor Cyan
    }
    "2" {
        Write-Host ""
        Write-Host "GitLab 设置步骤：" -ForegroundColor Yellow
        Write-Host "1. 访问 https://gitlab.com/projects/new 创建新项目"
        Write-Host "2. 项目名称建议：TestTool 或 TestTool-v0.4"
        Write-Host "3. 选择可见性级别"
        Write-Host "4. 不要初始化 README（因为本地已有）"
        Write-Host "5. 创建后复制仓库地址"
        Write-Host ""
        $username = Read-Host "请输入您的GitLab用户名或组织名"
        $repoName = Read-Host "请输入项目名称（默认：TestTool）"
        if (-not $repoName) { $repoName = "TestTool" }
        $repoUrl = "https://gitlab.com/$username/$repoName.git"
        Write-Host ""
        Write-Host "仓库地址：$repoUrl" -ForegroundColor Cyan
    }
    "3" {
        Write-Host ""
        Write-Host "Gitee 设置步骤：" -ForegroundColor Yellow
        Write-Host "1. 访问 https://gitee.com/projects/new 创建新仓库"
        Write-Host "2. 仓库名称建议：TestTool 或 TestTool-v0.4"
        Write-Host "3. 选择公开或私有"
        Write-Host "4. 不要初始化 README、.gitignore 或 license（因为本地已有）"
        Write-Host "5. 创建后复制仓库地址"
        Write-Host ""
        $username = Read-Host "请输入您的Gitee用户名或组织名"
        $repoName = Read-Host "请输入仓库名称（默认：TestTool）"
        if (-not $repoName) { $repoName = "TestTool" }
        $repoUrl = "https://gitee.com/$username/$repoName.git"
        Write-Host ""
        Write-Host "仓库地址：$repoUrl" -ForegroundColor Cyan
    }
    "4" {
        Write-Host ""
        $repoUrl = Read-Host "请输入完整的仓库地址（例如：https://github.com/username/repo.git）"
    }
    default {
        Write-Host "无效选项" -ForegroundColor Red
        exit 1
    }
}

if (-not $repoUrl) {
    Write-Host "错误：未提供仓库地址" -ForegroundColor Red
    exit 1
}

Write-Host ""
$confirm = Read-Host "确认添加远程仓库：$repoUrl (y/n)"
if ($confirm -ne "y" -and $confirm -ne "Y") {
    Write-Host "已取消操作" -ForegroundColor Yellow
    exit 0
}

# 添加远程仓库
Write-Host ""
Write-Host "正在添加远程仓库..." -ForegroundColor Yellow
try {
    git remote add origin $repoUrl
    Write-Host "✓ 远程仓库添加成功" -ForegroundColor Green
} catch {
    Write-Host "✗ 添加远程仓库失败：$_" -ForegroundColor Red
    exit 1
}

# 验证远程仓库
Write-Host ""
Write-Host "验证远程仓库配置：" -ForegroundColor Cyan
git remote -v

Write-Host ""
Write-Host "=== 下一步操作 ===" -ForegroundColor Green
Write-Host ""
Write-Host "1. 推送代码到远程仓库：" -ForegroundColor Yellow
Write-Host "   git push -u origin master" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. 如果远程仓库使用 main 分支，请先重命名本地分支：" -ForegroundColor Yellow
Write-Host "   git branch -M main" -ForegroundColor Cyan
Write-Host "   git push -u origin main" -ForegroundColor Cyan
Write-Host ""
Write-Host "3. 如果遇到认证问题，请配置SSH密钥或使用Personal Access Token" -ForegroundColor Yellow
Write-Host ""

$pushNow = Read-Host "是否现在推送代码到远程仓库？(y/n)"
if ($pushNow -eq "y" -or $pushNow -eq "Y") {
    Write-Host ""
    Write-Host "正在推送代码..." -ForegroundColor Yellow
    try {
        git push -u origin master
        Write-Host ""
        Write-Host "✓ 代码推送成功！" -ForegroundColor Green
    } catch {
        Write-Host ""
        Write-Host "✗ 推送失败，请检查：" -ForegroundColor Red
        Write-Host "  1. 远程仓库是否已创建" -ForegroundColor Yellow
        Write-Host "  2. 网络连接是否正常" -ForegroundColor Yellow
        Write-Host "  3. 认证信息是否正确（可能需要配置SSH密钥或Token）" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "您可以稍后手动运行：git push -u origin master" -ForegroundColor Cyan
    }
}














