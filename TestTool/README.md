## 智能硬件生产线检测软件 — 项目架构与技术规范

本项目面向 Windows 平台，采用 Python 3.10+ 与 PySide6 构建一套模块化、可维护的生产线测试工具。本文档描述项目架构、模块职责与统一接口、配置与日志规范、数据库设计、错误处理策略、插件/扩展机制、安全与权限模型以及报表与开发规范。待方案确认后再开始逐模块实现。

---

### 1. 技术栈与总体约束
- **语言**: Python 3.10+
- **GUI**: PySide6
- **数据库**: SQLite (用于配置/结果/用户/审计)
- **通信**: `pyserial`(串口/485), `socket`(TCP/UDP)
- **仪器控制**: `pyvisa` 或厂家 SDK
- **网络请求**: `requests`
- **数据处理/可视化**: `pandas`, `matplotlib`
- **日志**: Python `logging`（禁止使用 `print` 输出日志）
- **配置**: YAML（严禁硬编码）
- **并发/异步**: 优先 `asyncio` 提升多 I/O 效率
- **异常与可靠性**: 所有外设/网络操作需具备超时、重试与详尽日志

---

### 2. 目录结构（当前实现状态）

```
TestTool/
  ├─ src/
  │   ├─ app/                      # 人机交互与主程序入口（PySide6 UI、启动器）✅
  │   │   ├─ __init__.py
  │   │   ├─ main.py               # 主程序入口
  │   │   ├─ i18n.py               # 国际化支持
  │   │   ├─ log_bridge.py         # 日志桥接
  │   │   ├─ sequence_model.py     # 测试序列模型
  │   │   ├─ worker.py             # 后台工作线程
  │   │   └─ views/                # UI界面
  │   │       ├─ __init__.py
  │   │       ├─ main_window.py    # 主窗口
  │   │       ├─ port_panel.py     # 端口面板
  │   │       └─ config_dialog.py  # 配置对话框
  │   │
  │   ├─ config/                   # 配置加载/校验、加密及示例 YAML ✅
  │   │   ├─ __init__.py
  │   │   ├─ models.py             # Pydantic配置模型
  │   │   ├─ secrets.py            # 敏感信息加密
  │   │   └─ service.py            # 配置服务
  │   │
  │   ├─ core/                     # 通用基础设施（事件总线、调度器、插件、错误）✅
  │   │   ├─ __init__.py
  │   │   ├─ bus.py                # 事件总线（同步/异步）
  │   │   ├─ scheduler.py          # 调度器（once/interval/超时/重试/取消）
  │   │   ├─ lifecycle.py          # 生命周期管理（依赖拓扑启动/停止）
  │   │   ├─ messages.py           # 跨模块消息契约（TypedDict/Enum）
  │   │   ├─ errors.py             # 统一错误层级与分类
  │   │   ├─ health.py             # 健康检查聚合
  │   │   └─ plugins.py            # 插件注册表与入口点加载
  │   ├─ logging/                  # 日志初始化、格式、过滤与存储管理 ✅
  │   │   ├─ __init__.py
  │   │   ├─ config.py             # 日志配置模型
  │   │   ├─ manager.py            # 日志管理器
  │   │   ├─ handlers.py           # 自定义日志处理器
  │   │   ├─ formatters.py         # 日志格式化器
  │   │   ├─ test_logger.py        # 测试结果日志器
  │   │   └─ error_logger.py       # 错误日志器
  │   ├─ mes/                      # MES 统一接口与各厂商适配器 ✅
  │   │   ├─ __init__.py           # 模块入口
  │   │   ├─ models.py             # 数据模型（WorkOrder, TestResult, MESConfig等）
  │   │   ├─ interfaces.py         # 接口定义
  │   │   ├─ client.py             # MES客户端基类
  │   │   ├─ factory.py            # 适配器工厂
  │   │   ├─ heartbeat.py          # 心跳检测
  │   │   └─ adapters/             # 各厂商适配器
  │   │       ├─ __init__.py
  │   │       ├─ base.py           # 适配器基类
  │   │       └─ sample_mes.py     # 示例MES适配器
  │   ├─ testcases/                # 测试用例框架与内置步骤库 ✅
  │   │   ├─ __init__.py
  │   │   ├─ config.py             # 测试序列配置模型
  │   │   ├─ mode_manager.py       # 模式管理器（生产/调试）
  │   │   ├─ context.py            # 测试上下文管理
  │   │   ├─ step.py               # 测试步骤接口和基类
  │   │   ├─ runner.py             # 测试执行引擎
  │   │   ├─ validator.py          # 结果验证器
  │   │   ├─ variables.py          # 变量管理器
  │   │   ├─ utils.py              # 工具函数
  │   │   └─ steps/                # 内置测试步骤库
  │   │       ├─ __init__.py
  │   │       ├─ comm_steps.py     # 通信步骤
  │   │       ├─ instrument_steps.py # 仪器控制步骤
  │   │       ├─ uut_steps.py      # UUT测试步骤
  │   │       ├─ mes_steps.py      # MES集成步骤
  │   │       └─ utility_steps.py  # 工具步骤
  │   ├─ uut/                      # 被测单元适配层（协议解析、命令集）✅
  │   │   ├─ __init__.py
  │   │   ├─ models.py             # UUT数据模型
  │   │   ├─ interfaces.py         # UUT接口定义
  │   │   ├─ adapter.py            # UUT适配器核心实现
  │   │   ├─ protocols.py          # 协议适配器实现
  │   │   ├─ command_manager.py    # 命令管理器
  │   │   └─ status_manager.py     # 状态管理器
  │   │
  │   ├─ drivers/                  # 驱动模块 ✅
  │   │   ├─ comm/                 # 串口/485/TCP/UDP 物理通信驱动 ✅
  │   │   │   ├─ __init__.py
  │   │   │   ├─ interfaces.py     # 通信接口抽象
  │   │   │   ├─ serial_transport.py # 串口实现
  │   │   │   ├─ tcp_transport.py  # TCP实现
  │   │   │   └─ factory.py        # 工厂模式
  │   │   │
  │   │   └─ instruments/          # 仪器仪表驱动（SCPI/SDK）✅
  │   │       ├─ __init__.py
  │   │       ├─ session.py        # 仪器会话抽象
  │   │       ├─ psu.py            # 电源接口
  │   │       └─ psu_scpi.py       # SCPI电源实现
  │   │
  │   ├─ selfcheck/                # 系统自检与初始化流程 ✅
  │   │   ├─ __init__.py           # 模块入口
  │   │   ├─ models.py             # 数据模型定义
  │   │   ├─ interfaces.py         # 接口定义
  │   │   ├─ checkers.py           # 基础检查器实现
  │   │   ├─ checkers_ext.py       # 扩展检查器实现
  │   │   ├─ manager.py            # 系统自检管理器
  │   │   ├─ check_stages.py       # 分阶段检查管理
  │   │   ├─ simple_api.py         # 简化API接口
  │   │   └─ stage_configs.py      # 分阶段配置管理
  │   ├─ security/                 # 认证、RBAC、加解密、审计 ⏳
  │   │   ├─ __init__.py           # 模块入口
  │   │   ├─ models.py             # 数据模型（User, Role, Permission, AuditLog）
  │   │   ├─ interfaces.py         # 接口定义
  │   │   ├─ auth_service.py       # 认证服务
  │   │   ├─ rbac_service.py       # 权限控制服务
  │   │   ├─ audit_service.py      # 审计服务
  │   │   ├─ encryption_service.py # 加密服务
  │   │   └─ decorators.py         # 权限装饰器
  │   ├─ reports/                  # 报表与统计分析（模板、导出、图表）⏳
  │   ├─ db/                       # SQLite 访问层与迁移脚本 ⏳
  │   └─ utils/                    # 工具集合（重试/超时、序列化、校验、国际化）⏳
  │
  ├─ resources/                    # 图标、i18n 文本、UI 模板、报表模板 ⏳
  ├─ examples/                     # 示例配置文件 ✅
  │   ├─ test_sequence_example.yaml # 测试序列配置示例
  │   └─ uut_config_example.yaml   # UUT配置示例
  ├─ tests/                        # 单元/集成测试 ⏳
  ├─ scripts/                      # 运维脚本、打包脚本 ⏳
  ├─ .env.example                  # 环境变量示例（密钥/凭据不入库）⏳
  ├─ config.yaml                   # 默认配置文件 ✅
  └─ README.md
```

