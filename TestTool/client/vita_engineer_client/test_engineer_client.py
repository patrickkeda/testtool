#!/usr/bin/env python3
"""
VITA Engineer Service Test Client

Usage:
    vita-engineer-test [test_case] [robot_ip]

Test cases: 
    - Basic: tts, lidar, camera, head, light, battery, calibration, motion_sequence, all
    - Parameterized: pn=<op>,<device>,<status>%, lidar=<op>,<type>,<value>%
    
Examples:
    vita-engineer-test pn=test,power,on% 192.168.126.2
    vita-engineer-test lidar=scan,360,1000% 192.168.126.2
"""

import asyncio
import sys
import time
import json
import logging
import os
import re
from typing import Dict, List, Optional, Callable, Any, Tuple, Union
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from enum import Enum
from protocol import ResponseStatus, CommandMessage
# 支持直接运行和作为模块导入
try:
    from .engineer_client import EngineerServiceClient
except ImportError:
    # 直接运行时的导入方式
    from engineer_client import EngineerServiceClient

try:
    from .response_handlers import register_all_handlers, decode_base64
except ImportError:
    from response_handlers import register_all_handlers, decode_base64

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class OperationType(Enum):
    """操作类型枚举"""
    QUERY = "0"      # 查询
    SET = "1"        # 设置/启动
    STOP = "2"       # 停止/关闭
    CAPTURE = "3"    # 拍摄/捕获


@dataclass
class ParameterDefinition:
    """参数定义"""
    name: str
    description: str
    required: bool = True
    default_value: Optional[str] = None
    valid_values: Optional[List[str]] = None
    validation_pattern: Optional[str] = None


@dataclass
class CommandTemplate:
    """命令模板"""
    command_name: str
    description: str
    parameter_count: int
    parameters: List[ParameterDefinition]
    operation_mapping: Dict[str, str] = field(default_factory=dict)
    custom_handler: Optional[str] = None  # 自定义处理器名称


@dataclass
class TestCaseParams:
    """测试用例参数"""
    command_name: str
    operation: str
    parameters: List[str] = field(default_factory=list)
    extra_params: Dict[str, Any] = field(default_factory=dict)
    
    def get_param(self, index: int, default: str = "") -> str:
        """获取指定位置的参数"""
        return self.parameters[index] if index < len(self.parameters) else default
    
    def get_all_params(self, command_template: Optional[CommandTemplate] = None) -> Dict[str, str]:
        """获取所有参数作为字典，使用实际的参数名作为key
        
        支持可选参数：
        - 如果有命令模板，始终使用配置文件中定义的字段名
        - zip会自动处理参数数量不匹配的情况，只映射实际传入的参数
        - extra_params 中存放的命名参数（key=value形式）会覆盖/补充位置参数
        """
        if command_template:
            # 使用命令模板中的参数名，支持可选参数
            # zip会自动处理：只映射实际传入的参数到对应的字段名
            result = {}
            for param_def, param in zip(command_template.parameters, self.parameters):
                result[param_def.name] = param
            # 合并命名参数（key=value形式），允许跳过中间可选参数直接指定后面的字段
            result.update(self.extra_params)
            return result
        else:
            # 回退到默认格式（仅当没有命令模板时）
            result = {f"param_{i}": param for i, param in enumerate(self.parameters)}
            result.update(self.extra_params)
            return result


