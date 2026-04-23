"""
工具启动器 - 统一管理工具的启动和集成
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.app.i18n import I18n
from .integration_manager import get_integration_manager


class ToolLauncher(QObject):
    """工具启动器"""
    
    # 信号定义
    sig_tool_started = Signal(str)  # 工具启动信号
    sig_tool_stopped = Signal(str)  # 工具停止信号
    sig_tools_connected = Signal(str, str)  # 工具连接信号
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._i18n = I18n()
        self._running_tools: Dict[str, Any] = {}  # 运行中的工具
        self._integration_manager = get_integration_manager()
        
        # 连接集成管理器信号
        self._integration_manager.sig_tool_opened.connect(self._on_tool_opened)
        self._integration_manager.sig_tool_closed.connect(self._on_tool_closed)
    
    def launch_sequence_editor(self, parent: Optional[QWidget] = None) -> Optional[Any]:
        """启动序列编辑器"""
        try:
            # 统一入口：使用 views 版本的 SequenceEditor，避免两套实现分叉
            from ..views.sequence_editor import SequenceEditor
            editor = SequenceEditor(parent)
            
            # 设置窗口属性
            editor.setWindowTitle("测试序列编辑器")
            editor.setAttribute(Qt.WA_DeleteOnClose, True)
            
            # 显示窗口
            editor.show()
            editor.raise_()
            editor.activateWindow()
            
            # 记录运行中的工具
            self._running_tools["sequence_editor"] = editor
            self.sig_tool_started.emit("sequence_editor")
            
            return editor
            
        except ImportError as e:
            QMessageBox.warning(parent, "功能不可用", 
                               f"序列编辑器模块不可用：{e}\n\n请检查tools目录是否存在。")
            return None
        except Exception as e:
            QMessageBox.critical(parent, "错误", f"无法启动序列编辑器: {e}")
            return None
    
    def launch_step_library(self, parent: Optional[QWidget] = None) -> Optional[Any]:
        """启动步骤库管理器"""
        try:
            from .step_library import StepLibrary
            library = StepLibrary(parent)
            
            # 设置窗口属性
            library.setWindowTitle("步骤库管理器")
            library.setAttribute(Qt.WA_DeleteOnClose, True)
            
            # 显示窗口
            library.show()
            library.raise_()
            library.activateWindow()
            
            # 记录运行中的工具
            self._running_tools["step_library"] = library
            self.sig_tool_started.emit("step_library")
            
            return library
            
        except ImportError as e:
            QMessageBox.warning(parent, "功能不可用", 
                               f"步骤库管理器模块不可用：{e}\n\n请检查tools目录是否存在。")
            return None
        except Exception as e:
            QMessageBox.critical(parent, "错误", f"无法启动步骤库管理器: {e}")
            return None
    
    def launch_both_tools(self, parent: Optional[QWidget] = None) -> Dict[str, Any]:
        """同时启动两个工具"""
        try:
            tools = {}
            
            # 启动序列编辑器
            editor = self.launch_sequence_editor(parent)
            if editor:
                tools["sequence_editor"] = editor
            
            # 启动步骤库管理器
            library = self.launch_step_library(parent)
            if library:
                tools["step_library"] = library
            
            # 如果两个工具都启动成功，建立连接
            if len(tools) == 2:
                self._connect_tools(tools["sequence_editor"], tools["step_library"])
                self.sig_tools_connected.emit("sequence_editor", "step_library")
            
            return tools
            
        except Exception as e:
            QMessageBox.critical(parent, "错误", f"启动工具失败: {e}")
            return {}
    
    def _connect_tools(self, editor: Any, library: Any) -> None:
        """连接两个工具"""
        try:
            # 连接步骤库到序列编辑器
            if hasattr(library, 'sig_step_selected') and hasattr(editor, 'insert_step_template'):
                library.sig_step_selected.connect(editor.insert_step_template)
            
            # 连接序列编辑器到步骤库
            if hasattr(editor, 'sig_step_template_requested') and hasattr(library, '_on_template_requested'):
                editor.sig_step_template_requested.connect(library._on_template_requested)
            
        except Exception as e:
            print(f"连接工具失败: {e}")
    
    def _on_tool_opened(self, tool_name: str) -> None:
        """处理工具打开事件"""
        print(f"工具已打开: {tool_name}")
    
    def _on_tool_closed(self, tool_name: str) -> None:
        """处理工具关闭事件"""
        if tool_name in self._running_tools:
            del self._running_tools[tool_name]
        self.sig_tool_stopped.emit(tool_name)
        print(f"工具已关闭: {tool_name}")
    
    def get_running_tools(self) -> List[str]:
        """获取运行中的工具列表"""
        return list(self._running_tools.keys())
    
    def is_tool_running(self, tool_name: str) -> bool:
        """检查工具是否在运行"""
        return tool_name in self._running_tools
    
    def get_tool(self, tool_name: str) -> Optional[Any]:
        """获取工具实例"""
        return self._running_tools.get(tool_name)
    
    def close_all_tools(self) -> None:
        """关闭所有工具"""
        for tool_name, tool in list(self._running_tools.items()):
            try:
                if hasattr(tool, 'close'):
                    tool.close()
            except Exception as e:
                print(f"关闭工具 {tool_name} 失败: {e}")


# 全局工具启动器实例
_tool_launcher: Optional[ToolLauncher] = None


def get_tool_launcher() -> ToolLauncher:
    """获取全局工具启动器实例"""
    global _tool_launcher
    if _tool_launcher is None:
        _tool_launcher = ToolLauncher()
    return _tool_launcher


def launch_sequence_editor(parent: Optional[QWidget] = None) -> Optional[Any]:
    """启动序列编辑器"""
    launcher = get_tool_launcher()
    return launcher.launch_sequence_editor(parent)


def launch_step_library(parent: Optional[QWidget] = None) -> Optional[Any]:
    """启动步骤库管理器"""
    launcher = get_tool_launcher()
    return launcher.launch_step_library(parent)


def launch_both_tools(parent: Optional[QWidget] = None) -> Dict[str, Any]:
    """同时启动两个工具"""
    launcher = get_tool_launcher()
    return launcher.launch_both_tools(parent)
