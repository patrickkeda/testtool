"""
步骤库管理器 - 管理可重用的测试步骤模板
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTextEdit, QTabWidget,
    QPushButton, QLabel, QLineEdit, QComboBox, QGroupBox,
    QFormLayout, QDialog, QDialogButtonBox, QFileDialog,
    QMessageBox, QToolBar, QMenuBar, QStatusBar,
    QListWidget, QListWidgetItem, QCheckBox, QPlainTextEdit
)

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.testcases.config import TestStepConfig, ExpectConfig
from src.app.i18n import I18n
from .integration_manager import register_tool, unregister_tool


class StepTemplate:
    """步骤模板类"""
    
    def __init__(self, name: str, category: str, description: str, 
                 step_config: TestStepConfig, tags: List[str] = None):
        self.name = name
        self.category = category
        self.description = description
        self.step_config = step_config
        self.tags = tags or []
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "step_config": self.step_config.model_dump(),
            "tags": self.tags
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StepTemplate':
        """从字典创建"""
        step_config = TestStepConfig(**data["step_config"])
        return cls(
            name=data["name"],
            category=data["category"],
            description=data["description"],
            step_config=step_config,
            tags=data.get("tags", [])
        )


class StepLibrary(QMainWindow):
    """步骤库管理器主窗口"""
    
    sig_step_selected = Signal(TestStepConfig)
    sig_template_updated = Signal(str)  # 模板更新信号
    sig_template_deleted = Signal(str)  # 模板删除信号
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._i18n = I18n()
        self._templates: Dict[str, StepTemplate] = {}
        self._current_template: Optional[StepTemplate] = None
        self._pending_step: Optional[TestStepConfig] = None  # 待处理的步骤
        
        self._init_ui()
        self._init_actions()
        self._init_menubar()
        self._init_toolbar()
        self._init_statusbar()
        
        # 设置窗口属性
        self.setWindowTitle("步骤库管理器")
        self.setGeometry(200, 200, 1000, 700)
        
        # 注册到集成管理器
        register_tool("step_library", self)
        
        # 加载内置步骤模板
        self._load_builtin_templates()
    
    def _init_ui(self) -> None:
        """初始化用户界面"""
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout(central_widget)
        
        # 左侧：步骤列表
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # 搜索和过滤
        search_group = QGroupBox("搜索和过滤", self)
        search_layout = QFormLayout(search_group)
        
        self.edit_search = QLineEdit(self)
        self.edit_search.setPlaceholderText("搜索步骤...")
        self.edit_search.textChanged.connect(self._on_search_changed)
        
        self.combo_category = QComboBox(self)
        self.combo_category.addItems(["全部", "通信", "仪器", "UUT", "MES", "工具"])
        self.combo_category.currentTextChanged.connect(self._on_filter_changed)
        
        search_layout.addRow("搜索:", self.edit_search)
        search_layout.addRow("分类:", self.combo_category)
        
        # 步骤列表
        self.step_list = QListWidget(self)
        self.step_list.itemSelectionChanged.connect(self._on_step_selected)
        self.step_list.itemDoubleClicked.connect(self._on_step_double_clicked)
        
        # 步骤操作按钮
        step_buttons = QHBoxLayout()
        self.btn_add_template = QPushButton("添加模板", self)
        self.btn_edit_template = QPushButton("编辑模板", self)
        self.btn_delete_template = QPushButton("删除模板", self)
        self.btn_export_template = QPushButton("导出模板", self)
        
        step_buttons.addWidget(self.btn_add_template)
        step_buttons.addWidget(self.btn_edit_template)
        step_buttons.addWidget(self.btn_delete_template)
        step_buttons.addWidget(self.btn_export_template)
        
        # 组装左侧
        left_layout.addWidget(search_group)
        left_layout.addWidget(QLabel("步骤模板:"))
        left_layout.addWidget(self.step_list)
        left_layout.addLayout(step_buttons)
        
        # 右侧：步骤详情
        right_splitter = QSplitter(Qt.Vertical)
        
        # 基本信息
        info_group = QGroupBox("基本信息", self)
        info_layout = QFormLayout(info_group)
        
        self.lbl_name = QLabel("-")
        self.lbl_category = QLabel("-")
        self.lbl_description = QLabel("-")
        self.lbl_type = QLabel("-")
        self.lbl_tags = QLabel("-")
        
        info_layout.addRow("名称:", self.lbl_name)
        info_layout.addRow("分类:", self.lbl_category)
        info_layout.addRow("描述:", self.lbl_description)
        info_layout.addRow("类型:", self.lbl_type)
        info_layout.addRow("标签:", self.lbl_tags)
        
        # 步骤配置
        config_group = QGroupBox("步骤配置", self)
        config_layout = QVBoxLayout(config_group)
        
        self.config_editor = QPlainTextEdit(self)
        self.config_editor.setReadOnly(True)
        self.config_editor.setPlaceholderText("选择步骤模板查看配置...")
        config_layout.addWidget(self.config_editor)
        
        # 预览
        preview_group = QGroupBox("预览", self)
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_editor = QPlainTextEdit(self)
        self.preview_editor.setReadOnly(True)
        self.preview_editor.setPlaceholderText("选择步骤模板查看预览...")
        preview_layout.addWidget(self.preview_editor)
        
        right_splitter.addWidget(info_group)
        right_splitter.addWidget(config_group)
        right_splitter.addWidget(preview_group)
        right_splitter.setSizes([150, 200, 200])
        
        # 组装主布局
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([300, 700])
        
        main_layout.addWidget(main_splitter)
        
        # 连接信号
        self._connect_ui_signals()
    
    def _connect_ui_signals(self) -> None:
        """连接UI信号"""
        self.btn_add_template.clicked.connect(self._add_template)
        self.btn_edit_template.clicked.connect(self._edit_template)
        self.btn_delete_template.clicked.connect(self._delete_template)
        self.btn_export_template.clicked.connect(self._export_template)
    
    def _init_actions(self) -> None:
        """初始化动作"""
        # 文件操作
        self.act_import = QAction("导入模板", self)
        self.act_import.triggered.connect(self._import_templates)
        
        self.act_export = QAction("导出模板", self)
        self.act_export.triggered.connect(self._export_templates)
        
        self.act_exit = QAction("退出", self)
        self.act_exit.setShortcut("Ctrl+Q")
        self.act_exit.triggered.connect(self.close)
        
        # 编辑操作
        self.act_add = QAction("添加模板", self)
        self.act_add.setShortcut("Ctrl+N")
        self.act_add.triggered.connect(self._add_template)
        
        self.act_edit = QAction("编辑模板", self)
        self.act_edit.setShortcut("F2")
        self.act_edit.triggered.connect(self._edit_template)
        
        self.act_delete = QAction("删除模板", self)
        self.act_delete.setShortcut("Delete")
        self.act_delete.triggered.connect(self._delete_template)
    
    def _init_menubar(self) -> None:
        """初始化菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件")
        file_menu.addAction(self.act_import)
        file_menu.addAction(self.act_export)
        file_menu.addSeparator()
        file_menu.addAction(self.act_exit)
        
        # 编辑菜单
        edit_menu = menubar.addMenu("编辑")
        edit_menu.addAction(self.act_add)
        edit_menu.addAction(self.act_edit)
        edit_menu.addAction(self.act_delete)
    
    def _init_toolbar(self) -> None:
        """初始化工具栏"""
        toolbar = QToolBar("主工具栏", self)
        toolbar.setMovable(False)
        
        toolbar.addAction(self.act_add)
        toolbar.addAction(self.act_edit)
        toolbar.addAction(self.act_delete)
        toolbar.addSeparator()
        toolbar.addAction(self.act_import)
        toolbar.addAction(self.act_export)
        toolbar.addSeparator()
        
        # 序列编辑器集成按钮
        self.act_open_editor = QAction("打开序列编辑器", self)
        self.act_open_editor.setToolTip("打开序列编辑器")
        self.act_open_editor.triggered.connect(self._open_sequence_editor)
        
        toolbar.addAction(self.act_open_editor)
        
        self.addToolBar(toolbar)
    
    def _init_statusbar(self) -> None:
        """初始化状态栏"""
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        
        self.status_label = QLabel("就绪")
        self.status_bar.addWidget(self.status_label)
    
    def _load_builtin_templates(self) -> None:
        """加载内置步骤模板"""
        builtin_templates = [
            # 通信步骤
            StepTemplate(
                name="发送命令",
                category="通信",
                description="向UUT发送命令",
                step_config=TestStepConfig(
                    id="send_command",
                    name="发送命令",
                    type="comm.send",
                    params={"command": "${command}", "timeout": 1000},
                    timeout=5000,
                    retries=3,
                    on_failure="fail"
                ),
                tags=["通信", "发送", "命令"]
            ),
            StepTemplate(
                name="接收响应",
                category="通信",
                description="从UUT接收响应",
                step_config=TestStepConfig(
                    id="receive_response",
                    name="接收响应",
                    type="comm.receive",
                    params={"pattern": "${pattern}", "timeout": 2000},
                    timeout=5000,
                    retries=3,
                    on_failure="fail"
                ),
                tags=["通信", "接收", "响应"]
            ),
            StepTemplate(
                name="等待响应",
                category="通信",
                description="等待UUT响应",
                step_config=TestStepConfig(
                    id="wait_response",
                    name="等待响应",
                    type="comm.wait",
                    params={"timeout": 3000},
                    timeout=5000,
                    retries=1,
                    on_failure="skip"
                ),
                tags=["通信", "等待", "响应"]
            ),
            
            # 仪器步骤
            StepTemplate(
                name="设置电压",
                category="仪器",
                description="设置电源电压",
                step_config=TestStepConfig(
                    id="set_voltage",
                    name="设置电压",
                    type="instrument.set_voltage",
                    params={"voltage": "${voltage}", "channel": 1},
                    timeout=3000,
                    retries=2,
                    on_failure="fail"
                ),
                tags=["仪器", "电源", "电压"]
            ),
            StepTemplate(
                name="测量电压",
                category="仪器",
                description="测量电压值",
                step_config=TestStepConfig(
                    id="measure_voltage",
                    name="测量电压",
                    type="instrument.measure_voltage",
                    params={"channel": 1},
                    timeout=3000,
                    retries=2,
                    on_failure="fail",
                    expect=ExpectConfig(type="range", value=3.3, min_val=3.2, max_val=3.4)
                ),
                tags=["仪器", "测量", "电压"]
            ),
            
            # UUT步骤
            StepTemplate(
                name="上电",
                category="UUT",
                description="给UUT上电",
                step_config=TestStepConfig(
                    id="power_on",
                    name="上电",
                    type="uut.power_on",
                    params={},
                    timeout=2000,
                    retries=1,
                    on_failure="fail"
                ),
                tags=["UUT", "上电", "电源"]
            ),
            StepTemplate(
                name="下电",
                category="UUT",
                description="给UUT下电",
                step_config=TestStepConfig(
                    id="power_off",
                    name="下电",
                    type="uut.power_off",
                    params={},
                    timeout=2000,
                    retries=1,
                    on_failure="fail"
                ),
                tags=["UUT", "下电", "电源"]
            ),
            StepTemplate(
                name="复位",
                category="UUT",
                description="复位UUT",
                step_config=TestStepConfig(
                    id="reset",
                    name="复位",
                    type="uut.reset",
                    params={},
                    timeout=3000,
                    retries=2,
                    on_failure="fail"
                ),
                tags=["UUT", "复位", "重启"]
            ),
            
            # MES步骤
            StepTemplate(
                name="获取工单",
                category="MES",
                description="从MES获取工单信息",
                step_config=TestStepConfig(
                    id="get_work_order",
                    name="获取工单",
                    type="mes.get_work_order",
                    params={"sn": "${context.sn}"},
                    timeout=10000,
                    retries=3,
                    on_failure="fail"
                ),
                tags=["MES", "工单", "获取"]
            ),
            StepTemplate(
                name="更新结果",
                category="MES",
                description="向MES更新测试结果",
                step_config=TestStepConfig(
                    id="update_result",
                    name="更新结果",
                    type="mes.update_result",
                    params={"sn": "${context.sn}", "result": "${context.result}"},
                    timeout=10000,
                    retries=3,
                    on_failure="fail"
                ),
                tags=["MES", "结果", "更新"]
            ),
            
            # 工具步骤
            StepTemplate(
                name="延时",
                category="工具",
                description="延时等待",
                step_config=TestStepConfig(
                    id="delay",
                    name="延时",
                    type="utility.delay",
                    params={"duration": 1000},
                    timeout=2000,
                    retries=0,
                    on_failure="skip"
                ),
                tags=["工具", "延时", "等待"]
            ),
            StepTemplate(
                name="记录日志",
                category="工具",
                description="记录测试日志",
                step_config=TestStepConfig(
                    id="log",
                    name="记录日志",
                    type="utility.log",
                    params={"message": "${message}", "level": "INFO"},
                    timeout=1000,
                    retries=0,
                    on_failure="skip"
                ),
                tags=["工具", "日志", "记录"]
            ),
            StepTemplate(
                name="条件判断",
                category="工具",
                description="条件判断",
                step_config=TestStepConfig(
                    id="condition",
                    name="条件判断",
                    type="utility.condition",
                    params={"expression": "${value} > 0", "on_true": "continue", "on_false": "skip"},
                    timeout=1000,
                    retries=0,
                    on_failure="skip"
                ),
                tags=["工具", "条件", "判断"]
            ),
        ]
        
        # 添加到模板库
        for template in builtin_templates:
            self._templates[template.name] = template
        
        # 更新UI
        self._update_step_list()
    
    def _update_step_list(self) -> None:
        """更新步骤列表"""
        self.step_list.clear()
        
        search_text = self.edit_search.text().lower()
        category_filter = self.combo_category.currentText()
        
        for template in self._templates.values():
            # 搜索过滤
            if search_text:
                if (search_text not in template.name.lower() and 
                    search_text not in template.description.lower() and
                    not any(search_text in tag.lower() for tag in template.tags)):
                    continue
            
            # 分类过滤
            if category_filter != "全部":
                category_map = {
                    "通信": "通信",
                    "仪器": "仪器", 
                    "UUT": "UUT",
                    "MES": "MES",
                    "工具": "工具"
                }
                if template.category != category_map.get(category_filter, ""):
                    continue
            
            # 添加到列表
            item = QListWidgetItem(template.name)
            item.setData(Qt.UserRole, template)
            item.setToolTip(f"{template.description}\n分类: {template.category}\n标签: {', '.join(template.tags)}")
            self.step_list.addItem(item)
    
    def _on_search_changed(self) -> None:
        """搜索文本改变"""
        self._update_step_list()
    
    def _on_filter_changed(self) -> None:
        """过滤条件改变"""
        self._update_step_list()
    
    def _on_step_selected(self) -> None:
        """步骤选择改变"""
        current_item = self.step_list.currentItem()
        if current_item:
            template = current_item.data(Qt.UserRole)
            if template:
                self._current_template = template
                self._update_step_details(template)
            else:
                self._clear_step_details()
        else:
            self._clear_step_details()
    
    def _update_step_details(self, template: StepTemplate) -> None:
        """更新步骤详情"""
        # 基本信息
        self.lbl_name.setText(template.name)
        self.lbl_category.setText(template.category)
        self.lbl_description.setText(template.description)
        self.lbl_type.setText(template.step_config.type)
        self.lbl_tags.setText(", ".join(template.tags))
        
        # 配置信息
        import yaml
        config_text = yaml.dump(
            template.step_config.model_dump(),
            default_flow_style=False,
            allow_unicode=True
        )
        self.config_editor.setPlainText(config_text)
        
        # 预览信息
        preview_text = f"""步骤名称: {template.name}
分类: {template.category}
描述: {template.description}
类型: {template.step_config.type}
ID: {template.step_config.id}
超时: {template.step_config.timeout}ms
重试: {template.step_config.retries}
失败处理: {template.step_config.on_failure}

参数配置:
{config_text}

标签: {', '.join(template.tags)}
"""
        self.preview_editor.setPlainText(preview_text)
    
    def _clear_step_details(self) -> None:
        """清空步骤详情"""
        self.lbl_name.setText("-")
        self.lbl_category.setText("-")
        self.lbl_description.setText("-")
        self.lbl_type.setText("-")
        self.lbl_tags.setText("-")
        self.config_editor.clear()
        self.preview_editor.clear()
        self._current_template = None
    
    def _add_template(self) -> None:
        """添加模板"""
        dialog = TemplateEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            template = dialog.get_template()
            if template:
                self._templates[template.name] = template
                self._update_step_list()
                self.status_label.setText(f"已添加模板: {template.name}")
    
    def _edit_template(self) -> None:
        """编辑模板"""
        current_item = self.step_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "提示", "请先选择要编辑的模板")
            return
        
        template = current_item.data(Qt.UserRole)
        if not template:
            return
        
        dialog = TemplateEditDialog(self, template)
        if dialog.exec() == QDialog.Accepted:
            new_template = dialog.get_template()
            if new_template:
                # 如果名称改变，删除旧模板
                if new_template.name != template.name:
                    del self._templates[template.name]
                
                self._templates[new_template.name] = new_template
                self._update_step_list()
                self.status_label.setText(f"已更新模板: {new_template.name}")
    
    def _delete_template(self) -> None:
        """删除模板"""
        current_item = self.step_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "提示", "请先选择要删除的模板")
            return
        
        template = current_item.data(Qt.UserRole)
        if not template:
            return
        
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除模板 '{template.name}' 吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            del self._templates[template.name]
            self._update_step_list()
            self._clear_step_details()
            self.status_label.setText(f"已删除模板: {template.name}")
    
    def _export_template(self) -> None:
        """导出模板"""
        current_item = self.step_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "提示", "请先选择要导出的模板")
            return
        
        template = current_item.data(Qt.UserRole)
        if not template:
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出模板",
            f"{template.name}.yaml",
            "YAML文件 (*.yaml);;所有文件 (*)"
        )
        
        if file_path:
            try:
                import yaml
                with open(file_path, 'w', encoding='utf-8') as f:
                    yaml.dump(template.to_dict(), f, default_flow_style=False, allow_unicode=True)
                self.status_label.setText(f"已导出模板: {os.path.basename(file_path)}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"无法导出模板: {e}")
    
    def _import_templates(self) -> None:
        """导入模板"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入模板",
            "", "YAML文件 (*.yaml *.yml);;所有文件 (*)"
        )
        
        if file_path:
            try:
                import yaml
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                
                if isinstance(data, list):
                    # 批量导入
                    for item in data:
                        template = StepTemplate.from_dict(item)
                        self._templates[template.name] = template
                else:
                    # 单个导入
                    template = StepTemplate.from_dict(data)
                    self._templates[template.name] = template
                
                self._update_step_list()
                self.status_label.setText(f"已导入模板: {os.path.basename(file_path)}")
                
            except Exception as e:
                QMessageBox.critical(self, "导入失败", f"无法导入模板: {e}")
    
    def _export_templates(self) -> None:
        """导出所有模板"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出所有模板",
            "step_templates.yaml",
            "YAML文件 (*.yaml);;所有文件 (*)"
        )
        
        if file_path:
            try:
                import yaml
                templates_data = [template.to_dict() for template in self._templates.values()]
                with open(file_path, 'w', encoding='utf-8') as f:
                    yaml.dump(templates_data, f, default_flow_style=False, allow_unicode=True)
                self.status_label.setText(f"已导出所有模板: {os.path.basename(file_path)}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"无法导出模板: {e}")
    
    def get_selected_step(self) -> Optional[TestStepConfig]:
        """获取选中的步骤配置"""
        if self._current_template:
            return self._current_template.step_config
        return None
    
    def _on_step_double_clicked(self, item: QListWidgetItem) -> None:
        """处理步骤双击事件"""
        try:
            template = item.data(Qt.UserRole)
            if template:
                # 发送步骤选择信号
                self.sig_step_selected.emit(template.step_config)
                
                # 如果父窗口是序列编辑器，关闭步骤库
                if hasattr(self.parent(), 'insert_step_template'):
                    self.close()
                    
        except Exception as e:
            QMessageBox.critical(self, "错误", f"处理步骤选择失败: {e}")
    
    def _open_sequence_editor(self) -> None:
        """打开序列编辑器"""
        try:
            from .sequence_editor import SequenceEditor
            editor = SequenceEditor(self)
            
            # 连接信号
            editor.sig_step_template_requested.connect(self._on_template_requested)
            
            editor.show()
            editor.raise_()
            editor.activateWindow()
            
        except ImportError as e:
            QMessageBox.warning(self, "功能不可用", 
                               f"序列编辑器不可用：{e}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开序列编辑器: {e}")
    
    def _on_template_requested(self) -> None:
        """处理模板请求"""
        try:
            # 显示模板选择对话框
            if self._current_template:
                self.sig_step_selected.emit(self._current_template.step_config)
            else:
                QMessageBox.information(self, "提示", "请先选择一个模板")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"处理模板请求失败: {e}")
    
    def closeEvent(self, event) -> None:
        """窗口关闭事件"""
        # 从集成管理器注销
        unregister_tool("step_library")
        event.accept()