class CommandRegistry:
    """命令注册表"""
    
    def __init__(self, config_file: str = "command_config.json"):
        self._commands: Dict[str, CommandTemplate] = {}
        self._response_handlers: Dict[str, Callable] = {}
        self._command_handlers: Dict[str, Callable] = {}
        self.config_file = config_file
        self._load_commands_from_config()
    
    def _load_commands_from_config(self):
        """从JSON配置文件加载命令配置"""
        try:
            # 获取配置文件路径
            config_path = os.path.join(os.path.dirname(__file__), self.config_file)
            
            if not os.path.exists(config_path):
                logger.warning(f"配置文件不存在: {config_path}，使用默认配置")
                self._init_default_commands()
                return
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            commands_config = config_data.get("commands", {})
            
            for command_name, command_config in commands_config.items():
                try:
                    # 解析参数定义
                    parameters = []
                    for param_config in command_config.get("parameters", []):
                        param_def = ParameterDefinition(
                            name=param_config["name"],
                            description=param_config["description"],
                            required=param_config.get("required", True),
                            default_value=param_config.get("default_value"),
                            valid_values=param_config.get("valid_values"),
                            validation_pattern=param_config.get("validation_pattern")
                        )
                        parameters.append(param_def)
                    
                    # 创建命令模板
                    command_template = CommandTemplate(
                        command_name=command_name,
                        description=command_config["description"],
                        parameter_count=command_config["parameter_count"],
                        parameters=parameters,
                        operation_mapping=command_config.get("operation_mapping", {}),
                        custom_handler=command_config.get("custom_handler")
                    )
                    
                    self._commands[command_name] = command_template
                    #logger.info(f"加载命令配置: {command_name}")
                    
                except Exception as e:
                    logger.error(f"加载命令 {command_name} 配置失败: {e}")
                    continue
            
            logger.info(f"成功加载 {len(self._commands)} 个命令配置")
            
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            logger.info("使用默认配置")
            self._init_default_commands()

    
    def register_command(self, command: CommandTemplate):
        """注册命令"""
        self._commands[command.command_name] = command
        logger.info(f"注册命令: {command.command_name}")
    
    def register_response_handler(self, command_name: str, handler: Callable):
        """注册响应处理器"""
        self._response_handlers[command_name] = handler
        # logger.info(f"注册响应处理器: {command_name}")
    
    def register_command_handler(self, command_name: str, handler: Callable):
        """注册特殊命令处理器
        
        特殊命令处理器用于处理有特殊逻辑的命令（如需要文件读取、编码等）
        处理器签名: async def handler(client: EngineerServiceClient, params: TestCaseParams, command_template: CommandTemplate) -> bool
        如果命令有特殊处理器，将优先使用特殊处理器，否则使用通用处理器
        """
        self._command_handlers[command_name] = handler
        # logger.info(f"注册特殊命令处理器: {command_name}")
    
    def get_command_handler(self, command_name: str) -> Optional[Callable]:
        """获取特殊命令处理器"""
        return self._command_handlers.get(command_name)
    
    def get_command(self, command_name: str) -> Optional[CommandTemplate]:
        """获取命令模板"""
        return self._commands.get(command_name)
    
    def get_response_handler(self, command_name: str) -> Optional[Callable]:
        """获取响应处理器"""
        return self._response_handlers.get(command_name)
    
    def list_commands(self) -> List[str]:
        """列出所有命令"""
        return list(self._commands.keys())
    
    def list_response_handlers(self) -> List[str]:
        """列出所有响应处理器"""
        return list(self._response_handlers.keys())
    
    def validate_command(self, command_name: str, params: TestCaseParams) -> Tuple[bool, str]:
        """验证命令参数
        
        支持可选参数：
        - 传入的参数数量必须在必需参数数量和总参数数量之间
        - 所有必需参数必须被提供
        - 可选参数可以不提供
        """
        command = self.get_command(command_name)
        if not command:
            return False, f"未知命令: {command_name}"
        
        # 计算必需参数和总参数数量
        required_params_num = sum(1 for param_def in command.parameters if param_def.required)
        total_params_num = len(command.parameters)
        actual_params_num = len(params.parameters)
        
        # 检查参数数量是否在有效范围内
        if actual_params_num < required_params_num:
            return False, f"参数数量不足，至少需要{required_params_num}个必需参数，实际{actual_params_num}个"
        
        if actual_params_num > total_params_num:
            return False, f"参数数量过多，最多{total_params_num}个参数，实际{actual_params_num}个"
        
        # 验证每个实际传入的参数
        for i, param_def in enumerate(command.parameters):
            if i < actual_params_num:
                param_value = params.parameters[i]
                
                # 检查必需参数不能为空
                if param_def.required and not param_value:
                    return False, f"参数{param_def.name}是必需的，不能为空"
                
                # 检查有效值（如果参数值不为空）
                if param_value and param_def.valid_values and param_value not in param_def.valid_values:
                    return False, f"参数{param_def.name}的值'{param_value}'无效，有效值: {param_def.valid_values}"
                
                # 检查验证模式（如果参数值不为空）
                if param_value and param_def.validation_pattern and not re.match(param_def.validation_pattern, param_value):
                    return False, f"参数{param_def.name}的格式无效"
            else:
                # 如果这个位置的参数没有传入，检查它是否是必需的
                if param_def.required:
                    return False, f"必需参数{param_def.name}未提供"
        
        return True, "验证通过"
    
    def reload_config(self):
        """重新加载配置文件"""
        logger.info("重新加载配置文件...")
        self._commands.clear()
        self._load_commands_from_config()
    
    def validate_config(self) -> Tuple[bool, List[str]]:
        """验证配置文件格式"""
        errors = []
        
        try:
            config_path = os.path.join(os.path.dirname(__file__), self.config_file)
            
            if not os.path.exists(config_path):
                errors.append(f"配置文件不存在: {config_path}")
                return False, errors
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            if "commands" not in config_data:
                errors.append("配置文件缺少 'commands' 字段")
                return False, errors
            
            commands_config = config_data["commands"]
            
            for command_name, command_config in commands_config.items():
                # 检查必需字段
                required_fields = ["description", "parameter_count", "parameters"]
                for field in required_fields:
                    if field not in command_config:
                        errors.append(f"命令 {command_name} 缺少必需字段: {field}")
                
                # 检查参数定义
                if "parameters" in command_config:
                    for i, param_config in enumerate(command_config["parameters"]):
                        param_required_fields = ["name", "description"]
                        for field in param_required_fields:
                            if field not in param_config:
                                errors.append(f"命令 {command_name} 参数 {i} 缺少必需字段: {field}")
            
            return len(errors) == 0, errors
            
        except json.JSONDecodeError as e:
            errors.append(f"JSON格式错误: {e}")
            return False, errors
        except Exception as e:
            errors.append(f"配置文件验证失败: {e}")
            return False, errors


