"""
工具集成管理器 - 管理序列编辑器和步骤库管理器之间的集成
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QMessageBox

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.testcases.config import TestStepConfig, TestSequenceConfig
from src.app.i18n import I18n


class ToolIntegrationManager(QObject):
    """工具集成管理器"""
    
    # 信号定义
    sig_tool_opened = Signal(str)  # 工具打开信号
    sig_tool_closed = Signal(str)  # 工具关闭信号
    sig_data_exchanged = Signal(str, str, Any)  # 数据交换信号 (from_tool, to_tool, data)
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._i18n = I18n()
        self._open_tools: Dict[str, Any] = {}  # 打开的工具
        self._data_cache: Dict[str, Any] = {}  # 数据缓存
        
    def register_tool(self, tool_name: str, tool_instance: Any) -> None:
        """注册工具实例"""
        try:
            self._open_tools[tool_name] = tool_instance
            self.sig_tool_opened.emit(tool_name)
            
            # 连接工具信号
            if hasattr(tool_instance, 'sig_step_selected'):
                tool_instance.sig_step_selected.connect(
                    lambda step: self._handle_step_selection(tool_name, step)
                )
            
            if hasattr(tool_instance, 'sig_sequence_loaded'):
                tool_instance.sig_sequence_loaded.connect(
                    lambda path: self._handle_sequence_loaded(tool_name, path)
                )
                
        except Exception as e:
            print(f"注册工具失败: {e}")
    
    def unregister_tool(self, tool_name: str) -> None:
        """注销工具实例"""
        try:
            if tool_name in self._open_tools:
                del self._open_tools[tool_name]
                self.sig_tool_closed.emit(tool_name)
        except Exception as e:
            print(f"注销工具失败: {e}")
    
    def _handle_step_selection(self, from_tool: str, step_config: TestStepConfig) -> None:
        """处理步骤选择事件"""
        try:
            # 缓存步骤数据
            self._data_cache['last_selected_step'] = step_config
            
            # 通知其他工具
            for tool_name, tool in self._open_tools.items():
                if tool_name != from_tool and hasattr(tool, 'insert_step_template'):
                    tool.insert_step_template(step_config)
            
            self.sig_data_exchanged.emit(from_tool, "all", step_config)
            
        except Exception as e:
            print(f"处理步骤选择失败: {e}")
    
    def _handle_sequence_loaded(self, from_tool: str, sequence_path: str) -> None:
        """处理序列加载事件"""
        try:
            # 缓存序列路径
            self._data_cache['last_loaded_sequence'] = sequence_path
            
            # 通知其他工具
            for tool_name, tool in self._open_tools.items():
                if tool_name != from_tool and hasattr(tool, 'load_sequence'):
                    tool.load_sequence(sequence_path)
            
            self.sig_data_exchanged.emit(from_tool, "all", sequence_path)
            
        except Exception as e:
            print(f"处理序列加载失败: {e}")
    
    def get_cached_data(self, key: str) -> Any:
        """获取缓存数据"""
        return self._data_cache.get(key)
    
    def set_cached_data(self, key: str, value: Any) -> None:
        """设置缓存数据"""
        self._data_cache[key] = value
    
    def broadcast_message(self, message: str, tool_type: str = "all") -> None:
        """广播消息给指定类型的工具"""
        try:
            for tool_name, tool in self._open_tools.items():
                if tool_type == "all" or tool_name.startswith(tool_type):
                    if hasattr(tool, 'show_message'):
                        tool.show_message(message)
        except Exception as e:
            print(f"广播消息失败: {e}")
    
    def get_open_tools(self) -> List[str]:
        """获取打开的工具列表"""
        return list(self._open_tools.keys())
    
    def is_tool_open(self, tool_name: str) -> bool:
        """检查工具是否打开"""
        return tool_name in self._open_tools
    
    def get_tool_instance(self, tool_name: str) -> Optional[Any]:
        """获取工具实例"""
        return self._open_tools.get(tool_name)


# 全局集成管理器实例
_integration_manager: Optional[ToolIntegrationManager] = None


def get_integration_manager() -> ToolIntegrationManager:
    """获取全局集成管理器实例"""
    global _integration_manager
    if _integration_manager is None:
        _integration_manager = ToolIntegrationManager()
    return _integration_manager


def register_tool(tool_name: str, tool_instance: Any) -> None:
    """注册工具到全局集成管理器"""
    manager = get_integration_manager()
    manager.register_tool(tool_name, tool_instance)


def unregister_tool(tool_name: str) -> None:
    """从全局集成管理器注销工具"""
    manager = get_integration_manager()
    manager.unregister_tool(tool_name)
