# 测试用例错误代码使用指南

## 概述

`error_codes.py` 集中管理所有测试用例的错误代码，提供统一的错误代码定义和使用方式。

## 使用方式

### 1. 在测试用例中使用错误代码

```python
from ...error_codes import ConnectErrorCodes

# 在失败时返回错误代码
return StepResult(
    passed=False,
    message="连接失败",
    error=str(e),
    error_code=ConnectErrorCodes.CONNECT_FAILED.error_code,
    data={
        "error_code": ConnectErrorCodes.CONNECT_FAILED.error_code,
        "error_message": ConnectErrorCodes.CONNECT_FAILED.error_message
    }
)
```

### 2. 通过错误代码获取错误信息

```python
from ...error_codes import get_error_info

error_info = get_error_info("CONN_ERR_CONNECT_FAILED")
# 返回: {"code": "CONN_ERR_CONNECT_FAILED", "description": "WebSocket连接失败"}
```

## 错误代码分类

### Connect 测试用例错误代码

- `CONN_ERR_NO_HOST`: 主机地址未配置
- `CONN_ERR_CONNECT_FAILED`: WebSocket连接失败
- `CONN_ERR_NOT_OPEN`: WebSocket连接未建立
- `CONN_ERR_ENTER_ENGINEER_MODE_FAILED`: 进入工程模式失败
- `CONN_ERR_UNKNOWN`: 未知错误

### Disconnect 测试用例错误代码

- `DISCONN_ERR_NOT_CONNECTED`: 未建立连接
- `DISCONN_ERR_DISCONNECT_FAILED`: 断开连接失败

### ScanSN 测试用例错误代码

- `SN_ERR_USER_CANCELLED`: 用户取消输入
- `SN_ERR_TIMEOUT`: 输入超时
- `SN_ERR_INVALID_FORMAT`: SN格式无效

## 添加新的错误代码

1. 在对应的 Enum 类中添加新的错误代码
2. 在 `ERROR_CODE_REGISTRY` 中注册新错误代码
3. 提供清晰的错误描述

示例：

```python
class ConnectErrorCodes(Enum):
    NEW_ERROR = ("CONN_ERR_NEW_ERROR", "新错误描述")
    ...
```

然后在 `ERROR_CODE_REGISTRY` 中添加：

```python
ERROR_CODE_REGISTRY: Dict[str, Enum] = {
    ...
    "CONN_ERR_NEW_ERROR": ConnectErrorCodes.NEW_ERROR,
}
```

## 优势

1. **集中管理**: 所有错误代码在一个地方定义，易于维护
2. **类型安全**: 使用 Enum 提供类型检查和 IDE 自动补全
3. **易于扩展**: 添加新错误代码只需修改一个文件
4. **一致性**: 统一的错误代码格式，避免重复和冲突
5. **文档化**: 每个错误代码都有清晰的描述