**图例说明：**
- ✅ 已实现并可用
- ⏳ 待实现
- 📁 目录结构已规划，具体实现待定

### 2.1 实现进度总结

| 模块 | 状态 | 完成度 | 说明 |
|------|------|--------|------|
| **人机交互程序** | ✅ | 90% | 主界面、双端口面板、配置对话框、国际化、工作线程 |
| **配置管理** | ✅ | 95% | Pydantic模型、YAML支持、加密存储、配置服务 |
| **通信驱动** | ✅ | 85% | 串口/TCP实现、工厂模式、错误处理 |
| **仪器驱动** | ✅ | 80% | 程控电源SCPI、VISA会话、错误恢复 |
| **日志模块** | ✅ | 90% | 标准化日志管理、按日期组织、测试结果与错误分离 |
| **MES模块** | ✅ | 95% | MES集成和适配器、工单管理、结果上传、心跳监控 |
| **测试用例** | ✅ | 95% | 测试序列执行引擎、模式管理、权限控制、内置步骤库 |
| **UUT模块** | ✅ | 95% | 被测单元通信适配、协议解析、命令集管理、状态管理 |
| **系统自检** | ✅ | 95% | 分阶段检查、状态管理、全局状态变量 |
| **权限管理** | ✅ | 95% | 三角色权限控制、用户认证、操作审计 |
| **报表统计** | ⏳ | 0% | 待实现测试报告和数据分析 |
| **数据库** | ⏳ | 0% | 待实现SQLite数据访问层 |

