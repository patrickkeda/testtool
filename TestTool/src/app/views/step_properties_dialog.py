"""
主界面步骤属性对话框：可视化配置单步复测（retries）、超时、失败策略。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from ...testcases.config import TestSequenceConfig, TestStepConfig


class StepPropertiesDialog(QDialog):
    """编辑单步 retries / timeout / on_failure，可选写回 YAML。"""

    def __init__(
        self,
        parent,
        step: TestStepConfig,
        *,
        sequence: Optional[TestSequenceConfig] = None,
        save_yaml_path: Optional[str] = None,
        translator=None,
    ) -> None:
        super().__init__(parent)
        self._step = step
        self._sequence = sequence
        self._save_yaml_path = save_yaml_path
        self._translator = translator
        self.did_save_yaml = False

        title = "步骤属性"
        if translator:
            title = translator.t("seq.step_props.title")
        self.setWindowTitle(title)
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)

        hint = QLabel(
            "失败后额外重试次数为 N 时，本步共执行 N+1 次；任一次通过即本步通过。"
            if not translator
            else translator.t("seq.step_props.hint_retries")
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555;")
        root.addWidget(hint)

        form = QFormLayout()
        self.sp_retries = QSpinBox()
        self.sp_retries.setRange(0, 10)
        self.sp_retries.wheelEvent = lambda e: None
        self.sp_retries.setValue(int(getattr(step, "retries", 0) or 0))
        form.addRow(
            "失败额外重试" if not translator else translator.t("seq.step_props.retries"),
            self.sp_retries,
        )

        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(0, 3_600_000)
        self.sp_timeout.setSingleStep(1000)
        self.sp_timeout.setSuffix(" ms")
        self.sp_timeout.wheelEvent = lambda e: None
        to = getattr(step, "timeout", None)
        self.sp_timeout.setValue(int(to) if to is not None else 30_000)
        form.addRow(
            "超时" if not translator else translator.t("seq.step_props.timeout"),
            self.sp_timeout,
        )

        self.cb_on_failure = QComboBox()
        self.cb_on_failure.wheelEvent = lambda e: None
        for v in ("fail", "continue", "skip", "retry"):
            label = v if not translator else translator.t(f"seq.step_props.on_failure.{v}")
            self.cb_on_failure.addItem(label, v)
        of = (getattr(step, "on_failure", None) or "fail").lower()
        self._select_on_failure_by_value(of)
        form.addRow(
            "失败策略" if not translator else translator.t("seq.step_props.on_failure"),
            self.cb_on_failure,
        )

        root.addLayout(form)

        self.chk_save = QCheckBox(
            "保存到序列 YAML 文件"
            if not translator
            else translator.t("seq.step_props.save_yaml"),
        )
        self.chk_save.setChecked(bool(save_yaml_path))
        self.chk_save.setEnabled(bool(save_yaml_path))
        if not save_yaml_path:
            tip = QLabel(
                "（当前序列未关联磁盘路径，仅内存生效；请用「加载序列」打开 yaml 后再试。）"
                if not translator
                else translator.t("seq.step_props.no_path_hint"),
            )
            tip.setWordWrap(True)
            tip.setStyleSheet("color: #888; font-size: 11px;")
            root.addWidget(tip)
        root.addWidget(self.chk_save)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _select_on_failure_by_value(self, value: str) -> None:
        v = (value or "fail").lower()
        for i in range(self.cb_on_failure.count()):
            if self.cb_on_failure.itemData(i) == v:
                self.cb_on_failure.setCurrentIndex(i)
                return
        self.cb_on_failure.setCurrentIndex(0)

    def _on_accept(self) -> None:
        self._step.retries = self.sp_retries.value()
        self._step.timeout = self.sp_timeout.value()
        data = self.cb_on_failure.currentData()
        self._step.on_failure = str(data) if data is not None else "fail"
        if self.chk_save.isChecked() and self._save_yaml_path and self._sequence is not None:
            from ...testcases.utils import save_test_sequence

            try:
                save_test_sequence(self._sequence, self._save_yaml_path)
                self.did_save_yaml = True
            except Exception as e:  # noqa: BLE001
                title = "保存失败" if not self._translator else self._translator.t("dialog.error")
                body = (
                    f"无法写入序列文件：\n{e}"
                    if not self._translator
                    else self._translator.t("seq.step_props.save_fail").format(err=e)
                )
                QMessageBox.warning(self, title, body)
                return
        self.accept()
