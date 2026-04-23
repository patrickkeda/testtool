# UUT模块功能说明

## 模块概述

UUT模块是智能硬件生产线检测软件的被测单元通信核心，提供统一的UUT通信适配、协议解析、命令集管理、状态管理等功能，确保与不同UUT设备的可靠通信和数据交换。

## 核心功能

### 1. UUT通信适配

#### 通信适配器接口
- **统一接口**：提供统一的UUT通信接口
- **多协议支持**：支持多种通信协议
- **连接管理**：管理UUT连接状态
- **错误处理**：处理通信错误和异常

#### 通信适配器接口定义
```python
class IUUTAdapter(ABC):
    @abstractmethod
    async def connect(self, config: UUTConfig) -> bool:
        """连接UUT设备"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """断开UUT连接"""
        pass
    
    @abstractmethod
    async def send_command(self, command: UUTCommand) -> UUTResponse:
        """发送命令到UUT"""
        pass
    
    @abstractmethod
    async def receive_response(self, timeout: float = None) -> UUTResponse:
        """接收UUT响应"""
        pass
    
    @abstractmethod
    async def is_connected(self) -> bool:
        """检查连接状态"""
        pass
    
    @abstractmethod
    async def get_device_info(self) -> UUTDeviceInfo:
        """获取设备信息"""
        pass
```

### 2. 协议解析

#### 协议解析器
- **多协议支持**：支持多种UUT通信协议
- **消息解析**：解析UUT消息格式
- **数据验证**：验证消息数据完整性
- **错误检测**：检测通信错误

#### 协议解析器实现
```python
class ProtocolParser:
    def __init__(self, protocol_type: str):
        self.protocol_type = protocol_type
        self.parsers = {
            "modbus": ModbusProtocolParser(),
            "custom": CustomProtocolParser(),
            "scpi": SCPIProtocolParser()
        }
    
    def parse_message(self, data: bytes) -> UUTMessage:
        """解析UUT消息"""
        parser = self.parsers.get(self.protocol_type)
        if not parser:
            raise ValueError(f"不支持的协议类型: {self.protocol_type}")
        
        return parser.parse(data)
    
    def build_message(self, command: UUTCommand) -> bytes:
        """构建UUT消息"""
        parser = self.parsers.get(self.protocol_type)
        if not parser:
            raise ValueError(f"不支持的协议类型: {self.protocol_type}")
        
        return parser.build(command)

class ModbusProtocolParser:
    def parse(self, data: bytes) -> UUTMessage:
        """解析Modbus消息"""
        try:
            # 解析Modbus协议
            if len(data) < 8:
                raise ValueError("消息长度不足")
            
            slave_id = data[0]
            function_code = data[1]
            data_start = data[2:4]
            data_count = data[4:6]
            crc = data[6:8]
            
            # 验证CRC
            if not self._verify_crc(data[:-2], crc):
                raise ValueError("CRC校验失败")
            
            return UUTMessage(
                slave_id=slave_id,
                function_code=function_code,
                data=data[2:6],
                crc=crc,
                raw_data=data
            )
            
        except Exception as e:
            raise ProtocolParseError(f"Modbus消息解析失败: {e}")
    
    def build(self, command: UUTCommand) -> bytes:
        """构建Modbus消息"""
        try:
            # 构建Modbus协议
            data = bytearray()
            data.append(command.slave_id)
            data.append(command.function_code)
            data.extend(command.data_start.to_bytes(2, 'big'))
            data.extend(command.data_count.to_bytes(2, 'big'))
            
            # 计算CRC
            crc = self._calculate_crc(data)
            data.extend(crc.to_bytes(2, 'little'))
            
            return bytes(data)
            
        except Exception as e:
            raise ProtocolBuildError(f"Modbus消息构建失败: {e}")
```

### 3. 命令集管理

#### 命令管理器
- **命令定义**：定义UUT命令集
- **命令验证**：验证命令参数
- **命令执行**：执行UUT命令
- **响应处理**：处理命令响应

