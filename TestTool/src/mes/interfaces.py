"""
MES模块接口定义
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from datetime import datetime

from .models import WorkOrder, TestResult, MESResponse, MESConfig, HeartbeatStatus


class IMESClient(ABC):
    """MES客户端接口"""
    
    @abstractmethod
    async def authenticate(self) -> bool:
        """认证到MES系统
        
        Returns
        -------
        bool
            认证是否成功
        """
        pass
    
    @abstractmethod
    async def get_work_order(self, sn: str) -> Optional[WorkOrder]:
        """获取工单信息
        
        Parameters
        ----------
        sn : str
            产品序列号
            
        Returns
        -------
        Optional[WorkOrder]
            工单信息，如果不存在返回None
        """
        pass
    
    @abstractmethod
    async def upload_result(self, test_result: TestResult) -> bool:
        """上传测试结果
        
        Parameters
        ----------
        test_result : TestResult
            测试结果
            
        Returns
        -------
        bool
            上传是否成功
        """
        pass
    
    @abstractmethod
    async def heartbeat(self) -> bool:
        """发送心跳
        
        Returns
        -------
        bool
            心跳是否成功
        """
        pass
    
    @abstractmethod
    async def get_product_params(self, product_number: str) -> Dict[str, Any]:
        """获取产品参数
        
        Parameters
        ----------
        product_number : str
            产品型号
            
        Returns
        -------
        Dict[str, Any]
            产品参数
        """
        pass
    
    @abstractmethod
    async def is_connected(self) -> bool:
        """检查连接状态
        
        Returns
        -------
        bool
            是否已连接
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """断开连接
        
        Returns
        -------
        bool
            断开是否成功
        """
        pass


class IMESAdapter(ABC):
    """MES适配器接口"""
    
    @abstractmethod
    async def authenticate(self, config: MESConfig) -> MESResponse:
        """认证适配器
        
        Parameters
        ----------
        config : MESConfig
            MES配置
            
        Returns
        -------
        MESResponse
            认证响应
        """
        pass
    
    @abstractmethod
    async def get_work_order(self, config: MESConfig, sn: str) -> MESResponse:
        """获取工单适配器
        
        Parameters
        ----------
        config : MESConfig
            MES配置
        sn : str
            产品序列号
            
        Returns
        -------
        MESResponse
            工单响应
        """
        pass
    
    @abstractmethod
    async def upload_result(self, config: MESConfig, test_result: TestResult) -> MESResponse:
        """上传结果适配器
        
        Parameters
        ----------
        config : MESConfig
            MES配置
        test_result : TestResult
            测试结果
            
        Returns
        -------
        MESResponse
            上传响应
        """
        pass
    
    @abstractmethod
    async def heartbeat(self, config: MESConfig) -> MESResponse:
        """心跳适配器
        
        Parameters
        ----------
        config : MESConfig
            MES配置
            
        Returns
        -------
        MESResponse
            心跳响应
        """
        pass
    
    @abstractmethod
    async def get_product_params(self, config: MESConfig, product_number: str) -> MESResponse:
        """获取产品参数适配器
        
        Parameters
        ----------
        config : MESConfig
            MES配置
        product_number : str
            产品型号
            
        Returns
        -------
        MESResponse
            产品参数响应
        """
        pass
    
    @abstractmethod
    def parse_work_order(self, response_data: Any) -> Optional[WorkOrder]:
        """解析工单数据
        
        Parameters
        ----------
        response_data : Any
            响应数据
            
        Returns
        -------
        Optional[WorkOrder]
            解析后的工单信息
        """
        pass
    
    @abstractmethod
    def parse_product_params(self, response_data: Any) -> Dict[str, Any]:
        """解析产品参数
        
        Parameters
        ----------
        response_data : Any
            响应数据
            
        Returns
        -------
        Dict[str, Any]
            解析后的产品参数
        """
        pass


class IMESFactory(ABC):
    """MES工厂接口"""
    
    @abstractmethod
    def create_client(self, config: MESConfig) -> IMESClient:
        """创建MES客户端
        
        Parameters
        ----------
        config : MESConfig
            MES配置
            
        Returns
        -------
        IMESClient
            MES客户端实例
        """
        pass
    
    @abstractmethod
    def create_adapter(self, vendor: str) -> IMESAdapter:
        """创建MES适配器
        
        Parameters
        ----------
        vendor : str
            厂商名称
            
        Returns
        -------
        IMESAdapter
            MES适配器实例
        """
        pass
    
    @abstractmethod
    def get_supported_vendors(self) -> List[str]:
        """获取支持的厂商列表
        
        Returns
        -------
        List[str]
            支持的厂商列表
        """
        pass


class IHeartbeatManager(ABC):
    """心跳管理器接口"""
    
    @abstractmethod
    async def start(self, client: IMESClient, interval_ms: int) -> bool:
        """启动心跳
        
        Parameters
        ----------
        client : IMESClient
            MES客户端
        interval_ms : int
            心跳间隔（毫秒）
            
        Returns
        -------
        bool
            启动是否成功
        """
        pass
    
    @abstractmethod
    async def stop(self) -> bool:
        """停止心跳
        
        Returns
        -------
        bool
            停止是否成功
        """
        pass
    
    @abstractmethod
    async def get_status(self) -> HeartbeatStatus:
        """获取心跳状态
        
        Returns
        -------
        HeartbeatStatus
            心跳状态
        """
        pass
    
    @abstractmethod
    def is_running(self) -> bool:
        """检查是否正在运行
        
        Returns
        -------
        bool
            是否正在运行
        """
        pass
