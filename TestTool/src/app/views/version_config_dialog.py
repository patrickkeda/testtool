from __future__ import annotations

import json
from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
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


class VersionDiffDialog(QDialog):
    """对比两个 build 版本并生成可复制替换文本。"""

    DUAL_VERSION_KEYS = ("S100", "X5")
    SINGLE_VERSION_KEYS = ("MOTOR", "SERVO", "UWB", "LIDAR", "BMS")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Build版本对比")
        self.setModal(True)
        self.resize(980, 700)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "左侧粘贴旧 build 的 version JSON，右侧粘贴新 build 的 version JSON。"
            "点击“开始比对”后会展示改动项，并生成可直接替换 config.yaml 中 versions 节点的文本。",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        editors_layout = QHBoxLayout()
        old_group = QGroupBox("旧版本 JSON", self)
        old_layout = QVBoxLayout(old_group)
        self.old_editor = QPlainTextEdit(old_group)
        self.old_editor.setPlaceholderText('例如: {"S100": {...}, "devices": [...]}')
        old_layout.addWidget(self.old_editor)
        editors_layout.addWidget(old_group)

        new_group = QGroupBox("新版本 JSON", self)
        new_layout = QVBoxLayout(new_group)
        self.new_editor = QPlainTextEdit(new_group)
        self.new_editor.setPlaceholderText('例如: {"S100": {...}, "devices": [...]}')
        new_layout.addWidget(self.new_editor)
        editors_layout.addWidget(new_group)
        layout.addLayout(editors_layout)

        action_layout = QHBoxLayout()
        self.btn_compare = QPushButton("开始比对", self)
        self.btn_compare.clicked.connect(self._on_compare)
        action_layout.addWidget(self.btn_compare)

        self.btn_copy = QPushButton("一键复制替换文本", self)
        self.btn_copy.clicked.connect(self._on_copy_replace_text)
        self.btn_copy.setEnabled(False)
        action_layout.addWidget(self.btn_copy)
        action_layout.addStretch()
        layout.addLayout(action_layout)

        self.diff_output = QPlainTextEdit(self)
        self.diff_output.setReadOnly(True)
        self.diff_output.setPlaceholderText("这里会显示版本改动项...")
        layout.addWidget(self.diff_output)

        self.replace_output = QPlainTextEdit(self)
        self.replace_output.setReadOnly(True)
        self.replace_output.setPlaceholderText("这里会生成可直接替换到 config.yaml 的 versions 文本...")
        layout.addWidget(self.replace_output)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)

    def _on_compare(self) -> None:
        try:
            old_data = self._parse_editor_json(self.old_editor, "旧版本 JSON")
            new_data = self._parse_editor_json(self.new_editor, "新版本 JSON")
        except ValueError as exc:
            QMessageBox.warning(self, "解析失败", str(exc))
            return

        old_flat = self._flatten_version_payload(old_data)
        new_flat = self._flatten_version_payload(new_data)
        keys = sorted(set(old_flat.keys()) | set(new_flat.keys()))

        lines: list[str] = []
        changed = 0
        for key in keys:
            old_value = old_flat.get(key, "")
            new_value = new_flat.get(key, "")
            if old_value != new_value:
                changed += 1
                lines.append(f"- {key}: {old_value or 'EMPTY'} -> {new_value or 'EMPTY'}")

        if not lines:
            lines = ["未检测到版本改动。"]
        else:
            lines.insert(0, f"共检测到 {changed} 项改动：")

        replace_text = self._build_versions_yaml_text(new_flat)
        self.diff_output.setPlainText("\n".join(lines))
        self.replace_output.setPlainText(replace_text)
        self.btn_copy.setEnabled(True)

    def _on_copy_replace_text(self) -> None:
        text = self.replace_output.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "暂无可复制内容，请先执行版本比对。")
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        QMessageBox.information(self, "复制成功", "替换文本已复制到剪贴板，可直接粘贴替换。")

    def _parse_editor_json(self, editor: QPlainTextEdit, name: str) -> dict:
        raw_text = editor.toPlainText().strip()
        if not raw_text:
            raise ValueError(f"{name} 不能为空。")
        try:
            data = json.loads(raw_text)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"{name} 不是有效 JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{name} 必须是 JSON 对象。")
        return data

    def _flatten_version_payload(self, data: dict) -> dict[str, str]:
        result: dict[str, str] = {}
        for key in self.DUAL_VERSION_KEYS:
            block = data.get(key, {})
            if not isinstance(block, dict):
                block = {}
            result[f"{key}.app_version"] = str(block.get("app_version", "") or "").strip()
            result[f"{key}.sys_version"] = str(block.get("sys_version", "") or "").strip()

        device_map = self._extract_device_versions(data)
        for key in self.SINGLE_VERSION_KEYS:
            result[f"{key}.sw_version"] = device_map.get(key, "")
        return result

    def _extract_device_versions(self, data: dict) -> dict[str, str]:
        results: dict[str, str] = {}
        devices = data.get("devices", [])
        if not isinstance(devices, list):
            return results

        for device in devices:
            if not isinstance(device, dict):
                continue
            device_type = str(device.get("device_type", "") or "").upper()
            if device_type not in self.SINGLE_VERSION_KEYS:
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

            if preferred_value or fallback_value:
                results[device_type] = preferred_value or fallback_value
        return results

    def _build_versions_yaml_text(self, flat_versions: dict[str, str]) -> str:
        lines = ["versions:"]
        for key in self.DUAL_VERSION_KEYS:
            app_version = flat_versions.get(f"{key}.app_version", "")
            sys_version = flat_versions.get(f"{key}.sys_version", "")
            lines.extend(
                [
                    f"  {key}:",
                    f'    app_version: "{app_version}"',
                    f'    sys_version: "{sys_version}"',
                ]
            )

        for key in self.SINGLE_VERSION_KEYS:
            sw_version = flat_versions.get(f"{key}.sw_version", "")
            lines.extend(
                [
                    f"  {key}:",
                    f'    sw_version: "{sw_version}"',
                ]
            )
        return "\n".join(lines)


