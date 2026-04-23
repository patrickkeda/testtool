"""
WebSocket transport for engineer service communication.
Base on client project's implementation.
"""

from __future__ import annotations

import logging
import asyncio
import websockets
from typing import Optional, Dict, Any
from datetime import datetime

from .interfaces import ICommTransport, TimeoutError, RetryableError


class WebSocketTransport:
    """WebSocket传输层 - 封装WebSocket连接和通信"""
    
    def __init__(
        self,
        *,
        host: str,
        port: int = 3579,
        connection_timeout_ms: int = 30000,
        command_timeout_ms: int = 60000,
        x5_soc_id: str = "",
        s100_soc_id: str = "",
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._host = host
        self._port = port
        self._connection_timeout_ms = connection_timeout_ms
        self._command_timeout_ms = command_timeout_ms
        self._x5_soc_id = x5_soc_id
        self._s100_soc_id = s100_soc_id
        
        self._websocket: Optional[Any] = None
        self._is_connected = False
        self._secure_session: Optional[Dict[str, Any]] = None
        
        # 生成设备凭证（如果提供了SOC ID）
        if x5_soc_id and s100_soc_id:
            self._generate_credentials()
    
    def _generate_credentials(self):
        """生成设备凭证"""
        try:
            import hashlib
            combined_input = f"{self._x5_soc_id}-{self._s100_soc_id}"
            auth_token = hashlib.sha256(combined_input.encode('utf-8')).hexdigest()
            device_id = hashlib.sha1(combined_input.encode('utf-8')).hexdigest()
            
            self._secure_session = {
                "auth_token": auth_token,
                "device_id": device_id
            }
            self._logger.info(f"Generated credentials for device: {device_id}")
        except Exception as e:
            self._logger.warning(f"Failed to generate credentials: {e}")
    
    def open(self) -> None:
        """打开WebSocket连接（同步包装）"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_open())
        except Exception as e:
            self._logger.error(f"WebSocket connection failed: {e}")
            raise RetryableError(f"WebSocket connection failed: {e}")
        finally:
            loop.close()
    
    async def _async_open(self) -> None:
        """异步WebSocket连接实现"""
        try:
            uri = f"ws://{self._host}:{self._port}"
            self._logger.info(f"Connecting to {uri}")
            
            # 建立WebSocket连接
            self._websocket = await asyncio.wait_for(
                websockets.connect(uri),
                timeout=self._connection_timeout_ms / 1000
            )
            
            self._is_connected = True
            self._logger.info("Connected to engineer service")
            
        except Exception as e:
            self._logger.error(f"Connection failed: {e}")
            self._is_connected = False
            raise
    
    def close(self) -> None:
        """关闭WebSocket连接"""
        if self._websocket:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._async_close())
                finally:
                    loop.close()
            except Exception as e:
                self._logger.warning(f"Error during WebSocket close: {e}")
            finally:
                self._websocket = None
        
        self._is_connected = False
        self._logger.info("Disconnected from engineer service")
    
    async def _async_close(self) -> None:
        """异步关闭WebSocket连接"""
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception as e:
                self._logger.warning(f"Error during WebSocket close: {e}")
            finally:
                self._websocket = None
    
    def is_open(self) -> bool:
        """检查连接是否打开"""
        # 安全检查 closed 属性（兼容不同版本的 websockets 库）
        if not self._is_connected or self._websocket is None:
            return False
        
        try:
            # 尝试访问 closed 属性
            is_closed = getattr(self._websocket, 'closed', False)
            result = not is_closed
        except Exception as e:
            self._logger.warning(f"无法检查 WebSocket closed 状态: {e}，假设已连接")
            result = True  # 如果无法检查，假设已连接
        
        self._logger.debug(f"is_open check: connected={self._is_connected}, websocket={self._websocket is not None}, result={result}")
        return result
    
    async def send_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """发送命令并等待响应"""
        if not self.is_open():
            raise RetryableError("WebSocket not connected")
        
        try:
            import json
            
            # 构造命令消息
            message = {
                "command": command,
                "params": params or {},
                "timestamp": int(datetime.now().timestamp() * 1000)
            }
            
            # 添加认证令牌（如果有）
            if self._secure_session:
                message["auth_token"] = self._secure_session["auth_token"]
            
            # 发送JSON命令
            command_json = json.dumps(message)
            await self._websocket.send(command_json)
            self._logger.info(f"Sent command: {command}")
            
            # 接收响应
            response_data = await asyncio.wait_for(
                self._websocket.recv(),
                timeout=self._command_timeout_ms / 1000
            )
            
            if isinstance(response_data, str):
                response = json.loads(response_data)
            else:
                response = json.loads(response_data.decode('utf-8'))
            
            self._logger.info(f"Received response: {response.get('status', 'unknown')}")
            return response
            
        except asyncio.TimeoutError:
            self._logger.error(f"Command timeout: {command}")
            raise TimeoutError(f"Command timeout: {command}")
        except Exception as e:
            self._logger.error(f"Command failed: {command}, error: {e}")
            raise RetryableError(f"Command failed: {command}, error: {e}")
    
    async def check_connection(self) -> bool:
        """检查连接状态"""
        if not self._websocket:
            self._is_connected = False
            return False
        
        # 安全检查 closed 属性
        try:
            is_closed = getattr(self._websocket, 'closed', False)
            if is_closed:
                self._is_connected = False
                self._websocket = None
                return False
        except Exception:
            pass  # 无法检查，继续
        
        return self._is_connected
    
    async def reconnect(self) -> bool:
        """重新连接"""
        self._logger.info("Attempting to reconnect...")
        await self._async_close()
        await asyncio.sleep(1.0)
        await self._async_open()
        return self._is_connected