#### 命令管理器实现
```python
class CommandManager:
    def __init__(self):
        self.commands: Dict[str, UUTCommand] = {}
        self.command_sets: Dict[str, CommandSet] = {}
        self._load_default_commands()
    
    def _load_default_commands(self):
        """加载默认命令集"""
        # 基本命令
        self.register_command(UUTCommand(
            name="ping",
            code="PING",
            description="Ping测试",
            parameters=[],
            response_type="string"
        ))
        
        self.register_command(UUTCommand(
            name="get_version",
            code="VERSION",
            description="获取版本信息",
            parameters=[],
            response_type="string"
        ))
        
        self.register_command(UUTCommand(
            name="get_status",
            code="STATUS",
            description="获取设备状态",
            parameters=[],
            response_type="json"
        ))
        
        self.register_command(UUTCommand(
            name="set_parameter",
            code="SET_PARAM",
            description="设置参数",
            parameters=[
                CommandParameter(name="param", type="string", required=True),
                CommandParameter(name="value", type="any", required=True)
            ],
            response_type="boolean"
        ))
    
    def register_command(self, command: UUTCommand):
        """注册命令"""
        self.commands[command.name] = command
        logger.info(f"注册UUT命令: {command.name}")
    
    def get_command(self, name: str) -> Optional[UUTCommand]:
        """获取命令"""
        return self.commands.get(name)
    
    def validate_command(self, command: UUTCommand, parameters: Dict[str, Any]) -> ValidationResult:
        """验证命令参数"""
        try:
            # 检查必需参数
            for param in command.parameters:
                if param.required and param.name not in parameters:
                    return ValidationResult(
                        is_valid=False,
                        message=f"缺少必需参数: {param.name}"
                    )
                
                # 验证参数类型
                if param.name in parameters:
                    value = parameters[param.name]
                    if not self._validate_parameter_type(value, param.type):
                        return ValidationResult(
                            is_valid=False,
                            message=f"参数类型错误: {param.name}, 期望: {param.type}"
                        )
            
            return ValidationResult(is_valid=True)
            
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                message=f"命令验证失败: {e}"
            )
    
    def _validate_parameter_type(self, value: Any, expected_type: str) -> bool:
        """验证参数类型"""
        if expected_type == "string":
            return isinstance(value, str)
        elif expected_type == "integer":
            return isinstance(value, int)
        elif expected_type == "float":
            return isinstance(value, (int, float))
        elif expected_type == "boolean":
            return isinstance(value, bool)
        elif expected_type == "any":
            return True
        else:
            return False
```

### 4. 状态管理

#### 状态管理器
- **连接状态**：管理UUT连接状态
- **设备状态**：管理UUT设备状态
- **测试状态**：管理测试过程中的状态
- **错误状态**：管理错误状态和恢复

#### 状态管理器实现
```python
class StatusManager:
    def __init__(self):
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.device_status = DeviceStatus.UNKNOWN
        self.test_status = TestStatus.IDLE
        self.error_status = ErrorStatus.NONE
        
        self.last_heartbeat = None
        self.error_count = 0
        self.max_errors = 5
        
        self.status_observers: List[Callable] = []
    
    def set_connection_status(self, status: ConnectionStatus):
        """设置连接状态"""
        if self.connection_status != status:
            self.connection_status = status
            self._notify_observers("connection_status", status)
            logger.info(f"UUT连接状态变更: {status}")
    
    def set_device_status(self, status: DeviceStatus):
        """设置设备状态"""
        if self.device_status != status:
            self.device_status = status
            self._notify_observers("device_status", status)
            logger.info(f"UUT设备状态变更: {status}")
    
    def set_test_status(self, status: TestStatus):
        """设置测试状态"""
        if self.test_status != status:
            self.test_status = status
            self._notify_observers("test_status", status)
            logger.info(f"UUT测试状态变更: {status}")
    
    def set_error_status(self, status: ErrorStatus, message: str = ""):
        """设置错误状态"""
        if self.error_status != status:
            self.error_status = status
            self._notify_observers("error_status", status, message)
            logger.warning(f"UUT错误状态变更: {status} - {message}")
    
    def add_error(self, error: UUTError):
        """添加错误"""
        self.error_count += 1
        if self.error_count >= self.max_errors:
            self.set_error_status(ErrorStatus.CRITICAL, "错误次数超过限制")
        else:
            self.set_error_status(ErrorStatus.WARNING, error.message)
    
    def clear_errors(self):
        """清除错误"""
        self.error_count = 0
        self.set_error_status(ErrorStatus.NONE)
    
    def add_observer(self, callback: Callable):
        """添加状态观察者"""
        self.status_observers.append(callback)
    
    def _notify_observers(self, status_type: str, status: Any, message: str = ""):
        """通知状态观察者"""
        for observer in self.status_observers:
            try:
                observer(status_type, status, message)
            except Exception as e:
                logger.error(f"状态观察者通知失败: {e}")
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return {
            "connection_status": self.connection_status,
            "device_status": self.device_status,
            "test_status": self.test_status,
            "error_status": self.error_status,
            "error_count": self.error_count,
            "last_heartbeat": self.last_heartbeat
        }
```

