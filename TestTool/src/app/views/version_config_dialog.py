from __future__ import annotations

import json
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QMessageBox,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)


class VersionTextImportDialog(QDialog):
    """粘贴版本信息文本并导入。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("粘贴版本信息")
        self.setModal(True)
        self.resize(760, 560)

        layout = QVBoxLayout(self)

        hint = QLabel("请粘贴 version.txt 的完整内容，确认后会自动解析并回填到版本配置界面。", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.editor = QPlainTextEdit(self)
        self.editor.setPlaceholderText('请在这里粘贴类似 {"S100": {...}, "devices": [...]} 的版本信息...')
        layout.addWidget(self.editor)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.button(QDialogButtonBox.Ok).setText("导入")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def get_text(self) -> str:
        return self.editor.toPlainText().strip()


class VersionConfigDialog(QDialog):
    """版本配置对话框。"""

    DUAL_VERSION_KEYS = ("S100", "X5")
    SINGLE_VERSION_KEYS = ("MOTOR", "SERVO", "UWB", "LIDAR", "BMS")

    def __init__(self, parent: Optional[QWidget] = None, config_service=None) -> None:
        super().__init__(parent)
        self._config_service = config_service
        self._single_edits: dict[str, dict[str, QLineEdit]] = {}
        self._dual_edits: dict[str, dict[str, QLineEdit]] = {}

        self.setWindowTitle("版本配置")
        self.setModal(True)
        self.resize(520, 520)

        layout = QVBoxLayout(self)
        hint = QLabel("配置项按最终 version.txt 结构组织。S100/X5 配置 app_version 和 sys_version，其它设备配置 sw_version。", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        toolbar_layout = QHBoxLayout()
        toolbar_layout.addStretch()
        self.btn_import_text = QPushButton("一键配置", self)
        self.btn_import_text.clicked.connect(self._on_import_text)
        toolbar_layout.addWidget(self.btn_import_text)
        layout.addLayout(toolbar_layout)

        for key in self.DUAL_VERSION_KEYS:
            group = QGroupBox(key, self)
            form = QFormLayout(group)
            app_edit = QLineEdit(self)
            app_edit.setPlaceholderText(f"请输入 {key} 的 app_version")
            sys_edit = QLineEdit(self)
            sys_edit.setPlaceholderText(f"请输入 {key} 的 sys_version")
            self._dual_edits[key] = {
                "app_version": app_edit,
                "sys_version": sys_edit,
            }
            form.addRow("APP版本:", app_edit)
            form.addRow("系统版本:", sys_edit)
            layout.addWidget(group)

        for key in self.SINGLE_VERSION_KEYS:
            group = QGroupBox(key, self)
            form = QFormLayout(group)
            sw_edit = QLineEdit(self)
            sw_edit.setPlaceholderText(f"请输入 {key} 的 sw_version")
            self._single_edits[key] = {
                "sw_version": sw_edit,
            }
            form.addRow("软件版本:", sw_edit)
            layout.addWidget(group)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            self,
        )
        self.buttons.accepted.connect(self._on_ok)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._load_config()

    def _load_config(self) -> None:
        if self._config_service is None:
            return

        try:
            config = self._config_service.load()
            versions = getattr(config, "versions", None)
            if versions is None:
                return

            for key, edits in self._dual_edits.items():
                version_item = getattr(versions, key, None)
                if version_item is None:
                    continue
                edits["app_version"].setText(str(getattr(version_item, "app_version", "") or ""))
                edits["sys_version"].setText(str(getattr(version_item, "sys_version", "") or ""))

            for key, edits in self._single_edits.items():
                version_item = getattr(versions, key, None)
                if version_item is None:
                    continue
                edits["sw_version"].setText(str(getattr(version_item, "sw_version", "") or ""))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "警告", f"加载版本配置失败: {exc}")

    def _on_import_text(self) -> None:
        dialog = VersionTextImportDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        raw_text = dialog.get_text()
        if not raw_text:
            QMessageBox.information(self, "提示", "请先粘贴版本信息文本")
            return

        try:
            data = json.loads(raw_text)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "解析失败", f"版本信息不是有效的 JSON: {exc}")
            return

        try:
            self._apply_imported_data(data)
            QMessageBox.information(self, "导入成功", "版本信息已自动填充到当前界面，请确认后点击 OK 保存。")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "导入失败", f"处理版本信息时出错: {exc}")

    def _apply_imported_data(self, data: dict) -> None:
        for key, edits in self._dual_edits.items():
            block = data.get(key, {}) if isinstance(data, dict) else {}
            if not isinstance(block, dict):
                continue
            edits["app_version"].setText(str(block.get("app_version", "") or ""))
            edits["sys_version"].setText(str(block.get("sys_version", "") or ""))

        device_map = self._extract_device_versions(data)
        for key, edits in self._single_edits.items():
            edits["sw_version"].setText(device_map.get(key, ""))

    def _extract_device_versions(self, data: dict) -> dict[str, str]:
        results: dict[str, str] = {}
        devices = data.get("devices", []) if isinstance(data, dict) else []
        if not isinstance(devices, list):
            return results

        for device in devices:
            if not isinstance(device, dict):
                continue
            device_type = str(device.get("device_type", "") or "").upper()
            if not device_type or device_type not in self.SINGLE_VERSION_KEYS:
                continue

            versions = device.get("versions", [])
            if not isinstance(versions, list):
                continue

            preferred_value = ""
            fallback_value = ""
            for item in versions:
                if not isinstance(item, dict):
                    continue
                sw_version = str(item.get("sw_version", "") or "").strip()
                if not sw_version:
                    continue
                if not fallback_value:
                    fallback_value = sw_version
                if sw_version.lower() != "unknown":
                    preferred_value = sw_version
                    break

            results[device_type] = preferred_value or fallback_value

        return results

    def _on_ok(self) -> None:
        if self._config_service is None:
            self.accept()
            return

        try:
            config = self._config_service.load()
            versions = getattr(config, "versions", None)
            if versions is None:
                raise RuntimeError("版本配置模型不存在")

            for key, edits in self._dual_edits.items():
                version_item = getattr(versions, key, None)
                if version_item is None:
                    raise RuntimeError(f"{key} 版本配置不存在")
                version_item.app_version = edits["app_version"].text().strip()
                version_item.sys_version = edits["sys_version"].text().strip()

            for key, edits in self._single_edits.items():
                version_item = getattr(versions, key, None)
                if version_item is None:
                    raise RuntimeError(f"{key} 版本配置不存在")
                version_item.sw_version = edits["sw_version"].text().strip()

            self._config_service.save(config)
            QMessageBox.information(self, "保存成功", "版本配置已保存")
            self.accept()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "错误", f"保存版本配置失败: {exc}")
