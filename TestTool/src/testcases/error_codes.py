"""
测试用例错误代码定义

集中管理所有测试用例的错误代码，便于统一维护和使用。
"""

from enum import Enum
from typing import Dict


class ConnectErrorCodes(Enum):
    """Connect测试用例错误代码"""
    
    # 配置错误
    NO_HOST = ("CONN_ERR_NO_HOST", "主机地址未配置")
    NO_PORT = ("CONN_ERR_NO_PORT", "端口未配置")
    INVALID_TIMEOUT = ("CONN_ERR_INVALID_TIMEOUT", "超时时间无效")
    
    # 连接错误
    CONNECT_FAILED = ("CONN_ERR_CONNECT_FAILED", "WebSocket连接失败")
    NOT_OPEN = ("CONN_ERR_NOT_OPEN", "WebSocket连接未建立")
    CONNECTION_TIMEOUT = ("CONN_ERR_CONNECTION_TIMEOUT", "连接超时")
    CONNECTION_REFUSED = ("CONN_ERR_CONNECTION_REFUSED", "连接被拒绝")
    
    # 认证错误
    AUTH_FAILED = ("CONN_ERR_AUTH_FAILED", "认证失败")
    AUTH_TIMEOUT = ("CONN_ERR_AUTH_TIMEOUT", "认证超时")
    
    # 工程模式错误
    ENTER_ENGINEER_MODE_FAILED = ("CONN_ERR_ENTER_ENGINEER_MODE_FAILED", "进入工程模式失败")
    ENTER_ENGINEER_MODE_EXCEPTION = ("CONN_ERR_ENTER_ENGINEER_MODE_EXCEPTION", "进入工程模式异常")
    ENTER_ENGINEER_MODE_TIMEOUT = ("CONN_ERR_ENTER_ENGINEER_MODE_TIMEOUT", "进入工程模式超时")
    
    # 未知错误
    UNKNOWN = ("CONN_ERR_UNKNOWN", "未知错误")
    
    def __init__(self, code: str, description: str):
        self.code = code
        self.description = description
    
    def __str__(self):
        return self.code
    
    @property
    def error_code(self):
        """返回错误代码字符串"""
        return self.code
    
    @property
    def error_message(self):
        """返回错误描述"""
        return self.description


class DisconnectErrorCodes(Enum):
    """Disconnect测试用例错误代码"""
    
    NOT_CONNECTED = ("DISCONN_ERR_NOT_CONNECTED", "未建立连接")
    DISCONNECT_FAILED = ("DISCONN_ERR_DISCONNECT_FAILED", "断开连接失败")
    DISCONNECT_TIMEOUT = ("DISCONN_ERR_DISCONNECT_TIMEOUT", "断开连接超时")
    UNKNOWN = ("DISCONN_ERR_UNKNOWN", "未知错误")
    
    def __init__(self, code: str, description: str):
        self.code = code
        self.description = description
    
    def __str__(self):
        return self.code
    
    @property
    def error_code(self):
        """返回错误代码字符串"""
        return self.code
    
    @property
    def error_message(self):
        """返回错误描述"""
        return self.description


class ScanSNErrorCodes(Enum):
    """ScanSN测试用例错误代码"""
    
    USER_CANCELLED = ("SN_ERR_USER_CANCELLED", "用户取消输入")
    TIMEOUT = ("SN_ERR_TIMEOUT", "输入超时")
    INVALID_FORMAT = ("SN_ERR_INVALID_FORMAT", "SN格式无效")
    EMPTY = ("SN_ERR_EMPTY", "SN为空")
    UNKNOWN = ("SN_ERR_UNKNOWN", "未知错误")
    
    def __init__(self, code: str, description: str):
        self.code = code
        self.description = description
    
    def __str__(self):
        return self.code
    
    @property
    def error_code(self):
        """返回错误代码字符串"""
        return self.code
    
    @property
    def error_message(self):
        """返回错误描述"""
        return self.description


# 错误代码映射表，便于快速查找
ERROR_CODE_REGISTRY: Dict[str, Enum] = {
    # Connect错误代码
    "CONN_ERR_NO_HOST": ConnectErrorCodes.NO_HOST,
    "CONN_ERR_NO_PORT": ConnectErrorCodes.NO_PORT,
    "CONN_ERR_INVALID_TIMEOUT": ConnectErrorCodes.INVALID_TIMEOUT,
    "CONN_ERR_CONNECT_FAILED": ConnectErrorCodes.CONNECT_FAILED,
    "CONN_ERR_NOT_OPEN": ConnectErrorCodes.NOT_OPEN,
    "CONN_ERR_CONNECTION_TIMEOUT": ConnectErrorCodes.CONNECTION_TIMEOUT,
    "CONN_ERR_CONNECTION_REFUSED": ConnectErrorCodes.CONNECTION_REFUSED,
    "CONN_ERR_AUTH_FAILED": ConnectErrorCodes.AUTH_FAILED,
    "CONN_ERR_AUTH_TIMEOUT": ConnectErrorCodes.AUTH_TIMEOUT,
    "CONN_ERR_ENTER_ENGINEER_MODE_FAILED": ConnectErrorCodes.ENTER_ENGINEER_MODE_FAILED,
    "CONN_ERR_ENTER_ENGINEER_MODE_EXCEPTION": ConnectErrorCodes.ENTER_ENGINEER_MODE_EXCEPTION,
    "CONN_ERR_ENTER_ENGINEER_MODE_TIMEOUT": ConnectErrorCodes.ENTER_ENGINEER_MODE_TIMEOUT,
    "CONN_ERR_UNKNOWN": ConnectErrorCodes.UNKNOWN,
    
    # Disconnect错误代码
    "DISCONN_ERR_NOT_CONNECTED": DisconnectErrorCodes.NOT_CONNECTED,
    "DISCONN_ERR_DISCONNECT_FAILED": DisconnectErrorCodes.DISCONNECT_FAILED,
    "DISCONN_ERR_DISCONNECT_TIMEOUT": DisconnectErrorCodes.DISCONNECT_TIMEOUT,
    "DISCONN_ERR_UNKNOWN": DisconnectErrorCodes.UNKNOWN,
    
    # ScanSN错误代码
    "SN_ERR_USER_CANCELLED": ScanSNErrorCodes.USER_CANCELLED,
    "SN_ERR_TIMEOUT": ScanSNErrorCodes.TIMEOUT,
    "SN_ERR_INVALID_FORMAT": ScanSNErrorCodes.INVALID_FORMAT,
    "SN_ERR_EMPTY": ScanSNErrorCodes.EMPTY,
    "SN_ERR_UNKNOWN": ScanSNErrorCodes.UNKNOWN,
}


def get_error_info(error_code: str) -> Dict[str, str]:
    """
    根据错误代码获取错误信息
    
    Args:
        error_code: 错误代码字符串
        
    Returns:
        包含code和description的字典，如果找不到则返回未知错误
    """
    enum_value = ERROR_CODE_REGISTRY.get(error_code)
    if enum_value:
        return {
            "code": enum_value.code,
            "description": enum_value.description
        }
    else:
        return {
            "code": "UNKNOWN_ERR",
            "description": f"未知错误代码: {error_code}"
        }


__all__ = [
    "ConnectErrorCodes",
    "DisconnectErrorCodes",
    "ScanSNErrorCodes",
    "ERROR_CODE_REGISTRY",
    "get_error_info",
]
