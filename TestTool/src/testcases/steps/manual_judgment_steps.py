"""
人工判断步骤实现
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextEdit, QRadioButton, QButtonGroup, QSlider, QSpinBox,
    QGroupBox, QScrollArea, QWidget, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QPixmap

from ..step import BaseStep, StepResult
from ..config import ManualJudgmentStepConfig, StateControlConfig, JudgmentConfig
from ..context import TestContext
from .at_steps import ATCommunicator

logger = logging.getLogger(__name__)


class ManualJudgmentWindow(QDialog):
    """人工判断窗口"""
    
    judgment_completed = Signal(str)  # 判断完成信号
    
    def __init__(self, step_config, test_description: str, test_instructions: List[str], 
                 judgment_config: JudgmentConfig, parent=None):
        super().__init__(parent)
        self.step_config = step_config
        self.test_description = test_description
        self.test_instructions = test_instructions
        self.judgment_config = judgment_config
        self.judgment_result = None
        
        self.setWindowTitle("人工判断测试")
        self.setModal(True)
        self.setMinimumSize(600, 500)
        
        self._init_ui()
        self._setup_timer()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        
        # 测试描述
        desc_group = QGroupBox("测试描述")
        desc_layout = QVBoxLayout(desc_group)
        
        desc_label = QLabel(self.test_description)
        desc_label.setWordWrap(True)
        desc_label.setFont(QFont("Arial", 12, QFont.Bold))
        desc_layout.addWidget(desc_label)
        
        layout.addWidget(desc_group)
        
        # 测试指导
        if self.test_instructions:
            inst_group = QGroupBox("测试指导")
            inst_layout = QVBoxLayout(inst_group)
            
            for i, instruction in enumerate(self.test_instructions, 1):
                inst_label = QLabel(f"{i}. {instruction}")
                inst_label.setWordWrap(True)
                inst_layout.addWidget(inst_label)
            
            layout.addWidget(inst_group)
        
        # 判断区域
        judgment_group = QGroupBox("判断结果")
        judgment_layout = QVBoxLayout(judgment_group)
        
        if self.judgment_config.type == "simple":
            self._setup_simple_judgment(judgment_layout)
        elif self.judgment_config.type == "multi_choice":
            self._setup_multi_choice_judgment(judgment_layout)
        elif self.judgment_config.type == "rating":
            self._setup_rating_judgment(judgment_layout)
        else:
            self._setup_custom_judgment(judgment_layout)
        
        layout.addWidget(judgment_group)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        
        self.btn_pass = QPushButton("PASS")
        self.btn_pass.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 10px; }")
        self.btn_pass.clicked.connect(lambda: self._complete_judgment("PASS"))
        
        self.btn_fail = QPushButton("FAIL")
        self.btn_fail.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-weight: bold; padding: 10px; }")
        self.btn_fail.clicked.connect(lambda: self._complete_judgment("FAIL"))
        
        self.btn_retry = QPushButton("重试")
        self.btn_retry.setStyleSheet("QPushButton { background-color: #ff9800; color: white; font-weight: bold; padding: 10px; }")
        self.btn_retry.clicked.connect(lambda: self._complete_judgment("RETRY"))
        
        self.btn_skip = QPushButton("跳过")
        self.btn_skip.setStyleSheet("QPushButton { background-color: #9e9e9e; color: white; font-weight: bold; padding: 10px; }")
        self.btn_skip.clicked.connect(lambda: self._complete_judgment("SKIP"))
        
        button_layout.addWidget(self.btn_pass)
        button_layout.addWidget(self.btn_fail)
        button_layout.addWidget(self.btn_retry)
        button_layout.addWidget(self.btn_skip)
        
        layout.addLayout(button_layout)
    
    def _setup_simple_judgment(self, layout):
        """设置简单判断UI"""
        self.button_group = QButtonGroup()
        
        pass_radio = QRadioButton("PASS - 测试通过")
        fail_radio = QRadioButton("FAIL - 测试失败")
        
        self.button_group.addButton(pass_radio, 0)
        self.button_group.addButton(fail_radio, 1)
        
        layout.addWidget(pass_radio)
        layout.addWidget(fail_radio)
        
        # 默认选择PASS
        pass_radio.setChecked(True)
    
    def _setup_multi_choice_judgment(self, layout):
        """设置多选项判断UI"""
        self.button_group = QButtonGroup()
        
        if self.judgment_config.options:
            for i, option in enumerate(self.judgment_config.options):
                radio = QRadioButton(option.get("text", f"选项 {i+1}"))
                self.button_group.addButton(radio, i)
                layout.addWidget(radio)
        else:
            # 默认选项
            options = [
                {"text": "PASS - 测试通过", "value": "PASS"},
                {"text": "FAIL - 测试失败", "value": "FAIL"},
                {"text": "FAIL - 屏幕不亮", "value": "FAIL_NO_DISPLAY"},
                {"text": "FAIL - 颜色错误", "value": "FAIL_WRONG_COLOR"},
                {"text": "FAIL - 显示不均匀", "value": "FAIL_UNEVEN"}
            ]
            
            for i, option in enumerate(options):
                radio = QRadioButton(option["text"])
                self.button_group.addButton(radio, i)
                layout.addWidget(radio)
        
        # 默认选择第一个选项
        if self.button_group.buttons():
            self.button_group.buttons()[0].setChecked(True)
    
    def _setup_rating_judgment(self, layout):
        """设置评分判断UI"""
        rating_label = QLabel("请给出评分:")
        rating_label.setFont(QFont("Arial", 10, QFont.Bold))
        layout.addWidget(rating_label)
        
        # 评分滑块
        self.rating_slider = QSlider(Qt.Horizontal)
        min_rating = self.judgment_config.min_rating or 1
        max_rating = self.judgment_config.max_rating or 5
        self.rating_slider.setMinimum(min_rating)
        self.rating_slider.setMaximum(max_rating)
        self.rating_slider.setValue(min_rating)
        layout.addWidget(self.rating_slider)
        
        # 评分显示
        self.rating_display = QLabel(f"评分: {min_rating}")
        self.rating_slider.valueChanged.connect(
            lambda v: self.rating_display.setText(f"评分: {v}")
        )
        layout.addWidget(self.rating_display)
    
    def _setup_custom_judgment(self, layout):
        """设置自定义判断UI"""
        # 自定义判断可以扩展
        custom_label = QLabel("自定义判断选项")
        layout.addWidget(custom_label)
        
        # 这里可以根据需要添加更多自定义UI元素
        self._setup_simple_judgment(layout)  # 默认使用简单判断
    
    def _setup_timer(self):
        """设置定时器"""
        # 可以添加超时处理
        pass
    
    def _complete_judgment(self, result: str):
        """完成判断"""
        if self.judgment_config.type == "multi_choice":
            # 获取选中的选项
            selected_button = self.button_group.checkedButton()
            if selected_button:
                button_id = self.button_group.id(selected_button)
                if self.judgment_config.options and button_id < len(self.judgment_config.options):
                    self.judgment_result = self.judgment_config.options[button_id].get("value", result)
                else:
                    self.judgment_result = result
            else:
                self.judgment_result = result
        elif self.judgment_config.type == "rating":
            # 获取评分
            rating = self.rating_slider.value()
            self.judgment_result = f"RATING_{rating}"
        else:
            self.judgment_result = result
        
        self.judgment_completed.emit(self.judgment_result)
        self.accept()
    
    def get_judgment_result(self) -> str:
        """获取判断结果"""
        return self.judgment_result


class ManualJudgmentStep(BaseStep):
    """人工判断步骤"""
    
    def __init__(self, step_id: str, step_name: str, params: Dict[str, Any]):
        super().__init__(step_id, step_name, params)
        self.at_comm = None
        
    async def prepare(self, context: TestContext) -> bool:
        """准备人工判断步骤"""
        if not await super().prepare(context):
            return False
            
        # 初始化AT通信器
        self.at_comm = ATCommunicator(context.comm_manager)
        
        # 检查必要参数
        state_control = self.get_param("state_control")
        if not state_control or not state_control.get("at_command"):
            self.log_error("状态控制AT指令不能为空")
            return False
            
        test_description = self.get_param("test_description")
        if not test_description:
            self.log_error("测试描述不能为空")
            return False
            
        return True
    
    async def execute(self, context: TestContext) -> StepResult:
        """执行人工判断步骤"""
        try:
            # 1. 执行状态控制
            state_control = self.get_param("state_control")
            at_command = state_control["at_command"]
            port = self.get_param("port", "A")
            timeout = self.get_param("timeout", 5.0)
            
            self.log_info(f"执行状态控制: {at_command}")
            await self.at_comm.send_command(at_command, port, timeout)
            
            # 2. 等待状态稳定
            stabilization_time = state_control.get("stabilization_time", 1000)
            self.log_info(f"等待状态稳定: {stabilization_time}ms")
            await asyncio.sleep(stabilization_time / 1000)
            
            # 3. 显示人工判断界面
            test_description = self.get_param("test_description")
            test_instructions = self.get_param("test_instructions", [])
            judgment_config = self.get_param("judgment_config")
            
            # 创建判断窗口
            judgment_window = ManualJudgmentWindow(
                step_config=self.step_config,
                test_description=test_description,
                test_instructions=test_instructions,
                judgment_config=judgment_config
            )
            
            # 显示窗口并等待结果
            if judgment_window.exec() == QDialog.Accepted:
                judgment_result = judgment_window.get_judgment_result()
                
                if judgment_result == "PASS":
                    return self.create_result(
                        success=True,
                        value=judgment_result,
                        message="人工判断通过",
                        metadata={"judgment_result": judgment_result}
                    )
                elif judgment_result == "FAIL":
                    return self.create_result(
                        success=False,
                        value=judgment_result,
                        message="人工判断失败",
                        metadata={"judgment_result": judgment_result}
                    )
                elif judgment_result == "RETRY":
                    # 重新执行
                    return await self.execute(context)
                else:  # SKIP
                    return self.create_result(
                        success=False,
                        value=judgment_result,
                        message="测试被跳过",
                        metadata={"judgment_result": judgment_result}
                    )
            else:
                return self.create_result(
                    success=False,
                    value="CANCELLED",
                    message="人工判断被取消",
                    metadata={"judgment_result": "CANCELLED"}
                )
                
        except Exception as e:
            self.log_error(f"人工判断执行失败: {e}", e)
            return self.create_result(
                success=False,
                error=str(e),
                message="人工判断执行失败"
            )
    
    async def validate(self, result: StepResult, expect) -> bool:
        """验证人工判断结果"""
        # 人工判断的验证在execute方法中已经完成
        return result.success
    
    async def cleanup(self, context: TestContext):
        """清理人工判断步骤"""
        await super().cleanup(context)


def create_manual_judgment_step(step_config) -> ManualJudgmentStep:
    """创建人工判断步骤实例
    
    Parameters
    ----------
    step_config : TestStepConfig
        步骤配置
        
    Returns
    -------
    ManualJudgmentStep
        人工判断步骤实例
    """
    # 从配置中提取参数
    if step_config.manual_judgment_config:
        config = step_config.manual_judgment_config
        params = {
            "state_control": {
                "type": config.state_control.type,
                "at_command": config.state_control.at_command,
                "parameters": config.state_control.parameters,
                "stabilization_time": config.state_control.stabilization_time
            },
            "test_description": config.test_description,
            "test_instructions": config.test_instructions,
            "judgment_config": {
                "type": config.judgment_config.type,
                "options": config.judgment_config.options,
                "min_rating": config.judgment_config.min_rating,
                "max_rating": config.judgment_config.max_rating
            },
            "timeout": config.timeout,
            "retries": config.retries
        }
    else:
        # 从传统参数中提取
        params = step_config.params
    
    return ManualJudgmentStep(
        step_id=step_config.id,
        step_name=step_config.name,
        params=params
    )
