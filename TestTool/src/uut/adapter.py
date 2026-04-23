"""
UUT适配器核心实现
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from .interfaces import IUUTAdapter, IProtocolAdapter
from .models import UUTCommand, UUTResponse, UUTStatus, UUTConfig, UUTTestResult, UUTError, UUTErrorType, UUTMeasurement
from .command_manager import CommandManager
from .status_manager import StatusManager
from .protocols import ProtocolFactory

logger = logging.getLogger(__name__)


class UUTAdapter(IUUTAdapter):
    """UUT适配器实现"""
    
    def __init__(self, config: UUTConfig, comm_driver=None):
        self.config = config
        self.comm_driver = comm_driver
        self.protocol_adapter: Optional[IProtocolAdapter] = None
        self.command_manager = CommandManager()
        self.status_manager = StatusManager()
        self.is_connected_flag = False
        self.connection_lock = asyncio.Lock()
        
        # 初始化协议适配器
        self._init_protocol_adapter()
        
    def _init_protocol_adapter(self):
        """初始化协议适配器"""
        try:
            protocol_config = {
                "encoding": self.config.connection.get("encoding", "utf-8"),
                "terminator": self.config.connection.get("terminator", "\n"),
                "timeout": self.config.timeout.get("default", 2000),
                **self.config.connection
            }
            
            self.protocol_adapter = ProtocolFactory.create_adapter(
                self.config.protocol, 
                protocol_config
            )
            
            logger.info(f"协议适配器初始化成功: {self.config.protocol}")
            
        except Exception as e:
            logger.error(f"协议适配器初始化失败: {e}")
            raise
    
    async def connect(self) -> bool:
        """建立与UUT的连接"""
        async with self.connection_lock:
            try:
                if self.is_connected_flag:
                    logger.warning("UUT已连接")
                    return True
                
                # 更新连接状态
                await self.status_manager.update_connection_status("connecting")
                
                # 检查通信驱动
                if not self.comm_driver:
                    raise RuntimeError("通信驱动未设置")
                
                # 建立通信连接
                await self.comm_driver.connect()
                
                # 执行握手
                if self.protocol_adapter:
                    handshake_data = await self.protocol_adapter.create_handshake()
                    if handshake_data:
                        await self.comm_driver.send(handshake_data)
                        
                        # 等待握手响应
                        response = await self.comm_driver.recv(timeout=5000)
                        if response:
                            is_valid = await self.protocol_adapter.validate_handshake(response)
                            if not is_valid:
                                raise RuntimeError("握手验证失败")
                
                # 加载命令配置
                await self.command_manager.load_commands(self.config)
                
                # 更新连接状态
                self.is_connected_flag = True
                await self.status_manager.update_connection_status("connected")
                
                logger.info(f"UUT连接成功: {self.config.name}")
                return True
                
            except Exception as e:
                logger.error(f"UUT连接失败: {e}")
                await self.status_manager.update_connection_status("error")
                await self.status_manager.record_error(str(e))
                return False
    
    async def disconnect(self) -> bool:
        """断开与UUT的连接"""
        async with self.connection_lock:
            try:
                if not self.is_connected_flag:
                    logger.warning("UUT未连接")
                    return True
                
                # 更新连接状态
                await self.status_manager.update_connection_status("disconnected")
                
                # 断开通信连接
                if self.comm_driver:
                    await self.comm_driver.disconnect()
                
                # 更新状态
                self.is_connected_flag = False
                
                logger.info(f"UUT断开成功: {self.config.name}")
                return True
                
            except Exception as e:
                logger.error(f"UUT断开失败: {e}")
                await self.status_manager.record_error(str(e))
                return False
    
    async def send_command(self, command: UUTCommand) -> UUTResponse:
        """发送命令到UUT"""
        try:
            if not self.is_connected_flag:
                return UUTResponse(
                    success=False,
                    error=UUTError(
                        type=UUTErrorType.CONNECTION_ERROR,
                        message="UUT未连接"
                    ),
                    command_name=command.name
                )
            
            # 记录命令执行
            await self.status_manager.record_command(command)
            
            # 编码命令
            if self.protocol_adapter:
                command_data = await self.protocol_adapter.encode_command(command)
            else:
                command_data = command.command.encode()
            
            # 发送命令
            start_time = datetime.now()
            await self.comm_driver.send(command_data, timeout=command.timeout)
            
            # 读取响应
            response_data = await self.comm_driver.recv(timeout=command.timeout)
            
            # 计算响应时间
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            # 解码响应
            if self.protocol_adapter and response_data:
                response = await self.protocol_adapter.decode_response(response_data, command)
            else:
                response = UUTResponse(
                    success=bool(response_data),
                    data=response_data.decode() if response_data else "",
                    raw_data=response_data or b"",
                    command_name=command.name
                )
            
            # 设置响应时间
            response.response_time = response_time
            
            # 记录响应
            await self.status_manager.record_response(response)
            
            return response
            
        except Exception as e:
            logger.error(f"发送命令失败: {e}")
            error_response = UUTResponse(
                success=False,
                error=UUTError(
                    type=UUTErrorType.UNKNOWN_ERROR,
                    message=f"发送命令失败: {e}"
                ),
                command_name=command.name
            )
            await self.status_manager.record_response(error_response)
            return error_response
    
    async def read_response(self, timeout: Optional[int] = None) -> UUTResponse:
        """读取UUT响应"""
        try:
            if not self.is_connected_flag:
                return UUTResponse(
                    success=False,
                    error=UUTError(
                        type=UUTErrorType.CONNECTION_ERROR,
                        message="UUT未连接"
                    )
                )
            
            # 读取响应数据
            response_data = await self.comm_driver.recv(timeout=timeout or self.config.timeout.get("default", 2000))
            
            if not response_data:
                return UUTResponse(
                    success=False,
                    error=UUTError(
                        type=UUTErrorType.TIMEOUT_ERROR,
                        message="读取响应超时"
                    )
                )
            
            # 创建响应对象
            response = UUTResponse(
                success=True,
                data=response_data.decode(),
                raw_data=response_data
            )
            
            # 记录响应
            await self.status_manager.record_response(response)
            
            return response
            
        except Exception as e:
            logger.error(f"读取响应失败: {e}")
            return UUTResponse(
                success=False,
                error=UUTError(
                    type=UUTErrorType.UNKNOWN_ERROR,
                    message=f"读取响应失败: {e}"
                )
            )
    
    async def get_status(self) -> UUTStatus:
        """获取UUT状态"""
        return await self.status_manager.get_status()
    
    async def reset(self) -> bool:
        """重置UUT"""
        try:
            if not self.is_connected_flag:
                logger.warning("UUT未连接，无法重置")
                return False
            
            # 获取重置命令
            reset_command = await self.command_manager.get_command("reset")
            if not reset_command:
                logger.warning("未找到重置命令")
                return False
            
            # 执行重置命令
            response = await self.send_command(reset_command)
            
            if response.success:
                # 更新测试状态
                await self.status_manager.update_test_status("idle")
                logger.info("UUT重置成功")
                return True
            else:
                logger.error(f"UUT重置失败: {response.error}")
                return False
                
        except Exception as e:
            logger.error(f"UUT重置失败: {e}")
            await self.status_manager.record_error(str(e))
            return False
    
    async def is_connected(self) -> bool:
        """检查UUT是否已连接"""
        return self.is_connected_flag
    
    async def execute_test(self, test_name: str, commands: List[UUTCommand]) -> UUTTestResult:
        """执行测试序列"""
        test_result = UUTTestResult(test_name=test_name, success=True)
        
        try:
            # 更新测试状态
            await self.status_manager.update_test_status("testing")
            
            logger.info(f"开始执行测试: {test_name}")
            
            for command in commands:
                # 执行命令
                response = await self.send_command(command)
                
                # 记录测量数据
                if response.success and response.data is not None:
                    measurement = UUTMeasurement(
                        name=command.name,
                        value=float(response.data) if isinstance(response.data, (int, float)) else 0.0,
                        unit=command.metadata.get("unit", ""),
                        channel=command.metadata.get("channel")
                    )
                    test_result.add_measurement(measurement)
                
                # 检查命令是否成功
                if not response.success:
                    test_result.success = False
                    test_result.error = response.error
                    logger.error(f"测试命令失败: {command.name} - {response.error}")
                    break
            
            # 更新测试状态
            if test_result.success:
                await self.status_manager.update_test_status("completed")
                logger.info(f"测试完成: {test_name}")
            else:
                await self.status_manager.update_test_status("error")
                logger.error(f"测试失败: {test_name}")
            
            return test_result
            
        except Exception as e:
            logger.error(f"测试执行异常: {e}")
            test_result.success = False
            test_result.error = UUTError(
                type=UUTErrorType.UNKNOWN_ERROR,
                message=f"测试执行异常: {e}"
            )
            await self.status_manager.update_test_status("error")
            return test_result
    
    async def execute_command_by_name(self, name: str, parameters: Optional[Dict] = None) -> UUTResponse:
        """根据名称执行命令"""
        try:
            # 获取命令
            command = await self.command_manager.execute_command(name, parameters)
            
            # 执行命令
            return await self.send_command(command)
            
        except Exception as e:
            logger.error(f"执行命令失败: {name} - {e}")
            return UUTResponse(
                success=False,
                error=UUTError(
                    type=UUTErrorType.UNKNOWN_ERROR,
                    message=f"执行命令失败: {e}"
                ),
                command_name=name
            )
    
    async def get_command_list(self) -> List[str]:
        """获取命令列表"""
        return await self.command_manager.list_commands()
    
    async def get_health_status(self) -> Dict:
        """获取健康状态"""
        return await self.status_manager.get_health_status()
    
    async def get_statistics(self) -> Dict:
        """获取统计信息"""
        return await self.status_manager.get_statistics()
    
    async def pause_test(self) -> bool:
        """暂停测试"""
        try:
            await self.status_manager.update_test_status("paused")
            logger.info("测试已暂停")
            return True
        except Exception as e:
            logger.error(f"暂停测试失败: {e}")
            return False
    
    async def resume_test(self) -> bool:
        """恢复测试"""
        try:
            await self.status_manager.update_test_status("testing")
            logger.info("测试已恢复")
            return True
        except Exception as e:
            logger.error(f"恢复测试失败: {e}")
            return False
    
    async def stop_test(self) -> bool:
        """停止测试"""
        try:
            await self.status_manager.update_test_status("idle")
            logger.info("测试已停止")
            return True
        except Exception as e:
            logger.error(f"停止测试失败: {e}")
            return False