class TestCaseParser:
    """测试用例解析器"""
    
    def __init__(self, command_registry: CommandRegistry):
        self.command_registry = command_registry
    
    def parse_test_case(self, test_case: str) -> TestCaseParams:
        """解析测试用例字符串
        
        支持两种参数形式（可混用）：
          位置参数: command=<op>,<val1>,<val2>%
          命名参数: command=<op>,key1=val1,key2=val2%
        例如: bt=0,thres=-70%  或  bt=0,-70%  均可
        """
        # 检查是否是参数化格式: command=<op>[,<token>...]%
        # token 可以是普通值或 key=value 形式
        param_match = re.match(r'^(\w+)=(.+)%$', test_case)
        if param_match:
            command_name = param_match.group(1).lower()
            rest = param_match.group(2)
            tokens = rest.split(',')
            op = tokens[0]
            positional_params = [op]  # 位置参数列表（第一个始终是 op）
            named_params: Dict[str, str] = {}  # key=value 命名参数

            for token in tokens[1:]:
                if '=' in token:
                    # key=value 形式：存入 named_params，不加入位置列表
                    k, _, v = token.partition('=')
                    named_params[k.strip()] = v.strip()
                else:
                    positional_params.append(token)

            return TestCaseParams(
                command_name=command_name,
                operation=op,
                parameters=positional_params,
                extra_params=named_params
            )
        
        # 检查是否是基本格式: command
        if re.match(r'^[a-zA-Z_]+$', test_case):
            return TestCaseParams(
                command_name=test_case.lower(),
                operation="0",  # 默认查询操作
                parameters=["0"]
            )
        
        raise ValueError(f"无法解析测试用例格式: {test_case}")


