"""
权限控制服务实现
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from .interfaces import IRBACService
from .models import User, Role, Permission, UserRole, SYSTEM_ROLES, SYSTEM_PERMISSIONS, ROLE_PERMISSIONS

logger = logging.getLogger(__name__)


class RBACService(IRBACService):
    """权限控制服务实现"""
    
    def __init__(self):
        self.roles: Dict[str, Role] = {}
        self.permissions: Dict[str, Permission] = {}
        
        # 初始化系统角色和权限
        self._initialize_system_data()
    
    def _initialize_system_data(self):
        """初始化系统角色和权限"""
        # 初始化系统角色
        for role in SYSTEM_ROLES:
            self.roles[role.id] = role
        
        # 初始化系统权限
        for permission in SYSTEM_PERMISSIONS:
            self.permissions[permission.id] = permission
        
        logger.info(f"已初始化 {len(self.roles)} 个角色和 {len(self.permissions)} 个权限")
    
    async def has_permission(self, user_id: str, resource: str, action: str) -> bool:
        """检查用户权限"""
        try:
            # 获取用户角色
            role = await self.get_user_role(user_id)
            if not role:
                logger.warning(f"权限检查失败: 用户角色不存在 - {user_id}")
                return False
            
            # 检查角色权限
            return await self.check_role_permission(role.name, resource, action)
            
        except Exception as e:
            logger.error(f"权限检查异常: {e}")
            return False
    
    async def get_user_role(self, user_id: str) -> Optional[Role]:
        """获取用户角色"""
        try:
            # 这里需要从认证服务获取用户信息
            # 为了简化，我们假设用户ID就是角色名
            # 在实际实现中，应该从用户存储中获取用户角色
            
            # 检查是否是预定义角色
            if user_id in ["admin", "operator", "engineer"]:
                return self.roles.get(user_id)
            
            # 默认返回操作员角色
            return self.roles.get("operator")
            
        except Exception as e:
            logger.error(f"获取用户角色异常: {e}")
            return None
    
    async def get_user_permissions(self, user_id: str) -> List[Permission]:
        """获取用户权限列表"""
        try:
            role = await self.get_user_role(user_id)
            if not role:
                return []
            
            user_permissions = []
            for permission_key in role.permissions:
                # 查找对应的权限对象
                for permission in self.permissions.values():
                    if permission.key == permission_key:
                        user_permissions.append(permission)
                        break
            
            return user_permissions
            
        except Exception as e:
            logger.error(f"获取用户权限异常: {e}")
            return []
    
    async def check_role_permission(self, role: str, resource: str, action: str) -> bool:
        """检查角色权限"""
        try:
            role_obj = self.roles.get(role)
            if not role_obj:
                logger.warning(f"权限检查失败: 角色不存在 - {role}")
                return False
            
            permission_key = f"{resource}:{action}"
            return permission_key in role_obj.permissions
            
        except Exception as e:
            logger.error(f"角色权限检查异常: {e}")
            return False
    
    async def get_all_roles(self) -> List[Role]:
        """获取所有角色"""
        return list(self.roles.values())
    
    async def get_all_permissions(self) -> List[Permission]:
        """获取所有权限"""
        return list(self.permissions.values())
    
    async def get_role_by_id(self, role_id: str) -> Optional[Role]:
        """通过ID获取角色"""
        return self.roles.get(role_id)
    
    async def get_permission_by_id(self, permission_id: str) -> Optional[Permission]:
        """通过ID获取权限"""
        return self.permissions.get(permission_id)
    
    async def get_permissions_by_resource(self, resource: str) -> List[Permission]:
        """获取指定资源的所有权限"""
        try:
            permissions = []
            for permission in self.permissions.values():
                if permission.resource.value == resource:
                    permissions.append(permission)
            return permissions
        except Exception as e:
            logger.error(f"获取资源权限异常: {e}")
            return []
    
    async def get_permissions_by_action(self, action: str) -> List[Permission]:
        """获取指定操作的所有权限"""
        try:
            permissions = []
            for permission in self.permissions.values():
                if permission.action.value == action:
                    permissions.append(permission)
            return permissions
        except Exception as e:
            logger.error(f"获取操作权限异常: {e}")
            return []
    
    async def has_resource_permission(self, user_id: str, resource: str) -> bool:
        """检查用户是否有指定资源的任何权限"""
        try:
            role = await self.get_user_role(user_id)
            if not role:
                return False
            
            for permission_key in role.permissions:
                if permission_key.startswith(f"{resource}:"):
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"资源权限检查异常: {e}")
            return False
    
    async def has_action_permission(self, user_id: str, action: str) -> bool:
        """检查用户是否有指定操作的任何权限"""
        try:
            role = await self.get_user_role(user_id)
            if not role:
                return False
            
            for permission_key in role.permissions:
                if permission_key.endswith(f":{action}"):
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"操作权限检查异常: {e}")
            return False
    
    async def get_user_permission_summary(self, user_id: str) -> Dict[str, List[str]]:
        """获取用户权限摘要"""
        try:
            role = await self.get_user_role(user_id)
            if not role:
                return {}
            
            summary = {}
            for permission_key in role.permissions:
                resource, action = permission_key.split(":", 1)
                if resource not in summary:
                    summary[resource] = []
                summary[resource].append(action)
            
            return summary
            
        except Exception as e:
            logger.error(f"获取权限摘要异常: {e}")
            return {}
    
    async def check_multiple_permissions(self, user_id: str, permissions: List[tuple]) -> Dict[tuple, bool]:
        """批量检查权限"""
        try:
            results = {}
            for resource, action in permissions:
                results[(resource, action)] = await self.has_permission(user_id, resource, action)
            return results
        except Exception as e:
            logger.error(f"批量权限检查异常: {e}")
            return {}
    
    async def is_admin(self, user_id: str) -> bool:
        """检查用户是否是管理员"""
        try:
            role = await self.get_user_role(user_id)
            return role and role.name == "admin"
        except Exception as e:
            logger.error(f"管理员检查异常: {e}")
            return False
    
    async def is_engineer(self, user_id: str) -> bool:
        """检查用户是否是工程师"""
        try:
            role = await self.get_user_role(user_id)
            return role and role.name in ["engineer", "admin"]
        except Exception as e:
            logger.error(f"工程师检查异常: {e}")
            return False
    
    async def is_operator(self, user_id: str) -> bool:
        """检查用户是否是操作员"""
        try:
            role = await self.get_user_role(user_id)
            return role and role.name in ["operator", "engineer", "admin"]
        except Exception as e:
            logger.error(f"操作员检查异常: {e}")
            return False
    
    async def can_modify_config(self, user_id: str) -> bool:
        """检查用户是否可以修改配置"""
        return await self.has_permission(user_id, "config", "modify")
    
    async def can_execute_test(self, user_id: str) -> bool:
        """检查用户是否可以执行测试"""
        return await self.has_permission(user_id, "test", "execute")
    
    async def can_manage_users(self, user_id: str) -> bool:
        """检查用户是否可以管理用户"""
        return await self.has_permission(user_id, "user", "manage")
    
    async def can_view_audit_logs(self, user_id: str) -> bool:
        """检查用户是否可以查看审计日志"""
        return await self.has_permission(user_id, "audit", "view")
    
    async def can_modify_test_sequence(self, user_id: str) -> bool:
        """检查用户是否可以修改测试序列"""
        return await self.has_permission(user_id, "test", "modify")
    
    async def get_role_hierarchy(self) -> Dict[str, List[str]]:
        """获取角色层次结构"""
        return {
            "admin": ["engineer", "operator"],
            "engineer": ["operator"],
            "operator": []
        }
    
    async def get_effective_permissions(self, user_id: str) -> List[str]:
        """获取用户有效权限（包括继承的权限）"""
        try:
            role = await self.get_user_role(user_id)
            if not role:
                return []
            
            # 获取角色层次结构
            hierarchy = await self.get_role_hierarchy()
            
            # 收集所有权限
            all_permissions = set(role.permissions)
            
            # 添加继承的权限
            def add_inherited_permissions(role_name: str):
                if role_name in hierarchy:
                    for inherited_role in hierarchy[role_name]:
                        inherited_role_obj = self.roles.get(inherited_role)
                        if inherited_role_obj:
                            all_permissions.update(inherited_role_obj.permissions)
                            add_inherited_permissions(inherited_role)
            
            add_inherited_permissions(role.name)
            
            return list(all_permissions)
            
        except Exception as e:
            logger.error(f"获取有效权限异常: {e}")
            return []
