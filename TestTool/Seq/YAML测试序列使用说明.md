# YAML 测试序列使用说明

## 概述

本目录包含了多个YAML测试序列文件，用于 VITA 机器人的测试流程。

---

## 文件列表

### 1. Vita01-MT-1.0-20250913.yaml
**原始测试序列** - 仅包含扫描序列号步骤

```yaml
steps:
  - step_1: ScanSN (扫描序列号)
```

**用途**: 基础序列号扫描测试

---

### 2. Vita01-MT-1.0-EngineerMode.yaml ⭐ 推荐
**自动工程模式序列** - 连接时自动进入工程模式

```yaml
steps:
  - step_1: ScanSN (扫描序列号)
  - step_2: ConnectEngineerService (连接并自动进入工程模式)
```

**特点**:
- ✅ 使用系统内置的连接步骤
- ✅ 自动处理工程模式进入逻辑
- ✅ 更稳定可靠
- ✅ 推荐用于生产环境

**使用场景**:
- 需要连接工程服务并进入工程模式
- 标准的测试流程
- 生产线测试

**示例**:
```yaml
- id: step_2
  name: EnterEngineerMode
  type: connect_engineer
  params:
    host: '192.168.125.2'
    port: 3579
    timeout_ms: 10000
```

---

### 3. Vita01-MT-1.0-EnfacCommand.yaml
**显式命令序列** - 使用enfac命令控制工程模式

```yaml
steps:
  - step_1: ScanSN (扫描序列号)
  - step_2: ConnectEngineerService (连接工程服务)
  - step_3: EnterEngineerModeByEnfac (执行enfac=1,1%命令)
```

**特点**:
- ✅ 显式控制工程模式命令
- ✅ 可以自定义命令参数
- ✅ 支持任意工程服务命令
- ✅ 适合调试和开发

**使用场景**:
- 需要精确控制工程模式命令
- 调试工程服务通信
- 自定义测试流程

**示例**:
```yaml
- id: step_3
  name: EnterEngineerModeByEnfac
  type: engineer.command
  params:
    command: 'enfac=1,1%'
    timeout_ms: 5000
    expect_success: true
```

---

## 两种方式的对比

| 特性 | EngineerMode (推荐) | EnfacCommand (灵活) |
|------|---------------------|---------------------|
| **步骤数** | 2步 | 3步 |
| **简洁性** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **稳定性** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **灵活性** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **推荐场景** | 生产环境 | 调试开发 |
| **自动化程度** | 高（自动进入工程模式） | 中（需显式命令） |
| **命令自定义** | 不支持 | 支持 |

---

## 使用方法

### 方式1: 在测试工具中加载

在测试工具界面中：
1. 打开 "测试序列" 菜单
2. 选择 "加载序列文件"
3. 选择对应的 YAML 文件
4. 点击 "开始测试"

### 方式2: 命令行运行

```bash
# 使用推荐方式（自动工程模式）
python main.py --sequence Seq/Vita01-MT-1.0-EngineerMode.yaml

# 使用显式命令方式
python main.py --sequence Seq/Vita01-MT-1.0-EnfacCommand.yaml
```

---

## 新增步骤类型说明

### engineer.command 步骤

用于执行任意工程服务命令的通用步骤。

**参数**:
- `command` (必需): 命令字符串，如 "enfac=1,1%"
- `timeout_ms` (可选): 命令超时时间（毫秒），默认 5000
- `expect_success` (可选): 是否期望命令成功，默认 true

**支持的命令格式**:
```
# 工程模式控制
enfac=0%          # 查询工程模式状态
enfac=1,1%        # 进入工程模式
enfac=1,0%        # 退出工程模式

# 其他工程服务命令
version=0%        # 查询版本
battery=0%        # 查询电池
camera=3,rgb%     # 相机拍照
lidar=3,360,1000% # 雷达扫描
...

# 参考 client/TEST_COMMANDS_GUIDE.md 获取完整命令列表
```

**完整示例**:
```yaml
# 查询版本信息
- id: query_version
  name: QueryVersion
  type: engineer.command
  params:
    command: 'version=0%'
    timeout_ms: 5000

# 查询电池状态
- id: query_battery
  name: QueryBattery
  type: engineer.command
  params:
    command: 'battery=0%'
    timeout_ms: 3000

# 相机拍照
- id: camera_capture
  name: CameraCapture
  type: engineer.command
  params:
    command: 'camera=3,rgb%'
    timeout_ms: 10000

# 退出工程模式
- id: exit_engineer
  name: ExitEngineerMode
  type: engineer.command
  params:
    command: 'enfac=1,0%'
    timeout_ms: 5000
```

