"""
MES适配器工厂
"""

import logging
from typing import Dict, List, Type

from .interfaces import IMESClient, IMESAdapter, IMESFactory
from .client import MESClient
from .models import MESConfig
from .adapters.base import MESAdapter as BaseMESAdapter
from .adapters.sample_mes import SampleMESAdapter
from .adapters.huaqin_qmes import HuaqinQMESAdapter

logger = logging.getLogger(__name__)


class MESFactory(IMESFactory):
    """MES适配器工厂"""
    
    def __init__(self):
        self._adapters: Dict[str, Type[IMESAdapter]] = {}
        self._clients: Dict[str, IMESClient] = {}
        self._register_default_adapters()
    
    def _register_default_adapters(self):
        """注册默认适配器"""
        self.register_adapter("sample_mes", SampleMESAdapter)
        self.register_adapter("huaqin_qmes", HuaqinQMESAdapter)
        # 可以在这里注册更多适配器
        # self.register_adapter("sap_mes", SAPMESAdapter)
        # self.register_adapter("custom_mes", CustomMESAdapter)
    
    def register_adapter(self, vendor: str, adapter_class: Type[IMESAdapter]):
        """注册适配器
        
        Parameters
        ----------
        vendor : str
            厂商名称
        adapter_class : Type[IMESAdapter]
            适配器类
        """
        if not issubclass(adapter_class, BaseMESAdapter):
            raise ValueError(f"适配器类必须继承自MESAdapter: {adapter_class}")
        
        self._adapters[vendor] = adapter_class
        logger.info(f"注册MES适配器: {vendor} -> {adapter_class.__name__}")
    
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
        try:
            # 创建适配器
            adapter = self.create_adapter(config.vendor)
            if not adapter:
                raise ValueError(f"不支持的MES厂商: {config.vendor}")
            
            # 创建客户端
            client = MESClient(config, adapter)
            
            # 缓存客户端（可选）
            client_key = f"{config.vendor}_{config.base_url}"
            self._clients[client_key] = client
            
            logger.info(f"创建MES客户端: {config.vendor}")
            return client
            
        except Exception as e:
            logger.error(f"创建MES客户端失败: {e}")
            raise
    
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
        try:
            adapter_class = self._adapters.get(vendor)
            if not adapter_class:
                raise ValueError(f"不支持的MES厂商: {vendor}")
            
            adapter = adapter_class()
            logger.info(f"创建MES适配器: {vendor}")
            return adapter
            
        except Exception as e:
            logger.error(f"创建MES适配器失败: {e}")
            raise
    
    def get_supported_vendors(self) -> List[str]:
        """获取支持的厂商列表
        
        Returns
        -------
        List[str]
            支持的厂商列表
        """
        return list(self._adapters.keys())
    
    def is_vendor_supported(self, vendor: str) -> bool:
        """检查厂商是否支持
        
        Parameters
        ----------
        vendor : str
            厂商名称
            
        Returns
        -------
        bool
            是否支持
        """
        return vendor in self._adapters
    
    def get_adapter_info(self, vendor: str) -> Dict[str, str]:
        """获取适配器信息
        
        Parameters
        ----------
        vendor : str
            厂商名称
            
        Returns
        -------
        Dict[str, str]
            适配器信息
        """
        adapter_class = self._adapters.get(vendor)
        if not adapter_class:
            return {}
        
        return {
            "vendor": vendor,
            "class_name": adapter_class.__name__,
            "module": adapter_class.__module__,
            "description": getattr(adapter_class, "__doc__", "").strip() if adapter_class.__doc__ else ""
        }
    
    def get_all_adapter_info(self) -> Dict[str, Dict[str, str]]:
        """获取所有适配器信息
        
        Returns
        -------
        Dict[str, Dict[str, str]]
            所有适配器信息
        """
        return {vendor: self.get_adapter_info(vendor) for vendor in self._adapters.keys()}
    
    def remove_client(self, client_key: str) -> bool:
        """移除客户端
        
        Parameters
        ----------
        client_key : str
            客户端键
            
        Returns
        -------
        bool
            是否成功移除
        """
        if client_key in self._clients:
            del self._clients[client_key]
            logger.info(f"移除MES客户端: {client_key}")
            return True
        return False
    
    def get_client(self, client_key: str) -> IMESClient:
        """获取客户端
        
        Parameters
        ----------
        client_key : str
            客户端键
            
        Returns
        -------
        IMESClient
            MES客户端实例
        """
        return self._clients.get(client_key)
    
    def get_all_clients(self) -> Dict[str, IMESClient]:
        """获取所有客户端
        
        Returns
        -------
        Dict[str, IMESClient]
            所有客户端
        """
        return self._clients.copy()
    
    def clear_clients(self):
        """清空所有客户端"""
        self._clients.clear()
        logger.info("清空所有MES客户端")
    
    def __str__(self) -> str:
        return f"MESFactory(adapters={len(self._adapters)}, clients={len(self._clients)})"


# 全局工厂实例
_mes_factory = None


def get_mes_factory() -> MESFactory:
    """获取全局MES工厂实例
    
    Returns
    -------
    MESFactory
        全局MES工厂实例
    """
    global _mes_factory
    if _mes_factory is None:
        _mes_factory = MESFactory()
    return _mes_factory


def create_mes_client(config: MESConfig) -> IMESClient:
    """创建MES客户端（便捷函数）
    
    Parameters
    ----------
    config : MESConfig
        MES配置
        
    Returns
    -------
    IMESClient
        MES客户端实例
    """
    factory = get_mes_factory()
    return factory.create_client(config)


def create_mes_adapter(vendor: str) -> IMESAdapter:
    """创建MES适配器（便捷函数）
    
    Parameters
    ----------
    vendor : str
        厂商名称
        
    Returns
    -------
    IMESAdapter
        MES适配器实例
    """
    factory = get_mes_factory()
    return factory.create_adapter(vendor)
