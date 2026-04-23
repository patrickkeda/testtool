"""
加密服务实现
"""

import asyncio
import logging
import secrets
import base64
import os
from typing import Optional

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False

from .interfaces import IEncryptionService

logger = logging.getLogger(__name__)


class EncryptionService(IEncryptionService):
    """加密服务实现"""
    
    def __init__(self, master_key: str = None):
        self.master_key = master_key
        self._fernet = None
        
        # 检查依赖
        if not BCRYPT_AVAILABLE:
            logger.warning("bcrypt不可用，密码哈希功能受限")
        if not CRYPTOGRAPHY_AVAILABLE:
            logger.warning("cryptography不可用，数据加密功能受限")
    
    async def hash_password(self, password: str) -> str:
        """密码哈希"""
        try:
            if BCRYPT_AVAILABLE:
                # 使用bcrypt进行密码哈希
                salt = bcrypt.gensalt()
                hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
                return hashed.decode('utf-8')
            else:
                # 使用Python内置hashlib作为备选
                import hashlib
                salt = secrets.token_hex(16)
                hashed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
                return f"pbkdf2_sha256${salt}${base64.b64encode(hashed).decode('utf-8')}"
                
        except Exception as e:
            logger.error(f"密码哈希异常: {e}")
            raise
    
    async def verify_password(self, password: str, hashed_password: str) -> bool:
        """验证密码"""
        try:
            if BCRYPT_AVAILABLE and not hashed_password.startswith("pbkdf2_sha256$"):
                # 使用bcrypt验证
                return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
            else:
                # 使用PBKDF2验证
                if hashed_password.startswith("pbkdf2_sha256$"):
                    parts = hashed_password.split('$')
                    if len(parts) == 3:
                        salt = parts[1]
                        stored_hash = parts[2]
                        import hashlib
                        hashed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
                        return base64.b64encode(hashed).decode('utf-8') == stored_hash
                return False
                
        except Exception as e:
            logger.error(f"密码验证异常: {e}")
            return False
    
    async def encrypt_data(self, data: str, key: str = None) -> str:
        """加密数据"""
        try:
            if not CRYPTOGRAPHY_AVAILABLE:
                logger.warning("cryptography不可用，使用简单编码")
                return base64.b64encode(data.encode('utf-8')).decode('utf-8')
            
            encryption_key = key or await self.get_or_create_master_key()
            fernet = Fernet(encryption_key.encode('utf-8'))
            encrypted_data = fernet.encrypt(data.encode('utf-8'))
            return base64.b64encode(encrypted_data).decode('utf-8')
            
        except Exception as e:
            logger.error(f"数据加密异常: {e}")
            raise
    
    async def decrypt_data(self, encrypted_data: str, key: str = None) -> str:
        """解密数据"""
        try:
            if not CRYPTOGRAPHY_AVAILABLE:
                logger.warning("cryptography不可用，使用简单解码")
                return base64.b64decode(encrypted_data.encode('utf-8')).decode('utf-8')
            
            encryption_key = key or await self.get_or_create_master_key()
            fernet = Fernet(encryption_key.encode('utf-8'))
            encrypted_bytes = base64.b64decode(encrypted_data.encode('utf-8'))
            decrypted_data = fernet.decrypt(encrypted_bytes)
            return decrypted_data.decode('utf-8')
            
        except Exception as e:
            logger.error(f"数据解密异常: {e}")
            raise
    
    async def generate_key(self) -> str:
        """生成加密密钥"""
        try:
            if CRYPTOGRAPHY_AVAILABLE:
                return Fernet.generate_key().decode('utf-8')
            else:
                # 生成32字节的随机密钥
                return base64.b64encode(secrets.token_bytes(32)).decode('utf-8')
                
        except Exception as e:
            logger.error(f"密钥生成异常: {e}")
            raise
    
    async def get_or_create_master_key(self) -> str:
        """获取或创建主密钥"""
        try:
            if self.master_key:
                return self.master_key
            
            # 尝试从环境变量获取
            master_key = os.getenv('TESTTOOL_MASTER_KEY')
            if master_key:
                self.master_key = master_key
                return master_key
            
            # 尝试从文件读取
            key_file = 'master.key'
            if os.path.exists(key_file):
                with open(key_file, 'r') as f:
                    self.master_key = f.read().strip()
                return self.master_key
            
            # 生成新密钥
            self.master_key = await self.generate_key()
            
            # 保存到文件
            try:
                with open(key_file, 'w') as f:
                    f.write(self.master_key)
                os.chmod(key_file, 0o600)  # 设置文件权限
                logger.info("主密钥已生成并保存")
            except Exception as e:
                logger.warning(f"保存主密钥失败: {e}")
            
            return self.master_key
            
        except Exception as e:
            logger.error(f"获取主密钥异常: {e}")
            raise
    
    async def derive_key_from_password(self, password: str, salt: bytes = None) -> str:
        """从密码派生密钥"""
        try:
            if not CRYPTOGRAPHY_AVAILABLE:
                logger.warning("cryptography不可用，使用简单哈希")
                import hashlib
                if salt is None:
                    salt = secrets.token_bytes(16)
                key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
                return base64.b64encode(key).decode('utf-8')
            
            if salt is None:
                salt = secrets.token_bytes(16)
            
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode('utf-8')))
            return key.decode('utf-8')
            
        except Exception as e:
            logger.error(f"密钥派生异常: {e}")
            raise
    
    async def hash_data(self, data: str, algorithm: str = 'sha256') -> str:
        """数据哈希"""
        try:
            import hashlib
            
            if algorithm == 'sha256':
                return hashlib.sha256(data.encode('utf-8')).hexdigest()
            elif algorithm == 'sha1':
                return hashlib.sha1(data.encode('utf-8')).hexdigest()
            elif algorithm == 'md5':
                return hashlib.md5(data.encode('utf-8')).hexdigest()
            else:
                raise ValueError(f"不支持的哈希算法: {algorithm}")
                
        except Exception as e:
            logger.error(f"数据哈希异常: {e}")
            raise
    
    async def generate_token(self, length: int = 32) -> str:
        """生成随机令牌"""
        try:
            return secrets.token_urlsafe(length)
        except Exception as e:
            logger.error(f"令牌生成异常: {e}")
            raise
    
    async def verify_token(self, token: str, expected_length: int = 32) -> bool:
        """验证令牌格式"""
        try:
            if not token:
                return False
            
            # 检查长度（base64编码后的长度）
            expected_encoded_length = (expected_length * 4 + 2) // 3
            if len(token) != expected_encoded_length:
                return False
            
            # 尝试解码
            try:
                secrets.token_urlsafe(0)  # 验证token格式
                return True
            except:
                return False
                
        except Exception as e:
            logger.error(f"令牌验证异常: {e}")
            return False
