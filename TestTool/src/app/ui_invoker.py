"""
UI 调用器：提供在主线程中执行UI对话框的方法。

用于从工作线程（QThread）以阻塞方式在主线程显示对话框并获取返回值。
"""
from __future__ import annotations

import sys
from typing import Tuple

from PySide6.QtCore import QObject, QThread, Slot, Qt, QMetaObject, Q_ARG
from PySide6.QtWidgets import QApplication, QMainWindow

from src.testcases.steps.cases.scan_sn import ScanSNDialog


def find_testtool_main_window():
    """定位 TestTool 主 ``QMainWindow``，供对话框 ``parent`` 使用。

    中文界面标题为「测试工具人机界面」，不含 ``TestTool`` 子串；仅靠标题匹配会失败，
    对话框会变成无父顶层窗口，看起来像多出一个完整主界面。优先用 ``MainWindow``
    上设置的 ``objectName``，再回退到标题匹配。
    """
    app = QApplication.instance()
    if app is None:
        return None
    try:
        w = app.findChild(QMainWindow, "testtool_main_window")
        if w is not None:
            return w
    except Exception:
        pass
    try:
        for widget in app.topLevelWidgets():
            if not isinstance(widget, QMainWindow):
                continue
            try:
                title = widget.windowTitle() or ""
            except Exception:
                continue
            if "TestTool" in title or "测试工具" in title:
                return widget
    except Exception:
        pass
    return None


