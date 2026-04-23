"""
Port panel widget representing one testing port (A or B).

Contains header (identity/status), current step card placeholders,
results table placeholder, progress bar, and a tab for real-time plots.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
import logging
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QGroupBox,
    QSizePolicy,
    QHeaderView,
    QComboBox,
    QFrame,
)

from ..i18n import I18n


class PortPanel(QWidget):
    """Panel for a single port with UI placeholders.

    Parameters
    ----------
    title: str
        Panel title, e.g., "Port A" or "Port B".
    parent: Optional[QWidget]
        Parent widget.
    """
    
    # 信号定义
    sig_start = Signal()
    sig_pause = Signal()
    sig_stop = Signal()
    sig_retest = Signal()  # 复测信号：使用上一次SN并跳过扫描
    sig_mode_changed = Signal(str)  # 测试模式改变信号：'production' 或 'debug'

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self._i18n = I18n("zh_CN")
        self._logger = logging.getLogger(__name__)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        # 贴近分界线：减少面板整体外边距与间距
        root.setContentsMargins(6, 2, 6, 6)
        root.setSpacing(6)

        # Top banner (Header + Actions) - 用于测试完成时整块变色显示结果
        self._top_banner = QFrame(self)
        self._top_banner.setObjectName("topBanner")
        self._top_banner.setFrameShape(QFrame.NoFrame)
        banner_root = QVBoxLayout(self._top_banner)
        banner_root.setContentsMargins(6, 6, 6, 6)
        banner_root.setSpacing(6)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        # 选择复选框放在标题前
        self.chk_selected = QCheckBox(self._top_banner)
        self.chk_selected.setChecked(True)
        self.lbl_title = QLabel(self._title, self._top_banner)
        self.lbl_sn = QLabel(f"{self._i18n.t('panel.sn')}: -", self._top_banner)
        self.lbl_status = QLabel(f"{self._i18n.t('panel.status')}: Idle", self._top_banner)

        # 设置Port标题的字体样式（增大50%，不加粗）
        title_font = QFont()
        title_font.setPointSize(int(title_font.pointSize() * 1.5))  # 增大50%
        title_font.setBold(False)  # 不加粗
        self.lbl_title.setFont(title_font)

        # 整体测试结果大字提示（默认隐藏）
        self.lbl_overall = QLabel("", self._top_banner)
        overall_font = QFont()
        overall_font.setPointSize(int(overall_font.pointSize() * 1.8))
        overall_font.setBold(True)
        self.lbl_overall.setFont(overall_font)
        self.lbl_overall.setAlignment(Qt.AlignCenter)
        self.lbl_overall.setVisible(False)

        header.addWidget(self.chk_selected)
        header.addWidget(self.lbl_title)
        header.addStretch(1)
        header.addWidget(self.lbl_overall)
        header.addWidget(self.lbl_sn)
        header.addWidget(self.lbl_status)
        banner_root.addLayout(header)

        # Actions - 恢复到原来的布局
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        
        # 创建按钮
        self.btn_start = QPushButton(self._i18n.t("panel.actions.start"), self)
        self.btn_pause = QPushButton(self._i18n.t("panel.actions.pause"), self)
        self.btn_stop = QPushButton(self._i18n.t("panel.actions.stop"), self)
        self.btn_retest = QPushButton("复测", self)
        
        # 设置按钮样式
        self._setup_button_style()
        
        # 连接按钮信号
        self.btn_start.clicked.connect(self.sig_start.emit)
        self.btn_pause.clicked.connect(self.sig_pause.emit)
        self.btn_stop.clicked.connect(self.sig_stop.emit)
        self.btn_retest.clicked.connect(self.sig_retest.emit)
        
        # 添加按钮到布局 - 恢复到原来的紧凑布局
        actions.addWidget(self.btn_start)
        actions.addWidget(self.btn_pause)
        actions.addWidget(self.btn_stop)
        actions.addWidget(self.btn_retest)
        
        # 添加测试模式选择器
        mode_label = QLabel("测试模式:", self)
        self.combo_mode = QComboBox(self)
        self.combo_mode.addItems(["产线模式", "Debug模式"])
        self.combo_mode.setCurrentText("产线模式")  # 默认产线模式
        self.combo_mode.currentTextChanged.connect(self._on_mode_changed)
        
        # 设置模式选择器样式
        mode_label.setFixedHeight(30)
        self.combo_mode.setFixedHeight(30)
        self.combo_mode.setMinimumWidth(100)
        
        actions.addWidget(self._create_spacer(20))  # 添加间距
        actions.addWidget(mode_label)
        actions.addWidget(self.combo_mode)
        actions.addStretch(1)
        banner_root.addLayout(actions)

        root.addWidget(self._top_banner, 0)
        self.set_overall_result(None)

        # Current Step group - 进一步压缩高度
        step_group = QGroupBox(self._i18n.t("panel.current_step"), self)
        step_group.setFlat(True)
        step_layout = QHBoxLayout(step_group)
        step_layout.setContentsMargins(6, 2, 6, 2)
        step_layout.setSpacing(8)
        self.lbl_step = QLabel("-", step_group)
        self.lbl_expect = QLabel(f"{self._i18n.t('panel.expect')}: -", step_group)
        self.lbl_meas = QLabel(f"{self._i18n.t('panel.meas')}: -", step_group)
        self.lbl_retries = QLabel(f"{self._i18n.t('panel.retries')}: 0", step_group)
        step_layout.addWidget(self.lbl_step, 2)
        step_layout.addWidget(self.lbl_expect, 2)
        step_layout.addWidget(self.lbl_meas, 2)
        step_layout.addWidget(self.lbl_retries, 1)
        # 进一步压缩当前步骤组的高度
        step_group.setMaximumHeight(46)
        step_group.setMinimumHeight(36)
        root.addWidget(step_group, 0)  # 使用stretch factor 0，不扩展

        # Results table - 固定尺寸，布满整个区域
        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels([
            "Step",
            "Value",
            "Low",
            "High",
            "Unit",
        ])
        # 为避免自定义背景被交替色覆盖，这里关闭交替行颜色
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        from PySide6.QtWidgets import QAbstractItemView
        # 不允许选择，避免选中态影响视觉，也不可复制
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        # 设置表格为固定尺寸，不随内容动态调整
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 设置表格的最小和最大高度，确保固定尺寸
        self.table.setMinimumHeight(200)
        self.table.setMaximumHeight(400)
        # 设置固定行高，避免动态调整
        self.table.verticalHeader().setDefaultSectionSize(25)
        self.table.verticalHeader().setVisible(False)  # 隐藏行号
        # 设置表格为自适应拉伸，随容器宽度等比扩展，消除右侧留白
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # 仅设置选中态为透明（尽管已禁用选择）
        self.table.setStyleSheet("QTableWidget::item:selected { background: transparent; color: black; }")
        
        # 设置表格的网格线显示
        self.table.setShowGrid(True)
        root.addWidget(self.table, 1)

        # Progress - 进一步压缩高度
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMaximumHeight(15)  # 进一步限制进度条高度
        self.progress.setMinimumHeight(15)
        root.addWidget(self.progress, 0)  # 使用stretch factor 0，不扩展

    def _setup_button_style(self):
        """设置按钮样式 - 恢复到原来的合理尺寸"""
        from PySide6.QtWidgets import QStyle
        from PySide6.QtCore import QSize
        
        # 设置按钮字体 - 正常大小
        base_font = QFont()
        self.btn_start.setFont(base_font)
        self.btn_pause.setFont(base_font)
        self.btn_stop.setFont(base_font)
        self.btn_retest.setFont(base_font)
        
        # 设置图标 - 与主界面相同的图标
        self.btn_start.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_pause.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.btn_stop.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.btn_retest.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        
        # 设置图标大小 - 正常尺寸
        icon_size = QSize(20, 20)  # 20x20像素
        self.btn_start.setIconSize(icon_size)
        self.btn_pause.setIconSize(icon_size)
        self.btn_stop.setIconSize(icon_size)
        self.btn_retest.setIconSize(icon_size)
        
        # 设置按钮大小策略 - 固定宽度
        self.btn_start.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_pause.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_stop.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_retest.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        
        # 设置按钮尺寸 - 正常高度
        min_height = 30
        min_width = 80
        self.btn_start.setMinimumSize(min_width, min_height)
        self.btn_pause.setMinimumSize(min_width, min_height)
        self.btn_stop.setMinimumSize(min_width, min_height)
        self.btn_retest.setMinimumSize(min_width, min_height)
        
        # 设置按钮样式 - 简洁风格
        button_style = """
            QPushButton {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 6px 12px;
                text-align: center;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                border-color: #999;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
                border-color: #666;
            }
            QPushButton:disabled {
                background-color: #f5f5f5;
                border-color: #ddd;
                color: #999;
            }
        """
        
        self.btn_start.setStyleSheet(button_style)
        self.btn_pause.setStyleSheet(button_style)
        self.btn_stop.setStyleSheet(button_style)
        self.btn_retest.setStyleSheet(button_style)
    
    
    def add_test_result(self, step_name: str, value: str = "", low: str = "", high: str = "", unit: str = "", result: str = "Pass") -> None:
        """添加测试结果到表格，并根据结果设置颜色"""
        from PySide6.QtGui import QColor
        
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        # 添加数据（并设置为不可编辑）
        items = [
            QTableWidgetItem(step_name),
            QTableWidgetItem(value),
            QTableWidgetItem(low),
            QTableWidgetItem(high),
            QTableWidgetItem(unit),
        ]
        for col, it in enumerate(items):
            # 禁止单元格编辑与选择
            it.setFlags((it.flags() & ~Qt.ItemIsEditable) & ~Qt.ItemIsSelectable)
            self.table.setItem(row, col, it)
        
        # 根据测试结果设置行颜色
        res_norm = (result or "").strip().lower()
        if res_norm == "pass":
            # 绿色背景表示通过
            color = QColor(200, 255, 200)  # 浅绿色
        elif res_norm == "fail":
            # 红色背景表示失败
            color = QColor(255, 200, 200)  # 浅红色
        else:
            # 默认颜色
            color = QColor(255, 255, 255)  # 白色
        
        self._logger.debug(f"PortPanel[{self._title}] set row {row} result={result}, color={color.getRgb()}")

        # 设置整行背景色（文本保持黑色）
        for col in range(5):
            item = self.table.item(row, col)
            if item:
                from PySide6.QtGui import QBrush
                brush = QBrush(color)
                # 双重设置，兼容不同平台样式实现
                item.setBackground(brush)
                item.setData(Qt.BackgroundRole, brush)
                # 文字固定为黑色，避免看起来像“蓝色/高亮”
                item.setForeground(QColor(0, 0, 0))
        # 记录实际读取到的颜色，便于诊断
        probe = self.table.item(row, 0)
        if probe:
            bg = probe.background().color().getRgb() if probe.background() else None
            data_bg = probe.data(Qt.BackgroundRole).color().getRgb() if probe.data(Qt.BackgroundRole) else None
            self._logger.debug(f"Row {row} applied bg: background()={bg}, data(Qt.BackgroundRole)={data_bg}")
        # 通知模型数据已变更并强制刷新视图，确保颜色立即可见
        if self.table.model() is not None:
            top_left = self.table.model().index(row, 0)
            bottom_right = self.table.model().index(row, self.table.columnCount() - 1)
            self.table.model().dataChanged.emit(top_left, bottom_right, [Qt.BackgroundRole])
        self.table.viewport().update()
        self.table.repaint()
    
    def _create_spacer(self, width: int):
        """创建固定宽度的间距控件"""
        from PySide6.QtWidgets import QWidget
        spacer = QWidget()
        spacer.setFixedWidth(width)
        return spacer
    
    def _on_mode_changed(self, mode_text: str):
        """处理测试模式改变"""
        # 将中文模式名称转换为英文标识
        mode = "production" if mode_text == "产线模式" else "debug"
        self.sig_mode_changed.emit(mode)
    
    def get_test_mode(self) -> str:
        """获取当前选择的测试模式"""
        mode_text = self.combo_mode.currentText()
        return "production" if mode_text == "产线模式" else "debug"

    def set_overall_result(self, result: Optional[str]) -> None:
        """设置整轮测试结果横幅显示。

        result:
            - None: 清空横幅，恢复默认背景
            - "Pass"/"pass": 绿色 + '测试通过'
            - "Fail"/"fail": 红色 + '测试失败'
        """
        res = (result or "").strip().lower() if result is not None else ""
        if not res:
            self._top_banner.setStyleSheet(
                """
                QFrame#topBanner {
                    background: transparent;
                    border: 1px solid rgba(0,0,0,0.08);
                    border-radius: 6px;
                }
                """
            )
            self.lbl_overall.setVisible(False)
            self.lbl_overall.setText("")
            return

        if res == "pass":
            bg = "#1db954"  # 醒目的绿色
            text = "测试通过"
        else:
            bg = "#e53935"  # 醒目的红色
            text = "测试失败"

        self._top_banner.setStyleSheet(
            f"""
            QFrame#topBanner {{
                background: {bg};
                border: 1px solid rgba(0,0,0,0.10);
                border-radius: 6px;
            }}
            QLabel {{
                color: white;
            }}
            """
        )
        self.lbl_overall.setText(text)
        self.lbl_overall.setVisible(True)