**当前可用功能：**
- 双端口并行测试界面
- 配置参数管理（串口/TCP/MES）
- 通信驱动（串口/TCP）
- 程控电源控制
- 中英文界面切换
- 实时状态显示和日志输出
- 标准化日志管理（测试结果与错误分离）
- 按日期组织的日志文件结构
- 测试用例执行引擎（模式管理、权限控制、内置步骤库）
- UUT通信适配（协议解析、命令集管理、状态管理）
- 分阶段系统自检（启动检查、配置检查、测试检查）
- 全局状态管理（系统就绪、配置就绪、测试就绪）
- 三角色权限控制（操作员、工程师、管理员）
- 用户认证和会话管理
- 操作审计和日志追溯
- MES集成和适配器（工单管理、结果上传、心跳监控）

---

### 3. 模块职责与统一接口

以下为各模块核心职责与对外统一接口（概念级规范，具体类型与方法在实现时细化）。

- **人机交互程序（`app/`）**
  - 职责：主界面、实时结果/进度/告警可视化、多语言、看板、权限控制。
  


- **配置界面（`config/`）**
  - 职责：通信参数、产品/MES 参数管理；导入/导出；版本管理；校验；敏感信息加密存储。
  

- **Log 生成模块（`logging/`）**
  - 职责：标准化日志记录、分级存储、按日期组织、测试过程与错误分离；严格文件名规范。
 

- **MES 模块（`mes/`）** ✅
  - 职责：对接不同 MES，提供统一 API；结果上传、工单/参数获取；重试与超时、断网续传、心跳。
 

- **测试 Case 模块（`testcases/`）**
  - 职责：测试序列编排与执行、权限控制、模式管理、结果收集；支持从YAML加载、参数化、期望验证、暂停/跳过/重试。
 
- **UUT 模块（`uut/`）**
  - 职责：封装被测单元命令集（读 SN/启动测试/读测量值）；帧解析/校验；连接健康检查；并发控制。
  
- **接口驱动模块（`drivers/comm/`）**
  - 职责：统一抽象物理通信：串口/485/TCP/UDP；热插拔；性能监控（延迟、误码率）。
  

- **仪器仪表驱动模块（`drivers/instruments/`）**
  - 职责：仅保留程控电源（PSU）驱动；封装 SCPI/SDK；提供统一高级 API（`set_voltage()`, `set_current()`, `output()`, `measure_v/i()`）。
  

- **系统自检与初始化模块（`selfcheck/`）** ✅
  - 职责：分阶段系统自检（启动检查、配置检查、测试检查）；全局状态管理；失败预警；资源自动恢复。
 
- **系统安全与权限管理（`security/`）** ⏳
  - 职责：三角色权限控制、用户认证、操作审计、数据加密保护。
  
  