---

## 完整测试流程示例

### 场景1: 基础工程模式测试
```yaml
steps:
  - id: step_1
    name: ScanSN
    type: scan.sn
    
  - id: step_2
    name: ConnectAndEnterEngineer
    type: connect_engineer
    params:
      host: '192.168.125.2'
      port: 3579
      
  - id: step_3
    name: QueryVersion
    type: engineer.command
    params:
      command: 'version=0%'
      
  - id: step_4
    name: DisconnectEngineer
    type: disconnect_engineer
```

### 场景2: 完整传感器测试
```yaml
steps:
  - id: step_1
    name: ScanSN
    type: scan.sn
    
  - id: step_2
    name: ConnectEngineer
    type: connect_engineer
    params:
      host: '192.168.125.2'
      port: 3579
      
  - id: step_3
    name: QueryBattery
    type: engineer.command
    params:
      command: 'battery=0%'
      
  - id: step_4
    name: CameraCapture
    type: engineer.command
    params:
      command: 'camera=3,rgb%'
      timeout_ms: 10000
      
  - id: step_5
    name: LidarScan
    type: engineer.command
    params:
      command: 'lidar=3,360,1000%'
      timeout_ms: 15000
      
  - id: step_6
    name: DisconnectEngineer
    type: disconnect_engineer
```

---

## 注意事项

### 1. 连接顺序
- ⚠️ 必须先执行 `connect_engineer` 才能使用 `engineer.command`
- ⚠️ 测试完成后建议执行 `disconnect_engineer` 断开连接

### 2. 超时设置
- 不同命令需要不同的超时时间
- 相机拍照: 建议 10000ms
- 雷达扫描: 建议 15000ms
- 基本查询: 建议 3000-5000ms

### 3. 重试策略
- 网络连接步骤: 建议 `retries: 3`
- 命令执行步骤: 建议 `retries: 1-2`
- 关键步骤: 设置 `on_failure: fail`

### 4. IP地址配置
- 默认IP: `192.168.125.2`
- 默认端口: `3579`
- 可在配置文件中统一修改，也可在YAML中单独指定

---

## 配置文件集成

如果不想在每个YAML中指定IP和端口，可以在 `Config/config.yaml` 中配置：

```yaml
ports:
  1:
    uut:
      tcp:
        host: "192.168.125.2"
        port: 3579
        timeout_ms: 10000
```

然后在YAML中省略这些参数：

```yaml
- id: step_2
  name: ConnectEngineer
  type: connect_engineer
  params: {}  # 将从配置文件读取
```

---

## 故障排查

### 连接失败
```
错误: 未连接到工程师服务
解决: 
1. 检查机器人IP地址是否正确
2. 确认网络连接正常
3. 验证端口3579未被占用
4. 检查防火墙设置
```

### 命令执行失败
```
错误: 命令执行失败
解决:
1. 确认已执行 connect_engineer 步骤
2. 检查命令格式是否正确（必须以%结尾）
3. 增加超时时间
4. 查看详细日志了解具体错误
```

### 超时问题
```
错误: 命令执行超时
解决:
1. 增加 timeout_ms 参数值
2. 检查网络延迟
3. 确认机器人响应正常
```

---

## 扩展阅读

- **工程服务命令完整列表**: `client/TEST_COMMANDS_GUIDE.md`
- **命令快速参考**: `client/COMMAND_QUICK_REFERENCE.md`
- **测试步骤开发指南**: `测试Case二次开发指南.md`
- **配置文件说明**: `client/vita_engineer_client/README_JSON_CONFIG.md`

---

## 更新记录

- **2025-10-30**: 创建文档，添加两个新的测试序列YAML文件
- **2025-10-30**: 新增 `engineer.command` 步骤类型，支持执行任意工程服务命令

---

## 技术支持

如有问题，请参考：
1. 本文档的故障排查部分
2. `client/TEST_COMMANDS_GUIDE.md` 获取命令详细说明
3. 查看系统日志了解详细错误信息

