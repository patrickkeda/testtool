# MES模块功能说明

## 模块概述

MES模块是智能硬件生产线检测软件与制造执行系统的集成核心，提供统一的API接口，支持不同MES厂商的适配，实现工单管理、测试结果上传、心跳监控等功能。

## 核心功能

### 1. 多厂商适配

#### 适配器模式
- **统一接口**：提供IMESClient和IMESAdapter统一接口
- **厂商适配**：支持不同MES厂商的接口适配
- **工厂模式**：通过MESFactory统一创建和管理适配器
- **扩展性**：易于添加新的MES厂商适配器

#### 支持的厂商
- **SampleMES**：示例MES适配器，用于开发和测试
- **SAP MES**：SAP制造执行系统（待实现）
- **Custom MES**：自定义MES系统（待实现）

### 2. 工单管理

#### 工单信息获取
- **序列号查询**：根据产品序列号获取工单信息
- **产品参数**：获取产品测试参数和规格
- **批次信息**：获取批次、版本、数量等信息
- **参数验证**：验证工单参数的有效性

#### 工单数据模型
```python
@dataclass
class WorkOrder:
    work_order: str          # 工单号
    product_number: str      # 产品型号
    revision: str           # 版本
    batch: str              # 批次
    quantity: int           # 数量
    station_id: str         # 工位ID
    status: WorkOrderStatus # 状态
    parameters: Dict[str, Any] # 参数
```

### 3. 测试结果上传

#### 结果数据模型
```python
@dataclass
class TestResult:
    sn: str                 # 序列号
    station_id: str         # 工位ID
    port: str              # 端口
    work_order: str        # 工单号
    product_number: str    # 产品型号
    test_steps: List[TestStep] # 测试步骤
    overall_result: TestResultStatus # 整体结果
    started_at: datetime   # 开始时间
    ended_at: datetime     # 结束时间
```

#### 上传功能
- **实时上传**：测试完成后立即上传结果
- **批量上传**：支持批量上传多个测试结果
- **重试机制**：上传失败自动重试
- **断网续传**：网络恢复后自动补传

### 4. 心跳监控

#### 心跳功能
- **自动心跳**：定期发送心跳保持连接
- **状态监控**：监控MES系统连接状态
- **故障检测**：检测连接故障并自动重连
- **状态报告**：提供详细的心跳状态信息

#### 心跳管理器
```python
class HeartbeatManager:
    async def start(client, interval_ms)  # 启动心跳
    async def stop()                     # 停止心跳
    async def get_status()               # 获取状态
    def is_running()                     # 检查运行状态
```

## 技术实现

### 1. 模块结构

```
src/mes/
├── __init__.py              # 模块入口
├── models.py                # 数据模型定义
├── interfaces.py            # 接口定义
├── client.py                # MES客户端基类
├── factory.py               # 适配器工厂
├── heartbeat.py             # 心跳检测
└── adapters/                # 各厂商适配器
    ├── __init__.py
    ├── base.py              # 适配器基类
    └── sample_mes.py        # 示例MES适配器
```

### 2. 核心接口

#### MES客户端接口
```python
class IMESClient:
    async def authenticate() -> bool
    async def get_work_order(sn: str) -> Optional[WorkOrder]
    async def upload_result(test_result: TestResult) -> bool
    async def heartbeat() -> bool
    async def get_product_params(product_number: str) -> Dict[str, Any]
    async def is_connected() -> bool
    async def disconnect() -> bool
```

#### MES适配器接口
```python
class IMESAdapter:
    async def authenticate(config: MESConfig) -> MESResponse
    async def get_work_order(config: MESConfig, sn: str) -> MESResponse
    async def upload_result(config: MESConfig, test_result: TestResult) -> MESResponse
    async def heartbeat(config: MESConfig) -> MESResponse
    async def get_product_params(config: MESConfig, product_number: str) -> MESResponse
    def parse_work_order(response_data: Any) -> Optional[WorkOrder]
    def parse_product_params(response_data: Any) -> Dict[str, Any]
```

### 3. 配置管理

#### MES配置模型
```python
@dataclass
class MESConfig:
    vendor: str              # 厂商名称
    base_url: str           # 基础URL
    timeout_ms: int         # 超时时间
    retries: int            # 重试次数
    heartbeat_interval_ms: int # 心跳间隔
    credentials: Dict[str, str] # 认证凭据
    endpoints: Dict[str, str]   # 端点配置
    headers: Dict[str, str]     # 请求头
    station_id: str         # 工位ID
    enabled: bool           # 是否启用
```

