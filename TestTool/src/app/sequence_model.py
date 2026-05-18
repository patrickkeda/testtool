"""
Simple sequence tree model backed by QTreeWidget.

Provides an imperative API to set root, add steps, update status, and clear.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt

# 主界面左侧序列树「参数」列仅作摘要；PVT/SSH 等步骤的 command 可达数万字符，
# 若整段写入 QTreeWidgetItem 并 print 全量，易导致卡顿或进程退出。
_TREE_PARAM_TOKEN_MAX = 96
_TREE_PARAM_JOIN_MAX = 600


def _truncate_for_tree_cell(text: object, max_len: int = _TREE_PARAM_TOKEN_MAX) -> str:
    if text is None:
        return ""
    s = str(text).replace("\r", " ").replace("\n", " ")
    s = " ".join(s.split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


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

    def set_root(
        self,
        label: str,
        status: str = "Idle",
        *,
        header_labels: Optional[List[str]] = None,
    ) -> QTreeWidgetItem:
        self.clear()
        if header_labels is not None:
            self._tree.setHeaderLabels(header_labels)
        else:
            self._tree.setHeaderLabels(["测试步骤", "参数", "复测"])
        root = QTreeWidgetItem([label, status, ""])
        self._tree.addTopLevelItem(root)
        self._tree.expandItem(root)
        self._root_item = root
        return root

    def add_step(self, step_id: str, label: str, step_obj=None, parent_id: Optional[str] = None) -> QTreeWidgetItem:
        parent = self._root_item if parent_id is None else self._step_index.get(parent_id, self._root_item)

        # 提取参数信息
        params_text = self._extract_params_text(step_obj)

        retry_text = self._format_retry_attempts(step_obj)
        item = QTreeWidgetItem([label, params_text, retry_text])
        # 使用Qt.UserRole来存储step_id，避免覆盖显示文本
        item.setData(0, Qt.UserRole, step_id)
        if parent is not None:
            parent.addChild(item)
        else:
            self._tree.addTopLevelItem(item)
        self._step_index[step_id] = item
        return item

    def _extract_params_text(self, step_obj) -> str:
        """提取步骤参数信息，只显示数值，用逗号分隔"""
        if not step_obj:
            return "无参数"
        
        params_list = []
        
        # 基本参数 - 只显示数值
        if hasattr(step_obj, 'timeout') and step_obj.timeout:
            params_list.append(_truncate_for_tree_cell(step_obj.timeout))
        if hasattr(step_obj, 'type') and step_obj.type:
            params_list.append(_truncate_for_tree_cell(step_obj.type))

        # 步骤特定参数：键名 + 截断后的值，避免超长 command / message 撑爆树与日志
        if hasattr(step_obj, 'params') and step_obj.params:
            for key, value in step_obj.params.items():
                if value is not None and value != "":
                    tok = _truncate_for_tree_cell(value)
                    params_list.append(f"{key}={tok}")

        # AT命令参数
        if hasattr(step_obj, 'at_config') and step_obj.at_config:
            if hasattr(step_obj.at_config, 'command') and step_obj.at_config.command:
                params_list.append(_truncate_for_tree_cell(step_obj.at_config.command))
            if hasattr(step_obj.at_config, 'port') and step_obj.at_config.port:
                params_list.append(_truncate_for_tree_cell(step_obj.at_config.port))
        
        # 状态测量参数 - 只显示数值
        if hasattr(step_obj, 'state_measurement_config') and step_obj.state_measurement_config:
            if hasattr(step_obj.state_measurement_config, 'measurement_type'):
                params_list.append(
                    _truncate_for_tree_cell(step_obj.state_measurement_config.measurement_type)
                )

        # 人工判断参数
        if hasattr(step_obj, 'manual_judgment_config') and step_obj.manual_judgment_config:
            if hasattr(step_obj.manual_judgment_config, 'instruction'):
                params_list.append(
                    _truncate_for_tree_cell(step_obj.manual_judgment_config.instruction)
                )

        joined = ", ".join(params_list) if params_list else "无参数"
        if len(joined) > _TREE_PARAM_JOIN_MAX:
            return joined[: _TREE_PARAM_JOIN_MAX - 3] + "..."
        return joined

    @staticmethod
    def _format_retry_attempts(step_obj) -> str:
        if not step_obj:
            return ""
        r = int(getattr(step_obj, "retries", 0) or 0)
        n = r + 1
        return f"共{n}次"

    def update_step(self, step_id: str, *, label: Optional[str] = None, status: Optional[str] = None, port: str = "A") -> None:
        item = self._step_index.get(step_id)
        if not item:
            return
        if label is not None:
            item.setText(0, label)
        # 左侧序列树不再显示执行状态，状态信息由Port A/B窗口显示

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


