"""
扫描序列号测试步骤

实现弹出一个对话框，通过扫描器或手动输入产品序列号。
"""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
from PySide6.QtCore import Qt, QTimer
from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any


class ScanSNDialog(QDialog):
    """扫描SN对话框"""
    
    def __init__(self, parent=None, title="扫描序列号", instruction="请扫描或手动输入产品序列号"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(400, 200)
        
        # 布局
        layout = QVBoxLayout(self)
        
        # 说明文字
        self.instruction_label = QLabel(instruction)
        self.instruction_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.instruction_label)
        
        # 输入框
        self.sn_input = QLineEdit()
        self.sn_input.setPlaceholderText("请输入或扫描序列号...")
        self.sn_input.returnPressed.connect(self.accept_input)
        layout.addWidget(self.sn_input)
        
        # 按钮
        button_layout = QHBoxLayout()
        
        self.scan_button = QPushButton("扫描")
        self.scan_button.clicked.connect(self.start_scan)
        button_layout.addWidget(self.scan_button)
        
        self.manual_button = QPushButton("手动输入")
        self.manual_button.clicked.connect(self.accept_input)
        button_layout.addWidget(self.manual_button)
        
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        # 结果
        self.sn_result = None
        
        # 自动聚焦到输入框
        self.sn_input.setFocus()
    
    def start_scan(self):
        """开始扫描（模拟）"""
        self.instruction_label.setText("请将扫描器对准条码...")
        self.scan_button.setEnabled(False)
        
        # 模拟扫描延迟
        QTimer.singleShot(1000, self.simulate_scan)
    
    def simulate_scan(self):
        """模拟扫描结果"""
        # 这里可以集成真实的扫描器SDK
        # 现在只是模拟一个随机SN
        import random
        import string
        
        # 生成模拟SN
        sn = "SN" + ''.join(random.choices(string.digits, k=8))
        self.sn_input.setText(sn)
        self.instruction_label.setText(f"扫描成功: {sn}")
        self.scan_button.setEnabled(True)
    
    def accept_input(self):
        """接受输入"""
        sn = self.sn_input.text().strip()
        if not sn:
            QMessageBox.warning(self, "警告", "请输入序列号")
            return
        
        self.sn_result = sn
        self.accept()
    
    def get_sn(self) -> str:
        """获取扫描的SN"""
        return self.sn_result or ""


class ScanSNStep(BaseStep):
    """扫描序列号步骤"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行SN扫描
        
        参数示例：
        - dialog_title: 对话框标题 (默认 "扫描序列号")
        - instruction: 说明文字 (默认 "请扫描或手动输入产品序列号")
        - validate_regex: 验证正则表达式 (可选)
        - timeout_seconds: 对话框超时时间 (默认 60秒)
        """
        dialog_title = self.get_param_str(params, "dialog_title", "扫描序列号")
        instruction = self.get_param_str(params, "instruction", "请扫描或手动输入产品序列号")
        validate_regex = self.get_param_str(params, "validate_regex", "")
        timeout_seconds = self.get_param_int(params, "timeout_seconds", 60)
        
        ctx.log_info("开始扫描序列号")
        
        try:
            # 在主线程阻塞显示对话框
            from src.app.ui_invoker import invoke_in_gui_show_scan_sn
            accepted, sn = invoke_in_gui_show_scan_sn(
                title=dialog_title,
                hint=instruction,
                regex=validate_regex or "^[A-Za-z0-9_-]{1,64}$",
                timeout_ms=timeout_seconds * 1000 if timeout_seconds > 0 else 0,
            )
            
            if accepted:
                
                # 验证SN格式
                if validate_regex:
                    import re
                    if not re.match(validate_regex, sn):
                        error_msg = f"序列号格式不正确: {sn} (期望格式: {validate_regex})"
                        ctx.log_error(error_msg)
                        return self.create_failure_result(error_msg)
                
                # 设置SN到上下文
                ctx.set_sn(sn)
                
                # 构建结果数据
                result_data = {
                    "sn": sn,
                    "scan_method": "dialog",
                    "validation_passed": True
                }
                
                message = f"序列号扫描成功: {sn}"
                ctx.log_info(message)
                return self.create_success_result(result_data, message)
            else:
                error_msg = "用户取消了序列号扫描"
                ctx.log_warning(error_msg)
                return self.create_failure_result(error_msg)
                
        except Exception as e:
            error_msg = f"序列号扫描异常: {e}"
            ctx.log_error(error_msg)
            return self.create_failure_result(error_msg)
