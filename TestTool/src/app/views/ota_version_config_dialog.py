from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class OtaVersionConfigDialog(QDialog):
    """OTA 升级包版本配置（config.yaml → ota_version，与整机 version=0 比对分离）。"""

    DUAL_KEYS = ("S100", "X5")

    def __init__(self, parent: Optional[QWidget] = None, config_service=None) -> None:
        super().__init__(parent)
        self._config_service = config_service
        self._edits: dict[str, dict[str, QLineEdit]] = {}

        self.setWindowTitle("OTA 版本配置")
        self.setModal(True)
        self.resize(480, 320)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "用于 OTA 产线序列：校验本机升级包 zip 文件名是否包含下列 APP/SYS 版本特征串。"
            "与「配置 → 版本」中的整机版本（version=0 比对）相互独立。",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        toolbar = QHBoxLayout()
        toolbar.addStretch()
        self.btn_copy_from_versions = QPushButton("从整机版本复制", self)
        self.btn_copy_from_versions.clicked.connect(self._on_copy_from_versions)
        toolbar.addWidget(self.btn_copy_from_versions)
        layout.addLayout(toolbar)

        for key in self.DUAL_KEYS:
            group = QGroupBox(key, self)
            form = QFormLayout(group)
            app_edit = QLineEdit(self)
            app_edit.setPlaceholderText(f"{key} APP 包文件名应包含的版本特征")
            sys_edit = QLineEdit(self)
            sys_edit.setPlaceholderText(f"{key} SYS 包文件名应包含的版本特征")
            self._edits[key] = {"app_version": app_edit, "sys_version": sys_edit}
            form.addRow("APP版本:", app_edit)
            form.addRow("系统版本:", sys_edit)
            layout.addWidget(group)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self._on_ok)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._load_config()

    def _load_config(self) -> None:
        if self._config_service is None:
            return
        try:
            config = self._config_service.load()
            ota_versions = getattr(config, "ota_version", None)
            if ota_versions is None:
                return
            for key, edits in self._edits.items():
                item = getattr(ota_versions, key, None)
                if item is None:
                    continue
                edits["app_version"].setText(str(getattr(item, "app_version", "") or ""))
                edits["sys_version"].setText(str(getattr(item, "sys_version", "") or ""))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "警告", f"加载 OTA 版本配置失败: {exc}")

    def _on_copy_from_versions(self) -> None:
        if self._config_service is None:
            QMessageBox.information(self, "提示", "配置服务不可用")
            return
        try:
            config = self._config_service.load()
            versions = getattr(config, "versions", None)
            if versions is None:
                QMessageBox.warning(self, "提示", "未找到整机 versions 配置")
                return
            for key, edits in self._edits.items():
                item = getattr(versions, key, None)
                if item is None:
                    continue
                edits["app_version"].setText(str(getattr(item, "app_version", "") or ""))
                edits["sys_version"].setText(str(getattr(item, "sys_version", "") or ""))
            QMessageBox.information(
                self,
                "已复制",
                "已从整机版本配置复制 S100/X5，请确认后保存。",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "错误", f"复制失败: {exc}")

    def _on_ok(self) -> None:
        if self._config_service is None:
            self.accept()
            return
        try:
            config = self._config_service.load()
            ota_versions = getattr(config, "ota_version", None)
            if ota_versions is None:
                raise RuntimeError("ota_version 配置模型不存在")
            for key, edits in self._edits.items():
                item = getattr(ota_versions, key, None)
                if item is None:
                    raise RuntimeError(f"OTA {key} 配置不存在")
                item.app_version = edits["app_version"].text().strip()
                item.sys_version = edits["sys_version"].text().strip()
            self._config_service.save(config)
            QMessageBox.information(self, "保存成功", "OTA 版本配置已保存")
            self.accept()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "错误", f"保存 OTA 版本配置失败: {exc}")