class GenericCommandHandler:
    """通用命令处理器"""
    
    def __init__(self, command_registry: CommandRegistry):
        self.command_registry = command_registry
    
    async def execute_command(self, client: EngineerServiceClient, params: TestCaseParams) -> bool:
        """执行命令"""
        command_name = params.command_name
        
        # 验证命令
        is_valid, error_msg = self.command_registry.validate_command(command_name, params)
        if not is_valid:
            print(f"命令验证失败: {error_msg}")
            return False
        
        # 获取命令模板
        command_template = self.command_registry.get_command(command_name)
        if not command_template:
            print(f"未知命令: {command_name}")
            return False
        
        print(f"执行命令: {command_template.description}")
        print(f"操作: {command_template.operation_mapping.get(params.operation, '未知操作')}")
        
        # 检查是否有特殊命令处理器
        special_handler = self.command_registry.get_command_handler(command_name)
        if special_handler:
            print(f"   使用特殊命令处理器: {command_name}")
            return await special_handler(client, params, command_template)
        else:
            # 使用通用处理器
            return await self._generic_handler(client, params, command_template)
    
    async def _generic_handler(self, client: EngineerServiceClient, params: TestCaseParams, command_template: CommandTemplate) -> bool:
        """通用处理器 - 处理所有标准命令"""
        try:
            # 获取参数
            all_params = params.get_all_params(command_template)
            
            # 构建命令字符串
            command_str = f"{params.command_name}={','.join(params.parameters)}%"
            print(f"   发送命令: {command_str}")
            
            # 发送命令到服务器
            command = {
                "command": command_str,
                "params": all_params,
                "timestamp": int(time.time() * 1000)
            }
            print(f"   发送命令: {json.dumps(command, ensure_ascii=False)}")

            response_str = await self._send_command(client, command)
            response = json.loads(response_str)
            
            # 检查是否有自定义响应处理器
            response_handler = self.command_registry.get_response_handler(params.command_name)
            if response_handler:
                print(f"   使用自定义响应处理器: {params.command_name}")
                return await response_handler(response, params)
            
            # 默认响应处理
            if response.get("status") == ResponseStatus.SUCCESS.value:
                print(f"命令执行成功: {response.get('message', '')}")
                data_str = response.get("data", "")
                
                # 如果是 base64 编码的二进制数据，先解码
                if response.get("encoding") == "base64" and response.get("has_binary_data", False):
                    decoded_data = decode_base64(data_str)
                    # 尝试将字节数据转换为字符串
                    try:
                        data_str = decoded_data.decode('utf-8')
                    except UnicodeDecodeError:
                        # 如果不是文本数据，直接使用字节数据
                        data_str = decoded_data
                
                if data_str:
                    try:
                        # 尝试解析为 JSON
                        if isinstance(data_str, bytes):
                            parsed_data = json.loads(data_str.decode('utf-8'))
                        else:
                            parsed_data = json.loads(data_str)
                        print(f"   返回数据: \n {json.dumps(parsed_data, indent=4)}")
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        # 如果不是 JSON，直接打印
                        if isinstance(data_str, bytes):
                            print(f"   返回数据 (二进制): {len(data_str)} 字节")
                        else:
                            print(f"   返回数据: \n {data_str}")
                return True
            else:
                print(f"命令执行失败: {response.get('message', '')}")
                return False
                
        except Exception as e:
            print(f"命令执行异常: {e}")
            logger.exception("Command execution failed")
            return False

    async def _send_command(self, client: EngineerServiceClient, command: Dict[str, Any], timeout: float = 180.0) -> str:
        """发送命令并等待响应
        
        HTTP 是无状态的，每次请求都是独立的，不需要重连机制。
        """
        # 将字典转换为 CommandMessage 对象
        command_msg = CommandMessage(
            command=command.get("command", ""),
            params=command.get("params", {}),
            timestamp=command.get("timestamp", int(time.time() * 1000))
        )
        
        print("命令已发送，等待响应...")
        # 发送 HTTP 请求并接收响应, default timeout is 3 minutes
        # Use longer timeout for commands that may take a long time (e.g., servo calibration)
        # Servo calibration can take up to 60+ seconds (multiple movements with 10s timeout each)
        try:
            # 直接调用 _send_command，它会返回 ResponseMessage
            response_msg = await asyncio.wait_for(
                client._send_command(command_msg),
                timeout=timeout
            )
            
            # 如果有原始响应数据，使用它（包含所有字段如 encoding）
            if hasattr(response_msg, 'raw_response') and response_msg.raw_response:
                return json.dumps(response_msg.raw_response)
            
            # 否则，将 ResponseMessage 转换为字典
            response_dict = {
                "status": response_msg.status,
                "message": response_msg.message,
                "timestamp": response_msg.timestamp,
                "has_binary_data": response_msg.has_binary_data,
            }
            
            # 如果有二进制数据，需要从 binary_data 或 data 字段获取
            if hasattr(response_msg, 'binary_data') and response_msg.binary_data:
                import base64
                response_dict["data"] = base64.b64encode(response_msg.binary_data).decode('utf-8')
                response_dict["encoding"] = "base64"
                response_dict["data_size"] = len(response_msg.binary_data)
            elif response_msg.data:
                response_dict["data"] = response_msg.data
                if isinstance(response_msg.data, str):
                    response_dict["encoding"] = "base64"
            
            return json.dumps(response_dict)
        except ConnectionError as e:
            # 连接错误
            raise ConnectionError(f"请求失败: {e}")
        except TimeoutError as e:
            # 超时
            raise TimeoutError(f"命令执行超时（{timeout}秒），服务端可能无响应: {e}")


