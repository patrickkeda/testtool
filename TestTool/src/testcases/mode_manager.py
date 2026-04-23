"""
模式管理器 - 管理测试模式和权限控制
"""

from enum import Enum
from typing import List
import logging

logger = logging.getLogger(__name__)


class TestMode(Enum):
    """测试模式枚举"""
    PRODUCTION = "production"  # 产线测试模式
    DEBUG = "debug"           # 工程师调试模式


class ModeManager:
    """模式管理器"""
    
    def __init__(self):
        self.current_mode = TestMode.PRODUCTION
        self.is_engineer = False
        
    def set_mode(self, mode: TestMode, is_engineer: bool = False):
        """设置测试模式和工程师权限
        
        Parameters
        ----------
        mode : TestMode
            测试模式
        is_engineer : bool
            是否为工程师权限
        """
        self.current_mode = mode
        self.is_engineer = is_engineer
        logger.info(f"测试模式设置为: {mode.value}, 工程师权限: {is_engineer}")
        
    def can_pause(self) -> bool:
        """是否可以暂停"""
        return True  # 两种模式都支持暂停
        
    def can_skip_step(self) -> bool:
        """是否可以跳过步骤"""
        return self.current_mode == TestMode.DEBUG and self.is_engineer
        
    def can_retry_step(self) -> bool:
        """是否可以重试步骤"""
        return self.current_mode == TestMode.DEBUG and self.is_engineer
        
    def can_manual_control(self) -> bool:
        """是否可以手动控制"""
        return self.current_mode == TestMode.DEBUG and self.is_engineer
        
    def get_available_actions(self) -> List[str]:
        """获取可用操作列表"""
        actions = ["start", "pause", "stop"]
        if self.can_skip_step():
            actions.append("skip_step")
        if self.can_retry_step():
            actions.append("retry_step")
        return actions
        
    def is_production_mode(self) -> bool:
        """是否为生产模式"""
        return self.current_mode == TestMode.PRODUCTION
        
    def is_debug_mode(self) -> bool:
        """是否为调试模式"""
        return self.current_mode == TestMode.DEBUG
        
    def get_mode_description(self) -> str:
        """获取模式描述"""
        if self.is_debug_mode():
            return "工程师调试模式"
        else:
            return "产线测试模式"
            
    def check_permission(self, action: str) -> bool:
        """检查操作权限
        
        Parameters
        ----------
        action : str
            操作名称
            
        Returns
        -------
        bool
            是否有权限执行该操作
        """
        if action == "pause":
            return self.can_pause()
        elif action == "skip_step":
            return self.can_skip_step()
        elif action == "retry_step":
            return self.can_retry_step()
        elif action == "manual_control":
            return self.can_manual_control()
        else:
            return True  # 其他操作默认允许
