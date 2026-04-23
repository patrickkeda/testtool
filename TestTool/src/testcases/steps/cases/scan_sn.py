"""
扫描SN测试用例

功能：
1. 弹出对话框让用户输入或扫描条码
2. 验证条码格式是否符合既定规则
3. 将SN保存到测试上下文中
"""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QApplication
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from ...base import BaseStep, StepResult
from ...context import Context
from ...libs.common.validators import validate_sn_format
from typing import Dict, Any
import re

# 全局对话框位置管理器
_dialog_positions = {}


class ScanSNDialog(QDialog):
    """扫描SN对话框"""
    
    # 定义信号
    sn_entered = Signal(str)  # SN输入完成信号
    
    def __init__(self, parent=None, title="扫描/输入产品SN", hint="请用扫码枪扫描或手动输入后回车",
                 regex="^[A-Z0-9_-]{6,64}$", timeout_ms=60000, port="PortA", main_window=None):
        super().__init__(parent)
        self.title = title
        self.hint = hint
        self.regex = regex
        self.timeout_ms = timeout_ms
        self.port = port
        self.main_window = main_window
        self.sn_result = None

        # 设置窗口标题，明确标明端口
        self.setWindowTitle(f"{title} - {port}")

        self.setup_ui()
        self.setup_timer()
        self.setup_position()
        
    def setup_ui(self):
        """设置UI界面"""
        # 窗口标题已在__init__中设置，这里不需要重复设置
        self.resize(400, 200)
        
        # 设置窗口标志 - 简化，避免跨线程问题
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        
        # 主布局
        layout = QVBoxLayout()
        
        # 提示标签
        hint_label = QLabel(self.hint)
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setFont(QFont("Arial", 10))
        layout.addWidget(hint_label)
        
        # 输入框
        self.sn_input = QLineEdit()
        self.sn_input.setPlaceholderText("请输入或扫描SN...")
        self.sn_input.setFont(QFont("Arial", 12))
        # 输入法/输入限制：尽量使用英文（字母数字），并偏向大写
        try:
            self.sn_input.setInputMethodHints(
                Qt.ImhLatinOnly | Qt.ImhNoPredictiveText | Qt.ImhPreferUppercase
            )
        except Exception:
            pass
        self.sn_input.returnPressed.connect(self.on_sn_entered)
        self.sn_input.textChanged.connect(self.on_text_changed)
        layout.addWidget(self.sn_input)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 确定按钮
        self.ok_button = QPushButton("确定")
        self.ok_button.setEnabled(False)
        self.ok_button.clicked.connect(self.on_ok_clicked)
        button_layout.addWidget(self.ok_button)
        
        # 取消按钮
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.on_cancel_clicked)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # 状态标签
        self.status_label = QLabel("等待输入...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: blue;")
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        
        # 设置焦点到输入框：仅做 Qt 本地焦点处理，不再调用系统级输入法切换，
        # 避免在部分部署电脑上触发整机消息循环卡顿。
        QTimer.singleShot(0, self._focus_input)

    def _focus_input(self):
        """将焦点放到 SN 输入框。"""
        try:
            self.sn_input.setFocus(Qt.ActiveWindowFocusReason)
            self.sn_input.activateWindow()
        except Exception:
            pass
        
    def setup_timer(self):
        """设置超时定时器"""
        # 暂时禁用超时功能，避免跨线程问题
        # 用户可以通过取消按钮手动关闭对话框
        self.timer = None
        
    def setup_position(self):
        """设置对话框位置"""
        try:
            # 使用智能定位策略避免重叠
            x, y = self._calculate_position()
            self.move(x, y)
            
            # 记录当前对话框位置
            global _dialog_positions
            _dialog_positions[self.port] = (x, y)
            
            print(f"[{self.port}] 对话框位置设置完成: ({x}, {y})")
            print(f"[{self.port}] 当前所有对话框位置: {_dialog_positions}")
            
        except Exception as e:
            print(f"设置对话框位置失败: {e}")
            # 使用默认位置
            pass
        
        # 不强制激活，避免后创建的对话框抢占焦点
        
    def _calculate_position(self):
        """计算对话框位置，避免重叠"""
        global _dialog_positions
        
        # 对话框尺寸
        dialog_width = 400
        dialog_height = 200
        
        # 获取屏幕尺寸
        screen = QApplication.primaryScreen()
        if not screen:
            return 100, 100
            
        screen_geometry = screen.availableGeometry()
        
        # 基础位置 - 使用更大的偏移避免重叠
        if "PortA" in self.port or "A" in self.port:
            # PortA 显示在屏幕左侧
            base_x = screen_geometry.x() + 50
            base_y = screen_geometry.y() + 100
        else:
            # PortB 显示在屏幕右侧，增加更大的垂直偏移
            base_x = screen_geometry.x() + screen_geometry.width() // 2 + 50
            base_y = screen_geometry.y() + 300  # 增加200像素的垂直偏移
        
        # 检查是否有其他对话框，避免重叠
        x, y = base_x, base_y
        max_attempts = 10
        attempt = 0
        
        print(f"[{self.port}] 计算位置: 基础位置=({base_x}, {base_y}), 现有对话框={_dialog_positions}")
        
        while attempt < max_attempts:
            # 检查当前位置是否与其他对话框重叠
            overlap = False
            for port, (other_x, other_y) in _dialog_positions.items():
                if port != self.port:
                    # 检查矩形重叠 - 使用更严格的重叠检测
                    if (x < other_x + dialog_width and 
                        x + dialog_width > other_x and
                        y < other_y + dialog_height and 
                        y + dialog_height > other_y):
                        overlap = True
                        print(f"[{self.port}] 检测到与 {port} 重叠: 当前位置=({x}, {y}), 其他位置=({other_x}, {other_y})")
                        break
            
            if not overlap:
                print(f"[{self.port}] 找到无重叠位置: ({x}, {y})")
                break
                
            # 如果有重叠，调整位置
            if "PortA" in self.port or "A" in self.port:
                # PortA 向下移动
                y += dialog_height + 50  # 增加间距
            else:
                # PortB 向下移动
                y += dialog_height + 50  # 增加间距
                
            # 确保不超出屏幕边界
            if y + dialog_height > screen_geometry.y() + screen_geometry.height():
                y = base_y  # 重置到基础位置
                x += dialog_width + 50  # 水平移动，增加间距
                
            attempt += 1
            print(f"[{self.port}] 尝试 {attempt}: 新位置=({x}, {y})")
        
        if attempt >= max_attempts:
            print(f"[{self.port}] 警告: 达到最大尝试次数，使用最后位置=({x}, {y})")
        
        return x, y
        
    def _cleanup_position(self):
        """清理对话框位置记录"""
        global _dialog_positions
        if self.port in _dialog_positions:
            print(f"[{self.port}] 清理对话框位置记录")
            del _dialog_positions[self.port]
            print(f"[{self.port}] 清理后剩余对话框位置: {_dialog_positions}")
        
    def _delayed_activate(self):
        """延迟激活对话框"""
        try:
            self.raise_()
            self.activateWindow()
        except Exception as e:
            print(f"激活对话框失败: {e}")
            
    def on_text_changed(self, text):
        """输入文本变化时的处理"""
        if text.strip():
            self.ok_button.setEnabled(True)
            self.status_label.setText("输入完成，按回车或点击确定")
            self.status_label.setStyleSheet("color: green;")
        else:
            self.ok_button.setEnabled(False)
            self.status_label.setText("等待输入...")
            self.status_label.setStyleSheet("color: blue;")
            
    def on_sn_entered(self):
        """回车键处理"""
        self.on_ok_clicked()
        
    def on_cancel_clicked(self):
        """取消按钮处理"""
        self._cleanup_position()
        self.reject()
        
    def on_ok_clicked(self):
        """确定按钮处理"""
        sn = self.sn_input.text().strip()
        if sn:
            self.sn_result = sn
            self.sn_entered.emit(sn)
            self._cleanup_position()
            self.accept()
        else:
            QMessageBox.warning(self, "警告", "请输入有效的SN")
            
    def on_timeout(self):
        """超时处理"""
        self.status_label.setText("输入超时")
        self.status_label.setStyleSheet("color: red;")
        self._cleanup_position()
        self.reject()
        
    def get_sn(self) -> str:
        """获取扫描的SN"""
        return self.sn_result or ""


