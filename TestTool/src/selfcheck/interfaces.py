"""
系统自检接口定义
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import asyncio

from .models import CheckResult, CheckConfig, CheckCategory


class IResourceChecker(ABC):
    """资源检查器接口"""
    
    @abstractmethod
    async def check(self, config: Dict[str, Any]) -> CheckResult:
        """执行检查
        
        Parameters
        ----------
        config : Dict[str, Any]
            检查配置
            
        Returns
        -------
        CheckResult
            检查结果
        """
        pass
    
    @abstractmethod
    def get_category(self) -> CheckCategory:
        """获取检查类别
        
        Returns
        -------
        CheckCategory
            检查类别
        """
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """获取检查器名称
        
        Returns
        -------
        str
            检查器名称
        """
        pass


class ISystemChecker(ABC):
    """系统检查器接口"""
    
    @abstractmethod
    async def run_full_check(self, config: CheckConfig) -> 'SystemCheckResult':
        """执行完整系统检查
        
        Parameters
        ----------
        config : CheckConfig
            检查配置
            
        Returns
        -------
        SystemCheckResult
            系统检查结果
        """
        pass
    
    @abstractmethod
    async def check_category(self, category: CheckCategory, config: CheckConfig) -> CheckResult:
        """检查指定类别
        
        Parameters
        ----------
        category : CheckCategory
            检查类别
        config : CheckConfig
            检查配置
            
        Returns
        -------
        CheckResult
            检查结果
        """
        pass
    
    @abstractmethod
    async def register_checker(self, checker: IResourceChecker):
        """注册检查器
        
        Parameters
        ----------
        checker : IResourceChecker
            检查器实例
        """
        pass
    
    @abstractmethod
    async def unregister_checker(self, category: CheckCategory):
        """注销检查器
        
        Parameters
        ----------
        category : CheckCategory
            检查类别
        """
        pass
    
    @abstractmethod
    def get_available_checkers(self) -> Dict[CheckCategory, IResourceChecker]:
        """获取可用的检查器
        
        Returns
        -------
        Dict[CheckCategory, IResourceChecker]
            检查器字典
        """
        pass


class ICheckProgressCallback(ABC):
    """检查进度回调接口"""
    
    @abstractmethod
    async def on_check_started(self, category: CheckCategory, checker_name: str):
        """检查开始回调
        
        Parameters
        ----------
        category : CheckCategory
            检查类别
        checker_name : str
            检查器名称
        """
        pass
    
    @abstractmethod
    async def on_check_progress(self, category: CheckCategory, item_name: str, status: str):
        """检查进度回调
        
        Parameters
        ----------
        category : CheckCategory
            检查类别
        item_name : str
            检查项目名称
        status : str
            检查状态
        """
        pass
    
    @abstractmethod
    async def on_check_completed(self, category: CheckCategory, result: CheckResult):
        """检查完成回调
        
        Parameters
        ----------
        category : CheckCategory
            检查类别
        result : CheckResult
            检查结果
        """
        pass
    
    @abstractmethod
    async def on_system_check_completed(self, result: 'SystemCheckResult'):
        """系统检查完成回调
        
        Parameters
        ----------
        result : SystemCheckResult
            系统检查结果
        """
        pass


class ICheckReporter(ABC):
    """检查报告器接口"""
    
    @abstractmethod
    async def generate_report(self, result: 'SystemCheckResult', format: str = "text") -> str:
        """生成检查报告
        
        Parameters
        ----------
        result : SystemCheckResult
            系统检查结果
        format : str
            报告格式 (text, html, json)
            
        Returns
        -------
        str
            检查报告
        """
        pass
    
    @abstractmethod
    async def save_report(self, result: 'SystemCheckResult', file_path: str, format: str = "json"):
        """保存检查报告
        
        Parameters
        ----------
        result : SystemCheckResult
            系统检查结果
        file_path : str
            文件路径
        format : str
            文件格式
        """
        pass
    
    @abstractmethod
    async def load_report(self, file_path: str) -> Optional['SystemCheckResult']:
        """加载检查报告
        
        Parameters
        ----------
        file_path : str
            文件路径
            
        Returns
        -------
        Optional[SystemCheckResult]
            系统检查结果
        """
        pass


class ICheckScheduler(ABC):
    """检查调度器接口"""
    
    @abstractmethod
    async def schedule_periodic_check(self, interval: int, config: CheckConfig):
        """调度定期检查
        
        Parameters
        ----------
        interval : int
            检查间隔(秒)
        config : CheckConfig
            检查配置
        """
        pass
    
    @abstractmethod
    async def schedule_startup_check(self, config: CheckConfig):
        """调度启动检查
        
        Parameters
        ----------
        config : CheckConfig
            检查配置
        """
        pass
    
    @abstractmethod
    async def cancel_scheduled_checks(self):
        """取消调度的检查"""
        pass
    
    @abstractmethod
    def is_check_scheduled(self) -> bool:
        """检查是否有调度的检查
        
        Returns
        -------
        bool
            是否有调度的检查
        """
        pass
