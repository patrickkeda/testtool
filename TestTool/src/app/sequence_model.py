"""
Simple sequence tree model backed by QTreeWidget.

Provides an imperative API to set root, add steps, update status, and clear.
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt


class SequenceTreeModel:
    """An imperative helper to manage a sequence tree in QTreeWidget.

    Parameters
    ----------
    tree: QTreeWidget
        The tree widget to populate.
    """

    def __init__(self, tree: QTreeWidget) -> None:
        self._tree = tree
        self._root_item: Optional[QTreeWidgetItem] = None
        self._step_index: Dict[str, QTreeWidgetItem] = {}

    # ---- basic operations -------------------------------------------------
    def clear(self) -> None:
        self._tree.clear()
        self._root_item = None
        self._step_index.clear()

    def set_root(self, label: str, status: str = "Idle") -> QTreeWidgetItem:
        self.clear()
        # 设置列标题 - 只显示步骤名称和参数
        self._tree.setHeaderLabels(["测试步骤", "参数"])
        root = QTreeWidgetItem([label, "测试序列"])
        self._tree.addTopLevelItem(root)
        self._tree.expandItem(root)
        self._root_item = root
        return root

    def add_step(self, step_id: str, label: str, step_obj=None, parent_id: Optional[str] = None) -> QTreeWidgetItem:
        print(f"DEBUG: add_step called with step_id='{step_id}', label='{label}'")
        parent = self._root_item if parent_id is None else self._step_index.get(parent_id, self._root_item)
        
        # 提取参数信息
        params_text = self._extract_params_text(step_obj)
        
        # 创建两列：步骤名称、参数
        item = QTreeWidgetItem([label, params_text])
        print(f"DEBUG: QTreeWidgetItem created with text: {item.text(0)} - {item.text(1)}")
        # 使用Qt.UserRole来存储step_id，避免覆盖显示文本
        item.setData(0, Qt.UserRole, step_id)
        if parent is not None:
            parent.addChild(item)
        else:
            self._tree.addTopLevelItem(item)
        self._step_index[step_id] = item
        print(f"DEBUG: Item added to tree, final text: {item.text(0)} - {item.text(1)}")
        return item

    def _extract_params_text(self, step_obj) -> str:
        """提取步骤参数信息，只显示数值，用逗号分隔"""
        if not step_obj:
            return "无参数"
        
        params_list = []
        
        # 基本参数 - 只显示数值
        if hasattr(step_obj, 'timeout') and step_obj.timeout:
            params_list.append(str(step_obj.timeout))
        if hasattr(step_obj, 'retries') and step_obj.retries:
            params_list.append(str(step_obj.retries))
        if hasattr(step_obj, 'type') and step_obj.type:
            params_list.append(str(step_obj.type))
        
        # 步骤特定参数 - 只显示数值
        if hasattr(step_obj, 'params') and step_obj.params:
            for key, value in step_obj.params.items():
                if value is not None and value != "":
                    params_list.append(str(value))
        
        # AT命令参数 - 只显示数值
        if hasattr(step_obj, 'at_config') and step_obj.at_config:
            if hasattr(step_obj.at_config, 'command') and step_obj.at_config.command:
                params_list.append(str(step_obj.at_config.command))
            if hasattr(step_obj.at_config, 'port') and step_obj.at_config.port:
                params_list.append(str(step_obj.at_config.port))
        
        # 状态测量参数 - 只显示数值
        if hasattr(step_obj, 'state_measurement_config') and step_obj.state_measurement_config:
            if hasattr(step_obj.state_measurement_config, 'measurement_type'):
                params_list.append(str(step_obj.state_measurement_config.measurement_type))
        
        # 人工判断参数 - 只显示数值
        if hasattr(step_obj, 'manual_judgment_config') and step_obj.manual_judgment_config:
            if hasattr(step_obj.manual_judgment_config, 'instruction'):
                params_list.append(str(step_obj.manual_judgment_config.instruction))
        
        return ", ".join(params_list) if params_list else "无参数"

    def update_step(self, step_id: str, *, label: Optional[str] = None, status: Optional[str] = None, port: str = "A") -> None:
        print(f"DEBUG: update_step called with step_id='{step_id}', label='{label}', status='{status}', port='{port}'")
        item = self._step_index.get(step_id)
        if not item:
            print(f"DEBUG: update_step - item not found for step_id='{step_id}'")
            return
        if label is not None:
            item.setText(0, label)
            print(f"DEBUG: update_step - updated label to '{label}'")
        # 左侧序列树不再显示执行状态，状态信息由Port A/B窗口显示
        print(f"DEBUG: update_step - 左侧序列树不显示执行状态，状态由Port {port}窗口显示")

    def remove_step(self, step_id: str) -> None:
        item = self._step_index.pop(step_id, None)
        if not item:
            return
        parent = item.parent()
        if parent is None:
            idx = self._tree.indexOfTopLevelItem(item)
            if idx >= 0:
                self._tree.takeTopLevelItem(idx)
        else:
            parent.removeChild(item)


