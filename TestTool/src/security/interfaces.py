"""
权限管理接口定义
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime

from .models import User, Role, Permission, AuditLog, AuthResult, AuditFilter, AuditReport


class IAuthService(ABC):
    """认证服务接口"""
    
    @abstractmethod
    async def login(self, username: str, password: str, ip_address: str = "", user_agent: str = "") -> AuthResult:
        """用户登录
        
        Parameters
        ----------
        username : str
            用户名
        password : str
            密码
        ip_address : str
            IP地址
        user_agent : str
            用户代理
            
        Returns
        -------
        AuthResult
            认证结果
        """
        pass
    
    @abstractmethod
    async def logout(self, session_id: str) -> bool:
        """用户登出
        
        Parameters
        ----------
        session_id : str
            会话ID
            
        Returns
        -------
        bool
            是否成功登出
        """
        pass
    
    @abstractmethod
    async def validate_session(self, session_id: str) -> bool:
        """验证会话
        
        Parameters
        ----------
        session_id : str
            会话ID
            
        Returns
        -------
        bool
            会话是否有效
        """
        pass
    
    @abstractmethod
    async def get_user_by_session(self, session_id: str) -> Optional[User]:
        """通过会话ID获取用户
        
        Parameters
        ----------
        session_id : str
            会话ID
            
        Returns
        -------
        Optional[User]
            用户对象
        """
        pass
    
    @abstractmethod
    async def change_password(self, user_id: str, old_password: str, new_password: str) -> bool:
        """修改密码
        
        Parameters
        ----------
        user_id : str
            用户ID
        old_password : str
            旧密码
        new_password : str
            新密码
            
        Returns
        -------
        bool
            是否成功修改
        """
        pass
    
    @abstractmethod
    async def create_user(self, username: str, email: str, password: str, role: str) -> Optional[User]:
        """创建用户
        
        Parameters
        ----------
        username : str
            用户名
        email : str
            邮箱
        password : str
            密码
        role : str
            角色
            
        Returns
        -------
        Optional[User]
            创建的用户对象
        """
        pass


class IRBACService(ABC):
    """权限控制服务接口"""
    
    @abstractmethod
    async def has_permission(self, user_id: str, resource: str, action: str) -> bool:
        """检查用户权限
        
        Parameters
        ----------
        user_id : str
            用户ID
        resource : str
            资源
        action : str
            操作
            
        Returns
        -------
        bool
            是否有权限
        """
        pass
    
    @abstractmethod
    async def get_user_role(self, user_id: str) -> Optional[Role]:
        """获取用户角色
        
        Parameters
        ----------
        user_id : str
            用户ID
            
        Returns
        -------
        Optional[Role]
            角色对象
        """
        pass
    
    @abstractmethod
    async def get_user_permissions(self, user_id: str) -> List[Permission]:
        """获取用户权限列表
        
        Parameters
        ----------
        user_id : str
            用户ID
            
        Returns
        -------
        List[Permission]
            权限列表
        """
        pass
    
    @abstractmethod
    async def check_role_permission(self, role: str, resource: str, action: str) -> bool:
        """检查角色权限
        
        Parameters
        ----------
        role : str
            角色
        resource : str
            资源
        action : str
            操作
            
        Returns
        -------
        bool
            是否有权限
        """
        pass
    
    @abstractmethod
    async def get_all_roles(self) -> List[Role]:
        """获取所有角色
        
        Returns
        -------
        List[Role]
            角色列表
        """
        pass
    
    @abstractmethod
    async def get_all_permissions(self) -> List[Permission]:
        """获取所有权限
        
        Returns
        -------
        List[Permission]
            权限列表
        """
        pass


class IAuditService(ABC):
    """审计服务接口"""
    
    @abstractmethod
    async def log_event(self, user_id: str, action: str, resource: str, details: Dict[str, Any] = None, 
                       ip_address: str = "", user_agent: str = "", success: bool = True) -> bool:
        """记录审计事件
        
        Parameters
        ----------
        user_id : str
            用户ID
        action : str
            操作
        resource : str
            资源
        details : Dict[str, Any]
            详细信息
        ip_address : str
            IP地址
        user_agent : str
            用户代理
        success : bool
            是否成功
            
        Returns
        -------
        bool
            是否成功记录
        """
        pass
    
    @abstractmethod
    async def get_audit_logs(self, filters: AuditFilter) -> List[AuditLog]:
        """获取审计日志
        
        Parameters
        ----------
        filters : AuditFilter
            过滤条件
            
        Returns
        -------
        List[AuditLog]
            审计日志列表
        """
        pass
    
    @abstractmethod
    async def generate_audit_report(self, start_date: datetime, end_date: datetime, 
                                  title: str = "审计报告") -> AuditReport:
        """生成审计报告
        
        Parameters
        ----------
        start_date : datetime
            开始日期
        end_date : datetime
            结束日期
        title : str
            报告标题
            
        Returns
        -------
        AuditReport
            审计报告
        """
        pass
    
    @abstractmethod
    async def get_audit_statistics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """获取审计统计信息
        
        Parameters
        ----------
        start_date : datetime
            开始日期
        end_date : datetime
            结束日期
            
        Returns
        -------
        Dict[str, Any]
            统计信息
        """
        pass


class IEncryptionService(ABC):
    """加密服务接口"""
    
    @abstractmethod
    async def hash_password(self, password: str) -> str:
        """密码哈希
        
        Parameters
        ----------
        password : str
            明文密码
            
        Returns
        -------
        str
            哈希后的密码
        """
        pass
    
    @abstractmethod
    async def verify_password(self, password: str, hashed_password: str) -> bool:
        """验证密码
        
        Parameters
        ----------
        password : str
            明文密码
        hashed_password : str
            哈希密码
            
        Returns
        -------
        bool
            密码是否正确
        """
        pass
    
    @abstractmethod
    async def encrypt_data(self, data: str, key: str = None) -> str:
        """加密数据
        
        Parameters
        ----------
        data : str
            明文数据
        key : str
            加密密钥
            
        Returns
        -------
        str
            加密后的数据
        """
        pass
    
    @abstractmethod
    async def decrypt_data(self, encrypted_data: str, key: str = None) -> str:
        """解密数据
        
        Parameters
        ----------
        encrypted_data : str
            加密数据
        key : str
            解密密钥
            
        Returns
        -------
        str
            解密后的数据
        """
        pass
    
    @abstractmethod
    async def generate_key(self) -> str:
        """生成加密密钥
        
        Returns
        -------
        str
            加密密钥
        """
        pass
    
    @abstractmethod
    async def get_or_create_master_key(self) -> str:
        """获取或创建主密钥
        
        Returns
        -------
        str
            主密钥
        """
        pass