class VersionConfigDialog(QDialog):
    """版本配置对话框。"""

    DUAL_VERSION_KEYS = ("S100", "X5")
    SINGLE_VERSION_KEYS = ("MOTOR", "SERVO", "UWB", "LIDAR", "BMS")

    def __init__(self, parent: Optional[QWidget] = None, config_service=None) -> None:
        super().__init__(parent)
        self._config_service = config_service
        self._single_edits: dict[str, dict[str, QLineEdit]] = {}
        self._dual_edits: dict[str, dict[str, QLineEdit]] = {}
        self._device_json_edits: dict[str, QLineEdit] = {}

        self.setWindowTitle("版本配置")
        self.setModal(True)
        self.resize(520, 600)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "S100/X5、MOTOR 等用于 version=0 结果比对；"
            "device.json 区块仅写入上传用的出厂版本，不参与版本校验。"
            "OTA 升级包版本请在「配置 → OTA 版本」中单独维护。",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        toolbar_layout = QHBoxLayout()
        toolbar_layout.addStretch()
        self.btn_import_text = QPushButton("一键配置", self)
        self.btn_import_text.clicked.connect(self._on_import_text)
        toolbar_layout.addWidget(self.btn_import_text)
        self.btn_diff_build = QPushButton("Build版本对比", self)
        self.btn_diff_build.clicked.connect(self._on_diff_build_versions)
        toolbar_layout.addWidget(self.btn_diff_build)
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
            field_edits = {
                "sw_version": sw_edit,
            }
            form.addRow("软件版本:", sw_edit)
            if key in ("UWB", "BMS"):
                compat_edit = QLineEdit(self)
                compat_edit.setPlaceholderText("可选：兼容版本，与软件版本任一匹配即通过")
                field_edits["sw_version_compat"] = compat_edit
                form.addRow("兼容版本:", compat_edit)
            self._single_edits[key] = field_edits
            layout.addWidget(group)

        device_json_group = QGroupBox("device.json（不参与版本比对）", self)
        device_json_form = QFormLayout(device_json_group)
        enc_dl_edit = QLineEdit(self)
        enc_dl_edit.setPlaceholderText("S100 已加密 factoryDownloadVersion")
        enc_in_edit = QLineEdit(self)
        enc_in_edit.setPlaceholderText("S100 已加密 factoryInstallVersion")
        plain_dl_edit = QLineEdit(self)
        plain_dl_edit.setPlaceholderText("S100 未加密 factoryDownloadVersion")
        plain_in_edit = QLineEdit(self)
        plain_in_edit.setPlaceholderText("S100 未加密 factoryInstallVersion")
        self._device_json_edits = {
            "encrypted_factory_download_version": enc_dl_edit,
            "encrypted_factory_install_version": enc_in_edit,
            "not_encrypted_factory_download_version": plain_dl_edit,
            "not_encrypted_factory_install_version": plain_in_edit,
        }
        device_json_form.addRow("已加密-下载:", enc_dl_edit)
        device_json_form.addRow("已加密-安装:", enc_in_edit)
        device_json_form.addRow("未加密-下载:", plain_dl_edit)
        device_json_form.addRow("未加密-安装:", plain_in_edit)
        layout.addWidget(device_json_group)

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
                compat_edit = edits.get("sw_version_compat")
                if compat_edit is not None:
                    compat_edit.setText(str(getattr(version_item, "sw_version_compat", "") or ""))

            device_json_item = getattr(config, "device_json", None)
            if device_json_item is not None:
                enc_pair = getattr(device_json_item, "encrypted", None)
                if enc_pair is not None:
                    self._device_json_edits["encrypted_factory_download_version"].setText(
                        str(getattr(enc_pair, "factory_download_version", "") or "")
                    )
                    self._device_json_edits["encrypted_factory_install_version"].setText(
                        str(getattr(enc_pair, "factory_install_version", "") or "")
                    )
                plain_pair = getattr(device_json_item, "not_encrypted", None)
                if plain_pair is not None:
                    self._device_json_edits["not_encrypted_factory_download_version"].setText(
                        str(getattr(plain_pair, "factory_download_version", "") or "")
                    )
                    self._device_json_edits["not_encrypted_factory_install_version"].setText(
                        str(getattr(plain_pair, "factory_install_version", "") or "")
                    )
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

    def _on_diff_build_versions(self) -> None:
        dialog = VersionDiffDialog(self)
        dialog.exec()

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
                if "sw_version_compat" in edits:
                    version_item.sw_version_compat = edits["sw_version_compat"].text().strip()

            device_json_item = getattr(config, "device_json", None)
            if device_json_item is None:
                raise RuntimeError("device_json 配置不存在")
            enc_pair = getattr(device_json_item, "encrypted", None)
            if enc_pair is not None:
                enc_pair.factory_download_version = (
                    self._device_json_edits["encrypted_factory_download_version"]
                    .text()
                    .strip()
                )
                enc_pair.factory_install_version = (
                    self._device_json_edits["encrypted_factory_install_version"]
                    .text()
                    .strip()
                )
            plain_pair = getattr(device_json_item, "not_encrypted", None)
            if plain_pair is not None:
                plain_pair.factory_download_version = (
                    self._device_json_edits["not_encrypted_factory_download_version"]
                    .text()
                    .strip()
                )
                plain_pair.factory_install_version = (
                    self._device_json_edits["not_encrypted_factory_install_version"]
                    .text()
                    .strip()
                )

            self._config_service.save(config)
            QMessageBox.information(self, "保存成功", "版本配置已保存")
            self.accept()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "错误", f"保存版本配置失败: {exc}")