### 5. UUT适配器实现

#### 通用UUT适配器
- **连接管理**：管理UUT连接
- **命令执行**：执行UUT命令
- **响应处理**：处理UUT响应
- **错误处理**：处理通信错误

#### UUT适配器实现
```python
class UUTAdapter(IUUTAdapter):
    def __init__(self, config: UUTConfig):
        self.config = config
        self.transport = None
        self.protocol_parser = ProtocolParser(config.protocol_type)
        self.command_manager = CommandManager()
        self.status_manager = StatusManager()
        self._is_connected = False
    
    async def connect(self, config: UUTConfig) -> bool:
        """连接UUT设备"""
        try:
            # 创建传输层
            self.transport = self._create_transport(config)
            
            # 建立连接
            success = await self.transport.open()
            if not success:
                self.status_manager.set_connection_status(ConnectionStatus.FAILED)
                return False
            
            # 验证连接
            if await self._verify_connection():
                self._is_connected = True
                self.status_manager.set_connection_status(ConnectionStatus.CONNECTED)
                self.status_manager.last_heartbeat = datetime.now()
                logger.info(f"UUT连接成功: {config.device_id}")
                return True
            else:
                self.status_manager.set_connection_status(ConnectionStatus.FAILED)
                return False
                
        except Exception as e:
            self.status_manager.set_connection_status(ConnectionStatus.FAILED)
            logger.error(f"UUT连接失败: {e}")
            return False
    
    async def send_command(self, command: UUTCommand) -> UUTResponse:
        """发送命令到UUT"""
        try:
            if not self._is_connected or not self.transport:
                return UUTResponse(
                    success=False,
                    error="UUT未连接"
                )
            
            # 验证命令
            validation_result = self.command_manager.validate_command(command, command.parameters)
            if not validation_result.is_valid:
                return UUTResponse(
                    success=False,
                    error=f"命令验证失败: {validation_result.message}"
                )
            
            # 构建消息
            message = self.protocol_parser.build_message(command)
            
            # 发送消息
            success = await self.transport.send(message, self.config.timeout)
            if not success:
                self.status_manager.add_error(UUTError(
                    type="COMMUNICATION",
                    message="命令发送失败"
                ))
                return UUTResponse(
                    success=False,
                    error="命令发送失败"
                )
            
            # 接收响应
            response_data = await self.transport.receive(self.config.timeout)
            if not response_data:
                self.status_manager.add_error(UUTError(
                    type="COMMUNICATION",
                    message="响应接收超时"
                ))
                return UUTResponse(
                    success=False,
                    error="响应接收超时"
                )
            
            # 解析响应
            response_message = self.protocol_parser.parse_message(response_data)
            
            # 处理响应
            response = self._process_response(command, response_message)
            
            # 更新心跳
            self.status_manager.last_heartbeat = datetime.now()
            
            return response
            
        except Exception as e:
            self.status_manager.add_error(UUTError(
                type="COMMUNICATION",
                message=f"命令执行失败: {e}"
            ))
            return UUTResponse(
                success=False,
                error=f"命令执行失败: {e}"
            )
    
    async def _verify_connection(self) -> bool:
        """验证连接"""
        try:
            # 发送Ping命令
            ping_command = self.command_manager.get_command("ping")
            if ping_command:
                response = await self.send_command(ping_command)
                return response.success
            return True
        except Exception as e:
            logger.error(f"连接验证失败: {e}")
            return False
    
    def _process_response(self, command: UUTCommand, response_message: UUTMessage) -> UUTResponse:
        """处理响应"""
        try:
            # 根据命令类型处理响应
            if command.response_type == "string":
                data = response_message.data.decode('utf-8', errors='ignore')
            elif command.response_type == "json":
                data = json.loads(response_message.data.decode('utf-8', errors='ignore'))
            elif command.response_type == "boolean":
                data = response_message.data[0] == 1
            else:
                data = response_message.data
            
            return UUTResponse(
                success=True,
                data=data,
                raw_data=response_message.raw_data
            )
            
        except Exception as e:
            return UUTResponse(
                success=False,
                error=f"响应处理失败: {e}"
            )
```

