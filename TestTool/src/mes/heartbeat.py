"""
MES心跳检测管理
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from .interfaces import IMESClient, IHeartbeatManager
from .models import HeartbeatStatus

logger = logging.getLogger(__name__)


class HeartbeatManager(IHeartbeatManager):
    """MES心跳检测管理器"""
    
    def __init__(self):
        self._client: Optional[IMESClient] = None
        self._task: Optional[asyncio.Task] = None
        self._interval_ms: int = 10000  # 默认10秒
        self._is_running: bool = False
        self._status = HeartbeatStatus(is_alive=False)
        self._consecutive_failures: int = 0
        self._max_failures: int = 3  # 最大连续失败次数
    
    async def start(self, client: IMESClient, interval_ms: int) -> bool:
        """启动心跳
        
        Parameters
        ----------
        client : IMESClient
            MES客户端
        interval_ms : int
            心跳间隔（毫秒）
            
        Returns
        -------
        bool
            启动是否成功
        """
        try:
            if self._is_running:
                logger.warning("心跳已在运行中")
                return False
            
            if not client:
                logger.error("MES客户端不能为空")
                return False
            
            self._client = client
            self._interval_ms = interval_ms
            self._is_running = True
            self._consecutive_failures = 0
            
            # 启动心跳任务
            self._task = asyncio.create_task(self._heartbeat_loop())
            
            logger.info(f"启动MES心跳检测: 间隔{interval_ms}ms")
            return True
            
        except Exception as e:
            logger.error(f"启动心跳失败: {e}")
            return False
    
    async def stop(self) -> bool:
        """停止心跳
        
        Returns
        -------
        bool
            停止是否成功
        """
        try:
            if not self._is_running:
                logger.warning("心跳未在运行")
                return False
            
            self._is_running = False
            
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            
            self._task = None
            self._status = HeartbeatStatus(is_alive=False)
            
            logger.info("停止MES心跳检测")
            return True
            
        except Exception as e:
            logger.error(f"停止心跳失败: {e}")
            return False
    
    async def get_status(self) -> HeartbeatStatus:
        """获取心跳状态
        
        Returns
        -------
        HeartbeatStatus
            心跳状态
        """
        return self._status
    
    def is_running(self) -> bool:
        """检查是否正在运行
        
        Returns
        -------
        bool
            是否正在运行
        """
        return self._is_running
    
    async def _heartbeat_loop(self):
        """心跳循环"""
        logger.info("MES心跳检测循环开始")
        
        while self._is_running:
            try:
                # 执行心跳
                success = await self._perform_heartbeat()
                
                if success:
                    self._consecutive_failures = 0
                    self._status = HeartbeatStatus(
                        is_alive=True,
                        last_heartbeat=datetime.now(),
                        consecutive_failures=0
                    )
                    logger.debug("MES心跳成功")
                else:
                    self._consecutive_failures += 1
                    self._status = HeartbeatStatus(
                        is_alive=False,
                        last_heartbeat=datetime.now(),
                        consecutive_failures=self._consecutive_failures,
                        error_message=f"连续失败{self._consecutive_failures}次"
                    )
                    logger.warning(f"MES心跳失败: 连续失败{self._consecutive_failures}次")
                    
                    # 检查是否超过最大失败次数
                    if self._consecutive_failures >= self._max_failures:
                        logger.error(f"MES心跳连续失败{self._consecutive_failures}次，停止心跳检测")
                        await self.stop()
                        break
                
                # 等待下次心跳
                await asyncio.sleep(self._interval_ms / 1000.0)
                
            except asyncio.CancelledError:
                logger.info("MES心跳检测被取消")
                break
            except Exception as e:
                logger.error(f"MES心跳检测异常: {e}")
                self._consecutive_failures += 1
                self._status = HeartbeatStatus(
                    is_alive=False,
                    last_heartbeat=datetime.now(),
                    consecutive_failures=self._consecutive_failures,
                    error_message=str(e)
                )
                
                # 等待一段时间后重试
                await asyncio.sleep(min(self._interval_ms / 1000.0, 5.0))
        
        logger.info("MES心跳检测循环结束")
    
    async def _perform_heartbeat(self) -> bool:
        """执行心跳
        
        Returns
        -------
        bool
            心跳是否成功
        """
        try:
            if not self._client:
                return False
            
            start_time = datetime.now()
            success = await self._client.heartbeat()
            end_time = datetime.now()
            
            # 计算响应时间
            response_time_ms = int((end_time - start_time).total_seconds() * 1000)
            
            if success:
                self._status.response_time_ms = response_time_ms
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"执行心跳异常: {e}")
            return False
    
    def set_max_failures(self, max_failures: int):
        """设置最大失败次数
        
        Parameters
        ----------
        max_failures : int
            最大失败次数
        """
        self._max_failures = max_failures
        logger.info(f"设置最大失败次数: {max_failures}")
    
    def get_max_failures(self) -> int:
        """获取最大失败次数
        
        Returns
        -------
        int
            最大失败次数
        """
        return self._max_failures
    
    def get_consecutive_failures(self) -> int:
        """获取连续失败次数
        
        Returns
        -------
        int
            连续失败次数
        """
        return self._consecutive_failures
    
    def reset_failures(self):
        """重置失败计数"""
        self._consecutive_failures = 0
        logger.info("重置失败计数")
    
    def __str__(self) -> str:
        return f"HeartbeatManager(running={self._is_running}, failures={self._consecutive_failures})"


# 全局心跳管理器实例
_heartbeat_manager = None


def get_heartbeat_manager() -> HeartbeatManager:
    """获取全局心跳管理器实例
    
    Returns
    -------
    HeartbeatManager
        全局心跳管理器实例
    """
    global _heartbeat_manager
    if _heartbeat_manager is None:
        _heartbeat_manager = HeartbeatManager()
    return _heartbeat_manager
