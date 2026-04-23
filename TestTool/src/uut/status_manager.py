"""
状态管理器
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from .interfaces import IStatusManager
from .models import UUTStatus, UUTCommand, UUTResponse, UUTError, UUTConnectionStatus, UUTTestStatus

logger = logging.getLogger(__name__)


class StatusManager(IStatusManager):
    """状态管理器实现"""
    
    def __init__(self):
        self.status = UUTStatus()
        self.status_history: List[UUTStatus] = []
        self.max_history = 1000  # 最大历史记录数
        self.start_time = datetime.now()
        
    async def update_connection_status(self, status: str) -> None:
        """更新连接状态
        
        Parameters
        ----------
        status : str
            连接状态
        """
        try:
            # 转换状态字符串为枚举
            if status == "disconnected":
                new_status = UUTConnectionStatus.DISCONNECTED
            elif status == "connecting":
                new_status = UUTConnectionStatus.CONNECTING
            elif status == "connected":
                new_status = UUTConnectionStatus.CONNECTED
            elif status == "error":
                new_status = UUTConnectionStatus.ERROR
            else:
                logger.warning(f"未知的连接状态: {status}")
                return
            
            # 更新状态
            old_status = self.status.connection_status
            self.status.connection_status = new_status
            self.status.update_activity()
            
            # 记录状态变化
            if old_status != new_status:
                logger.info(f"连接状态变化: {old_status.value} -> {new_status.value}")
                await self._record_status_change()
            
        except Exception as e:
            logger.error(f"更新连接状态失败: {e}")
    
    async def update_test_status(self, status: str) -> None:
        """更新测试状态
        
        Parameters
        ----------
        status : str
            测试状态
        """
        try:
            # 转换状态字符串为枚举
            if status == "idle":
                new_status = UUTTestStatus.IDLE
            elif status == "testing":
                new_status = UUTTestStatus.TESTING
            elif status == "paused":
                new_status = UUTTestStatus.PAUSED
            elif status == "completed":
                new_status = UUTTestStatus.COMPLETED
            elif status == "error":
                new_status = UUTTestStatus.ERROR
            else:
                logger.warning(f"未知的测试状态: {status}")
                return
            
            # 更新状态
            old_status = self.status.test_status
            self.status.test_status = new_status
            self.status.update_activity()
            
            # 记录状态变化
            if old_status != new_status:
                logger.info(f"测试状态变化: {old_status.value} -> {new_status.value}")
                await self._record_status_change()
            
        except Exception as e:
            logger.error(f"更新测试状态失败: {e}")
    
    async def record_command(self, command: UUTCommand) -> None:
        """记录命令执行
        
        Parameters
        ----------
        command : UUTCommand
            执行的命令
        """
        try:
            self.status.last_command = command.name
            self.status.update_activity()
            
            logger.debug(f"记录命令执行: {command.name}")
            
        except Exception as e:
            logger.error(f"记录命令失败: {e}")
    
    async def record_response(self, response: UUTResponse) -> None:
        """记录响应
        
        Parameters
        ----------
        response : UUTResponse
            UUT响应
        """
        try:
            self.status.last_response = response
            
            if response.success:
                self.status.increment_success()
                logger.debug(f"记录成功响应: {response.command_name}")
            else:
                if response.error:
                    self.status.increment_error(response.error)
                    logger.warning(f"记录错误响应: {response.command_name} - {response.error}")
            
        except Exception as e:
            logger.error(f"记录响应失败: {e}")
    
    async def record_error(self, error: str) -> None:
        """记录错误
        
        Parameters
        ----------
        error : str
            错误信息
        """
        try:
            uut_error = UUTError(
                type=UUTErrorType.UNKNOWN_ERROR,
                message=error,
                timestamp=datetime.now()
            )
            
            self.status.increment_error(uut_error)
            logger.error(f"记录错误: {error}")
            
        except Exception as e:
            logger.error(f"记录错误失败: {e}")
    
    async def get_status(self) -> UUTStatus:
        """获取当前状态
        
        Returns
        -------
        UUTStatus
            当前状态
        """
        # 更新运行时间
        self.status.uptime = (datetime.now() - self.start_time).total_seconds()
        
        return self.status
    
    async def get_status_history(self, limit: Optional[int] = None) -> List[UUTStatus]:
        """获取状态历史
        
        Parameters
        ----------
        limit : Optional[int]
            限制数量
            
        Returns
        -------
        List[UUTStatus]
            状态历史列表
        """
        if limit is None:
            return self.status_history.copy()
        else:
            return self.status_history[-limit:]
    
    async def clear_history(self) -> None:
        """清空状态历史"""
        self.status_history.clear()
        logger.info("状态历史已清空")
    
    async def get_health_status(self) -> Dict:
        """获取健康状态
        
        Returns
        -------
        Dict
            健康状态信息
        """
        current_status = await self.get_status()
        
        return {
            "is_healthy": current_status.is_healthy(),
            "connection_status": current_status.connection_status.value,
            "test_status": current_status.test_status.value,
            "success_rate": current_status.get_success_rate(),
            "error_count": current_status.error_count,
            "success_count": current_status.success_count,
            "uptime": current_status.uptime,
            "last_activity": current_status.last_activity.isoformat() if current_status.last_activity else None,
            "last_error": str(current_status.last_error) if current_status.last_error else None
        }
    
    async def get_statistics(self) -> Dict:
        """获取统计信息
        
        Returns
        -------
        Dict
            统计信息
        """
        current_status = await self.get_status()
        
        # 计算状态持续时间
        status_durations = await self._calculate_status_durations()
        
        return {
            "current_status": {
                "connection": current_status.connection_status.value,
                "test": current_status.test_status.value
            },
            "counts": {
                "success": current_status.success_count,
                "error": current_status.error_count,
                "total": current_status.success_count + current_status.error_count
            },
            "rates": {
                "success_rate": current_status.get_success_rate(),
                "error_rate": 1 - current_status.get_success_rate()
            },
            "durations": status_durations,
            "uptime": current_status.uptime,
            "last_activity": current_status.last_activity.isoformat() if current_status.last_activity else None
        }
    
    async def reset_statistics(self) -> None:
        """重置统计信息"""
        self.status.error_count = 0
        self.status.success_count = 0
        self.status.last_error = None
        self.start_time = datetime.now()
        self.status.uptime = 0.0
        
        logger.info("统计信息已重置")
    
    async def _record_status_change(self) -> None:
        """记录状态变化"""
        # 创建状态快照
        status_snapshot = UUTStatus(
            connection_status=self.status.connection_status,
            test_status=self.status.test_status,
            last_command=self.status.last_command,
            last_response=self.status.last_response,
            error_count=self.status.error_count,
            success_count=self.status.success_count,
            last_error=self.status.last_error,
            last_activity=self.status.last_activity,
            uptime=self.status.uptime,
            metadata=self.status.metadata.copy()
        )
        
        self.status_history.append(status_snapshot)
        
        # 限制历史记录数量
        if len(self.status_history) > self.max_history:
            self.status_history = self.status_history[-self.max_history:]
    
    async def _calculate_status_durations(self) -> Dict[str, float]:
        """计算状态持续时间"""
        durations = {}
        
        if not self.status_history:
            return durations
        
        # 按状态分组计算持续时间
        current_status = None
        start_time = None
        
        for status in self.status_history:
            status_key = f"{status.connection_status.value}_{status.test_status.value}"
            
            if current_status != status_key:
                if current_status and start_time:
                    end_time = status.last_activity or datetime.now()
                    duration = (end_time - start_time).total_seconds()
                    durations[current_status] = durations.get(current_status, 0) + duration
                
                current_status = status_key
                start_time = status.last_activity or datetime.now()
        
        # 处理最后一个状态
        if current_status and start_time:
            duration = (datetime.now() - start_time).total_seconds()
            durations[current_status] = durations.get(current_status, 0) + duration
        
        return durations
    
    async def get_error_summary(self) -> Dict:
        """获取错误摘要
        
        Returns
        -------
        Dict
            错误摘要信息
        """
        current_status = await self.get_status()
        
        return {
            "total_errors": current_status.error_count,
            "last_error": {
                "type": current_status.last_error.type.value if current_status.last_error else None,
                "message": current_status.last_error.message if current_status.last_error else None,
                "timestamp": current_status.last_error.timestamp.isoformat() if current_status.last_error else None
            },
            "error_rate": 1 - current_status.get_success_rate(),
            "is_healthy": current_status.is_healthy()
        }
    
    async def get_performance_metrics(self) -> Dict:
        """获取性能指标
        
        Returns
        -------
        Dict
            性能指标
        """
        current_status = await self.get_status()
        
        # 计算平均响应时间
        avg_response_time = 0.0
        if current_status.last_response:
            avg_response_time = current_status.last_response.response_time
        
        return {
            "uptime": current_status.uptime,
            "success_rate": current_status.get_success_rate(),
            "avg_response_time": avg_response_time,
            "total_operations": current_status.success_count + current_status.error_count,
            "operations_per_second": (current_status.success_count + current_status.error_count) / max(current_status.uptime, 1),
            "last_activity": current_status.last_activity.isoformat() if current_status.last_activity else None
        }
