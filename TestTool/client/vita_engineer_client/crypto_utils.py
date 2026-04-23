"""
Cryptographic utilities for Engineer Service client.
Based on the cloud_agent encryption implementation.
"""

import hashlib
import hmac
import secrets
import base64
from typing import Tuple, Optional
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend


class CryptoUtils:
    """Cryptographic utilities for secure communication."""
    
    @staticmethod
    def generate_sha256_hash(input_string: str) -> str:
        """Generate SHA256 hash of input string."""
        return hashlib.sha256(input_string.encode('utf-8')).hexdigest()
    
    @staticmethod
    def generate_sha1_hash(input_string: str) -> str:
        """Generate SHA1 hash of input string."""
        return hashlib.sha1(input_string.encode('utf-8')).hexdigest()
    
    @staticmethod
    def generate_device_credentials(x5_soc_id: str, s100_soc_id: str) -> Tuple[str, str]:
        """
        Generate device credentials based on SOC IDs.
        Returns (auth_token, device_id) tuple.
        """
        combined_input = f"{x5_soc_id}-{s100_soc_id}"
        auth_token = CryptoUtils.generate_sha256_hash(combined_input)
        device_id = CryptoUtils.generate_sha1_hash(combined_input)
        return auth_token, device_id
    
    @staticmethod
    def generate_aes_key() -> bytes:
        """Generate a random AES-256 key."""
        return secrets.token_bytes(32)  # 256 bits
    
    @staticmethod
    def generate_iv() -> bytes:
        """Generate a random initialization vector for AES."""
        return secrets.token_bytes(16)  # 128 bits
    
    @staticmethod
    def encrypt_aes_cbc(data: bytes, key: bytes, iv: bytes) -> bytes:
        """Encrypt data using AES-256-CBC."""
        # Pad data to multiple of 16 bytes
        padding_length = 16 - (len(data) % 16)
        padded_data = data + bytes([padding_length] * padding_length)
        
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        return encryptor.update(padded_data) + encryptor.finalize()
    
    @staticmethod
    def decrypt_aes_cbc(encrypted_data: bytes, key: bytes, iv: bytes) -> bytes:
        """Decrypt data using AES-256-CBC."""
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(encrypted_data) + decryptor.finalize()
        
        # Remove padding
        padding_length = padded_data[-1]
        return padded_data[:-padding_length]
    
    @staticmethod
    def generate_rsa_keypair(key_size: int = 2048) -> Tuple[bytes, bytes]:
        """
        Generate RSA key pair.
        Returns (private_key_pem, public_key_pem) tuple.
        """
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
            backend=default_backend()
        )
        
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        return private_pem, public_pem
    
    @staticmethod
    def encrypt_rsa(data: bytes, public_key_pem: bytes) -> bytes:
        """Encrypt data using RSA public key."""
        public_key = serialization.load_pem_public_key(
            public_key_pem, backend=default_backend()
        )
        
        return public_key.encrypt(
            data,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
    
    @staticmethod
    def decrypt_rsa(encrypted_data: bytes, private_key_pem: bytes) -> bytes:
        """Decrypt data using RSA private key."""
        private_key = serialization.load_pem_private_key(
            private_key_pem, password=None, backend=default_backend()
        )
        
        return private_key.decrypt(
            encrypted_data,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
    
    @staticmethod
    def encode_base64(data: bytes) -> str:
        """Encode bytes to base64 string."""
        return base64.b64encode(data).decode('utf-8')
    
    @staticmethod
    def decode_base64(data: str) -> bytes:
        """Decode base64 string to bytes."""
        return base64.b64decode(data.encode('utf-8'))


class SecureSession:
    """Manages a secure communication session."""
    
    def __init__(self, auth_token: str, device_id: str):
        """Initialize secure session with credentials."""
        self.auth_token = auth_token
        self.device_id = device_id
        self.session_key: Optional[bytes] = None
        self.session_iv: Optional[bytes] = None
        self.is_established = False
    
    def establish_session(self, server_public_key_pem: bytes) -> bytes:
        """
        Establish secure session with server.
        Returns encrypted session key for server.
        """
        # Generate session key and IV
        self.session_key = CryptoUtils.generate_aes_key()
        self.session_iv = CryptoUtils.generate_iv()
        
        # Encrypt session key with server's public key
        encrypted_session_key = CryptoUtils.encrypt_rsa(
            self.session_key, server_public_key_pem
        )
        
        self.is_established = True
        return encrypted_session_key
    
    def encrypt_message(self, message: str) -> str:
        """Encrypt message using session key."""
        if not self.is_established or not self.session_key or not self.session_iv:
            raise ValueError("Session not established")
        
        message_bytes = message.encode('utf-8')
        encrypted_data = CryptoUtils.encrypt_aes_cbc(
            message_bytes, self.session_key, self.session_iv
        )
        
        return CryptoUtils.encode_base64(encrypted_data)
    
    def decrypt_message(self, encrypted_message: str) -> str:
        """Decrypt message using session key."""
        if not self.is_established or not self.session_key or not self.session_iv:
            raise ValueError("Session not established")
        
        encrypted_data = CryptoUtils.decode_base64(encrypted_message)
        decrypted_bytes = CryptoUtils.decrypt_aes_cbc(
            encrypted_data, self.session_key, self.session_iv
        )
        
        return decrypted_bytes.decode('utf-8')
    
    def get_auth_token(self) -> str:
        """Get authentication token."""
        return self.auth_token
    
    def get_device_id(self) -> str:
        """Get device ID."""
        return self.device_id
