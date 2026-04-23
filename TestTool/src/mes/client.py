"""
MES客户端基类实现
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp
import json

from .interfaces import IMESClient
from .models import WorkOrder, TestResult, MESResponse, MESConfig, MESError, MESStatus, MESConnectionInfo

logger = logging.getLogger(__name__)


class MESClient(IMESClient):
    """MES客户端基类实现"""
    
    def __init__(self, config: MESConfig, adapter=None):
        self.config = config
        self.adapter = adapter
        self.session: Optional[aiohttp.ClientSession] = None
        self.connection_info = MESConnectionInfo(
            vendor=config.vendor,
            base_url=config.base_url
        )
        self._is_authenticated = False
        self._auth_token: Optional[str] = None
        
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.disconnect()
    
    async def connect(self) -> bool:
        """连接到MES系统"""
        try:
            if self.session is None or self.session.closed:
                timeout = aiohttp.ClientTimeout(total=self.config.timeout_ms / 1000)
                self.session = aiohttp.ClientSession(timeout=timeout)
            
            # 尝试认证
            if await self.authenticate():
                self.connection_info.status = MESStatus.CONNECTED
                self.connection_info.last_connected = datetime.now()
                logger.info(f"MES连接成功: {self.config.vendor}")
                return True
            else:
                self.connection_info.status = MESStatus.ERROR
                if not self.connection_info.last_error:
                    self.connection_info.last_error = "MES认证失败"
                logger.error(f"MES认证失败: {self.config.vendor}")
                return False
                
        except Exception as e:
            self.connection_info.status = MESStatus.ERROR
            self.connection_info.last_error = str(e)
            logger.error(f"MES连接异常: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """断开MES连接"""
        try:
            if self.adapter and self._is_authenticated:
                uninit = getattr(self.adapter, "uninitialize", None)
                if callable(uninit):
                    try:
                        response = await uninit(self.config)
                        if not response.is_success():
                            logger.warning(f"MES反初始化失败: {response.message}")
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"MES反初始化异常: {e}")

            if self.session and not self.session.closed:
                await self.session.close()
            
            self._is_authenticated = False
            self._auth_token = None
            self.connection_info.status = MESStatus.DISCONNECTED
            logger.info(f"MES断开连接: {self.config.vendor}")
            return True
            
        except Exception as e:
            logger.error(f"MES断开连接异常: {e}")
            return False
    
    async def authenticate(self) -> bool:
        """认证到MES系统"""
        try:
            if not self.adapter:
                logger.error("MES适配器未设置")
                return False
            
            # 使用适配器进行认证
            response = await self.adapter.authenticate(self.config)
            
            if response.is_success():
                self._is_authenticated = True
                self._auth_token = response.data.get('token') if response.data else None
                self.connection_info.last_error = None
                self.connection_info.record_request(True)
                logger.info(f"MES认证成功: {self.config.vendor}")
                return True
            else:
                self.connection_info.last_error = response.message or "MES认证失败"
                self.connection_info.record_request(False)
                logger.error(f"MES认证失败: {response.message}")
                return False
                
        except Exception as e:
            self.connection_info.last_error = str(e)
            self.connection_info.record_request(False)
            logger.error(f"MES认证异常: {e}")
            return False
    
    async def get_work_order(self, sn: str) -> Optional[WorkOrder]:
        """获取工单信息"""
        try:
            if not self._is_authenticated:
                logger.warning("MES未认证，尝试重新认证")
                if not await self.authenticate():
                    return None
            
            if not self.adapter:
                logger.error("MES适配器未设置")
                return None
            
            # 使用适配器获取工单
            response = await self.adapter.get_work_order(self.config, sn)
            
            if response.is_success():
                work_order = self.adapter.parse_work_order(response.data)
                self.connection_info.record_request(True)
                logger.info(f"获取工单成功: {sn}")
                return work_order
            else:
                self.connection_info.record_request(False)
                logger.warning(f"获取工单失败: {sn}, {response.message}")
                return None
                
        except Exception as e:
            self.connection_info.record_request(False)
            logger.error(f"获取工单异常: {e}")
            return None
    
    async def upload_result(self, test_result: TestResult) -> bool:
        """上传测试结果"""
        try:
            if not self._is_authenticated:
                logger.warning("MES未认证，尝试重新认证")
                if not await self.authenticate():
                    return False
            
            if not self.adapter:
                logger.error("MES适配器未设置")
                return False
            
            # 使用适配器上传结果
            response = await self.adapter.upload_result(self.config, test_result)
            
            if response.is_success():
                self.connection_info.record_request(True)
                logger.info(f"上传测试结果成功: {test_result.sn}")
                return True
            else:
                self.connection_info.record_request(False)
                logger.error(f"上传测试结果失败: {test_result.sn}, {response.message}")
                return False
                
        except Exception as e:
            self.connection_info.record_request(False)
            logger.error(f"上传测试结果异常: {e}")
            return False
    
    async def heartbeat(self) -> bool:
        """发送心跳"""
        try:
            if not self._is_authenticated:
                logger.warning("MES未认证，尝试重新认证")
                if not await self.authenticate():
                    return False
            
            if not self.adapter:
                logger.error("MES适配器未设置")
                return False
            
            # 使用适配器发送心跳
            response = await self.adapter.heartbeat(self.config)
            
            if response.is_success():
                self.connection_info.record_request(True)
                logger.debug(f"MES心跳成功: {self.config.vendor}")
                return True
            else:
                self.connection_info.record_request(False)
                logger.warning(f"MES心跳失败: {response.message}")
                return False
                
        except Exception as e:
            self.connection_info.record_request(False)
            logger.error(f"MES心跳异常: {e}")
            return False
    
    async def get_product_params(self, product_number: str) -> Dict[str, Any]:
        """获取产品参数"""
        try:
            if not self._is_authenticated:
                logger.warning("MES未认证，尝试重新认证")
                if not await self.authenticate():
                    return {}
            
            if not self.adapter:
                logger.error("MES适配器未设置")
                return {}
            
            # 使用适配器获取产品参数
            response = await self.adapter.get_product_params(self.config, product_number)
            
            if response.is_success():
                params = self.adapter.parse_product_params(response.data)
                self.connection_info.record_request(True)
                logger.info(f"获取产品参数成功: {product_number}")
                return params
            else:
                self.connection_info.record_request(False)
                logger.warning(f"获取产品参数失败: {product_number}, {response.message}")
                return {}
                
        except Exception as e:
            self.connection_info.record_request(False)
            logger.error(f"获取产品参数异常: {e}")
            return {}
    
    async def is_connected(self) -> bool:
        """检查连接状态"""
        return (self.session is not None and 
                not self.session.closed and 
                self._is_authenticated and
                self.connection_info.status == MESStatus.CONNECTED)
    
    async def _make_request(self, method: str, url: str, **kwargs) -> MESResponse:
        """发送HTTP请求"""
        try:
            if not self.session:
                raise MESError("MES会话未初始化")
            
            # 添加认证头
            headers = kwargs.get('headers', {})
            if self._auth_token:
                headers['Authorization'] = f"Bearer {self._auth_token}"
            
            # 添加默认头
            for key, value in self.config.headers.items():
                if key not in headers:
                    headers[key] = value
            
            kwargs['headers'] = headers
            
            # 发送请求
            async with self.session.request(method, url, **kwargs) as response:
                response_data = await response.json() if response.content_type == 'application/json' else await response.text()
                
                return MESResponse(
                    success=response.status < 400,
                    status_code=response.status,
                    data=response_data,
                    message=response.reason,
                    request_id=response.headers.get('X-Request-ID')
                )
                
        except aiohttp.ClientError as e:
            raise MESError(f"网络请求失败: {e}")
        except json.JSONDecodeError as e:
            raise MESError(f"响应解析失败: {e}")
        except Exception as e:
            raise MESError(f"请求异常: {e}")
    
    def get_connection_info(self) -> MESConnectionInfo:
        """获取连接信息"""
        return self.connection_info
    
    def get_config(self) -> MESConfig:
        """获取配置"""
        return self.config
    
    def set_adapter(self, adapter):
        """设置适配器"""
        self.adapter = adapter
    
    def __str__(self) -> str:
        return f"MESClient(vendor={self.config.vendor}, connected={self._is_authenticated})"
