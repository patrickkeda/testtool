"""
测试序列编辑器 - 提供可视化编辑测试序列的功能
"""

from __future__ import annotations

import os
from typing import Optional, Dict, Any, List
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTextEdit, QTabWidget,
    QPushButton, QLabel, QLineEdit, QSpinBox, QComboBox,
    QGroupBox, QFormLayout, QDialog, QDialogButtonBox,
    QFileDialog, QMessageBox, QToolBar, QScrollArea
)
from PySide6.QtGui import QAction
from PySide6.QtGui import QFont

from ...testcases.config import TestSequenceConfig, TestStepConfig, ExpectConfig, TestMetadata
from ...testcases.utils import load_test_sequence, save_test_sequence, apply_mes_debug_station_from_config


class SequenceEditor(QMainWindow):
    """测试序列编辑器主窗口"""
    
    sig_sequence_changed = Signal(TestSequenceConfig)
    sig_sequence_saved = Signal(str)  # 文件路径
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.current_sequence: Optional[TestSequenceConfig] = None
        self.current_file_path: Optional[str] = None
        self.is_modified = False
        
        self.setWindowTitle("测试序列编辑器")
        self.resize(1200, 800)
        
        self._init_ui()
        self._init_actions()
        self._init_toolbar()
        self._init_menu()
        
    def _init_ui(self):
        """初始化用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        
        # 工具栏移除：菜单已覆盖常用操作，避免重复按钮
        
        # 主分割器
        main_splitter = QSplitter(Qt.Horizontal)
        
        # 左侧：序列树和属性面板
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # 序列树
        self.sequence_tree = QTreeWidget()
        self.sequence_tree.setHeaderLabels(["步骤", "类型", "状态"])
        self.sequence_tree.itemSelectionChanged.connect(self._on_step_selected)
        left_layout.addWidget(QLabel("测试步骤"))
        left_layout.addWidget(self.sequence_tree)
        
        # 步骤操作按钮
        step_buttons = QHBoxLayout()
        self.btn_add_step = QPushButton("添加步骤")
        self.btn_remove_step = QPushButton("删除步骤")
        self.btn_move_up = QPushButton("上移")
        self.btn_move_down = QPushButton("下移")
        
        self.btn_add_step.clicked.connect(self._add_step)
        self.btn_remove_step.clicked.connect(self._remove_step)
        self.btn_move_up.clicked.connect(self._move_step_up)
        self.btn_move_down.clicked.connect(self._move_step_down)
        
        step_buttons.addWidget(self.btn_add_step)
        step_buttons.addWidget(self.btn_remove_step)
        step_buttons.addWidget(self.btn_move_up)
        step_buttons.addWidget(self.btn_move_down)
        step_buttons.addStretch()
        
        left_layout.addLayout(step_buttons)
        
        # 右侧：编辑面板
        self.edit_tabs = QTabWidget()
        
        # 可视化编辑标签页
        self.visual_editor = self._create_visual_editor()
        self.edit_tabs.addTab(self.visual_editor, "可视化编辑")
        
        # 代码编辑标签页
        self.code_editor = QTextEdit()
        self.code_editor.setFont(QFont("Consolas", 10))
        self.code_editor.textChanged.connect(self._on_code_changed)
        self.edit_tabs.addTab(self.code_editor, "代码编辑")
        
        # 添加面板到分割器
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(self.edit_tabs)
        main_splitter.setSizes([400, 800])
        
        main_layout.addWidget(main_splitter)
        
        # 状态栏
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("就绪")
        
    def _create_visual_editor(self) -> QWidget:
        """创建可视化编辑器"""
        editor = QWidget()
        layout = QVBoxLayout(editor)
        
        # 滚动区域
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # 序列基本信息
        basic_group = QGroupBox("序列信息")
        basic_layout = QFormLayout(basic_group)
        
        self.edit_name = QLineEdit()
        self.edit_description = QLineEdit()
        self.edit_author = QLineEdit()
        self.edit_product = QLineEdit()
        self.edit_station = QLineEdit()
        self.edit_version = QLineEdit()
        
        basic_layout.addRow("名称:", self.edit_name)
        basic_layout.addRow("描述:", self.edit_description)
        basic_layout.addRow("作者:", self.edit_author)
        basic_layout.addRow("产品:", self.edit_product)
        basic_layout.addRow("测试站:", self.edit_station)
        basic_layout.addRow("版本:", self.edit_version)
        
        # 连接信号
        for widget in [self.edit_name, self.edit_description, self.edit_author, 
                      self.edit_product, self.edit_station, self.edit_version]:
            widget.textChanged.connect(self._on_sequence_changed)
        
        scroll_layout.addWidget(basic_group)
        
        # 步骤编辑区域
        self.step_editor = self._create_step_editor()
        scroll_layout.addWidget(self.step_editor)
        
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        
        layout.addWidget(scroll_area)
        return editor
        
    def _create_step_editor(self) -> QGroupBox:
        """创建步骤编辑器"""
        group = QGroupBox("步骤编辑")
        layout = QFormLayout(group)
        
        # 步骤基本信息
        self.edit_step_id = QLineEdit()
        self.edit_step_name = QLineEdit()
        self.edit_step_type = QComboBox()
        self.edit_step_type.setEditable(True)
        # 禁用鼠标滚轮修改，避免误操作
        self.edit_step_type.wheelEvent = lambda event: None
        # 确保步骤在填充前已完成注册
        try:
            from ...testcases.register_steps import register_all_steps
            register_all_steps()
        except Exception:
            pass
        # 动态填充步骤类型（包括别名）
        try:
            from ...testcases.registry import list_step_types, get_registry
            step_types = list_step_types()
            aliases_map = get_registry().list_aliases()
            alias_names = list(aliases_map.keys())
            options = sorted(set(step_types + alias_names))
            if options:
                self.edit_step_type.addItems(options)
        except Exception:
            # 回退到一组基础类型，避免编辑器空白
            self.edit_step_type.addItems([
                "comm.open", "comm.close", "comm.send", "comm.receive",
                "instrument.set_voltage", "instrument.set_current", 
                "instrument.measure_voltage", "instrument.measure_current",
                "uut.read_sn", "uut.send_command", "uut.read_response",
                "mes.get_work_order", "mes.upload_result",
                "utility.delay", "utility.log",
                "scan.sn", "measure.current"
            ])
        
        layout.addRow("步骤ID:", self.edit_step_id)
        layout.addRow("步骤名称:", self.edit_step_name)
        layout.addRow("步骤类型:", self.edit_step_type)
        
        # 超时和重试
        self.edit_timeout = QSpinBox()
        self.edit_timeout.setRange(0, 300000)
        self.edit_timeout.setSuffix(" ms")
        # 禁用鼠标滚轮修改，避免误操作
        self.edit_timeout.wheelEvent = lambda event: None
        self.edit_retries = QSpinBox()
        self.edit_retries.setRange(0, 10)
        # 禁用鼠标滚轮修改，避免误操作
        self.edit_retries.wheelEvent = lambda event: None
        
        layout.addRow("超时时间:", self.edit_timeout)
        layout.addRow("重试次数:", self.edit_retries)
        
        # 失败策略
        self.edit_on_failure = QComboBox()
        self.edit_on_failure.addItems(["fail", "skip", "retry", "continue"])
        # 禁用鼠标滚轮修改，避免误操作
        self.edit_on_failure.wheelEvent = lambda event: None
        layout.addRow("失败策略:", self.edit_on_failure)
        
        # 参数编辑
        self.edit_params = QTextEdit()
        self.edit_params.setMaximumHeight(100)
        self.edit_params.setPlaceholderText("参数 (YAML格式):\nparam1: value1\nparam2: value2")
        layout.addRow("参数:", self.edit_params)
        
        # 期望结果
        expect_group = QGroupBox("期望结果")
        expect_layout = QFormLayout(expect_group)
        
        # 期望结果字段（仅测量值判定）
        self.edit_expect_unit = QLineEdit()
        self.edit_expect_low = QLineEdit()
        self.edit_expect_high = QLineEdit()
        self.edit_expect_precision = QSpinBox()
        self.edit_expect_precision.setRange(0, 6)
        # 禁用鼠标滚轮修改，避免误操作
        self.edit_expect_precision.wheelEvent = lambda event: None
        
        expect_layout.addRow("单位:", self.edit_expect_unit)
        expect_layout.addRow("下限:", self.edit_expect_low)
        expect_layout.addRow("上限:", self.edit_expect_high)
        expect_layout.addRow("小数位:", self.edit_expect_precision)
        
        layout.addRow(expect_group)
        
        # 连接信号
        for widget in [self.edit_step_id, self.edit_step_name, self.edit_step_type,
                      self.edit_timeout, self.edit_retries, self.edit_on_failure,
                      self.edit_params, self.edit_expect_unit, self.edit_expect_low, 
                      self.edit_expect_high, self.edit_expect_precision]:
            if hasattr(widget, 'textChanged'):
                widget.textChanged.connect(self._on_step_changed)
            elif hasattr(widget, 'currentTextChanged'):
                widget.currentTextChanged.connect(self._on_step_changed)
            elif hasattr(widget, 'valueChanged'):
                widget.valueChanged.connect(self._on_step_changed)
        
        return group
        
    def _init_actions(self):
        """初始化动作"""
        # 文件操作
        self.act_new = QAction("新建", self)
        self.act_open = QAction("打开", self)
        self.act_save = QAction("保存", self)
        self.act_save_as = QAction("另存为", self)
        
        self.act_new.triggered.connect(self._new_sequence)
        self.act_open.triggered.connect(self._open_sequence)
        self.act_save.triggered.connect(self._save_sequence)
        self.act_save_as.triggered.connect(self._save_sequence_as)
        
        # 编辑操作
        self.act_undo = QAction("撤销", self)
        self.act_redo = QAction("重做", self)
        self.act_cut = QAction("剪切", self)
        self.act_copy = QAction("复制", self)
        self.act_paste = QAction("粘贴", self)
        
    def _init_toolbar(self):
        """初始化工具栏"""
        # 工具栏移除：菜单已覆盖常用操作，避免重复按钮
        
    def _init_menu(self):
        """初始化菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件")
        file_menu.addAction(self.act_new)
        file_menu.addAction(self.act_open)
        file_menu.addSeparator()
        file_menu.addAction(self.act_save)
        file_menu.addAction(self.act_save_as)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)
        
        # 编辑菜单
        edit_menu = menubar.addMenu("编辑")
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_cut)
        edit_menu.addAction(self.act_copy)
        edit_menu.addAction(self.act_paste)
        
        # 工具菜单
        tools_menu = menubar.addMenu("工具")
        tools_menu.addAction("验证序列", self._validate_sequence)
        tools_menu.addAction("导入步骤库", self._import_step_library)
        tools_menu.addAction("导出步骤库", self._export_step_library)
        
    # ---- 文件操作 ----
    def _new_sequence(self):
        """新建序列"""
        if self._check_unsaved_changes():
            self._create_new_sequence()
            
    def _open_sequence(self):
        """打开序列"""
        if self._check_unsaved_changes():
            file_path, _ = QFileDialog.getOpenFileName(
                self, "打开测试序列", "", 
                "YAML文件 (*.yaml *.yml);;JSON文件 (*.json);;所有文件 (*.*)"
            )
            if file_path:
                self._load_sequence(file_path)
                
    def _save_sequence(self):
        """保存序列"""
        if self.current_file_path:
            self._save_to_file(self.current_file_path)
        else:
            self._save_sequence_as()
            
    def _save_sequence_as(self):
        """另存为序列"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存测试序列", "", 
            "YAML文件 (*.yaml);;JSON文件 (*.json)"
        )
        if file_path:
            self._save_to_file(file_path)
            
    def _check_unsaved_changes(self) -> bool:
        """检查未保存的更改"""
        if self.is_modified:
            reply = QMessageBox.question(
                self, "未保存的更改", 
                "当前序列有未保存的更改，是否保存？",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if reply == QMessageBox.Yes:
                self._save_sequence()
                return True
            elif reply == QMessageBox.Cancel:
                return False
        return True
        
    def _create_new_sequence(self):
        """创建新序列"""
        self.current_sequence = TestSequenceConfig(
            metadata=TestMetadata(
                name="新测试序列",
                description="",
                author="",
                product="",
                station=""
            )
        )
        self.current_file_path = None
        self.is_modified = False
        self._update_ui_from_sequence()
        self.status_bar.showMessage("新建序列")
        
    def _load_sequence(self, file_path: str):
        """加载序列"""
        try:
            self.current_sequence = load_test_sequence(file_path)
            self.current_file_path = file_path
            self.is_modified = False
            self._update_ui_from_sequence()
            self.status_bar.showMessage(f"已加载: {os.path.basename(file_path)}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法加载序列文件:\n{str(e)}")
            
    def _save_to_file(self, file_path: str):
        """保存到文件"""
        try:
            if self.current_sequence:
                apply_mes_debug_station_from_config(self.current_sequence)
                save_test_sequence(self.current_sequence, file_path)
                self.current_file_path = file_path
                self.is_modified = False
                self.status_bar.showMessage(f"已保存: {os.path.basename(file_path)}")
                self.sig_sequence_saved.emit(file_path)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法保存序列文件:\n{str(e)}")
            
    def _update_ui_from_sequence(self):
        """从序列更新UI"""
        if not self.current_sequence:
            return
            
        # 更新基本信息
        metadata = self.current_sequence.metadata
        self.edit_name.setText(metadata.name)
        self.edit_description.setText(metadata.description)
        self.edit_author.setText(metadata.author)
        self.edit_product.setText(metadata.product)
        self.edit_station.setText(metadata.station)
        self.edit_version.setText(metadata.version)
        
        # 更新序列树
        self.sequence_tree.clear()
        for step in self.current_sequence.steps:
            item = QTreeWidgetItem([step.name, step.type, "Pending"])
            item.setData(0, Qt.UserRole, step.id)
            self.sequence_tree.addTopLevelItem(item)
            
        # 更新代码编辑器
        self._update_code_editor()
        
    def _update_code_editor(self):
        """更新代码编辑器"""
        if self.current_sequence:
            import yaml
            data = self.current_sequence.dict()
            yaml_content = yaml.dump(data, default_flow_style=False, allow_unicode=True)
            self.code_editor.setPlainText(yaml_content)
            
    def _on_code_changed(self):
        """代码编辑器内容改变"""
        if self.edit_tabs.currentWidget() == self.code_editor:
            self.is_modified = True
            self.status_bar.showMessage("代码已修改")
            
    def _on_sequence_changed(self):
        """序列信息改变"""
        self.is_modified = True
        self.status_bar.showMessage("序列已修改")
        
    def _on_step_changed(self):
        """步骤信息改变"""
        current_item = self.sequence_tree.currentItem()
        if current_item and self.current_sequence:
            step_id = current_item.data(0, Qt.UserRole)
            step = self.current_sequence.get_step_by_id(step_id)
            if step:
                # 更新步骤对象
                step.name = self.edit_step_name.text()
                step.type = self.edit_step_type.currentText()
                step.timeout = self.edit_timeout.value()
                step.retries = self.edit_retries.value()
                step.on_failure = self.edit_on_failure.currentText()
                
                # 更新参数
                params_text = self.edit_params.toPlainText()
                if params_text:
                    try:
                        import yaml
                        step.params = yaml.safe_load(params_text) or {}
                    except Exception as e:
                        self.status_bar.showMessage(f"参数格式错误: {e}")
                
                # 更新期望结果
                if hasattr(step, 'expect') and step.expect is not None:
                    step.expect.unit = self.edit_expect_unit.text()
                    step.expect.low = self.edit_expect_low.text()
                    step.expect.high = self.edit_expect_high.text()
                    step.expect.precision = self.edit_expect_precision.value()
                
                # 更新树显示
                current_item.setText(0, step.name)
                current_item.setText(1, step.type)
                
        self.is_modified = True
        self.status_bar.showMessage("步骤已修改")
        
    def _on_step_selected(self):
        """步骤选择改变"""
        current_item = self.sequence_tree.currentItem()
        if current_item and self.current_sequence:
            step_id = current_item.data(0, Qt.UserRole)
            step = self.current_sequence.get_step_by_id(step_id)
            if step:
                self._update_step_editor(step)
                
    def _update_step_editor(self, step: TestStepConfig):
        """更新步骤编辑器"""
        self.edit_step_id.setText(step.id)
        self.edit_step_name.setText(step.name)
        self.edit_step_type.setCurrentText(step.type)
        self.edit_timeout.setValue(step.timeout or 0)
        self.edit_retries.setValue(step.retries)
        self.edit_on_failure.setCurrentText(step.on_failure)
        
        # 更新参数
        if step.params:
            import yaml
            params_text = yaml.dump(step.params, default_flow_style=False)
            self.edit_params.setPlainText(params_text)
        else:
            self.edit_params.clear()
            
        # 更新期望结果
        if step.expect:
            self.edit_expect_unit.setText(step.expect.unit or "")
            self.edit_expect_low.setText(str(step.expect.low or ""))
            self.edit_expect_high.setText(str(step.expect.high or ""))
            self.edit_expect_precision.setValue(step.expect.precision or 0)
        else:
            self.edit_expect_unit.clear()
            self.edit_expect_low.clear()
            self.edit_expect_high.clear()
            self.edit_expect_precision.setValue(0)
            
    def _add_step(self):
        """添加步骤"""
        if not self.current_sequence:
            return
            
        # 创建新步骤
        step_id = f"step_{len(self.current_sequence.steps) + 1}"
        new_step = TestStepConfig(
            id=step_id,
            name="新步骤",
            type="utility.delay"
        )
        
        self.current_sequence.steps.append(new_step)
        self._update_ui_from_sequence()
        self.is_modified = True
        
    def _remove_step(self):
        """删除步骤"""
        current_item = self.sequence_tree.currentItem()
        if current_item and self.current_sequence:
            step_id = current_item.data(0, Qt.UserRole)
            self.current_sequence.steps = [s for s in self.current_sequence.steps if s.id != step_id]
            self._update_ui_from_sequence()
            self.is_modified = True
            
    def _move_step_up(self):
        """上移步骤"""
        # TODO: 实现步骤上移
        pass
        
    def _move_step_down(self):
        """下移步骤"""
        # TODO: 实现步骤下移
        pass
        
    def _validate_sequence(self):
        """验证序列"""
        if self.current_sequence:
            errors = self.current_sequence.validate()
            if errors:
                QMessageBox.warning(self, "验证失败", "\n".join(errors))
            else:
                QMessageBox.information(self, "验证成功", "序列验证通过")
                
    def _import_step_library(self):
        """导入步骤库"""
        # TODO: 实现步骤库导入
        pass
        
    def _export_step_library(self):
        """导出步骤库"""
        # TODO: 实现步骤库导出
        pass