class TestCase(ABC):
    """测试用例基类"""
    
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
    
    @abstractmethod
    async def execute(self, client: EngineerServiceClient, params: TestCaseParams) -> bool:
        """执行测试用例"""
        pass
    
    def validate_params(self, params: TestCaseParams) -> bool:
        """验证参数是否有效"""
        return True


class TestCaseRegistry:
    """测试用例注册表"""
    
    def __init__(self):
        self._test_cases: Dict[str, TestCase] = {}
        self._param_handlers: Dict[str, Callable[[EngineerServiceClient, TestCaseParams], bool]] = {}
    
    def register_test_case(self, test_case: TestCase):
        """注册测试用例"""
        self._test_cases[test_case.name] = test_case
        logger.info(f"注册测试用例: {test_case.name}")
    
    def register_param_handler(self, test_type: str, handler: Callable[[EngineerServiceClient, TestCaseParams], bool]):
        """注册参数化处理器"""
        self._param_handlers[test_type] = handler
        logger.info(f"注册参数化处理器: {test_type}")
    
    def get_test_case(self, name: str) -> Optional[TestCase]:
        """获取测试用例"""
        return self._test_cases.get(name)
    
    def get_param_handler(self, test_type: str) -> Optional[Callable]:
        """获取参数化处理器"""
        return self._param_handlers.get(test_type)
    
    def list_test_cases(self) -> List[str]:
        """列出所有测试用例"""
        return list(self._test_cases.keys())

# 全局命令注册表和处理器
command_registry = CommandRegistry()
command_handler = GenericCommandHandler(command_registry)
parser = TestCaseParser(command_registry)

async def test_single_case(test_case: str, robot_ip: str = "192.168.126.2", port: int = 3579):
    """测试单个用例"""
    # Use context manager to ensure HTTP client is always closed
    async with EngineerServiceClient(host=robot_ip, port=port) as client:
        try:
            try:
                params = parser.parse_test_case(test_case)
                print(f"解析参数: {params}")
            except ValueError as e:
                print(f"参数解析失败: {e}")
                return False
            
            return await command_handler.execute_command(client, params)
                
        except Exception as e:
            print(f"测试过程异常: {e}")
            logger.exception("Test failed with exception")
            return False


register_all_handlers(command_registry)


