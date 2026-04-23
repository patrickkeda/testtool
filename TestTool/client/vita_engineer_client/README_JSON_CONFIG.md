# JSON配置文件使用示例

## 添加新命令示例

假设要添加一个新的温度传感器命令 `temp`，只需要在 `command_config.json` 中添加：

```json
{
  "commands": {
    "temp": {
      "description": "温度传感器控制",
      "parameter_count": 2,
      "parameters": [
        {
          "name": "op",
          "description": "操作类型",
          "required": true,
          "valid_values": ["0", "1", "2"]
        },
        {
          "name": "sensor_id",
          "description": "传感器ID",
          "required": true,
          "validation_pattern": "^[0-9]+$"
        }
      ],
      "operation_mapping": {
        "0": "查询温度",
        "1": "启动传感器",
        "2": "停止传感器"
      }
    }
  }
}
```

## 使用新命令

添加配置后，可以直接使用：

```bash
# 查询温度
python test_engineer_client.py temp=0,1% 10.100.100.88

# 启动传感器
python test_engineer_client.py temp=1,2% 10.100.100.88

# 停止传感器
python test_engineer_client.py temp=2,1% 10.100.100.88
```

## 配置文件验证

在修改配置文件后，建议先验证：

```bash
python test_engineer_client.py --validate-config
```

## 重新加载配置

如果需要重新加载配置（在运行时）：

```bash
python test_engineer_client.py --reload-config
```

## 自定义处理器

如果某个命令需要特殊处理逻辑，可以注册自定义处理器：

```python
async def handle_temp_custom(client: EngineerServiceClient, params: TestCaseParams) -> bool:
    """温度传感器自定义处理器"""
    print(f"🌡️ 执行温度传感器测试: {params.operation}")
    
    if params.operation == "0":  # 查询温度
        print("   查询温度数据...")
        # 这里可以添加特殊的温度查询逻辑
        return True
    
    # 其他操作使用通用处理器
    return await command_handler._generic_handler(client, params, command_registry.get_command("temp"))

# 注册自定义处理器
command_registry.register_custom_handler("temp", handle_temp_custom)
```

## 配置文件结构说明

- `description`: 命令描述
- `parameter_count`: 参数数量
- `parameters`: 参数定义数组
  - `name`: 参数名称
  - `description`: 参数描述
  - `required`: 是否必需（默认true）
  - `valid_values`: 有效值列表（可选）
  - `validation_pattern`: 正则表达式验证（可选）
  - `default_value`: 默认值（可选）
- `operation_mapping`: 操作码映射（可选）
- `custom_handler`: 自定义处理器名称（可选）
