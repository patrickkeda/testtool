"""
认证服务实现
"""

import asyncio
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any
import json
import os

from .interfaces import IAuthService
from .models import User, UserRole, AuthResult
from .encryption_service import EncryptionService

logger = logging.getLogger(__name__)


class AuthService(IAuthService):
    """认证服务实现"""
    
    def __init__(self, encryption_service: EncryptionService = None):
        self.encryption_service = encryption_service or EncryptionService()
        self.users: Dict[str, User] = {}
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.session_timeout = 30 * 60  # 30分钟
        self.max_failed_attempts = 5
        self.lockout_duration = 30 * 60  # 30分钟
        
        # 初始化默认用户
        self._initialize_default_users()
    
    def _initialize_default_users(self):
        """初始化默认用户"""
        # 创建默认管理员用户
        admin_user = User(
            id="admin",
            username="admin",
            email="admin@testtool.com",
            role=UserRole.ADMIN,
            password_hash="",  # 将在首次登录时设置
            is_active=True
        )
        self.users["admin"] = admin_user
        
        # 创建默认操作员用户
        operator_user = User(
            id="operator",
            username="operator", 
            email="operator@testtool.com",
            role=UserRole.OPERATOR,
            password_hash="",  # 将在首次登录时设置
            is_active=True
        )
        self.users["operator"] = operator_user
        
        # 创建默认工程师用户
        engineer_user = User(
            id="engineer",
            username="engineer",
            email="engineer@testtool.com", 
            role=UserRole.ENGINEER,
            password_hash="",  # 将在首次登录时设置
            is_active=True
        )
        self.users["engineer"] = engineer_user
        
        logger.info("已初始化默认用户")
    
    async def login(self, username: str, password: str, ip_address: str = "", user_agent: str = "") -> AuthResult:
        """用户登录"""
        try:
            # 查找用户
            user = None
            for u in self.users.values():
                if u.username == username:
                    user = u
                    break
            
            if not user:
                logger.warning(f"登录失败: 用户不存在 - {username}")
                return AuthResult(
                    success=False,
                    message="用户名或密码错误"
                )
            
            # 检查用户状态
            if not user.can_login():
                if user.is_locked():
                    logger.warning(f"登录失败: 用户被锁定 - {username}")
                    return AuthResult(
                        success=False,
                        message="用户账户已被锁定，请稍后再试"
                    )
                else:
                    logger.warning(f"登录失败: 用户未激活 - {username}")
                    return AuthResult(
                        success=False,
                        message="用户账户未激活"
                    )
            
            # 验证密码
            if not user.password_hash:
                # 首次登录，设置密码
                if password == "admin123":  # 默认密码
                    user.password_hash = await self.encryption_service.hash_password(password)
                    user.failed_login_attempts = 0
                    logger.info(f"首次登录成功，密码已设置 - {username}")
                else:
                    logger.warning(f"登录失败: 首次登录密码错误 - {username}")
                    return AuthResult(
                        success=False,
                        message="首次登录请使用默认密码: admin123"
                    )
            else:
                # 验证密码
                if not await self.encryption_service.verify_password(password, user.password_hash):
                    # 密码错误，增加失败次数
                    user.failed_login_attempts += 1
                    if user.failed_login_attempts >= self.max_failed_attempts:
                        user.locked_until = datetime.now() + timedelta(seconds=self.lockout_duration)
                        logger.warning(f"用户被锁定 - {username}")
                        return AuthResult(
                            success=False,
                            message="密码错误次数过多，账户已被锁定30分钟"
                        )
                    else:
                        logger.warning(f"登录失败: 密码错误 - {username}, 失败次数: {user.failed_login_attempts}")
                        return AuthResult(
                            success=False,
                            message=f"密码错误，还有{self.max_failed_attempts - user.failed_login_attempts}次机会"
                        )
                else:
                    # 密码正确，重置失败次数
                    user.failed_login_attempts = 0
                    user.locked_until = None
            
            # 更新最后登录时间
            user.last_login = datetime.now()
            
            # 创建会话
            session_id = self._create_session(user.id, ip_address, user_agent)
            
            logger.info(f"用户登录成功 - {username}")
            return AuthResult(
                success=True,
                user=user,
                session_id=session_id,
                message="登录成功",
                expires_at=datetime.now() + timedelta(seconds=self.session_timeout)
            )
            
        except Exception as e:
            logger.error(f"登录异常: {e}")
            return AuthResult(
                success=False,
                message="登录过程中发生错误"
            )
    
    async def logout(self, session_id: str) -> bool:
        """用户登出"""
        try:
            if session_id in self.sessions:
                user_id = self.sessions[session_id].get("user_id")
                del self.sessions[session_id]
                logger.info(f"用户登出成功 - session_id: {session_id}, user_id: {user_id}")
                return True
            else:
                logger.warning(f"登出失败: 会话不存在 - {session_id}")
                return False
        except Exception as e:
            logger.error(f"登出异常: {e}")
            return False
    
    async def validate_session(self, session_id: str) -> bool:
        """验证会话"""
        try:
            if session_id not in self.sessions:
                return False
            
            session_data = self.sessions[session_id]
            expires_at = session_data.get("expires_at")
            
            if expires_at and datetime.now() > expires_at:
                # 会话过期，删除会话
                del self.sessions[session_id]
                logger.info(f"会话过期 - {session_id}")
                return False
            
            # 检查用户是否仍然存在且活跃
            user_id = session_data.get("user_id")
            if user_id not in self.users:
                del self.sessions[session_id]
                return False
            
            user = self.users[user_id]
            if not user.is_active:
                del self.sessions[session_id]
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"会话验证异常: {e}")
            return False
    
    async def get_user_by_session(self, session_id: str) -> Optional[User]:
        """通过会话ID获取用户"""
        try:
            if not await self.validate_session(session_id):
                return None
            
            session_data = self.sessions[session_id]
            user_id = session_data.get("user_id")
            return self.users.get(user_id)
            
        except Exception as e:
            logger.error(f"获取用户异常: {e}")
            return None
    
    async def change_password(self, user_id: str, old_password: str, new_password: str) -> bool:
        """修改密码"""
        try:
            if user_id not in self.users:
                logger.warning(f"修改密码失败: 用户不存在 - {user_id}")
                return False
            
            user = self.users[user_id]
            
            # 验证旧密码
            if not await self.encryption_service.verify_password(old_password, user.password_hash):
                logger.warning(f"修改密码失败: 旧密码错误 - {user_id}")
                return False
            
            # 验证新密码
            if len(new_password) < 8:
                logger.warning(f"修改密码失败: 新密码长度不足 - {user_id}")
                return False
            
            # 设置新密码
            user.password_hash = await self.encryption_service.hash_password(new_password)
            logger.info(f"密码修改成功 - {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"修改密码异常: {e}")
            return False
    
    async def create_user(self, username: str, email: str, password: str, role: str) -> Optional[User]:
        """创建用户"""
        try:
            # 检查用户名是否已存在
            for user in self.users.values():
                if user.username == username:
                    logger.warning(f"创建用户失败: 用户名已存在 - {username}")
                    return None
            
            # 验证角色
            try:
                user_role = UserRole(role)
            except ValueError:
                logger.warning(f"创建用户失败: 无效角色 - {role}")
                return None
            
            # 验证密码
            if len(password) < 8:
                logger.warning(f"创建用户失败: 密码长度不足 - {username}")
                return None
            
            # 创建用户
            user_id = str(uuid.uuid4())
            user = User(
                id=user_id,
                username=username,
                email=email,
                role=user_role,
                password_hash=await self.encryption_service.hash_password(password),
                is_active=True
            )
            
            self.users[user_id] = user
            logger.info(f"用户创建成功 - {username}")
            return user
            
        except Exception as e:
            logger.error(f"创建用户异常: {e}")
            return None
    
    def _create_session(self, user_id: str, ip_address: str, user_agent: str) -> str:
        """创建会话"""
        session_id = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(seconds=self.session_timeout)
        
        self.sessions[session_id] = {
            "user_id": user_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "created_at": datetime.now(),
            "expires_at": expires_at
        }
        
        return session_id
    
    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """通过ID获取用户"""
        return self.users.get(user_id)
    
    async def get_all_users(self) -> List[User]:
        """获取所有用户"""
        return list(self.users.values())
    
    async def update_user(self, user_id: str, **kwargs) -> bool:
        """更新用户信息"""
        try:
            if user_id not in self.users:
                return False
            
            user = self.users[user_id]
            for key, value in kwargs.items():
                if hasattr(user, key):
                    setattr(user, key, value)
            
            logger.info(f"用户信息更新成功 - {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"更新用户异常: {e}")
            return False
    
    async def delete_user(self, user_id: str) -> bool:
        """删除用户"""
        try:
            if user_id not in self.users:
                return False
            
            # 不能删除默认用户
            if user_id in ["admin", "operator", "engineer"]:
                logger.warning(f"删除用户失败: 不能删除默认用户 - {user_id}")
                return False
            
            del self.users[user_id]
            logger.info(f"用户删除成功 - {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"删除用户异常: {e}")
            return False
    
    async def cleanup_expired_sessions(self):
        """清理过期会话"""
        try:
            current_time = datetime.now()
            expired_sessions = []
            
            for session_id, session_data in self.sessions.items():
                expires_at = session_data.get("expires_at")
                if expires_at and current_time > expires_at:
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                del self.sessions[session_id]
            
            if expired_sessions:
                logger.info(f"清理过期会话: {len(expired_sessions)}个")
                
        except Exception as e:
            logger.error(f"清理会话异常: {e}")
    
    async def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话信息"""
        return self.sessions.get(session_id)
    
    async def get_active_sessions_count(self) -> int:
        """获取活跃会话数量"""
        return len(self.sessions)