async def transfer_command_handler(client: EngineerServiceClient, params: TestCaseParams, command_template: CommandTemplate) -> bool:
    """Transfer命令特殊处理器
    
    处理文件传输命令的特殊逻辑：
    - op=1: 从狗传输到电脑（标准处理）
    - op=2: 从电脑传输到狗（需要读取文件并编码）
    """
    try:
        all_params = params.get_all_params(command_template)
        
        if params.operation == "2":
            source_path = params.get_param(1)  # addrA是第2个参数（索引1）
            if not source_path:
                print("错误: 未指定源文件路径 (addrA)")
                return False
            
            if not os.path.exists(source_path):
                print(f"错误: 源文件/文件夹不存在: {source_path}")
                return False
            
            try:
                import base64
                import zipfile
                import tempfile
                
                if os.path.isdir(source_path):
                    tmp_zip_path = None
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_zip:
                            tmp_zip_path = tmp_zip.name
                        
                        with zipfile.ZipFile(tmp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                            for root, dirs, files in os.walk(source_path):
                                for file in files:
                                    file_path = os.path.join(root, file)
                                    arcname = os.path.relpath(file_path, source_path)
                                    zipf.write(file_path, arcname)
                        
                        with open(tmp_zip_path, "rb") as f:
                            file_data = f.read()
                        print(f"压缩完成: {source_path} -> {len(file_data)} 字节 (zip)")
                    finally:
                        if tmp_zip_path and os.path.exists(tmp_zip_path):
                            try:
                                os.unlink(tmp_zip_path)
                            except Exception as e:
                                print(f"警告: 清理临时文件失败: {e}")
                else:
                    with open(source_path, "rb") as f:
                        file_data = f.read()
                    print(f"读取文件: {source_path} ({len(file_data)} 字节)")
                
                encoded_data = base64.b64encode(file_data).decode('utf-8')
                all_params["data"] = encoded_data
            except Exception as e:
                print(f"读取文件/文件夹失败: {e}")
                return False
        
        command_str = f"{params.command_name}={','.join(params.parameters)}%"
        print(f"   发送命令: {command_str}")
        
        command = {
            "command": command_str,
            "params": all_params,
            "timestamp": int(time.time() * 1000)
        }
        
        command_for_display = command.copy()
        if "params" in command_for_display and "data" in command_for_display["params"]:
            command_for_display["params"] = command_for_display["params"].copy()
            data_size = len(command['params']['data']) if isinstance(command['params']['data'], str) else 0
            command_for_display["params"]["data"] = f"<base64_encoded_data_{data_size}_bytes>"
        print(f"   发送命令: {json.dumps(command_for_display, ensure_ascii=False)}")
        
        # 发送命令
        response_str = await command_handler._send_command(client, command)
        response = json.loads(response_str)
        
        response_handler = command_registry.get_response_handler(params.command_name)
        if response_handler:
            print(f"   使用自定义响应处理器: {params.command_name}")
            return await response_handler(response, params)
        
        # 默认响应处理
        if response.get("status") == ResponseStatus.SUCCESS.value:
            print(f"命令执行成功: {response.get('message', '')}")
            return True
        else:
            print(f"命令执行失败: {response.get('message', '')}")
            return False
            
    except Exception as e:
        print(f"命令执行异常: {e}")
        logger.exception("Command execution failed")
        return False


async def motor_ota_command_handler(client: EngineerServiceClient, params: TestCaseParams, command_template: CommandTemplate) -> bool:
    """MotorOTA命令特殊处理器
    
    处理电机固件升级命令的特殊逻辑：
    - op=1: 对所有电机进行固件升级
    - op=2: 对指定motor id list进行固件升级
    
    需要读取本地bin文件并编码为base64发送
    电机类型由服务端自动从配置文件读取（默认vita），无需手动指定
    用法: motor_ota=1,/path/to/firmware.bin%
          motor_ota=2,/path/to/firmware.bin,1-2-3%
    """
    try:
        all_params = params.get_all_params(command_template)

        file_path = params.get_param(1)
        if not file_path:
            print("错误: 未指定固件文件路径 (file)")
            return False
        
        if not os.path.exists(file_path):
            print(f"错误: 固件文件不存在: {file_path}")
            return False
        
        if not os.path.isfile(file_path):
            print(f"错误: 路径不是文件: {file_path}")
            return False
        
        try:
            import base64
            
            # 读取bin文件
            with open(file_path, "rb") as f:
                file_data = f.read()
            
            print(f"读取固件文件: {file_path} ({len(file_data)} 字节)")
            
            # 编码为base64
            encoded_data = base64.b64encode(file_data).decode('utf-8')
            all_params["data"] = encoded_data
            
            # 对于op=2，motor_ids参数是第3个参数（索引2）
            if params.operation == "2":
                motor_ids_str = params.get_param(2)
                if motor_ids_str:
                    all_params["motor_ids"] = motor_ids_str
                    print(f"指定电机ID列表: {motor_ids_str}")
                else:
                    print("警告: op=2但未指定motor_ids参数")
        except Exception as e:
            print(f"读取/编码文件失败: {e}")
            logger.exception("Failed to read/encode file")
            return False
        
        command_str = f"{params.command_name}={','.join(params.parameters)}%"
        print(f"   发送命令: {command_str}")
        
        command = {
            "command": command_str,
            "params": all_params,
            "timestamp": int(time.time() * 1000)
        }
        
        command_for_display = command.copy()
        if "params" in command_for_display and "data" in command_for_display["params"]:
            command_for_display["params"] = command_for_display["params"].copy()
            data_size = len(command['params']['data']) if isinstance(command['params']['data'], str) else 0
            command_for_display["params"]["data"] = f"<base64_encoded_data_{data_size}_bytes>"
        print(f"   发送命令: {json.dumps(command_for_display, ensure_ascii=False)}")
        
        # 发送命令（使用统一的超时时间，服务端保证在180s内处理完成）
        response_str = await command_handler._send_command(client, command, timeout=500.0)
        response = json.loads(response_str)
        
        response_handler = command_registry.get_response_handler(params.command_name)
        if response_handler:
            print(f"   使用自定义响应处理器: {params.command_name}")
            return await response_handler(response, params)
        
        # 默认响应处理
        if response.get("status") == ResponseStatus.SUCCESS.value:
            print(f"命令执行成功: {response.get('message', '')}")
            return True
        else:
            print(f"命令执行失败: {response.get('message', '')}")
            return False
            
    except Exception as e:
        print(f"命令执行异常: {e}")
        logger.exception("Command execution failed")
        return False

async def uwb_command_handler(client: EngineerServiceClient, params: TestCaseParams, command_template: CommandTemplate) -> bool:
    """UWB命令特殊处理器

    支持:
    - op=0: 查询
    - op=1: 配对 tag_name
    - op=2: 清理配对
    - op=3: 整机标定
    - op=4: 批量序列: 参数顺序 t, n, tags (tags 用 '-' 连接)
    """
    try:
        all_params = params.get_all_params(command_template)
        # Compute timeout depending on operation
        timeout = 180.0
        if params.operation == "4":
            # t seconds per tag, n tags
            tags_str = params.get_param(1, "")
            n_str = params.get_param(2, "0")
            t_str = params.get_param(3, "0")
            if not tags_str:
                print("错误: op=4 需要 tags 参数（用'-'连接）")
                return False
            try:
                t_sec = int(t_str)
                n_val = int(n_str)
            except Exception:
                print("错误: t 或 n 参数格式不正确，应为整数")
                return False
            
            input_tag_num = len(tags_str.split('-'))
            if input_tag_num != n_val:
                print(f"错误: tags 数量与 n 不匹配，tags数量={input_tag_num}，n={n_val}")
                return False

            # set timeout to accommodate sequence and calibration (with margin)
            estimated = max(90, n_val * t_sec + 30)
            timeout = max(timeout, float(estimated) + 120.0)

        elif params.operation == "1":
            # pairing single tag may be quick, but give some grace
            timeout = 30.0

        # build and send command
        command_str = f"{params.command_name}={','.join(params.parameters)}%"
        print(f"   发送命令: {command_str}")

        command = {
            "command": command_str,
            "params": all_params,
            "timestamp": int(time.time() * 1000)
        }

        command_for_display = command.copy()
        print(f"   发送命令: {json.dumps(command_for_display, ensure_ascii=False)}")

        response_str = await command_handler._send_command(client, command, timeout=timeout)
        response = json.loads(response_str)

        response_handler = command_registry.get_response_handler(params.command_name)
        if response_handler:
            print(f"   使用自定义响应处理器: {params.command_name}")
            return await response_handler(response, params)

        if response.get("status") == ResponseStatus.SUCCESS.value:
            print(f"命令执行成功: {response.get('message', '')}")
            data_str = response.get("data", "")
            if data_str:
                try:
                    # 尝试解析为 JSON
                    parsed_data = json.loads(data_str)
                    print(f"   返回数据: \n {json.dumps(parsed_data, indent=4)}")
                except json.JSONDecodeError:
                    print(f"   返回数据: \n {data_str}")
            return True
        else:
            print(f"命令执行失败: {response.get('message', '')}")
            return False

    except Exception as e:
        print(f"UWB 命令执行异常: {e}")
        logger.exception("UWB command failed")
        return False

async def rtc_command_handler(client: EngineerServiceClient, params: TestCaseParams, command_template: CommandTemplate) -> bool:
    """RTC命令特殊处理器

    当 op=1 时，自动从本机获取当前日期和时间，无需用户手动输入。
    用法: rtc=1%  (自动获取本机时间发送给工程模式服务)
    """
    try:
        if params.operation == "1":
            from datetime import datetime
            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M:%S")
            print(f"   自动获取本机时间: {date_str} {time_str}")

            # 重建 parameters 列表，注入 date 和 time
            params.parameters = ["1", date_str, time_str]

        all_params = params.get_all_params(command_template)

        command_str = f"{params.command_name}={','.join(params.parameters)}%"
        print(f"   发送命令: {command_str}")

        command = {
            "command": command_str,
            "params": all_params,
            "timestamp": int(time.time() * 1000)
        }
        print(f"   发送命令: {json.dumps(command, ensure_ascii=False)}")

        response_str = await command_handler._send_command(client, command)
        response = json.loads(response_str)

        response_handler = command_registry.get_response_handler(params.command_name)
        if response_handler:
            print(f"   使用自定义响应处理器: {params.command_name}")
            return await response_handler(response, params)

        if response.get("status") == ResponseStatus.SUCCESS.value:
            print(f"命令执行成功: {response.get('message', '')}")
            data_str = response.get("data", "")
            if data_str:
                print(f"   返回数据: {data_str}")
            return True
        else:
            print(f"命令执行失败: {response.get('message', '')}")
            return False

    except Exception as e:
        print(f"RTC 命令执行异常: {e}")
        logger.exception("RTC command failed")
        return False

# 注册特殊命令处理器
command_registry.register_command_handler("transfer", transfer_command_handler)
command_registry.register_command_handler("motor_ota", motor_ota_command_handler)
command_registry.register_command_handler("uwb", uwb_command_handler)
command_registry.register_command_handler("rtc", rtc_command_handler)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ["--help", "-h", "help"]:
        print(__doc__)
        print("\n支持的命令:")
        print("   基本命令:")
        for cmd_name in command_registry.list_commands():
            cmd = command_registry.get_command(cmd_name)
            print(f"     - {cmd_name}: {cmd.description}")
        
        print("\n参数化格式:")
        print("     - command=<op>,<param1>,<param2>%  (例: pn=1,sn,test%)")
        print("     - command=<op>,<param>%             (例: version=0%)")
        
        print("\n操作类型:")
        print("     - 0: 查询")
        print("     - 1: 设置/启动")
        print("     - 2: 停止/关闭")
        print("     - 3: 拍摄/捕获")
        
        print("\n使用示例:")
        print("     python test_engineer_client.py pn=1,s100,SN99999999999% 192.168.126.2")
        print("     python test_engineer_client.py lidar=0% 192.168.126.2")
        print("     python test_engineer_client.py version=0% 192.168.126.2")
        print("     python test_engineer_client.py all 192.168.126.2  # 执行所有测试用例")
        
        print("\n配置文件管理:")
        print("     python test_engineer_client.py --validate-config")
        print("     python test_engineer_client.py --reload-config")
        
        print("\n响应处理器:")
        for handler_name in command_registry.list_response_handlers():
            print(f"     - {handler_name}: 自定义响应处理")
        sys.exit(1)
    
    # 处理特殊命令
    if sys.argv[1] == "--validate-config":
        is_valid, errors = command_registry.validate_config()
        if is_valid:
            print("配置文件验证通过")
        else:
            print("配置文件验证失败:")
            for error in errors:
                print(f"   - {error}")
        sys.exit(0 if is_valid else 1)
    
    if sys.argv[1] == "--reload-config":
        command_registry.reload_config()
        print("配置文件重新加载完成")
        sys.exit(0)
    
    # 检查是否是test all命令
    if sys.argv[1] == "all" or sys.argv[1] == "test-all":
        # 导入并运行test_all_runner
        try:
            from .test_all_runner import main as test_all_main
        except ImportError:
            from test_all_runner import main as test_all_main
        
        test_all_main()
        return
    
    test_case = sys.argv[1]
    robot_ip = sys.argv[2] if len(sys.argv) > 2 else "192.168.126.2"
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 3579
    
    #print(f"Engineer Service 测试工具 (重构版)")
    print(f"目标机器人: {robot_ip}:{port}")
    print(f"测试用例: {test_case}")
    print("-" * 50)
    
    try:
        result = asyncio.run(test_single_case(test_case, robot_ip, port))
        
        if result:
            print("\n测试完成 - 测试通过！")
            sys.exit(0)
        else:
            print("\n测试失败 - 请检查错误信息")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n测试过程发生异常: {e}")
        logger.exception("Unexpected error")
        sys.exit(1)

if __name__ == "__main__":
    main()

