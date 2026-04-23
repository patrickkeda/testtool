"""
权限管理数据模型
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class UserRole(Enum):
    """用户角色枚举"""
    OPERATOR = "operator"    # 操作员
    ENGINEER = "engineer"    # 工程师
    ADMIN = "admin"          # 管理员


class PermissionResource(Enum):
    """权限资源枚举"""
    TEST = "test"            # 测试相关
    CONFIG = "config"        # 配置相关
    USER = "user"            # 用户管理
    SYSTEM = "system"        # 系统管理
    AUDIT = "audit"          # 审计相关


class PermissionAction(Enum):
    """权限操作枚举"""
    EXECUTE = "execute"      # 执行
    VIEW = "view"            # 查看
    MODIFY = "modify"        # 修改
    MANAGE = "manage"        # 管理


@dataclass
class User:
    """用户模型"""
    id: str
    username: str
    email: str
    role: UserRole
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    last_login: Optional[datetime] = None
    password_hash: str = ""
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None
    
    def is_locked(self) -> bool:
        """检查用户是否被锁定"""
        if self.locked_until is None:
            return False
        return datetime.now() < self.locked_until
    
    def can_login(self) -> bool:
        """检查用户是否可以登录"""
        return self.is_active and not self.is_locked()
    
    def __str__(self) -> str:
        return f"User(id={self.id}, username={self.username}, role={self.role.value})"


@dataclass
class Role:
    """角色模型"""
    id: str
    name: str
    description: str
    permissions: List[str] = field(default_factory=list)
    is_system_role: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    
    def has_permission(self, resource: str, action: str) -> bool:
        """检查角色是否有指定权限"""
        permission_key = f"{resource}:{action}"
        return permission_key in self.permissions
    
    def __str__(self) -> str:
        return f"Role(id={self.id}, name={self.name}, permissions={len(self.permissions)})"


@dataclass
class Permission:
    """权限模型"""
    id: str
    resource: PermissionResource
    action: PermissionAction
    description: str
    is_system_permission: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    
    @property
    def key(self) -> str:
        """权限键值"""
        return f"{self.resource.value}:{self.action.value}"
    
    def __str__(self) -> str:
        return f"Permission(id={self.id}, key={self.key})"


@dataclass
class AuditLog:
    """审计日志模型"""
    id: str
    user_id: str
    username: str
    action: str
    resource: str
    details: Dict[str, Any] = field(default_factory=dict)
    ip_address: str = ""
    user_agent: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    
    def __str__(self) -> str:
        return f"AuditLog(id={self.id}, user={self.username}, action={self.action}, success={self.success})"


@dataclass
class AuthResult:
    """认证结果"""
    success: bool
    user: Optional[User] = None
    session_id: Optional[str] = None
    message: str = ""
    expires_at: Optional[datetime] = None
    
    def __str__(self) -> str:
        return f"AuthResult(success={self.success}, user={self.user}, message={self.message})"


@dataclass
class AuditFilter:
    """审计日志过滤条件"""
    user_id: Optional[str] = None
    username: Optional[str] = None
    action: Optional[str] = None
    resource: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    success: Optional[bool] = None
    ip_address: Optional[str] = None
    limit: int = 100
    offset: int = 0


@dataclass
class AuditReport:
    """审计报告"""
    title: str
    start_date: datetime
    end_date: datetime
    total_events: int
    events_by_user: Dict[str, int] = field(default_factory=dict)
    events_by_action: Dict[str, int] = field(default_factory=dict)
    events_by_resource: Dict[str, int] = field(default_factory=dict)
    success_rate: float = 0.0
    failed_events: List[AuditLog] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)
    
    def __str__(self) -> str:
        return f"AuditReport(title={self.title}, total_events={self.total_events}, success_rate={self.success_rate:.2%})"


# 预定义角色权限映射
ROLE_PERMISSIONS = {
    UserRole.OPERATOR: [
        "test:execute",
        "test:view", 
        "config:view",
        "test:view_sequence"
    ],
    UserRole.ENGINEER: [
        "test:execute",
        "test:view",
        "config:view",
        "config:modify",
        "config:import_export",
        "system:maintain",
        "system:view_logs",
        "test:view_sequence"
    ],
    UserRole.ADMIN: [
        "test:execute",
        "test:view",
        "config:view",
        "config:modify",
        "config:import_export",
        "system:maintain",
        "system:view_logs",
        "system:configure",
        "user:manage",
        "user:view",
        "test:modify_sequence",
        "test:create_sequence",
        "test:delete_sequence",
        "audit:view",
        "audit:report"
    ]
}

# 预定义权限列表
SYSTEM_PERMISSIONS = [
    # 测试相关权限
    Permission("test_execute", PermissionResource.TEST, PermissionAction.EXECUTE, "执行测试"),
    Permission("test_view", PermissionResource.TEST, PermissionAction.VIEW, "查看测试结果"),
    Permission("test_export", PermissionResource.TEST, PermissionAction.VIEW, "导出测试数据"),
    Permission("test_view_sequence", PermissionResource.TEST, PermissionAction.VIEW, "查看测试序列"),
    Permission("test_modify_sequence", PermissionResource.TEST, PermissionAction.MODIFY, "修改测试序列"),
    Permission("test_create_sequence", PermissionResource.TEST, PermissionAction.MANAGE, "创建测试序列"),
    Permission("test_delete_sequence", PermissionResource.TEST, PermissionAction.MANAGE, "删除测试序列"),
    
    # 配置相关权限
    Permission("config_view", PermissionResource.CONFIG, PermissionAction.VIEW, "查看配置"),
    Permission("config_modify", PermissionResource.CONFIG, PermissionAction.MODIFY, "修改配置"),
    Permission("config_import_export", PermissionResource.CONFIG, PermissionAction.MODIFY, "导入/导出配置"),
    
    # 用户管理权限
    Permission("user_view", PermissionResource.USER, PermissionAction.VIEW, "查看用户列表"),
    Permission("user_manage", PermissionResource.USER, PermissionAction.MANAGE, "管理用户"),
    
    # 系统管理权限
    Permission("system_maintain", PermissionResource.SYSTEM, PermissionAction.MODIFY, "系统维护"),
    Permission("system_view_logs", PermissionResource.SYSTEM, PermissionAction.VIEW, "查看系统日志"),
    Permission("system_configure", PermissionResource.SYSTEM, PermissionAction.MANAGE, "系统配置"),
    
    # 审计权限
    Permission("audit_view", PermissionResource.AUDIT, PermissionAction.VIEW, "查看审计日志"),
    Permission("audit_report", PermissionResource.AUDIT, PermissionAction.VIEW, "生成审计报告"),
]

# 预定义角色
SYSTEM_ROLES = [
    Role("operator", "操作员", "日常测试操作", ROLE_PERMISSIONS[UserRole.OPERATOR]),
    Role("engineer", "工程师", "配置修改、诊断故障", ROLE_PERMISSIONS[UserRole.ENGINEER]),
    Role("admin", "管理员", "用户管理、系统配置、测试序列修改", ROLE_PERMISSIONS[UserRole.ADMIN]),
]
