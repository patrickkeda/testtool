"""
UUT接口定义
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
import asyncio

from .models import UUTCommand, UUTResponse, UUTStatus, UUTConfig, UUTTestResult


class IUUTAdapter(ABC):
    """UUT适配器接口"""
    
    @abstractmethod
    async def connect(self) -> bool:
        """建立与UUT的连接
        
        Returns
        -------
        bool
            连接是否成功
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """断开与UUT的连接
        
        Returns
        -------
        bool
            断开是否成功
        """
        pass
    
    @abstractmethod
    async def send_command(self, command: UUTCommand) -> UUTResponse:
        """发送命令到UUT
        
        Parameters
        ----------
        command : UUTCommand
            UUT命令
            
        Returns
        -------
        UUTResponse
            UUT响应
        """
        pass
    
    @abstractmethod
    async def read_response(self, timeout: Optional[int] = None) -> UUTResponse:
        """读取UUT响应
        
        Parameters
        ----------
        timeout : Optional[int]
            超时时间(毫秒)
            
        Returns
        -------
        UUTResponse
            UUT响应
        """
        pass
    
    @abstractmethod
    async def get_status(self) -> UUTStatus:
        """获取UUT状态
        
        Returns
        -------
        UUTStatus
            UUT状态
        """
        pass
    
    @abstractmethod
    async def reset(self) -> bool:
        """重置UUT
        
        Returns
        -------
        bool
            重置是否成功
        """
        pass
    
    @abstractmethod
    async def is_connected(self) -> bool:
        """检查UUT是否已连接
        
        Returns
        -------
        bool
            是否已连接
        """
        pass
    
    @abstractmethod
    async def execute_test(self, test_name: str, commands: List[UUTCommand]) -> UUTTestResult:
        """执行测试序列
        
        Parameters
        ----------
        test_name : str
            测试名称
        commands : List[UUTCommand]
            命令列表
            
        Returns
        -------
        UUTTestResult
            测试结果
        """
        pass


class IProtocolAdapter(ABC):
    """协议适配器接口"""
    
    @abstractmethod
    async def encode_command(self, command: UUTCommand) -> bytes:
        """编码命令
        
        Parameters
        ----------
        command : UUTCommand
            UUT命令
            
        Returns
        -------
        bytes
            编码后的命令数据
        """
        pass
    
    @abstractmethod
    async def decode_response(self, data: bytes, command: UUTCommand) -> UUTResponse:
        """解码响应
        
        Parameters
        ----------
        data : bytes
            原始响应数据
        command : UUTCommand
            对应的命令
            
        Returns
        -------
        UUTResponse
            解码后的响应
        """
        pass
    
    @abstractmethod
    async def validate_data(self, data: bytes) -> bool:
        """验证数据格式
        
        Parameters
        ----------
        data : bytes
            待验证的数据
            
        Returns
        -------
        bool
            数据是否有效
        """
        pass
    
    @abstractmethod
    async def create_handshake(self) -> bytes:
        """创建握手数据
        
        Returns
        -------
        bytes
            握手数据
        """
        pass
    
    @abstractmethod
    async def validate_handshake(self, data: bytes) -> bool:
        """验证握手响应
        
        Parameters
        ----------
        data : bytes
            握手响应数据
            
        Returns
        -------
        bool
            握手是否成功
        """
        pass


class ICommandManager(ABC):
    """命令管理器接口"""
    
    @abstractmethod
    async def load_commands(self, config: UUTConfig) -> None:
        """加载命令配置
        
        Parameters
        ----------
        config : UUTConfig
            UUT配置
        """
        pass
    
    @abstractmethod
    async def get_command(self, name: str) -> Optional[UUTCommand]:
        """获取命令
        
        Parameters
        ----------
        name : str
            命令名称
            
        Returns
        -------
        Optional[UUTCommand]
            命令对象
        """
        pass
    
    @abstractmethod
    async def add_command(self, command: UUTCommand) -> None:
        """添加命令
        
        Parameters
        ----------
        command : UUTCommand
            命令对象
        """
        pass
    
    @abstractmethod
    async def remove_command(self, name: str) -> bool:
        """删除命令
        
        Parameters
        ----------
        name : str
            命令名称
            
        Returns
        -------
        bool
            是否删除成功
        """
        pass
    
    @abstractmethod
    async def list_commands(self) -> List[str]:
        """列出所有命令名称
        
        Returns
        -------
        List[str]
            命令名称列表
        """
        pass


class IStatusManager(ABC):
    """状态管理器接口"""
    
    @abstractmethod
    async def update_connection_status(self, status: str) -> None:
        """更新连接状态
        
        Parameters
        ----------
        status : str
            连接状态
        """
        pass
    
    @abstractmethod
    async def update_test_status(self, status: str) -> None:
        """更新测试状态
        
        Parameters
        ----------
        status : str
            测试状态
        """
        pass
    
    @abstractmethod
    async def record_command(self, command: UUTCommand) -> None:
        """记录命令执行
        
        Parameters
        ----------
        command : UUTCommand
            执行的命令
        """
        pass
    
    @abstractmethod
    async def record_response(self, response: UUTResponse) -> None:
        """记录响应
        
        Parameters
        ----------
        response : UUTResponse
            UUT响应
        """
        pass
    
    @abstractmethod
    async def record_error(self, error: str) -> None:
        """记录错误
        
        Parameters
        ----------
        error : str
            错误信息
        """
        pass
    
    @abstractmethod
    async def get_status(self) -> UUTStatus:
        """获取当前状态
        
        Returns
        -------
        UUTStatus
            当前状态
        """
        pass