- **报表与统计分析（`reports/`）**
  - 职责：日报/月报/单件报告；历史统计（良率、直通率、缺陷、SPC、OEE）；图表与导出（HTML/PDF/CSV）。
 
---

### 4. 配置（YAML）与密钥管理

- 配置文件位于 `src/config/`，用 YAML 管理；所有超时/重试/日志/MES/通信/站别信息均可配置。
- 敏感字段（如 MES Token、数据库密钥）使用 `ISecretsProvider` 加密存储；明文不入库。
- 支持导入/导出与版本标识（`version`, `updated_at`）。

示例（片段）：
```yaml
app:
  language: zh_CN
  station_name: "FT-1"
  theme: light

logging:
  level: INFO
  dir: D:/Logs/TestTool
  rotation:
    when: midnight
    backupCount: 14
  remote:
    enabled: false
    endpoint: null

comm:
  serial:
    port: COM3
    baudrate: 115200
    bytesize: 8
    parity: N
    stopbits: 1
    timeout_ms: 2000
    retries: 3
    retry_backoff_ms: 200
  tcp:
    host: 192.168.1.100
    port: 5020
    timeout_ms: 2000
    retries: 3

mes:
  vendor: sample_mes
  base_url: https://mes.example.com/api
  timeout_ms: 3000
  retries: 3
  heartbeat_interval_ms: 10000
  credentials:
    client_id: TEST_TOOL
    client_secret_enc: "{ENCRYPTED}..."

test_sequence:
  file: D:/TestSequences/ft1.yaml

selfcheck:
  checklist: D:/Configs/selfcheck.yaml
```

参数校验规则：
- 路径/端口/地址/数值范围均需验证；
- 超时（ms）、重试次数、退避时间可全局或分模块覆盖；
- 敏感字段以 `{ENCRYPTED}` 前缀标识加密格式。

---

### 5. 日志规范与文件名格式

- 统一使用 `logging`，禁止 `print`。
- 日志级别：DEBUG/INFO/WARNING/ERROR/CRITICAL；默认 `INFO`，调试模式可切 `DEBUG`。
- 记录范围：外设/MES 调用均需记录 请求/响应/耗时/结果（成功或异常）。
- 文件名格式（强制）：
  - `{SN}-{测试站名}-{端口号}-%Y%m%d_%H%M%S.log`
- 轮转策略：建议 `TimedRotatingFileHandler`（`when=midnight`, `backupCount=14`）+ 按 SN 保存子日志。
- 远程聚合（可选）：提供 HTTP/Socket 上传接口与筛选。

---

### 6. 数据库设计（SQLite）

最小表集合（字段略）：
- `configs`：配置版本存储（name, version, content_yaml, checksum, created_at, created_by）。
- `test_results`：测试结果明细（sn, station, port, step, result, value, unit, started_at, ended_at, duration_ms, log_path）。
- `work_orders`：工单/产品信息缓存（wo, pn, rev, batch, updated_at）。
- `users`：用户账号（username, password_hash, salt, role_id, is_active, last_login_at）。
- `roles`：角色（id, name, description）。
- `permissions`：权限（id, action, resource）。
- `role_permissions`：角色-权限关联。
- `audit_logs`：审计记录（user, action, resource, details, created_at, ip, success）。
- `instruments`：仪器资产/校准（model, sn, last_cal_date, next_cal_date, status）。

索引建议：对 `sn`, `station`, `started_at`, `wo` 建立联合/单列索引以支撑报表查询。

---

### 7. 错误处理、超时与重试策略

- 所有 I/O 操作（串口/网口/MES/仪器）必须：
  - 设置超时（ms）；
  - 具备重试（默认 3 次）；
  - 指数退避（如 200ms、400ms、800ms），并记录每次失败原因；
  - 对幂等操作优先重试；对非幂等操作采用补偿/确认机制；
  - 异常分类：`RetryableError`、`TimeoutError`、`ValidationError`、`AuthError`、`ResourceBusyError` 等。
- 在测试序列层面，步骤可配置：`timeout_ms`、`retries`、`on_fail`（fail/skip/retry/downgrade）。

---

### 8. 插件/扩展架构