class _UIInvoker(QObject):
    """主线程UI调用器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sftp_pull_progress_dlg = None
        self._sftp_pull_dest_dir = ""

    @Slot(str, str, int)
    def sftp_pull_progress_open(self, title: str, dest_dir: str, total: int) -> None:
        """SFTP 拉取时显示进度条；须从 GUI 线程或通过 BlockingQueuedConnection 调用。"""
        from PySide6.QtWidgets import QProgressDialog

        self.sftp_pull_progress_close()
        self._sftp_pull_dest_dir = dest_dir or ""
        parent = _find_parent_window()
        dlg = QProgressDialog(parent)
        dlg.setWindowTitle(title or "正在导出数据")
        dlg.setLabelText(f"保存到本机：\n{self._sftp_pull_dest_dir}\n\n准备下载…")
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(True)
        dlg.setAutoReset(True)
        dlg.setRange(0, max(1, int(total)))
        dlg.setValue(0)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.show()
        self._sftp_pull_progress_dlg = dlg
        try:
            app = QApplication.instance()
            if app is not None:
                app.processEvents()
        except Exception:
            pass

    @Slot(int, str)
    def sftp_pull_progress_update(self, current: int, detail: str) -> None:
        dlg = self._sftp_pull_progress_dlg
        if dlg is None:
            return
        dlg.setValue(min(int(current), dlg.maximum()))
        base = self._sftp_pull_dest_dir or ""
        tail = (detail or "").strip()
        if tail:
            dlg.setLabelText(f"保存到本机：\n{base}\n\n正在下载：\n{tail}")
        else:
            dlg.setLabelText(f"保存到本机：\n{base}\n\n下载中…")
        try:
            app = QApplication.instance()
            if app is not None:
                app.processEvents()
        except Exception:
            pass

    @Slot()
    def sftp_pull_progress_close(self) -> None:
        dlg = self._sftp_pull_progress_dlg
        if dlg is not None:
            try:
                dlg.setValue(dlg.maximum())
            except Exception:
                pass
            dlg.close()
            dlg.deleteLater()
        self._sftp_pull_progress_dlg = None
        self._sftp_pull_dest_dir = ""
        try:
            app = QApplication.instance()
            if app is not None:
                app.processEvents()
        except Exception:
            pass

    @Slot(str, str, str, int, str, bool, result=tuple)
    def show_scan_sn(
        self,
        title: str,
        hint: str,
        regex: str,
        timeout_ms: int,
        port: str,
        force_english_keyboard: bool,
    ) -> Tuple[bool, str]:
        app = QApplication.instance()
        parent_window = find_testtool_main_window()
        dlg = ScanSNDialog(
            parent=parent_window,
            title=title,
            hint=hint,
            regex=regex,
            timeout_ms=timeout_ms,
            port=port,
            force_english_keyboard=force_english_keyboard,
        )
        # 应用退出时确保对话框关闭
        try:
            app.aboutToQuit.connect(dlg.close)
        except Exception:
            pass
        from PySide6.QtWidgets import QDialog
        result = dlg.exec()
        return (result == QDialog.Accepted, dlg.get_sn())


_invoker_instance: _UIInvoker | None = None


def get_ui_invoker() -> _UIInvoker:
    """获取单例UI调用器，保证运行在主线程。"""
    global _invoker_instance
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication 未初始化，无法显示UI对话框")
    if _invoker_instance is None:
        _invoker_instance = _UIInvoker()
        # 确保对象属于主线程
        _invoker_instance.moveToThread(app.thread())
    return _invoker_instance


def _sftp_progress_invoke_mode():
    app = QApplication.instance()
    if app is None:
        return None
    if QThread.currentThread() == app.thread():
        return Qt.DirectConnection
    return Qt.BlockingQueuedConnection


def invoke_sftp_pull_progress_open(title: str, dest_dir: str, total: int) -> bool:
    """在工作线程中阻塞调用：于主线程打开 SFTP 导出进度条。无 GUI 时返回 False。"""
    mode = _sftp_progress_invoke_mode()
    if mode is None:
        return False
    try:
        inv = get_ui_invoker()
    except Exception:
        return False
    return bool(
        QMetaObject.invokeMethod(
            inv,
            "sftp_pull_progress_open",
            mode,
            Q_ARG(str, title or "正在导出数据"),
            Q_ARG(str, dest_dir or ""),
            Q_ARG(int, int(total)),
        )
    )


def invoke_sftp_pull_progress_update(current: int, detail: str) -> None:
    mode = _sftp_progress_invoke_mode()
    if mode is None:
        return
    try:
        inv = get_ui_invoker()
    except Exception:
        return
    QMetaObject.invokeMethod(
        inv,
        "sftp_pull_progress_update",
        mode,
        Q_ARG(int, int(current)),
        Q_ARG(str, detail or ""),
    )


def invoke_sftp_pull_progress_close() -> None:
    mode = _sftp_progress_invoke_mode()
    if mode is None:
        return
    try:
        inv = get_ui_invoker()
    except Exception:
        return
    QMetaObject.invokeMethod(inv, "sftp_pull_progress_close", mode)


def _find_parent_window():
    """尝试查找 TestTool 主窗口，作为对话框父窗口。"""
    return find_testtool_main_window()


def _render_countdown_message(message: str, remaining_seconds: int, mmss_text: str) -> str:
    """渲染倒计时文案，支持简单占位符。"""
    template = message or "等待中"
    if "{remaining_seconds}" in template or "{seconds}" in template or "{mmss}" in template:
        return (
            template
            .replace("{remaining_seconds}", str(remaining_seconds))
            .replace("{seconds}", str(remaining_seconds))
            .replace("{mmss}", mmss_text)
        )
    return f"{template}\n\n剩余时间: {mmss_text}"


def invoke_in_gui_show_scan_sn(
    title: str,
    hint: str,
    regex: str,
    timeout_ms: int,
    port: str = "PortA",
    main_window=None,
    *,
    force_english_keyboard: bool = True,
) -> Tuple[bool, str]:
    """在主线程阻塞调用显示ScanSN对话框并返回结果。"""
    print(f"[{port}] UI调用器被调用: title={title}, port={port}")
    
    from PySide6.QtCore import QThread
    
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication 未初始化")
    
    current_thread = QThread.currentThread()
    main_thread = app.thread()
    is_frozen = getattr(sys, "frozen", False)
    
    # 打包为 exe 后部署到其它电脑时，强制走信号槽路径，确保对话框一定在主线程显示，避免死机
    if is_frozen:
        current_thread = None  # 强制视为“非主线程”，走下面的 else 分支
    else:
        pass  # 开发环境仍按线程判断
    
    print(f"[{port}] 线程检查: current_thread={current_thread}, main_thread={main_thread}, is_frozen={is_frozen}")
    
    if not is_frozen and current_thread == main_thread:
        # 已经在主线程，直接创建对话框
        print(f"[{port}] 在主线程中，直接创建对话框")
        try:
            from src.testcases.steps.cases.scan_sn import ScanSNDialog
            print(f"[{port}] ScanSNDialog导入成功")
            # 如未提供main_window，这里在主线程内解析
            if main_window is None:
                main_window_local = find_testtool_main_window()
            else:
                main_window_local = main_window
            dlg = ScanSNDialog(
                parent=main_window_local,
                title=title,
                hint=hint,
                regex=regex,
                timeout_ms=timeout_ms,
                port=port,
                main_window=main_window_local,
                force_english_keyboard=force_english_keyboard,
            )
            # 应用退出时确保对话框关闭
            try:
                app.aboutToQuit.connect(dlg.close)
            except Exception:
                pass
            print(f"[{port}] ScanSNDialog创建成功，非模态打开并等待结果")
            from PySide6.QtWidgets import QDialog
            dlg.setWindowModality(Qt.ApplicationModal)
            result = dlg.exec()
            accepted = result == QDialog.Accepted
            print(f"[{port}] 对话框完成，accepted={accepted}")
            return (accepted, dlg.get_sn())
        except Exception as e:
            print(f"[{port}] 对话框显示异常: {e}")
            import traceback
            traceback.print_exc()
            return (False, "")
    else:
        # 不在主线程，使用信号槽机制
        print(f"[{port}] 不在主线程，使用信号槽机制")
        from PySide6.QtCore import QEventLoop, QTimer, QObject, Signal, Slot
        
        class DialogHelper(QObject):
            finished = Signal(bool, str)
            
            @Slot(str, str, str, int, str, bool)
            def show_dialog(self, title, hint, regex, timeout_ms, port, force_english_keyboard):
                print(f"[{port}] DialogHelper.show_dialog被调用")
                from PySide6.QtCore import QEventLoop
                from PySide6.QtWidgets import QDialog
                
                def _do_show():
                    try:
                        from src.testcases.steps.cases.scan_sn import ScanSNDialog
                        print(f"[{port}] ScanSNDialog导入成功")
                        main_window_local = find_testtool_main_window()
                        dlg = ScanSNDialog(
                            parent=main_window_local,
                            title=title,
                            hint=hint,
                            regex=regex,
                            timeout_ms=timeout_ms,
                            port=port,
                            main_window=main_window_local,
                            force_english_keyboard=force_english_keyboard,
                        )
                        try:
                            QApplication.instance().aboutToQuit.connect(dlg.close)
                        except Exception:
                            pass
                        dlg.setWindowModality(Qt.ApplicationModal)
                        print(f"[{port}] ScanSNDialog已显示，等待结果")
                        result = dlg.exec()
                        accepted = result == QDialog.Accepted
                        print(f"[{port}] 对话框完成，accepted={accepted}")
                        self.finished.emit(accepted, dlg.get_sn())
                    except Exception as e:
                        print(f"[{port}] 对话框显示异常: {e}")
                        import traceback
                        traceback.print_exc()
                        self.finished.emit(False, "")
                
                # 直接显示，不再 singleShot(0) 延迟，避免“等特别久”和第二次不弹窗
                _do_show()
        
        # 创建helper对象并移动到主线程
        helper = DialogHelper()
        helper.moveToThread(main_thread)
        
        # 创建事件循环等待结果
        loop = QEventLoop()
        result_container = [False, ""]
        
        def on_finished(accepted, sn):
            result_container[0] = accepted
            result_container[1] = sn
            loop.quit()
        
        helper.finished.connect(on_finished)
        
        # 使用QMetaObject.invokeMethod在主线程中调用
        from PySide6.QtCore import QMetaObject, Q_ARG
        QMetaObject.invokeMethod(
            helper,
            "show_dialog",
            Qt.QueuedConnection,
            Q_ARG(str, title),
            Q_ARG(str, hint),
            Q_ARG(str, regex),
            Q_ARG(int, timeout_ms),
            Q_ARG(str, port),
            Q_ARG(bool, force_english_keyboard),
        )
        
        # 等待结果
        loop.exec()
        return (result_container[0], result_container[1])


def _show_instruction_dialog(title: str, message: str, confirm_text: str, cancel_text: str, allow_cancel: bool) -> bool:
    """在主线程中以自定义样式显示提示对话框。"""
    from PySide6.QtWidgets import (
        QDialog,
        QVBoxLayout,
        QLabel,
        QPushButton,
        QHBoxLayout,
    )
    from PySide6.QtGui import QFont

    parent_window = _find_parent_window()

    dialog = QDialog(parent_window)
    dialog.setWindowTitle(title or "操作提示")
    dialog.setModal(True)
    dialog.setMinimumSize(420, 200)

    layout = QVBoxLayout(dialog)
    label = QLabel(message or "")
    label.setWordWrap(True)
    label.setFont(QFont("Microsoft YaHei", 12))
    layout.addWidget(label)

    layout.addStretch(1)

    button_layout = QHBoxLayout()
    button_layout.addStretch(1)

    confirm_button = QPushButton(confirm_text or "确认")
    confirm_button.setDefault(True)
    confirm_button.clicked.connect(dialog.accept)
    button_layout.addWidget(confirm_button)

    if allow_cancel and cancel_text:
        cancel_button = QPushButton(cancel_text)
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_button)

    layout.addLayout(button_layout)

    return dialog.exec() == QDialog.Accepted


def _show_pass_fail_dialog(
    title: str,
    message: str,
    pass_text: str,
    fail_text: str,
    cancel_text: str,
    allow_cancel: bool,
) -> str | None:
    """在主线程显示「成功/失败/取消」三选一。"""
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
    from PySide6.QtGui import QFont

    parent_window = _find_parent_window()
    dialog = QDialog(parent_window)
    dialog.setWindowTitle(title or "MES上传")
    dialog.setModal(True)
    dialog.setMinimumSize(440, 220)

    layout = QVBoxLayout(dialog)
    label = QLabel(message or "")
    label.setWordWrap(True)
    label.setFont(QFont("Microsoft YaHei", 12))
    layout.addWidget(label)
    layout.addStretch(1)

    outcome: dict[str, str | None] = {"v": None}

    def on_pass() -> None:
        outcome["v"] = "PASS"
        dialog.accept()

    def on_fail() -> None:
        outcome["v"] = "FAIL"
        dialog.accept()

    button_layout = QHBoxLayout()
    button_layout.addStretch(1)
    pass_btn = QPushButton(pass_text or "PASS")
    pass_btn.setDefault(True)
    pass_btn.clicked.connect(on_pass)
    fail_btn = QPushButton(fail_text or "FAIL")
    fail_btn.clicked.connect(on_fail)
    button_layout.addWidget(pass_btn)
    button_layout.addWidget(fail_btn)
    if allow_cancel and cancel_text:
        cancel_btn = QPushButton(cancel_text)
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
    layout.addLayout(button_layout)

    if dialog.exec() != QDialog.Accepted:
        return None
    return outcome["v"]


def _show_countdown_dialog(
    title: str,
    message: str,
    duration_ms: int,
    allow_interrupt: bool = False,
    *,
    completion_buttons: bool = False,
    ok_button_text: str = "煲机无异常",
    abnormal_button_text: str = "煲机异常",
) -> Tuple[bool, str]:
    """在主线程显示倒计时对话框。

    返回 ``(accepted, outcome)``：``accepted`` 为是否正常结束；``outcome`` 在
    ``completion_buttons=False`` 且正常结束时为空字符串；在煲机双按钮模式下为
    ``\"ok\"`` 或 ``\"abnormal\"``。「煲机异常」可随时点击；「煲机无异常」须待倒计时结束方可点。
    关闭窗口（允许中断时）为 ``(False, \"\")``。
    """
    from time import monotonic

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QDialog,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QVBoxLayout,
    )

    safe_duration_ms = max(0, int(duration_ms))
    parent_window = _find_parent_window()

    dialog = QDialog(parent_window)
    dialog.setWindowTitle(title or "倒计时")
    dialog.setModal(True)
    dialog.setMinimumSize(460, 280)
    dialog.setWindowFlag(Qt.WindowCloseButtonHint, bool(allow_interrupt))

    layout = QVBoxLayout(dialog)

    label = QLabel()
    label.setWordWrap(True)
    label.setFont(QFont("Microsoft YaHei", 12))
    layout.addWidget(label)

    countdown_label = QLabel()
    countdown_label.setAlignment(Qt.AlignCenter)
    countdown_label.setFont(QFont("Consolas", 24))
    layout.addWidget(countdown_label)

    outcome_holder: dict[str, str] = {"v": ""}

    ok_btn = QPushButton(ok_button_text or "煲机无异常")
    abnormal_btn = QPushButton(abnormal_button_text or "煲机异常")
    if completion_buttons:
        ok_btn.setEnabled(False)
        abnormal_btn.setEnabled(True)
    else:
        ok_btn.setEnabled(False)
        abnormal_btn.setEnabled(False)

    timer = QTimer(dialog)
    timer.setInterval(200)

    def on_ok_click() -> None:
        timer.stop()
        outcome_holder["v"] = "ok"
        dialog.accept()

    def on_abnormal_click() -> None:
        timer.stop()
        outcome_holder["v"] = "abnormal"
        dialog.accept()

    ok_btn.clicked.connect(on_ok_click)
    abnormal_btn.clicked.connect(on_abnormal_click)

    button_row = QHBoxLayout()
    button_row.addStretch(1)
    button_row.addWidget(ok_btn)
    button_row.addWidget(abnormal_btn)
    button_row.addStretch(1)
    layout.addLayout(button_row)

    if not completion_buttons:
        ok_btn.hide()
        abnormal_btn.hide()

    layout.addStretch(1)

    start_time = monotonic()

    def update_label() -> None:
        elapsed_ms = int((monotonic() - start_time) * 1000)
        remaining_ms = max(0, safe_duration_ms - elapsed_ms)
        remaining_seconds = (remaining_ms + 999) // 1000
        mmss_text = f"{remaining_seconds // 60:02d}:{remaining_seconds % 60:02d}"
        label.setText(_render_countdown_message(message, remaining_seconds, mmss_text))
        countdown_label.setText(mmss_text)

        if remaining_ms <= 0:
            timer.stop()
            if not completion_buttons:
                dialog.accept()
            else:
                ok_btn.setEnabled(True)
                label.setText(
                    (message or "")
                    + "\n\n倒计时已结束，请选择煲机结果后点击对应按钮（无异常 / 异常均会继续后续拉取数据）。"
                )
                countdown_label.setText("00:00")

    timer.timeout.connect(update_label)
    update_label()
    timer.start()

    app = QApplication.instance()
    if app is not None:
        try:
            app.aboutToQuit.connect(dialog.close)
        except Exception:
            pass

    accepted = dialog.exec() == QDialog.Accepted
    if not accepted:
        return False, ""
    if completion_buttons:
        oc = outcome_holder["v"].strip()
        if oc not in ("ok", "abnormal"):
            return False, ""
        return True, oc
    return True, ""


def invoke_in_gui_countdown(
    title: str,
    message: str,
    duration_ms: int,
    port: str = "PortA",
    *,
    allow_interrupt: bool = False,
    completion_buttons: bool = False,
    ok_button_text: str = "煲机无异常",
    abnormal_button_text: str = "煲机异常",
) -> Tuple[bool, str]:
    """在主线程显示倒计时提示框。

    返回 ``(accepted, outcome)``。``outcome`` 为 ``\"\"``、``\"ok\"`` 或 ``\"abnormal\"``（见
    :func:`_show_countdown_dialog`；「煲机异常」可随时点，「煲机无异常」须倒计时结束）。兼容旧调用：仅判断 ``result[0]`` 即等价于原 bool。
    """
    from PySide6.QtCore import QEventLoop, QThread, Signal

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication 未初始化")

    current_thread = QThread.currentThread()
    main_thread = app.thread()

    if current_thread == main_thread:
        return _show_countdown_dialog(
            title,
            message,
            duration_ms,
            allow_interrupt,
            completion_buttons=completion_buttons,
            ok_button_text=ok_button_text,
            abnormal_button_text=abnormal_button_text,
        )

    class CountdownHelper(QObject):
        finished = Signal(bool, str)

        @Slot(str, str, int, bool, bool, str, str)
        def show_dialog(
            self,
            dlg_title: str,
            dlg_message: str,
            dlg_duration_ms: int,
            dlg_allow_interrupt: bool,
            dlg_completion_buttons: bool,
            dlg_ok_text: str,
            dlg_abnormal_text: str,
        ) -> None:
            try:
                ok, oc = _show_countdown_dialog(
                    dlg_title,
                    dlg_message,
                    dlg_duration_ms,
                    dlg_allow_interrupt,
                    completion_buttons=dlg_completion_buttons,
                    ok_button_text=dlg_ok_text,
                    abnormal_button_text=dlg_abnormal_text,
                )
            except Exception:
                ok, oc = False, ""
            self.finished.emit(ok, oc or "")

    helper = CountdownHelper()
    helper.moveToThread(main_thread)

    loop = QEventLoop()
    result_holder: dict[str, bool | str] = {"ok": False, "outcome": ""}

    def on_finished(accepted: bool, outcome: str) -> None:
        result_holder["ok"] = accepted
        result_holder["outcome"] = outcome or ""
        loop.quit()

    helper.finished.connect(on_finished)

    QMetaObject.invokeMethod(
        helper,
        "show_dialog",
        Qt.QueuedConnection,
        Q_ARG(str, title),
        Q_ARG(str, message),
        Q_ARG(int, int(duration_ms)),
        Q_ARG(bool, bool(allow_interrupt)),
        Q_ARG(bool, bool(completion_buttons)),
        Q_ARG(str, ok_button_text or "煲机无异常"),
        Q_ARG(str, abnormal_button_text or "煲机异常"),
    )

    loop.exec()
    return bool(result_holder["ok"]), str(result_holder.get("outcome") or "")


def invoke_in_gui_confirmation(
    title: str,
    message: str,
    confirm_text: str = "确认",
    cancel_text: str = "取消",
    port: str = "PortA",
    allow_cancel: bool = True,
) -> bool:
    """
    在主线程显示自定义确认提示框并返回是否点击确认。
    """
    from PySide6.QtCore import QThread, QEventLoop, QObject, Signal

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication 未初始化")

    current_thread = QThread.currentThread()
    main_thread = app.thread()

    if current_thread == main_thread:
        return _show_instruction_dialog(title, message, confirm_text, cancel_text, allow_cancel)

    class ConfirmHelper(QObject):
        finished = Signal(bool)

        @Slot(str, str, str, str, bool)
        def show_dialog(self, dlg_title, dlg_message, dlg_confirm, dlg_cancel, dlg_allow_cancel):
            try:
                result = _show_instruction_dialog(dlg_title, dlg_message, dlg_confirm, dlg_cancel, dlg_allow_cancel)
            except Exception:
                result = False
            self.finished.emit(result)

    helper = ConfirmHelper()
    helper.moveToThread(main_thread)

    loop = QEventLoop()
    result_holder = {"result": False}

    def on_finished(res: bool):
        result_holder["result"] = res
        loop.quit()

    helper.finished.connect(on_finished)

    QMetaObject.invokeMethod(
        helper,
        "show_dialog",
        Qt.QueuedConnection,
        Q_ARG(str, title),
        Q_ARG(str, message),
        Q_ARG(str, confirm_text or "确认"),
        Q_ARG(str, cancel_text or ""),
        Q_ARG(bool, allow_cancel),
    )

    loop.exec()
    return result_holder["result"]


def invoke_in_gui_pass_fail_choice(
    title: str = "MES上传结果",
    message: str = "请选择本次上传为测试通过或失败：",
    pass_text: str = "上传成功(PASS)",
    fail_text: str = "上传失败(FAIL)",
    cancel_text: str = "取消",
    port: str = "PortA",
    allow_cancel: bool = True,
) -> str | None:
    """在主线程弹出 PASS/FAIL 选择框。"""
    from PySide6.QtCore import QThread, QEventLoop, QObject, Signal

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication 未初始化")

    current_thread = QThread.currentThread()
    main_thread = app.thread()
    if current_thread == main_thread:
        return _show_pass_fail_dialog(title, message, pass_text, fail_text, cancel_text, allow_cancel)

    class ChoiceHelper(QObject):
        finished = Signal(object)

        @Slot(str, str, str, str, str, bool)
        def show_dialog(self, dlg_title, dlg_message, dlg_pass, dlg_fail, dlg_cancel, dlg_allow_cancel):
            try:
                result = _show_pass_fail_dialog(
                    dlg_title,
                    dlg_message,
                    dlg_pass,
                    dlg_fail,
                    dlg_cancel,
                    dlg_allow_cancel,
                )
            except Exception:
                result = None
            self.finished.emit(result)

    helper = ChoiceHelper()
    helper.moveToThread(main_thread)

    loop = QEventLoop()
    result_holder = {"result": None}

    def on_finished(res):
        result_holder["result"] = res
        loop.quit()

    helper.finished.connect(on_finished)
    QMetaObject.invokeMethod(
        helper,
        "show_dialog",
        Qt.QueuedConnection,
        Q_ARG(str, title),
        Q_ARG(str, message),
        Q_ARG(str, pass_text),
        Q_ARG(str, fail_text),
        Q_ARG(str, cancel_text),
        Q_ARG(bool, allow_cancel),
    )
    loop.exec()
    return result_holder["result"]

