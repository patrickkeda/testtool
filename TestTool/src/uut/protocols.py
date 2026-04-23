"""
协议适配器实现
"""

import json
import struct
import logging
from typing import Any, Dict, Optional
from abc import ABC, abstractmethod

from .interfaces import IProtocolAdapter
from .models import UUTCommand, UUTResponse, UUTError, UUTErrorType

logger = logging.getLogger(__name__)


class BaseProtocolAdapter(IProtocolAdapter):
    """协议适配器基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.encoding = config.get("encoding", "utf-8")
        self.terminator = config.get("terminator", "\n")
        self.timeout = config.get("timeout", 2000)
        
    async def encode_command(self, command: UUTCommand) -> bytes:
        """编码命令"""
        try:
            # 基础命令编码
            cmd_str = command.command
            
            # 添加参数
            if command.parameters:
                for key, value in command.parameters.items():
                    cmd_str += f" {key}={value}"
            
            # 添加终止符
            if not cmd_str.endswith(self.terminator):
                cmd_str += self.terminator
            
            return cmd_str.encode(self.encoding)
            
        except Exception as e:
            logger.error(f"命令编码失败: {e}")
            raise
    
    async def decode_response(self, data: bytes, command: UUTCommand) -> UUTResponse:
        """解码响应"""
        try:
            # 基础响应解码
            response_str = data.decode(self.encoding).strip()
            
            # 根据响应格式处理数据
            if command.response_format == "json":
                try:
                    data_obj = json.loads(response_str)
                    return UUTResponse(
                        success=True,
                        data=data_obj,
                        raw_data=data,
                        command_name=command.name
                    )
                except json.JSONDecodeError:
                    return UUTResponse(
                        success=False,
                        data=response_str,
                        raw_data=data,
                        error=UUTError(
                            type=UUTErrorType.PROTOCOL_ERROR,
                            message="JSON解析失败",
                            details={"response": response_str}
                        ),
                        command_name=command.name
                    )
            
            elif command.response_format == "float":
                try:
                    value = float(response_str)
                    return UUTResponse(
                        success=True,
                        data=value,
                        raw_data=data,
                        command_name=command.name
                    )
                except ValueError:
                    return UUTResponse(
                        success=False,
                        data=response_str,
                        raw_data=data,
                        error=UUTError(
                            type=UUTErrorType.PROTOCOL_ERROR,
                            message="浮点数解析失败",
                            details={"response": response_str}
                        ),
                        command_name=command.name
                    )
            
            elif command.response_format == "int":
                try:
                    value = int(response_str)
                    return UUTResponse(
                        success=True,
                        data=value,
                        raw_data=data,
                        command_name=command.name
                    )
                except ValueError:
                    return UUTResponse(
                        success=False,
                        data=response_str,
                        raw_data=data,
                        error=UUTError(
                            type=UUTErrorType.PROTOCOL_ERROR,
                            message="整数解析失败",
                            details={"response": response_str}
                        ),
                        command_name=command.name
                    )
            
            else:  # string or default
                return UUTResponse(
                    success=True,
                    data=response_str,
                    raw_data=data,
                    command_name=command.name
                )
                
        except Exception as e:
            logger.error(f"响应解码失败: {e}")
            return UUTResponse(
                success=False,
                data=str(data),
                raw_data=data,
                error=UUTError(
                    type=UUTErrorType.PROTOCOL_ERROR,
                    message=f"响应解码失败: {e}",
                    details={"raw_data": data}
                ),
                command_name=command.name
            )
    
    async def validate_data(self, data: bytes) -> bool:
        """验证数据格式"""
        try:
            # 基础数据验证
            if not data:
                return False
            
            # 检查编码是否有效
            data.decode(self.encoding)
            return True
            
        except Exception:
            return False
    
    async def create_handshake(self) -> bytes:
        """创建握手数据"""
        return b"*IDN?\n"  # 标准SCPI握手命令
    
    async def validate_handshake(self, data: bytes) -> bool:
        """验证握手响应"""
        try:
            response = data.decode(self.encoding).strip()
            # 简单的握手验证：检查是否包含设备信息
            return len(response) > 0 and not response.startswith("ERROR")
        except Exception:
            return False


class SerialProtocolAdapter(BaseProtocolAdapter):
    """串口协议适配器"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.baudrate = config.get("baudrate", 115200)
        self.parity = config.get("parity", "N")
        self.stopbits = config.get("stopbits", 1)
        self.bytesize = config.get("bytesize", 8)
    
    async def encode_command(self, command: UUTCommand) -> bytes:
        """串口命令编码"""
        # 串口协议可能需要特殊的编码方式
        cmd_str = command.command
        
        # 添加参数
        if command.parameters:
            for key, value in command.parameters.items():
                cmd_str += f" {key}={value}"
        
        # 添加终止符
        if not cmd_str.endswith(self.terminator):
            cmd_str += self.terminator
        
        return cmd_str.encode(self.encoding)
    
    async def validate_data(self, data: bytes) -> bool:
        """串口数据验证"""
        if not await super().validate_data(data):
            return False
        
        # 串口特定的验证逻辑
        response = data.decode(self.encoding).strip()
        
        # 检查是否包含错误标识
        if "ERROR" in response.upper():
            return False
        
        return True