class ScanSNStep(BaseStep):
    """扫描SN测试用例"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行SN扫描测试
        
        参数示例：
        - dialog_title: 对话框标题 (默认 "扫描/输入产品SN")
        - hint: 提示信息 (默认 "请用扫码枪扫描或手动输入后回车")
        - regex: 验证正则表达式 (默认 "^[A-Z0-9_-]{6,64}$")
        - timeout_ms: 超时时间(毫秒) (默认 60000)
        - allow_manual: 是否允许手动输入 (默认 True)
        """
        try:
            # 1) 读取参数
            dialog_title = params.get("dialog_title", "扫描/输入产品SN")
            hint = params.get("hint", "请用扫码枪扫描或手动输入后回车")
            regex = params.get("regex", "^[A-Z0-9_-]{6,64}$")
            timeout_ms = int(params.get("timeout_ms", 60000))
            allow_manual = bool(params.get("allow_manual", True))
            
            ctx.log_info(f"开始SN扫描测试: 标题='{dialog_title}', 超时={timeout_ms}ms")
            
            # 2) 在主线程阻塞显示对话框
            ctx.log_info(f"[{ctx.port}] 准备导入UI调用器...")
            from src.app.ui_invoker import invoke_in_gui_show_scan_sn
            ctx.log_info(f"[{ctx.port}] UI调用器导入成功")
            ctx.log_info(f"[{ctx.port}] 显示SN输入对话框...")
            
            # 获取主窗口引用
            main_window = None
            try:
                app = QApplication.instance()
                if app:
                    # 查找主窗口
                    for widget in app.allWidgets():
                        if hasattr(widget, 'windowTitle') and 'TestTool' in widget.windowTitle():
                            main_window = widget
                            break
            except Exception as e:
                ctx.log_warning(f"无法获取主窗口引用: {e}")
            
            accepted, sn = invoke_in_gui_show_scan_sn(
                title=dialog_title,
                hint=hint,
                regex=regex,
                timeout_ms=timeout_ms,
                port=ctx.port,
                main_window=main_window,
            )
            
            if accepted:
                ctx.log_info(f"用户输入SN: {sn}")
                
                # 4) 验证SN格式
                is_valid, error_msg = validate_sn_format(sn, regex)
                
                if is_valid:
                    # 5) 保存SN到上下文
                    ctx.set_sn(sn)
                    ctx.log_info(f"SN验证通过: {sn}")
                    
                    # 6) 构建成功结果
                    result_data = {
                        "sn": sn,
                        "regex": regex,
                        "input_method": "manual" if allow_manual else "scanner"
                    }
                    
                    message = f"SN扫描成功: {sn}"
                    return self.create_success_result(result_data, message)
                else:
                    # 7) 格式验证失败
                    ctx.log_error(f"SN格式验证失败: {error_msg}")
                    return self.create_failure_result(f"SN格式不符合要求: {error_msg}")
            else:
                # 8) 用户取消或超时
                ctx.log_warning("SN输入被取消或超时")
                return self.create_failure_result("SN输入被取消或超时")
                
        except Exception as e:
            ctx.log_error(f"SN扫描测试执行异常: {e}", exc_info=True)
            return self.create_failure_result(f"SN扫描测试执行异常: {e}", error=str(e))