## 技术实现

### 1. 模块结构

```
src/uut/
├── __init__.py              # 模块入口
├── adapter.py               # UUT适配器
├── interfaces.py            # 接口定义
├── models.py                # 数据模型
├── protocols.py             # 协议解析
├── command_manager.py       # 命令管理
└── status_manager.py        # 状态管理
```

### 2. 数据模型

#### UUT配置模型
```python
class UUTConfig(BaseModel):
    device_id: str
    device_type: str
    protocol_type: str = "modbus"
    transport_type: str = "serial"
    transport_config: Dict[str, Any] = {}
    timeout: float = 5.0
    retries: int = 3
    heartbeat_interval: float = 30.0
    enabled: bool = True

class UUTCommand(BaseModel):
    name: str
    code: str
    description: str = ""
    parameters: List[CommandParameter] = []
    response_type: str = "string"
    timeout: float = 5.0

class UUTResponse(BaseModel):
    success: bool
    data: Any = None
    error: str = ""
    raw_data: bytes = b""
    timestamp: datetime = Field(default_factory=datetime.now)

class UUTDeviceInfo(BaseModel):
    device_id: str
    device_type: str
    firmware_version: str = ""
    hardware_version: str = ""
    serial_number: str = ""
    manufacturer: str = ""
    model: str = ""
    capabilities: List[str] = []
```

### 3. 状态枚举

#### 状态定义
```python
class ConnectionStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"
    RECONNECTING = "reconnecting"

class DeviceStatus(Enum):
    UNKNOWN = "unknown"
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    MAINTENANCE = "maintenance"

class TestStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"

class ErrorStatus(Enum):
    NONE = "none"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
```

## 使用方式

### 1. 基本使用

```python
from src.uut import UUTAdapter, UUTConfig, UUTCommand

# 创建UUT配置
config = UUTConfig(
    device_id="UUT001",
    device_type="test_device",
    protocol_type="modbus",
    transport_type="serial",
    transport_config={
        "port": "COM3",
        "baudrate": 115200
    }
)

# 创建UUT适配器
adapter = UUTAdapter(config)

# 连接UUT
success = await adapter.connect(config)
if success:
    print("UUT连接成功")
    
    # 发送命令
    command = UUTCommand(
        name="get_status",
        code="STATUS",
        response_type="json"
    )
    
    response = await adapter.send_command(command)
    if response.success:
        print(f"设备状态: {response.data}")
    else:
        print(f"命令执行失败: {response.error}")
    
    # 断开连接
    await adapter.disconnect()
```

### 2. 命令管理

```python
from src.uut import CommandManager, UUTCommand

# 创建命令管理器
cmd_manager = CommandManager()

# 注册自定义命令
custom_command = UUTCommand(
    name="custom_test",
    code="CUSTOM_TEST",
    description="自定义测试命令",
    parameters=[
        CommandParameter(name="test_id", type="string", required=True),
        CommandParameter(name="timeout", type="integer", required=False)
    ],
    response_type="json"
)

cmd_manager.register_command(custom_command)

# 获取命令
command = cmd_manager.get_command("custom_test")
if command:
    print(f"命令: {command.name} - {command.description}")
```

### 3. 状态监控

```python
from src.uut import StatusManager, ConnectionStatus

# 创建状态管理器
status_manager = StatusManager()

# 添加状态观察者
def on_status_change(status_type: str, status: Any, message: str = ""):
    print(f"状态变更: {status_type} = {status} - {message}")

status_manager.add_observer(on_status_change)

# 设置状态
status_manager.set_connection_status(ConnectionStatus.CONNECTED)
status_manager.set_device_status(DeviceStatus.IDLE)

# 获取状态摘要
summary = status_manager.get_status_summary()
print(f"状态摘要: {summary}")
```

