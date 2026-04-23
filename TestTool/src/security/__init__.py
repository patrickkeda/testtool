"""
系统安全与权限管理模块

主要组件：
- AuthService: 认证服务
- RBACService: 权限控制服务
- AuditService: 审计服务
- EncryptionService: 加密服务
- 权限装饰器
"""

from .models import User, Role, Permission, AuditLog, AuthResult, AuditFilter, AuditReport, UserRole, PermissionResource, PermissionAction
from .interfaces import IAuthService, IRBACService, IAuditService, IEncryptionService
from .auth_service import AuthService
from .rbac_service import RBACService
from .audit_service import AuditService
from .encryption_service import EncryptionService
from .decorators import require_permission, require_role, PermissionChecker

__all__ = [
    'User',
    'Role', 
    'Permission',
    'AuditLog',
    'AuthResult',
    'AuditFilter',
    'AuditReport',
    'UserRole',
    'PermissionResource',
    'PermissionAction',
    'IAuthService',
    'IRBACService', 
    'IAuditService',
    'IEncryptionService',
    'AuthService',
    'RBACService',
    'AuditService',
    'EncryptionService',
    'require_permission',
    'require_role',
    'PermissionChecker'
]