class TemplateEditDialog(QDialog):
    """模板编辑对话框"""
    
    def __init__(self, parent: Optional[QWidget] = None, template: Optional[StepTemplate] = None):
        super().__init__(parent)
        self._template = template
        self._init_ui()
        
        if template:
            self._load_template(template)
    
    def _init_ui(self) -> None:
        """初始化UI"""
        self.setWindowTitle("编辑模板" if self._template else "添加模板")
        self.setModal(True)
        self.resize(500, 400)
        
        layout = QVBoxLayout(self)
        
        # 基本信息
        basic_group = QGroupBox("基本信息", self)
        basic_layout = QFormLayout(basic_group)
        
        self.edit_name = QLineEdit(self)
        self.edit_category = QComboBox(self)
        self.edit_category.addItems(["通信", "仪器", "UUT", "MES", "工具"])
        self.edit_description = QLineEdit(self)
        self.edit_tags = QLineEdit(self)
        self.edit_tags.setPlaceholderText("用逗号分隔多个标签")
        
        basic_layout.addRow("名称:", self.edit_name)
        basic_layout.addRow("分类:", self.edit_category)
        basic_layout.addRow("描述:", self.edit_description)
        basic_layout.addRow("标签:", self.edit_tags)
        
        # 步骤配置
        config_group = QGroupBox("步骤配置", self)
        config_layout = QVBoxLayout(config_group)
        
        self.edit_config = QPlainTextEdit(self)
        self.edit_config.setPlaceholderText("输入YAML格式的步骤配置...")
        config_layout.addWidget(self.edit_config)
        
        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        
        # 布局组装
        layout.addWidget(basic_group)
        layout.addWidget(config_group)
        layout.addWidget(buttons)
    
    def _load_template(self, template: StepTemplate) -> None:
        """加载模板数据"""
        self.edit_name.setText(template.name)
        self.edit_category.setCurrentText(template.category)
        self.edit_description.setText(template.description)
        self.edit_tags.setText(", ".join(template.tags))
        
        import yaml
        config_text = yaml.dump(
            template.step_config.model_dump(),
            default_flow_style=False,
            allow_unicode=True
        )
        self.edit_config.setPlainText(config_text)
    
    def get_template(self) -> Optional[StepTemplate]:
        """获取模板"""
        try:
            name = self.edit_name.text().strip()
            if not name:
                QMessageBox.warning(self, "错误", "模板名称不能为空")
                return None
            
            category = self.edit_category.currentText()
            description = self.edit_description.text().strip()
            tags = [tag.strip() for tag in self.edit_tags.text().split(",") if tag.strip()]
            
            # 解析步骤配置
            import yaml
            config_text = self.edit_config.toPlainText().strip()
            if not config_text:
                QMessageBox.warning(self, "错误", "步骤配置不能为空")
                return None
            
            config_data = yaml.safe_load(config_text)
            step_config = TestStepConfig(**config_data)
            
            return StepTemplate(
                name=name,
                category=category,
                description=description,
                step_config=step_config,
                tags=tags
            )
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"创建模板失败: {e}")
            return None
    
    def set_template_from_step(self, step_config: TestStepConfig) -> None:
        """从步骤配置设置模板"""
        try:
            self._pending_step = step_config
            
            # 自动打开添加模板对话框
            self._add_template()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"设置模板失败: {e}")
    
    


def main():
    """主函数"""
    import sys
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # 设置应用信息
    app.setApplicationName("步骤库管理器")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("TestTool")
    
    # 创建主窗口
    window = StepLibrary()
    window.show()
    
    # 运行应用
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
