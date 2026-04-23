"""
UUT自定义命令动作库

提供UUT自定义命令相关的业务动作，可被测试用例调用。
"""
from typing import Optional
from ...context import Context


def send_custom_command(ctx: Context, command: str, timeout_ms: int = 3000) -> Optional[str]:
    """
    发送自定义命令并获取响应
    
    Args:
        ctx: 测试上下文
        command: 自定义命令
        timeout_ms: 超时时间(毫秒)
        
    Returns:
        str: 响应内容，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        ctx.uut.send(command.encode())
        ctx.log_info(f"发送自定义命令: {command}")
        
        # 等待响应
        ctx.sleep_ms(100)
        
        # 读取响应
        response = ctx.uut.receive()
        ctx.log_info(f"自定义命令响应: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"自定义命令发送失败: {e}")
        return None


def send_at_command(ctx: Context, command: str, timeout_ms: int = 3000) -> Optional[str]:
    """
    发送AT命令并获取响应
    
    Args:
        ctx: 测试上下文
        command: AT命令
        timeout_ms: 超时时间(毫秒)
        
    Returns:
        str: 响应内容，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        ctx.uut.send(command.encode())
        ctx.log_info(f"发送AT命令: {command}")
        
        # 等待响应
        ctx.sleep_ms(100)
        
        # 读取响应
        response = ctx.uut.receive()
        ctx.log_info(f"AT命令响应: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"AT命令发送失败: {e}")
        return None


def send_binary_command(ctx: Context, data: bytes, timeout_ms: int = 3000) -> Optional[bytes]:
    """
    发送二进制命令并获取响应
    
    Args:
        ctx: 测试上下文
        data: 二进制数据
        timeout_ms: 超时时间(毫秒)
        
    Returns:
        bytes: 响应数据，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        ctx.uut.send(data)
        ctx.log_info(f"发送二进制命令: {data.hex()}")
        
        # 等待响应
        ctx.sleep_ms(100)
        
        # 读取响应
        response = ctx.uut.receive()
        ctx.log_info(f"二进制命令响应: {response.hex() if isinstance(response, bytes) else response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"二进制命令发送失败: {e}")
        return None


def query_response(ctx: Context, command: str, timeout_ms: int = 3000) -> Optional[str]:
    """
    查询命令并获取响应
    
    Args:
        ctx: 测试上下文
        command: 查询命令
        timeout_ms: 超时时间(毫秒)
        
    Returns:
        str: 响应内容，失败时返回None
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return None
            
        ctx.uut.send(command.encode())
        ctx.log_info(f"发送查询命令: {command}")
        
        # 等待响应
        ctx.sleep_ms(100)
        
        # 读取响应
        response = ctx.uut.receive()
        ctx.log_info(f"查询命令响应: {response}")
        
        return response
        
    except Exception as e:
        ctx.log_error(f"查询命令发送失败: {e}")
        return None


def send_and_wait_response(ctx: Context, command: str, expected_response: str, timeout_ms: int = 3000) -> bool:
    """
    发送命令并等待特定响应
    
    Args:
        ctx: 测试上下文
        command: 发送的命令
        expected_response: 期望的响应
        timeout_ms: 超时时间(毫秒)
        
    Returns:
        bool: 是否收到期望响应
    """
    try:
        if not ctx.uut:
            ctx.log_error("UUT通讯不可用")
            return False
            
        ctx.uut.send(command.encode())
        ctx.log_info(f"发送命令: {command}")
        
        # 等待响应
        ctx.sleep_ms(100)
        
        # 读取响应
        response = ctx.uut.receive()
        ctx.log_info(f"命令响应: {response}")
        
        # 检查是否匹配期望响应
        if expected_response in response:
            ctx.log_info(f"收到期望响应: {expected_response}")
            return True
        else:
            ctx.log_warning(f"响应不匹配期望: 期望 '{expected_response}', 实际 '{response}'")
            return False
        
    except Exception as e:
        ctx.log_error(f"命令发送失败: {e}")
        return False