#### 配置示例
```yaml
mes:
  vendor: sample_mes
  base_url: https://mes.example.com/api
  timeout_ms: 3000
  retries: 3
  retry_backoff_ms: 200
  heartbeat_interval_ms: 10000
  credentials:
    client_id: TEST_TOOL
    client_secret_enc: "{ENCRYPTED}..."
  endpoints:
    auth: "/auth/login"
    work_order: "/workorders/{sn}"
    upload: "/testresults"
    heartbeat: "/heartbeat"
    product_params: "/products/{product_number}"
  headers:
    Content-Type: "application/json"
    User-Agent: "TestTool/1.0"
  station_id: "FT-1"
  enabled: true
```

## 使用方式

### 1. 基本使用

```python
from src.mes import MESConfig, MESFactory, TestResult, TestStep

# 创建MES配置
config = MESConfig(
    vendor="sample_mes",
    base_url="https://mes.example.com/api",
    credentials={"client_id": "TEST_TOOL", "client_secret": "test_secret"}
)

# 创建MES客户端
factory = MESFactory()
client = factory.create_client(config)

# 连接MES系统
await client.connect()

# 获取工单信息
work_order = await client.get_work_order("SN001")

# 上传测试结果
test_result = TestResult(sn="SN001", station_id="FT-1", ...)
await client.upload_result(test_result)

# 断开连接
await client.disconnect()
```

### 2. 心跳监控

```python
from src.mes import HeartbeatManager

# 创建心跳管理器
heartbeat_manager = HeartbeatManager()

# 启动心跳监控
await heartbeat_manager.start(client, 10000)  # 10秒间隔

# 检查心跳状态
status = await heartbeat_manager.get_status()
print(f"心跳状态: {status}")

# 停止心跳监控
await heartbeat_manager.stop()
```

### 3. 适配器扩展

```python
from src.mes.adapters.base import MESAdapter

class CustomMESAdapter(MESAdapter):
    def __init__(self):
        super().__init__("custom_mes")
    
    async def authenticate(self, config: MESConfig) -> MESResponse:
        # 实现认证逻辑
        pass
    
    async def get_work_order(self, config: MESConfig, sn: str) -> MESResponse:
        # 实现工单获取逻辑
        pass
    
    # 实现其他接口方法...

# 注册适配器
factory = MESFactory()
factory.register_adapter("custom_mes", CustomMESAdapter)
```

## 集成点

### 1. 与测试用例集成
- **工单参数获取**：从MES获取测试参数
- **结果上传**：测试完成后上传结果到MES
- **参数验证**：验证MES参数的有效性

### 2. 与配置管理集成
- **MES配置**：从配置文件读取MES设置
- **凭据管理**：安全存储MES认证凭据
- **端点配置**：配置MES API端点

### 3. 与日志系统集成
- **交互日志**：记录MES交互过程
- **错误日志**：记录MES操作错误
- **审计日志**：记录MES操作审计

### 4. 与权限管理集成
- **操作权限**：控制MES操作权限
- **审计记录**：记录MES操作审计
- **用户管理**：MES操作用户管理

## 错误处理

### 1. 网络错误
- **超时处理**：网络请求超时自动重试
- **连接错误**：连接失败自动重连
- **断网续传**：网络恢复后自动补传

### 2. 认证错误
- **认证失败**：自动重新认证
- **令牌过期**：自动刷新令牌
- **权限错误**：记录权限错误日志

### 3. 数据错误
- **数据验证**：验证MES数据格式
- **解析错误**：处理MES响应解析错误
- **业务错误**：处理MES业务逻辑错误

## 性能优化

### 1. 连接管理
- **连接池**：复用HTTP连接
- **异步操作**：使用asyncio异步处理
- **批量操作**：支持批量数据上传

### 2. 缓存机制
- **工单缓存**：缓存工单信息
- **参数缓存**：缓存产品参数
- **状态缓存**：缓存连接状态

### 3. 监控指标
- **成功率**：MES操作成功率
- **响应时间**：MES响应时间
- **错误率**：MES错误率统计

## 测试策略

### 1. 单元测试
- **适配器测试**：测试各厂商适配器
- **客户端测试**：测试MES客户端功能
- **心跳测试**：测试心跳监控功能

### 2. 集成测试
- **端到端测试**：完整MES集成流程测试
- **多厂商测试**：多厂商适配器测试
- **故障测试**：网络故障和恢复测试

### 3. 性能测试
- **负载测试**：高并发MES操作测试
- **压力测试**：长时间运行稳定性测试
- **响应测试**：MES响应时间测试

## 总结

MES模块为智能硬件生产线检测软件提供了完整的MES集成功能，通过适配器模式支持不同MES厂商，实现了工单管理、测试结果上传、心跳监控等核心功能。模块设计灵活、扩展性强，易于维护和升级，为生产线测试工具提供了可靠的数据集成基础。
