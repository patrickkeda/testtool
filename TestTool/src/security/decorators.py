"""
权限装饰器实现
"""

import functools
import logging
from typing import Callable, Any, Optional, Union
from datetime import datetime

from .models import UserRole
from .interfaces import IAuthService, IRBACService, IAuditService

logger = logging.getLogger(__name__)


def require_permission(resource: str, action: str, audit: bool = True):
    """权限检查装饰器
    
    Parameters
    ----------
    resource : str
        资源名称
    action : str
        操作名称
    audit : bool
        是否记录审计日志
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 从参数中获取用户ID和权限服务
            user_id = None
            auth_service = None
            rbac_service = None
            audit_service = None
            
            # 尝试从参数中获取用户ID和服务
            if args and len(args) > 0:
                # 检查第一个参数是否是用户ID
                if isinstance(args[0], str):
                    user_id = args[0]
                # 检查是否是关键字参数
                elif hasattr(args[0], 'user_id'):
                    user_id = args[0].user_id
            elif 'user_id' in kwargs:
                user_id = kwargs['user_id']
            
            # 尝试从关键字参数获取服务
            if 'auth_service' in kwargs:
                auth_service = kwargs['auth_service']
            if 'rbac_service' in kwargs:
                rbac_service = kwargs['rbac_service']
            if 'audit_service' in kwargs:
                audit_service = kwargs['audit_service']
            
            # 如果没有用户ID，尝试从全局服务获取
            if not user_id:
                # 这里可以添加从全局服务获取当前用户的逻辑
                logger.warning("权限检查失败: 无法获取用户ID")
                raise PermissionError("无法获取用户信息")
            
            # 检查权限
            if rbac_service:
                has_permission = await rbac_service.has_permission(user_id, resource, action)
                if not has_permission:
                    logger.warning(f"权限检查失败: 用户 {user_id} 没有 {resource}:{action} 权限")
                    if audit and audit_service:
                        await audit_service.log_event(
                            user_id=user_id,
                            action="permission_denied",
                            resource=f"{resource}:{action}",
                            details={"function": func.__name__},
                            success=False
                        )
                    raise PermissionError(f"没有 {resource}:{action} 权限")
            else:
                logger.warning("权限检查跳过: 未提供权限服务")
            
            # 记录审计日志
            if audit and audit_service:
                await audit_service.log_event(
                    user_id=user_id,
                    action=f"{func.__name__}_executed",
                    resource=resource,
                    details={"function": func.__name__, "action": action},
                    success=True
                )
            
            # 执行原函数
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def require_role(role: Union[str, UserRole], audit: bool = True):
    """角色检查装饰器
    
    Parameters
    ----------
    role : Union[str, UserRole]
        角色名称或角色枚举
    audit : bool
        是否记录审计日志
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 从参数中获取用户ID和权限服务
            user_id = None
            rbac_service = None
            audit_service = None
            
            # 尝试从参数中获取用户ID和服务
            if args and len(args) > 0:
                if isinstance(args[0], str):
                    user_id = args[0]
                elif hasattr(args[0], 'user_id'):
                    user_id = args[0].user_id
            elif 'user_id' in kwargs:
                user_id = kwargs['user_id']
            
            if 'rbac_service' in kwargs:
                rbac_service = kwargs['rbac_service']
            if 'audit_service' in kwargs:
                audit_service = kwargs['audit_service']
            
            if not user_id:
                logger.warning("角色检查失败: 无法获取用户ID")
                raise PermissionError("无法获取用户信息")
            
            # 检查角色
            if rbac_service:
                user_role = await rbac_service.get_user_role(user_id)
                if not user_role:
                    logger.warning(f"角色检查失败: 用户 {user_id} 没有角色")
                    raise PermissionError("用户没有分配角色")
                
                # 角色层次检查
                role_name = role.value if isinstance(role, UserRole) else role
                if not await _check_role_hierarchy(user_role.name, role_name):
                    logger.warning(f"角色检查失败: 用户 {user_id} 角色 {user_role.name} 不满足 {role_name} 要求")
                    if audit and audit_service:
                        await audit_service.log_event(
                            user_id=user_id,
                            action="role_denied",
                            resource=f"role:{role_name}",
                            details={"function": func.__name__, "required_role": role_name, "user_role": user_role.name},
                            success=False
                        )
                    raise PermissionError(f"需要 {role_name} 角色")
            else:
                logger.warning("角色检查跳过: 未提供权限服务")
            
            # 记录审计日志
            if audit and audit_service:
                await audit_service.log_event(
                    user_id=user_id,
                    action=f"{func.__name__}_executed",
                    resource=f"role:{role_name}",
                    details={"function": func.__name__, "role": role_name},
                    success=True
                )
            
            # 执行原函数
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def require_admin(audit: bool = True):
    """管理员权限装饰器"""
    return require_role(UserRole.ADMIN, audit)