### 4. 协议解析

```python
from src.uut import ProtocolParser, UUTCommand

# 创建协议解析器
parser = ProtocolParser("modbus")

# 构建命令
command = UUTCommand(
    name="read_register",
    code="READ_REG",
    parameters={"address": 0x1000, "count": 1}
)

# 构建消息
message = parser.build_message(command)
print(f"构建的消息: {message.hex()}")

# 解析响应
response_data = b"\x01\x03\x02\x12\x34\xB5\xC9"
response_message = parser.parse_message(response_data)
print(f"解析的响应: {response_message}")
```

## 配置示例

### 1. UUT配置

```yaml
uut:
  device_id: "UUT001"
  device_type: "test_device"
  protocol_type: "modbus"
  transport_type: "serial"
  transport_config:
    port: "COM3"
    baudrate: 115200
    bytesize: 8
    parity: "N"
    stopbits: 1
  timeout: 5.0
  retries: 3
  heartbeat_interval: 30.0
  enabled: true
```

### 2. 命令集配置

```yaml
uut_commands:
  - name: "ping"
    code: "PING"
    description: "Ping测试"
    response_type: "string"
    timeout: 2.0
  
  - name: "get_version"
    code: "VERSION"
    description: "获取版本信息"
    response_type: "string"
    timeout: 5.0
  
  - name: "get_status"
    code: "STATUS"
    description: "获取设备状态"
    response_type: "json"
    timeout: 5.0
  
  - name: "set_parameter"
    code: "SET_PARAM"
    description: "设置参数"
    parameters:
      - name: "param"
        type: "string"
        required: true
      - name: "value"
        type: "any"
        required: true
    response_type: "boolean"
    timeout: 5.0
```

## 集成点

### 1. 与测试用例集成
- **命令执行**：在测试步骤中执行UUT命令
- **结果验证**：验证UUT命令执行结果
- **状态检查**：检查UUT设备状态

### 2. 与通信模块集成
- **传输层**：使用通信模块进行数据传输
- **连接管理**：管理UUT连接状态
- **错误处理**：处理通信错误

### 3. 与配置管理集成
- **UUT配置**：从配置文件读取UUT设置
- **命令配置**：从配置文件加载命令集
- **参数验证**：验证UUT配置参数

### 4. 与日志系统集成
- **通信日志**：记录UUT通信日志
- **命令日志**：记录UUT命令执行日志
- **错误日志**：记录UUT错误日志

## 错误处理

### 1. 连接错误
- **连接失败**：处理UUT连接失败
- **连接超时**：处理连接超时
- **连接断开**：处理连接意外断开

### 2. 通信错误
- **命令发送失败**：处理命令发送失败
- **响应接收超时**：处理响应接收超时
- **协议解析错误**：处理协议解析错误

### 3. 设备错误
- **设备无响应**：处理设备无响应
- **设备错误状态**：处理设备错误状态
- **设备维护状态**：处理设备维护状态

## 性能优化

### 1. 连接优化
- **连接池**：复用UUT连接
- **异步操作**：使用异步IO
- **批量操作**：批量处理命令

### 2. 通信优化
- **命令缓存**：缓存常用命令
- **响应缓存**：缓存设备响应
- **超时优化**：优化超时设置

### 3. 状态管理
- **状态缓存**：缓存设备状态
- **增量更新**：只更新变化的状态
- **状态同步**：同步状态变更

## 测试策略

### 1. 单元测试
- **适配器测试**：测试UUT适配器功能
- **协议测试**：测试协议解析功能
- **命令测试**：测试命令管理功能

### 2. 集成测试
- **端到端测试**：完整UUT通信流程测试
- **多设备测试**：多UUT设备并发测试
- **错误场景测试**：各种错误场景测试

### 3. 性能测试
- **通信性能**：测试UUT通信性能
- **响应时间**：测试命令响应时间
- **并发性能**：测试并发通信性能

## 总结

UUT模块为智能硬件生产线检测软件提供了完整的被测单元通信解决方案，通过统一的通信适配、协议解析、命令集管理、状态管理等功能，确保与不同UUT设备的可靠通信和数据交换。模块设计灵活、功能完善，为生产线测试工具提供了可靠的UUT通信基础。