class TcpProtocolAdapter(BaseProtocolAdapter):
    """TCP协议适配器"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 8080)
        self.keepalive = config.get("keepalive", True)
    
    async def encode_command(self, command: UUTCommand) -> bytes:
        """TCP命令编码"""
        # TCP协议可能需要添加长度前缀或其他标识
        cmd_str = command.command
        
        # 添加参数
        if command.parameters:
            for key, value in command.parameters.items():
                cmd_str += f" {key}={value}"
        
        # 添加终止符
        if not cmd_str.endswith(self.terminator):
            cmd_str += self.terminator
        
        # TCP可能需要添加长度前缀
        data = cmd_str.encode(self.encoding)
        length = len(data)
        length_prefix = struct.pack(">I", length)  # 4字节大端序长度
        
        return length_prefix + data
    
    async def decode_response(self, data: bytes, command: UUTCommand) -> UUTResponse:
        """TCP响应解码"""
        try:
            # 移除长度前缀
            if len(data) > 4:
                # 假设前4字节是长度
                length = struct.unpack(">I", data[:4])[0]
                response_data = data[4:4+length]
            else:
                response_data = data
            
            # 使用基类方法解码
            return await super().decode_response(response_data, command)
            
        except Exception as e:
            logger.error(f"TCP响应解码失败: {e}")
            return UUTResponse(
                success=False,
                data=str(data),
                raw_data=data,
                error=UUTError(
                    type=UUTErrorType.PROTOCOL_ERROR,
                    message=f"TCP响应解码失败: {e}",
                    details={"raw_data": data}
                ),
                command_name=command.name
            )


class CustomProtocolAdapter(BaseProtocolAdapter):
    """自定义协议适配器"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.protocol_type = config.get("protocol_type", "custom")
        self.custom_encoder = config.get("encoder")
        self.custom_decoder = config.get("decoder")
        self.custom_validator = config.get("validator")
    
    async def encode_command(self, command: UUTCommand) -> bytes:
        """自定义命令编码"""
        if self.custom_encoder:
            # 使用自定义编码器
            return await self.custom_encoder(command)
        else:
            # 使用基类方法
            return await super().encode_command(command)
    
    async def decode_response(self, data: bytes, command: UUTCommand) -> UUTResponse:
        """自定义响应解码"""
        if self.custom_decoder:
            # 使用自定义解码器
            return await self.custom_decoder(data, command)
        else:
            # 使用基类方法
            return await super().decode_response(data, command)
    
    async def validate_data(self, data: bytes) -> bool:
        """自定义数据验证"""
        if self.custom_validator:
            # 使用自定义验证器
            return await self.custom_validator(data)
        else:
            # 使用基类方法
            return await super().validate_data(data)


class ProtocolFactory:
    """协议适配器工厂"""
    
    @staticmethod
    def create_adapter(protocol_type: str, config: Dict[str, Any]) -> IProtocolAdapter:
        """创建协议适配器
        
        Parameters
        ----------
        protocol_type : str
            协议类型
        config : Dict[str, Any]
            配置参数
            
        Returns
        -------
        IProtocolAdapter
            协议适配器实例
        """
        if protocol_type == "serial":
            return SerialProtocolAdapter(config)
        elif protocol_type == "tcp":
            return TcpProtocolAdapter(config)
        elif protocol_type == "custom":
            return CustomProtocolAdapter(config)
        else:
            raise ValueError(f"不支持的协议类型: {protocol_type}")
    
    @staticmethod
    def get_supported_protocols() -> list:
        """获取支持的协议类型
        
        Returns
        -------
        list
            支持的协议类型列表
        """
        return ["serial", "tcp", "custom"]