def require_engineer(audit: bool = True):
    """工程师权限装饰器"""
    return require_role(UserRole.ENGINEER, audit)


def require_operator(audit: bool = True):
    """操作员权限装饰器"""
    return require_role(UserRole.OPERATOR, audit)


def audit_action(action: str, resource: str = "system"):
    """审计装饰器
    
    Parameters
    ----------
    action : str
        操作名称
    resource : str
        资源名称
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 从参数中获取用户ID和审计服务
            user_id = None
            audit_service = None
            
            if args and len(args) > 0:
                if isinstance(args[0], str):
                    user_id = args[0]
                elif hasattr(args[0], 'user_id'):
                    user_id = args[0].user_id
            elif 'user_id' in kwargs:
                user_id = kwargs['user_id']
            
            if 'audit_service' in kwargs:
                audit_service = kwargs['audit_service']
            
            # 执行原函数
            try:
                result = await func(*args, **kwargs)
                
                # 记录成功审计
                if audit_service and user_id:
                    await audit_service.log_event(
                        user_id=user_id,
                        action=action,
                        resource=resource,
                        details={"function": func.__name__, "result": "success"},
                        success=True
                    )
                
                return result
                
            except Exception as e:
                # 记录失败审计
                if audit_service and user_id:
                    await audit_service.log_event(
                        user_id=user_id,
                        action=action,
                        resource=resource,
                        details={"function": func.__name__, "result": "failed", "error": str(e)},
                        success=False
                    )
                
                raise
        
        return wrapper
    return decorator


def rate_limit(max_calls: int, time_window: int = 60):
    """速率限制装饰器
    
    Parameters
    ----------
    max_calls : int
        最大调用次数
    time_window : int
        时间窗口（秒）
    """
    def decorator(func: Callable) -> Callable:
        call_history = {}
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 获取用户ID
            user_id = None
            if args and len(args) > 0:
                if isinstance(args[0], str):
                    user_id = args[0]
                elif hasattr(args[0], 'user_id'):
                    user_id = args[0].user_id
            elif 'user_id' in kwargs:
                user_id = kwargs['user_id']
            
            if not user_id:
                user_id = "anonymous"
            
            # 检查速率限制
            current_time = datetime.now()
            if user_id in call_history:
                # 清理过期记录
                call_history[user_id] = [
                    call_time for call_time in call_history[user_id]
                    if (current_time - call_time).total_seconds() < time_window
                ]
                
                # 检查是否超过限制
                if len(call_history[user_id]) >= max_calls:
                    logger.warning(f"速率限制: 用户 {user_id} 超过 {max_calls} 次/{time_window}秒 限制")
                    raise PermissionError(f"操作过于频繁，请等待 {time_window} 秒后重试")
            else:
                call_history[user_id] = []
            
            # 记录本次调用
            call_history[user_id].append(current_time)
            
            # 执行原函数
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


async def _check_role_hierarchy(user_role: str, required_role: str) -> bool:
    """检查角色层次结构
    
    Parameters
    ----------
    user_role : str
        用户角色
    required_role : str
        需要的角色
        
    Returns
    -------
    bool
        是否满足角色要求
    """
    # 角色层次结构
    hierarchy = {
        "admin": ["engineer", "operator"],
        "engineer": ["operator"],
        "operator": []
    }
    
    # 如果用户角色就是需要的角色，直接返回True
    if user_role == required_role:
        return True
    
    # 检查用户角色是否包含需要的角色
    if user_role in hierarchy:
        return required_role in hierarchy[user_role]
    
    return False


class PermissionChecker:
    """权限检查器"""
    
    def __init__(self, rbac_service: IRBACService, audit_service: IAuditService = None):
        self.rbac_service = rbac_service
        self.audit_service = audit_service
    
    async def check_permission(self, user_id: str, resource: str, action: str) -> bool:
        """检查权限"""
        try:
            has_permission = await self.rbac_service.has_permission(user_id, resource, action)
            
            if self.audit_service:
                await self.audit_service.log_event(
                    user_id=user_id,
                    action="permission_check",
                    resource=f"{resource}:{action}",
                    details={"result": has_permission},
                    success=has_permission
                )
            
            return has_permission
            
        except Exception as e:
            logger.error(f"权限检查异常: {e}")
            return False
    
    async def check_role(self, user_id: str, required_role: str) -> bool:
        """检查角色"""
        try:
            user_role = await self.rbac_service.get_user_role(user_id)
            if not user_role:
                return False
            
            has_role = await _check_role_hierarchy(user_role.name, required_role)
            
            if self.audit_service:
                await self.audit_service.log_event(
                    user_id=user_id,
                    action="role_check",
                    resource=f"role:{required_role}",
                    details={"result": has_role, "user_role": user_role.name},
                    success=has_role
                )
            
            return has_role
            
        except Exception as e:
            logger.error(f"角色检查异常: {e}")
            return False