- 采用适配器/工厂模式：
  - MES：`IMESClient` + `MesClientFactory(vendor)` 加载对应实现；
  - 通信驱动：`ICommTransport` + `TransportFactory(type=serial/tcp/udp)`；
  - 仪器：`IInstrumentDriver` + `InstrumentFactory(kind=model)`；
  - 测试步骤：`IStep` 通过入口点或约定目录自动发现；
  - UUT：`IUUTAdapter` 按产品型号装配。
- 插件发现：支持基于入口点（`pkg_resources`/`importlib.metadata`）或 `plugins/` 目录热插拔加载。
- 版本与兼容性：插件需声明 `api_version`，主程序做兼容校验。

---

### 9. 安全与权限（RBAC）

- 认证：本地用户表 + 可选域集成；密码采用强哈希（如 `argon2`/`bcrypt`），从不明文存储。
- 授权：基于角色的访问控制（操作员/工程师/管理员），以 `action`-`resource` 维度授予。
- 审计：所有敏感操作（配置变更、结果修改、导出、登录失败）记录到 `audit_logs`。
- 加密：
  - 存储：敏感配置字段加密；
  - 传输：与 MES/远程日志采用 TLS；
  - 本地密钥：通过系统凭据/DPAPI/自定义 KMS 保护，不入库。

---

### 10. 报表与统计分析

- 数据源：`test_results`、`work_orders`、`instruments`。
- 指标：良率、直通率、缺陷分布、SPC（Xbar-R 等）、OEE。
- 输出：DataFrame、HTML/PDF 报告、CSV 导出；可配置模板（`resources/templates/`）。
- 可视化：`matplotlib` 为基础，UI 内嵌实时/离线图表。

---

### 11. 开发规范与依赖

- 依赖（初版）：
  - `PySide6`, `pyserial`, `pyvisa`, `requests`, `pandas`, `matplotlib`, `pydantic`（配置校验）, `cryptography`（加密）, `bcrypt/argon2-cffi`（口令哈希）
- 代码规范：PEP 8；所有公有 API 提供类型注解与 Docstring；模块化设计，严禁全局变量。
- 日志：严格遵循文件名与记录规范。
- 测试：核心业务逻辑具备单元测试；驱动与 MES 使用模拟/桩进行集成测试；关键路径建立回归集。
- 打包与分发：后续采用 `pyinstaller` 生成可执行；提供 `scripts/` 统一构建与签名流程。

---

### 12. 里程碑（实现进度）

1) ✅ **架构设计与配置规范** - 已完成
   - 项目架构设计
   - 配置/日志/DB 规范定义
   - 模块接口设计

2) ✅ **原型实现** - 已完成
   - ✅ 配置加载与验证（Pydantic + YAML）
   - ✅ 通用通信驱动（串口/TCP）
   - ✅ 基础 UI 框架（双端口界面）
   - ✅ 仪器驱动（程控电源）
   - ✅ 国际化支持
   - ✅ 标准化日志管理（测试结果与错误分离）

3) ✅ **核心功能实现** - 已完成
   - ✅ 测试用例执行引擎（模式管理、权限控制、步骤库）
   - ✅ MES 适配器集成
   - ✅ UUT 通信适配（协议解析、命令集管理、状态管理）

4) ⏳ **系统完善** - 待开始
   - ✅ 权限管理与安全
   - ⏳ 数据库集成
   - ⏳ 报表与统计分析
   - ✅ 系统自检

5) ⏳ **生产就绪** - 待开始
   - ⏳ 性能优化
   - ⏳ 可靠性加固
   - ⏳ 打包与部署
   - ⏳ 文档完善

---

### 13. 附：测试序列 YAML 设计（简版示例）
```yaml
version: 1
metadata:
  product: ABC-1000
  station: FT-1
variables:
  supply_voltage: 3.3
steps:
  - id: open_comm
    type: comm.open
    params:
      interface: serial
      port: COM3
    timeout_ms: 2000

  - id: read_sn
    type: uut.read_sn
    expect:
      regex: "^[A-Z0-9]{10}$"
    retries: 2

  - id: set_power
    type: instrument.psu.set_voltage
    params:
      channel: 1
      voltage: "${variables.supply_voltage}"

  - id: meas_current
    type: instrument.dmm.measure_current
    expect:
      range: [0.05, 0.20]

  - id: result_upload
    type: mes.upload
    params:
      fields: [sn, meas_current]
    on_fail: retry
```

---

### 14. 部署与代码保护（避免源码泄露）











