"""
MainWindow implementation with dual-port layout and placeholders for
toolbar actions, alerts panel, sequence tree, and localization.
"""

from __future__ import annotations

import logging
from typing import Optional, Dict

from PySide6.QtCore import Qt, QTranslator, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QListWidget,
    QToolBar,
    QStatusBar,
    QLabel,
    QFileDialog,
    QMessageBox,
    QMenu,
    QApplication,
    QTableWidgetItem,
    QPlainTextEdit,
)

from .port_panel import PortPanel
from .config_dialog import ConfigDialog
from ..i18n import I18n
from ..log_bridge import QtLogSignalHandler
from ..sequence_model import SequenceTreeModel
from ..worker import PortWorker
from ...config import ConfigService
from ...app_logging import get_logging_manager, get_test_logger, get_error_logger

# 导入新架构组件
from ...testcases.context import Context, create_context
from ...testcases.register_steps import register_all_steps
from ...testcases.simple_config import TestSequenceConfig
from ...instruments.psu import create_power_supply


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main window with dual-port panels and common HMI widgets.

    Features
    --------
    - Toolbar with start/pause/stop and language switch placeholders
    - Left: sequence tree
    - Center: Port A and Port B panels in a splitter
    - Right: alerts/events list
    - Bottom: status bar (connection/MES heartbeat placeholders)
    """

    sig_start = Signal()
    sig_pause = Signal()
    sig_stop = Signal()
    sig_switch_language = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        
        # 注册所有测试步骤
        register_all_steps()
        
        self._i18n = I18n(locale="zh_CN")
        self.setWindowTitle(self._i18n.t("app.title"))
        self.resize(1280, 800)

        self._translator = QTranslator(self)
        
        # 初始化配置服务
        # 在 exe 环境中：
        #   - 读取：优先从 _internal/Config/config.yaml（打包的默认配置）
        #   - 保存：保存到 exe 所在目录的 Config/config.yaml（用户可写）
        # 在开发环境中：使用 Config/config.yaml
        import sys
        import os
        from pathlib import Path
        
        if getattr(sys, 'frozen', False):
            # exe 环境：使用 exe 所在目录
            exe_dir = Path(sys.executable).parent
            
            # 读取配置：优先从 _internal 读取（打包的默认配置）
            read_config_paths = [
                exe_dir / '_internal' / 'Config' / 'config.yaml',
                exe_dir / 'Config' / 'config.yaml',
                exe_dir / 'config' / 'config.yaml',
            ]
            read_config_path = None
            for path in read_config_paths:
                if path.exists():
                    read_config_path = str(path)
                    break
            
            # 保存配置：始终保存到 exe 所在目录的 Config 目录（用户可写）
            save_config_path = exe_dir / 'Config' / 'config.yaml'
            save_config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 如果读取路径存在且与保存路径不同，先复制默认配置
            if read_config_path and read_config_path != str(save_config_path):
                if not save_config_path.exists():
                    import shutil
                    shutil.copy2(read_config_path, save_config_path)
                    logger.info("Copied default config from %s to %s", read_config_path, save_config_path)
            
            config_path = str(save_config_path)
        else:
            # 开发环境：使用相对路径
            config_path = "Config/config.yaml"
            Path(config_path).parent.mkdir(parents=True, exist_ok=True)
        
        self._config_service = ConfigService(config_path)
        self._config_service.load()
        
        # 断点管理
        self._breakpoints = set()  # 存储断点步骤ID
        self._current_breakpoint = None  # 当前暂停的断点
        self._running_ports = set()  # 当前运行的端口
        # 记录本轮是否出现失败，用于完成时显示 Pass/Fail
        self._port_a_had_fail = False
        self._port_b_had_fail = False
        
        # 当前测试序列
        self._current_sequence = None
        
        # SN管理
        self._sn_by_port: Dict[str, str] = {"PortA": "NULL", "PortB": "NULL"}

        # 初始化新架构
        self._init_new_architecture()

        self._init_actions()
        self._init_menubar()
        self._init_toolbar()
        self._init_workers()  # 先初始化workers
        self._init_layout()
        # 默认仅显示 Port A（PortB 默认不选中且隐藏，可在工具菜单中开启）
        self._set_port_b_visible(False)
        self._init_statusbar()
        self._init_logging_bridge()
        self._init_sequence_model()  # 先初始化序列模型
        self._init_logging_system()
        
        # 在序列模型初始化后加载默认序列
        self._load_default_sequence()
    
    def _init_new_architecture(self) -> None:
        """初始化新架构组件"""
        # 注册所有测试步骤
        register_all_steps()
        
        # 初始化测试上下文（将在启动测试时创建具体实例）
        self._context_a = None
        self._context_b = None

        # 端口SN状态（会话级）
        self._sn_by_port = {"PortA": "NULL", "PortB": "NULL"}

    # ---- UI init helpers -------------------------------------------------
    def _init_menubar(self) -> None:
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu(self._i18n.t("menu.file"))
        file_menu.addAction("Load Seq", self._load_test_sequence)
        file_menu.addSeparator()
        exit_action = file_menu.addAction(self._i18n.t("menu.file.exit"))
        exit_action.triggered.connect(self._on_exit)

        # Config menu
        config_menu = menubar.addMenu(self._i18n.t("menu.config"))
        mes_action = config_menu.addAction(self._i18n.t("menu.config.mes"))
        mes_action.triggered.connect(self._on_open_mes_config)
        version_action = config_menu.addAction(self._i18n.t("menu.config.version"))
        version_action.triggered.connect(self._on_open_version_config)
        ports_action = config_menu.addAction(self._i18n.t("menu.config.ports"))
        ports_action.triggered.connect(self._on_open_ports_config)

        # Help menu (语言/版本)
        help_menu = menubar.addMenu("帮助")
        act_cn = help_menu.addAction("中文")
        act_en = help_menu.addAction("English")
        act_ver = help_menu.addAction("版本")
        act_cn.triggered.connect(lambda: self._on_switch_language("zh_CN"))
        act_en.triggered.connect(lambda: self._on_switch_language("en_US"))
        act_ver.triggered.connect(self._on_show_version)
        
        # Tools menu
        tools_menu = menubar.addMenu("工具")
        tools_menu.addAction("序列编辑器", self._open_sequence_editor)
        tools_menu.addAction("步骤库管理", self._open_step_library)
        tools_menu.addSeparator()
        self.act_show_port_b = QAction("显示 Port B", self)
        self.act_show_port_b.setCheckable(True)
        self.act_show_port_b.setChecked(False)
        self.act_show_port_b.triggered.connect(self._on_toggle_port_b)
        tools_menu.addAction(self.act_show_port_b)
        
        # Note: Log level selector will be added to toolbar

    def _init_actions(self) -> None:
        # Control actions with icons
        from PySide6.QtWidgets import QStyle
        
        self.act_start = QAction(self._i18n.t("toolbar.start"), self)
        self.act_start.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.act_pause = QAction(self._i18n.t("toolbar.pause"), self)
        self.act_pause.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.act_stop = QAction(self._i18n.t("toolbar.stop"), self)
        self.act_stop.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        
        # Other actions
        self.act_lang_zh = QAction(self._i18n.t("toolbar.lang.zh"), self)
        self.act_lang_en = QAction(self._i18n.t("toolbar.lang.en"), self)
        self.act_config = QAction("Config", self)

        self.act_start.triggered.connect(self.sig_start.emit)
        self.act_pause.triggered.connect(self.sig_pause.emit)
        self.act_stop.triggered.connect(self.sig_stop.emit)
        self.act_lang_zh.triggered.connect(lambda: self.sig_switch_language.emit("zh_CN"))
        self.act_lang_en.triggered.connect(lambda: self.sig_switch_language.emit("en_US"))
        self.act_config.triggered.connect(self._on_open_config)
        # connect start/pause/stop to Port A worker (demo)
        self.sig_start.connect(self._on_start)
        self.sig_pause.connect(self._on_pause)
        self.sig_stop.connect(self._on_stop)

    def _init_toolbar(self) -> None:
        toolbar = QToolBar("ControlToolbar", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)

        # Add control buttons with icons and increased spacing
        toolbar.addAction(self.act_start)
        toolbar.addWidget(self._create_spacer(20))  # 增加间距
        toolbar.addAction(self.act_pause)
        toolbar.addWidget(self._create_spacer(20))  # 增加间距
        toolbar.addAction(self.act_stop)
        
        # Port 选择（可单独运行 PortA/PortB）
        from PySide6.QtWidgets import QComboBox, QLabel, QHBoxLayout, QWidget

        # Add log level selector to toolbar with expanded spacing
        toolbar.addWidget(self._create_spacer(40))  # 扩大两倍间距 (20 * 2)
        
        log_label = QLabel("日志级别:", self)
        self.cbo_log_level = QComboBox(self)
        self.cbo_log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.cbo_log_level.setCurrentText("INFO")
        self.cbo_log_level.currentTextChanged.connect(self._on_log_level_changed)
        
        # Set consistent size and spacing
        log_label.setFixedHeight(32)  # Match button height
        log_label.setAlignment(Qt.AlignCenter)  # Center align text
        self.cbo_log_level.setFixedHeight(32)  # Match button height
        self.cbo_log_level.setMinimumWidth(100)  # Set minimum width
        
        toolbar.addWidget(log_label)
        toolbar.addWidget(self.cbo_log_level)
        
        # Add flexible spacer to push status info to the right
        from PySide6.QtWidgets import QWidget, QSizePolicy
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        
        # Add status information to toolbar (comm, mes, log) - positioned at far right
        from PySide6.QtWidgets import QLabel
        
        self.lbl_comm = QLabel("Comm: -", self)
        self.lbl_mes = QLabel("MES: -", self)
        self.lbl_log = QLabel("Log: -", self)
        
        # Set consistent styling for status labels
        self.lbl_comm.setFixedHeight(32)
        self.lbl_mes.setFixedHeight(32)
        self.lbl_log.setFixedHeight(32)
        self.lbl_comm.setAlignment(Qt.AlignCenter)
        self.lbl_mes.setAlignment(Qt.AlignCenter)
        self.lbl_log.setAlignment(Qt.AlignCenter)
        
        # Add small spacing before status labels
        toolbar.addWidget(self._create_spacer(10))
        toolbar.addWidget(self.lbl_comm)
        toolbar.addWidget(self.lbl_mes)
        toolbar.addWidget(self.lbl_log)

        self.addToolBar(Qt.TopToolBarArea, toolbar)
    
    def _create_spacer(self, width: int):
        """创建固定宽度的间距控件"""
        from PySide6.QtWidgets import QWidget
        spacer = QWidget()
        spacer.setFixedWidth(width)
        return spacer

    def _init_layout(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)

        # Main splitter for vertical division (top content vs bottom info)
        main_splitter = QSplitter(Qt.Vertical, central)
        
        # Top splitter for horizontal division (left sequence vs right ports)
        top_splitter = QSplitter(Qt.Horizontal, central)

        # Left: sequence tree
        self.sequence_tree = QTreeWidget(central)
        self.sequence_tree.setHeaderLabels([
            self._i18n.t("seq.header.step"),
            self._i18n.t("seq.header.status"),
        ])
        # 启用右键菜单
        self.sequence_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sequence_tree.customContextMenuRequested.connect(self._show_sequence_context_menu)
        # 不添加占位符数据，让_load_default_sequence处理

        # Right: splitter with two port panels
        port_splitter = QSplitter(Qt.Horizontal, central)
        self._port_splitter = port_splitter
        self.port_a = PortPanel(title="Port A", parent=port_splitter)
        self.port_b = PortPanel(title="Port B", parent=port_splitter)
        
        # 连接Port Panel的信号
        self.port_a.sig_start.connect(lambda: self._start_port("A"))
        self.port_a.sig_pause.connect(lambda: self._pause_port("A"))
        self.port_a.sig_stop.connect(lambda: self._stop_port("A"))
        self.port_a.sig_mode_changed.connect(lambda mode: self._on_port_mode_changed("A", mode))
        if hasattr(self.port_a, "sig_retest"):
            self.port_a.sig_retest.connect(lambda: self._retest_port("A"))
        
        self.port_b.sig_start.connect(lambda: self._start_port("B"))
        self.port_b.sig_pause.connect(lambda: self._pause_port("B"))
        self.port_b.sig_stop.connect(lambda: self._stop_port("B"))
        self.port_b.sig_mode_changed.connect(lambda mode: self._on_port_mode_changed("B", mode))
        if hasattr(self.port_b, "sig_retest"):
            self.port_b.sig_retest.connect(lambda: self._retest_port("B"))
        
        port_splitter.addWidget(self.port_a)
        port_splitter.addWidget(self.port_b)
        port_splitter.setStretchFactor(0, 1)
        port_splitter.setStretchFactor(1, 1)

        # Add sequence tree and port panels to top splitter
        top_splitter.addWidget(self.sequence_tree)
        top_splitter.addWidget(port_splitter)
        
        # Set initial sizes for top splitter (sequence tree: 30%, ports: 70%)
        top_splitter.setSizes([300, 700])
        top_splitter.setStretchFactor(0, 0)  # sequence tree fixed size
        top_splitter.setStretchFactor(1, 1)  # ports expandable

        # Bottom: alerts/events text (QPlainTextEdit 支持按字符选择)
        self.alerts = QPlainTextEdit(central)
        self.alerts.setReadOnly(True)
        self.alerts.setLineWrapMode(QPlainTextEdit.WidgetWidth)  # 启用自动换行
        self.alerts.setPlainText(self._i18n.t("alerts.started"))
        self.alerts.setMinimumHeight(100)  # 最小高度
        self.alerts.setMaximumHeight(400)  # 最大高度
        # 确保垂直滚动条始终可见
        self.alerts.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 右键复制与 Ctrl+C（QPlainTextEdit 支持按字符选择，无需列表选择模式）
        self.alerts.setContextMenuPolicy(Qt.CustomContextMenu)
        self.alerts.customContextMenuRequested.connect(self._on_alerts_context_menu)
        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence.Copy, self.alerts, activated=self._copy_selected_alerts)

        # Add top splitter and alerts to main splitter
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(self.alerts)
        
        # Set initial sizes for main splitter (top: 80%, bottom: 20%)
        main_splitter.setSizes([800, 200])
        main_splitter.setStretchFactor(0, 1)  # top expandable
        main_splitter.setStretchFactor(1, 0)  # bottom fixed size

        # Add main splitter to root layout
        root.addWidget(main_splitter)
        self.setCentralWidget(central)

        # connect language switch
        self.sig_switch_language.connect(self._on_switch_language)

    def _on_toggle_port_b(self, checked: bool) -> None:
        self._set_port_b_visible(checked)

    def _set_port_b_visible(self, visible: bool) -> None:
        """显示/隐藏 PortB 面板。隐藏时确保 PortB 不被选中。"""
        if not hasattr(self, "port_b"):
            return
        try:
            self.port_b.setVisible(bool(visible))
        except Exception:
            pass

        # PortB 默认不选中；隐藏时强制不选中
        try:
            if hasattr(self.port_b, "chk_selected"):
                if not visible:
                    self.port_b.chk_selected.setChecked(False)
                # 显示时也不自动勾选，保持用户选择
        except Exception:
            pass

        # PortA 默认选中
        try:
            if hasattr(self, "port_a") and hasattr(self.port_a, "chk_selected"):
                if not self.port_a.chk_selected.isChecked():
                    self.port_a.chk_selected.setChecked(True)
        except Exception:
            pass

        # 调整 splitter 尺寸，让隐藏时 PortA 占满
        try:
            if hasattr(self, "_port_splitter") and self._port_splitter:
                if visible:
                    self._port_splitter.setSizes([1, 1])
                else:
                    self._port_splitter.setSizes([1, 0])
        except Exception:
            pass

    def _init_statusbar(self) -> None:
        """初始化状态栏"""
        # 创建状态标签
        self.status_label = QLabel("就绪")
        self.statusBar().addWidget(self.status_label)
        
        # 添加其他状态信息
        self.connection_label = QLabel("连接: 未连接")
        self.mes_label = QLabel("MES: 未连接")
        self.statusBar().addPermanentWidget(self.connection_label)
        self.statusBar().addPermanentWidget(self.mes_label)

    def _init_logging_bridge(self) -> None:
        import logging
        self._qt_log_handler = QtLogSignalHandler(level=logging.INFO, parent=self)
        self._qt_log_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
        self._qt_log_handler.sig_log.connect(self._on_log_message)
        root_logger = logging.getLogger()
        root_logger.addHandler(self._qt_log_handler)

    def _init_sequence_model(self) -> None:
        # bind a simple model to the left tree
        self.seq_model = SequenceTreeModel(self.sequence_tree)
        # 不添加硬编码的步骤数据，让_load_default_sequence处理

    # ---- logging bridge callbacks ---------------------------------------
    def _on_log_level_changed(self, level_text: str) -> None:
        import logging
        level = getattr(logging, level_text.upper(), logging.INFO)
        self._qt_log_handler.setLevel(level)

    def _on_log_message(self, message: str, levelno: int) -> None:
        # filter also on UI side based on combo selection
        current = self.cbo_log_level.currentText()
        from logging import _nameToLevel
        if levelno < _nameToLevel.get(current, 20):
            return
        # 追加文本并滚动到底部
        self.alerts.appendPlainText(message)
        from PySide6.QtGui import QTextCursor
        self.alerts.moveCursor(QTextCursor.MoveOperation.End)

    # ---- runtime language switch ----------------------------------------
    def _on_switch_language(self, locale: str) -> None:
        self._i18n.set_locale(locale)
        self._retranslate()

    def _on_show_version(self) -> None:
        try:
            import pkg_resources  # type: ignore
            version = pkg_resources.get_distribution("TestTool").version
        except Exception:
            version = "1.0.0"
        QMessageBox.information(self, "版本", f"TestTool 版本: {version}")

    def _retranslate(self) -> None:
        # window and toolbar
        self.setWindowTitle(self._i18n.t("app.title"))
        self.act_start.setText(self._i18n.t("toolbar.start"))
        self.act_pause.setText(self._i18n.t("toolbar.pause"))
        self.act_stop.setText(self._i18n.t("toolbar.stop"))
        self.act_lang_zh.setText(self._i18n.t("toolbar.lang.zh"))
        self.act_lang_en.setText(self._i18n.t("toolbar.lang.en"))

        # left tree
        self.sequence_tree.setHeaderLabels([
            self._i18n.t("seq.header.step"),
            self._i18n.t("seq.header.status"),
        ])

        # QPlainTextEdit 无需替换首项，避免覆盖已输出内容

        # propagate to child panels
        self.port_a.retranslate(self._i18n)
        self.port_b.retranslate(self._i18n)

    # ---- config dialog ---------------------------------------------------
    def _on_open_config(self) -> None:
        # lazy init config service with default path in cwd
        import os
        if not hasattr(self, "_config_service"):
            cfg_path = os.path.join(os.getcwd(), "config", "config.yaml")
            self._config_service = ConfigService(cfg_path)
            # subscribe hot-reload hooks
            self._config_service.add_listener(self._on_config_changed)
        dlg = ConfigDialog(self, translator=self._i18n, service=self._config_service)
        dlg.exec()

    def _on_config_changed(self, cfg) -> None:
        import logging
        logging.getLogger(__name__).info("config changed -> hot-reload hooks")
        # TODO: reload transports/MES/logging according to cfg

    # ---- workers ---------------------------------------------------------
    def _init_workers(self) -> None:
        # Port A worker
        self._worker_a = PortWorker("PortA")
        self._worker_a.sig_status.connect(self._on_worker_a_status)
        self._worker_a.sig_progress.connect(self._on_worker_a_progress)
        self._worker_a.sig_step.connect(self._on_worker_a_step)
        self._worker_a.sig_step_result.connect(self._on_worker_a_step_result)
        
        # Port B worker
        self._worker_b = PortWorker("PortB")
        self._worker_b.sig_status.connect(self._on_worker_b_status)
        self._worker_b.sig_progress.connect(self._on_worker_b_progress)
        self._worker_b.sig_step.connect(self._on_worker_b_step)
        self._worker_b.sig_step_result.connect(self._on_worker_b_step_result)

    def _on_start(self) -> None:
        """全局开始 - 按选择启动 Port A/Port B"""
        if not self._current_sequence:
            QMessageBox.warning(self, "警告", "请先加载测试序列")
            return
        ports = self._selected_ports()
        if not ports:
            QMessageBox.information(self, "提示", "请先选择要运行的端口 (Port A/Port B)")
            return
        for p in ports:
            if p == "A":
                if self._worker_a.is_paused():
                    self._worker_a.resume()
                elif self._worker_a.is_idle() or self._worker_a.is_completed():
                    self._start_port_with_sequence("A", self._current_sequence)
            elif p == "B":
                if self._worker_b.is_paused():
                    self._worker_b.resume()
                elif self._worker_b.is_idle() or self._worker_b.is_completed():
                    self._start_port_with_sequence("B", self._current_sequence)

    def _on_pause(self) -> None:
        """全局暂停 - 按选择暂停端口"""
        ports = self._selected_ports()
        if "A" in ports and self._worker_a.is_running():
            self._worker_a.pause()
        if "B" in ports and self._worker_b.is_running():
            self._worker_b.pause()

    def _on_stop(self) -> None:
        """全局停止 - 按选择停止端口"""
        ports = self._selected_ports()
        # 停止Port A
        if "A" in ports:
            if hasattr(self, "_worker_a") and self._worker_a:
                self._worker_a.stop()
            if hasattr(self, "_thread_a") and self._thread_a and self._thread_a.isRunning():
                self._thread_a.quit()
                self._thread_a.wait(3000)  # 等待3秒
            self.port_a.lbl_status.setText("Status: Idle")
            self._running_ports.discard("A")
        # 停止Port B
        if "B" in ports:
            if hasattr(self, "_worker_b") and self._worker_b:
                self._worker_b.stop()
            if hasattr(self, "_thread_b") and self._thread_b and self._thread_b.isRunning():
                self._thread_b.quit()
                self._thread_b.wait(3000)  # 等待3秒
            self.port_b.lbl_status.setText("Status: Idle")
            self._running_ports.discard("B")

        # 如果两个都停止，则清空运行端口记录
        if not self._running_ports:
            self._running_ports.clear()

    def _selected_ports(self) -> list[str]:
        """返回当前勾选的端口标识列表，例如 ["A"], ["B"], ["A","B"] 或 []

        直接读取各自 `PortPanel` 的 `chk_selected` 作为选择源。
        """
        selected = []
        try:
            if hasattr(self, 'port_a') and hasattr(self.port_a, 'chk_selected') and self.port_a.chk_selected.isChecked():
                selected.append("A")
        except Exception:
            pass
        try:
            if hasattr(self, 'port_b') and hasattr(self.port_b, 'chk_selected') and self.port_b.chk_selected.isChecked():
                selected.append("B")
        except Exception:
            pass
        return selected
    
    def _start_port(self, port: str) -> None:
        """启动指定端口 - 处理暂停状态恢复"""
        print(f"DEBUG: 启动端口 {port}")
        if not self._current_sequence:
            QMessageBox.warning(self, "警告", "请先加载测试序列")
            return
            
        if port == "A":
            if hasattr(self, "_worker_a") and self._worker_a:
                if self._worker_a.is_paused():
                    print(f"DEBUG: Port A 从暂停状态恢复")
                    self._worker_a.resume()
                elif self._worker_a.is_idle() or self._worker_a.is_completed():
                    print(f"DEBUG: Port A 开始新的测试")
                    self._start_port_with_sequence("A", self._current_sequence)
                else:
                    print(f"DEBUG: Port A 正在运行中，无法启动")
            else:
                print(f"DEBUG: Port A worker 不存在，创建新的")
                self._start_port_with_sequence("A", self._current_sequence)
        elif port == "B":
            if hasattr(self, "_worker_b") and self._worker_b:
                if self._worker_b.is_paused():
                    print(f"DEBUG: Port B 从暂停状态恢复")
                    self._worker_b.resume()
                elif self._worker_b.is_idle() or self._worker_b.is_completed():
                    print(f"DEBUG: Port B 开始新的测试")
                    self._start_port_with_sequence("B", self._current_sequence)
                else:
                    print(f"DEBUG: Port B 正在运行中，无法启动")
            else:
                print(f"DEBUG: Port B worker 不存在，创建新的")
                self._start_port_with_sequence("B", self._current_sequence)
    
    def _pause_port(self, port: str) -> None:
        """暂停指定端口"""
        print(f"DEBUG: 暂停端口 {port}")
        if port == "A":
            if hasattr(self, "_worker_a") and self._worker_a:
                if self._worker_a.is_running():
                    self._worker_a.pause()
                    print(f"DEBUG: Port A 已暂停")
                else:
                    print(f"DEBUG: Port A 未运行，无法暂停")
            else:
                print(f"DEBUG: Port A worker 不存在")
        elif port == "B":
            if hasattr(self, "_worker_b") and self._worker_b:
                if self._worker_b.is_running():
                    self._worker_b.pause()
                    print(f"DEBUG: Port B 已暂停")
                else:
                    print(f"DEBUG: Port B 未运行，无法暂停")
            else:
                print(f"DEBUG: Port B worker 不存在")
    
    def _stop_port(self, port: str) -> None:
        """停止指定端口"""
        print(f"DEBUG: 停止端口 {port}")
        if port == "A":
            if hasattr(self, "_worker_a") and self._worker_a:
                self._worker_a.stop()
                print(f"DEBUG: Port A worker 已停止")
            if hasattr(self, "_thread_a") and self._thread_a and self._thread_a.isRunning():
                self._thread_a.quit()
                self._thread_a.wait(3000)
                print(f"DEBUG: Port A 线程已停止")
            self._running_ports.discard("A")
            self.port_a.lbl_status.setText("Status: Idle")
            print(f"DEBUG: Port A 状态已更新为 Idle")
        elif port == "B":
            if hasattr(self, "_worker_b") and self._worker_b:
                self._worker_b.stop()
                print(f"DEBUG: Port B worker 已停止")
            if hasattr(self, "_thread_b") and self._thread_b and self._thread_b.isRunning():
                self._thread_b.quit()
                self._thread_b.wait(3000)
                print(f"DEBUG: Port B 线程已停止")
            self._running_ports.discard("B")
            self.port_b.lbl_status.setText("Status: Idle")
            print(f"DEBUG: Port B 状态已更新为 Idle")
    
    def _start_port_with_sequence(self, port: str, sequence, retest: bool = False) -> None:
        """使用指定序列启动Port"""
        if not sequence:
            QMessageBox.warning(self, "警告", "请先加载测试序列")
            return
        
        # 将端口名称转换为完整格式
        full_port_name = f"Port{port}" if len(port) == 1 else port
        
        # 创建测试上下文
        context = self._create_test_context(full_port_name)
        if not context:
            QMessageBox.warning(self, "警告", f"无法创建{full_port_name}的测试上下文")
            return
            
        # 清零结果表和当前测试项显示
        if port == "A":
            self.port_a.table.setRowCount(0)
            self.port_a.lbl_step.setText("-")
            self.port_a.lbl_expect.setText("期望: -")
            self.port_a.lbl_meas.setText("测量: -")
            self.port_a.lbl_retries.setText("重试: 0")
            self._port_a_had_fail = False
            self.port_a.lbl_status.setText("Status: Running")
            if hasattr(self.port_a, "set_overall_result"):
                self.port_a.set_overall_result(None)
        elif port == "B":
            self.port_b.table.setRowCount(0)
            self.port_b.lbl_step.setText("-")
            self.port_b.lbl_expect.setText("期望: -")
            self.port_b.lbl_meas.setText("测量: -")
            self.port_b.lbl_retries.setText("重试: 0")
            self._port_b_had_fail = False
            self.port_b.lbl_status.setText("Status: Running")
            if hasattr(self.port_b, "set_overall_result"):
                self.port_b.set_overall_result(None)
            
        # 记录运行端口
        self._running_ports.add(port)
        
        # 启动工作线程
        self._start_worker_thread(full_port_name, sequence, retest=retest)
    
    def _on_port_mode_changed(self, port: str, mode: str) -> None:
        """处理端口测试模式改变"""
        if port == "A" and hasattr(self, "_worker_a") and self._worker_a:
            self._worker_a.set_test_mode(mode)
            logger.info(f"Port A 测试模式已设置为: {mode}")
        elif port == "B" and hasattr(self, "_worker_b") and self._worker_b:
            self._worker_b.set_test_mode(mode)
            logger.info(f"Port B 测试模式已设置为: {mode}")
    
    def _create_test_context(self, port: str) -> Optional[Context]:
        """创建测试上下文"""
        try:
            self.alerts.appendPlainText(f"[{port}] 开始创建测试上下文...")
            
            # 获取端口配置
            config = self._config_service.load()
            if not config:
                self.alerts.appendPlainText(f"[{port}] 配置加载失败")
                return None
                
            # 将端口名称转换为配置中的键名
            port_key = port[0].lower() + port[1:]  # PortA -> portA, PortB -> portB
            self.alerts.appendPlainText(f"[{port}] 端口键名: {port_key}")
            
            port_config = getattr(config.ports, port_key, None)
            if not port_config:
                self.alerts.appendPlainText(f"[{port}] 端口配置不存在，可用端口: {dir(config.ports)}")
                return None
                
            self.alerts.appendPlainText(f"[{port}] 端口配置获取成功")
            
            # 创建设备实例
            instruments = {}
            
            # 创建电源实例（如果启用）
            if hasattr(port_config, 'instruments') and port_config.instruments:
                for inst_id, inst_config in port_config.instruments.items():
                    if inst_config.enabled and inst_config.type == "PSU":
                        try:
                            psu = create_power_supply(
                                instrument_id=inst_id,
                                interface_type=inst_config.interface,
                                resource=inst_config.resource if inst_config.interface == "VISA" else None,
                                host=inst_config.host if inst_config.interface == "TCP" else None,
                                port=inst_config.port if inst_config.interface == "TCP" else None,
                                timeout_ms=inst_config.timeout_ms
                            )
                            instruments[inst_id] = psu
                            self.alerts.appendPlainText(f"[{port}] 创建电源 {inst_id}: {inst_config.interface}")
                        except Exception as e:
                            self.alerts.appendPlainText(f"[{port}] 创建电源 {inst_id} 失败: {e}")
            
            # 创建上下文
            self.alerts.appendPlainText(f"[{port}] 开始创建Context对象...")
            
            # 获取TestLogger的logger实例，确保Context使用相同的logger
            # 这样ctx.log_info()等调用就能写入到TestLogger创建的文件中
            test_logger_instance = None
            if port == "PortA" and hasattr(self, '_test_logger_a') and self._test_logger_a:
                test_logger_instance = self._test_logger_a.logger
            elif port == "PortB" and hasattr(self, '_test_logger_b') and self._test_logger_b:
                test_logger_instance = self._test_logger_b.logger
            
            # 如果TestLogger还没有初始化logger，使用相同的名称获取logger
            # logging.getLogger()对于相同名称会返回同一个实例，这样会与TestLogger共享logger
            if test_logger_instance is None:
                test_logger_instance = logging.getLogger(f"Test.{port}")
                self.alerts.appendPlainText(f"[{port}] 使用默认logger: Test.{port}")
            else:
                self.alerts.appendPlainText(f"[{port}] 使用TestLogger的logger实例")
            
            context = create_context(
                port=port,
                uut=None,  # TODO: 从配置创建UUT实例
                fixture=None,  # TODO: 从配置创建治具实例
                instruments=instruments,
                logger=test_logger_instance  # 使用TestLogger的logger，确保日志能写入文件
            )
            
            if not context:
                self.alerts.appendPlainText(f"[{port}] Context对象创建失败")
                return None
                
            self.alerts.appendPlainText(f"[{port}] Context对象创建成功")
            
            # 将端口配置转换为字典并设置到context（使用Pydantic的model_dump方法）
            port_config_dict = port_config.model_dump(exclude_none=True)
            context.set_port_config(port_config_dict)

            # 将端口配置中与 PLC / 治具相关的串口参数注入到 Context.state，
            # 供 plc.modbus.* 步骤直接使用（避免每次都手动改 YAML）
            try:
                fixture_cfg = getattr(port_config, "fixture", None)
                if fixture_cfg and getattr(fixture_cfg, "enabled", False):
                    serial_cfg = fixture_cfg.serial
                    # COM 口
                    if getattr(serial_cfg, "port", None):
                        context.set_data("plc_serial_port", serial_cfg.port)
                        self.alerts.appendPlainText(
                            f"[{port}] 使用治具串口作为 PLC 串口: {serial_cfg.port}"
                        )
                    # 波特率
                    if getattr(serial_cfg, "baudrate", None):
                        context.set_data("plc_baudrate", serial_cfg.baudrate)
                    # 超时时间：ms -> s，至少 1 秒
                    timeout_ms = getattr(serial_cfg, "timeout_ms", None)
                    if timeout_ms is not None:
                        plc_timeout_s = max(1, int(timeout_ms / 1000))
                        context.set_data("plc_timeout", plc_timeout_s)
                    # 默认从站地址（如未在序列中覆盖）
                    if context.get_data("plc_unit_id", None) is None:
                        context.set_data("plc_unit_id", 1)
            except Exception as e:
                # 不因配置注入失败中断创建，仅记录日志
                self.alerts.appendPlainText(f"[{port}] 注入 PLC 串口配置失败: {e}")
            
            # 设置SN
            sn = self._sn_by_port.get(port, "NULL")
            self.alerts.appendPlainText(f"[{port}] 设置SN: {sn}")
            context.set_sn(sn)
            
            self.alerts.appendPlainText(f"[{port}] 测试上下文创建成功，SN: {sn}")
            return context
            
        except Exception as e:
            self.alerts.appendPlainText(f"[{port}] 创建测试上下文失败: {e}")
            return None
    
    def _start_worker_thread(self, port: str, sequence, retest: bool = False) -> None:
        """启动工作线程
        
        Parameters
        ----------
        port : str
            端口名称，如 "PortA"/"PortB" 或 "A"/"B"
        sequence :
            要执行的测试序列
        retest : bool
            是否为复测模式（跳过SN扫描，使用上一轮SN）
        """
        from PySide6.QtCore import QThread
        from ..worker import PortWorker
        
        # 统一端口标识，兼容传入 "A"/"B" 或 "PortA"/"PortB"
        port_short = port[-1] if port.upper().endswith(("A", "B")) else port
        if port_short == "A":
            # 如果线程存在且正在运行，先停止
            if hasattr(self, "_thread_a") and self._thread_a.isRunning():
                self._thread_a.quit()
                self._thread_a.wait()
            
            # 断开旧的信号连接（如果存在）
            if hasattr(self, "_worker_a"):
                try:
                    self._worker_a.sig_status.disconnect()
                    self._worker_a.sig_progress.disconnect()
                    self._worker_a.sig_step.disconnect()
                except:
                    pass  # 忽略断开连接时的错误
            
            # 重新创建worker对象，避免线程移动问题
            self._worker_a = PortWorker("PortA")
            self._worker_a.sig_status.connect(self._on_worker_a_status)
            self._worker_a.sig_progress.connect(self._on_worker_a_progress)
            self._worker_a.sig_step.connect(self._on_worker_a_step)
            # 确保接收步骤结果以更新SN
            if hasattr(self._worker_a, 'sig_step_result'):
                self._worker_a.sig_step_result.connect(self._on_worker_a_step_result)
            
            # 设置测试序列和上下文
            self._worker_a.set_sequence(sequence)
            context = self._create_test_context("PortA")
            if context:
                self._worker_a.set_context(context)
            # 设置测试模式（从PortPanel获取）
            test_mode = self.port_a.get_test_mode()
            self._worker_a.set_test_mode(test_mode)
            # 设置是否为复测模式
            if hasattr(self._worker_a, "set_retest_mode"):
                self._worker_a.set_retest_mode(retest)
            self._thread_a = QThread(self)
            self._worker_a.moveToThread(self._thread_a)
            self._thread_a.started.connect(self._worker_a.start_run)
            self._thread_a.start()

            # 记录测试开始日志（带端口SN）
            sn = self._sn_by_port.get("PortA", "NULL")
            self.log_test_start("PortA", sn, sequence.metadata.name)
        elif port_short == "B":
            # 如果线程存在且正在运行，先停止
            if hasattr(self, "_thread_b") and self._thread_b.isRunning():
                self._thread_b.quit()
                self._thread_b.wait()
            
            # 断开旧的信号连接（如果存在）
            if hasattr(self, "_worker_b"):
                try:
                    self._worker_b.sig_status.disconnect()
                    self._worker_b.sig_progress.disconnect()
                    self._worker_b.sig_step.disconnect()
                except:
                    pass  # 忽略断开连接时的错误
            
            # 重新创建worker对象，避免线程移动问题
            self._worker_b = PortWorker("PortB")
            self._worker_b.sig_status.connect(self._on_worker_b_status)
            self._worker_b.sig_progress.connect(self._on_worker_b_progress)
            self._worker_b.sig_step.connect(self._on_worker_b_step)
            # 确保接收步骤结果以更新SN
            if hasattr(self._worker_b, 'sig_step_result'):
                self._worker_b.sig_step_result.connect(self._on_worker_b_step_result)
            
            # 设置测试序列和上下文
            self._worker_b.set_sequence(sequence)
            context = self._create_test_context("PortB")
            if context:
                self._worker_b.set_context(context)
            # 设置测试模式（从PortPanel获取）
            test_mode = self.port_b.get_test_mode()
            self._worker_b.set_test_mode(test_mode)
            # 设置是否为复测模式
            if hasattr(self._worker_b, "set_retest_mode"):
                self._worker_b.set_retest_mode(retest)
            self._thread_b = QThread(self)
            self._worker_b.moveToThread(self._thread_b)
            self._thread_b.started.connect(self._worker_b.start_run)
            self._thread_b.start()
            
            # 记录测试开始日志（带端口SN）
            sn = self._sn_by_port.get("PortB", "NULL")
            self.log_test_start("PortB", sn, sequence.metadata.name)

    def _on_worker_a_status(self, status: str) -> None:
        # 完成时根据是否失败显示 Pass/Fail
        if status == "Completed":
            final = "Fail" if self._port_a_had_fail else "Pass"
            self.port_a.lbl_status.setText(f"Status: {final}")
            self.port_a.lbl_step.setText("-")
            self.port_a.lbl_expect.setText("期望: -")
            self.port_a.progress.setValue(100)
            if hasattr(self.port_a, "set_overall_result"):
                self.port_a.set_overall_result(final)
            # 记录测试结束日志（带端口SN）
            sn = self._sn_by_port.get("PortA", "NULL")
            self.log_test_end("PortA", sn, final, 0.0)
        else:
            self.port_a.lbl_status.setText(f"Status: {status}")
            if status in ("Idle", "Preparing", "Running", "Paused") and hasattr(self.port_a, "set_overall_result"):
                # 非完成态不展示整体结果
                self.port_a.set_overall_result(None)
            if status in ("Idle", "Completed") and hasattr(self, "_thread_a"):
                self._running_ports.discard("A")  # 移除运行端口记录
                self._thread_a.quit()
                self._thread_a.wait()
                # 不需要移动worker，因为下次会重新创建

    def _on_worker_a_progress(self, percent: int) -> None:
        self.port_a.progress.setValue(percent)

    def _on_worker_a_step(self, step_id: str, status: str) -> None:
        # update sequence tree status for matching id (if exists) - Port A
        self.seq_model.update_step(step_id, status=status, port="A")
        
        # 记录失败状态
        if status == "Fail":
            self._port_a_had_fail = True
        
        # 更新Port A的当前测试项显示（Pass/Fail/Skipped 时清除，避免界面一直停在上一项“运行中”）
        if self._current_sequence:
            for step in self._current_sequence.steps:
                if step.id == step_id:
                    if status == "Running":
                        self.port_a.lbl_step.setText(step.name)
                        self.port_a.lbl_expect.setText(f"期望: {getattr(step, 'expect', 'N/A')}")
                    elif status == "Pass":
                        self.port_a.lbl_step.setText("-")
                        self.port_a.lbl_expect.setText("期望: -")
                    elif status == "Fail":
                        self.port_a.lbl_step.setText(f"{step.name} — 失败")
                        self.port_a.lbl_expect.setText("期望: -")
                    elif status == "Skipped":
                        self.port_a.lbl_step.setText("-")
                        self.port_a.lbl_expect.setText("期望: -")
                    break
    
    def _on_worker_a_step_result(self, step_id: str, result) -> None:
        """Port A 步骤结果处理"""
        # 如果步骤返回了SN并且通过，更新PortA的SN缓存，供日志文件命名使用
        try:
            if getattr(result, "passed", False) and hasattr(result, "data") and isinstance(result.data, dict):
                sn_value = result.data.get("sn")
                if isinstance(sn_value, str) and sn_value:
                    self._sn_by_port["PortA"] = sn_value
                    # 更新Port A 面板上的 SN 显示
                    try:
                        self.port_a.lbl_sn.setText(f"SN: {sn_value}")
                    except Exception:
                        pass
        except Exception:
            pass
        
        # 将显示名设置为步骤描述（名称），不展示ID
        display_name = step_id
        if self._current_sequence:
            for step in self._current_sequence.steps:
                if step.id == step_id:
                    display_name = step.name
                    break
        
        # 从结果数据中提取测试值（如果有）
        if hasattr(result, 'data') and result.data:
            value = result.data.get('current', result.data.get('value', ''))
            low = result.data.get('expect_min', result.data.get('low', ''))
            high = result.data.get('expect_max', result.data.get('high', ''))
            unit = result.data.get('unit', '')  # 如果没有指定单位，使用空字符串
        else:
            # 如果没有数据，使用空值
            value = ""
            low = ""
            high = ""
            unit = ""
        
        # 如果是失败且有错误代码，在value列显示错误代码
        if not result.passed:
            # 获取错误代码，优先从error_code字段，其次从data中
            error_code = result.error_code if hasattr(result, 'error_code') else None
            if not error_code and result.data:
                error_code = result.data.get('error_code')
            
            if error_code:
                value = error_code
                unit = ""  # 错误代码不使用单位
        
        # 添加到测试结果表格
        self.port_a.add_test_result(
            step_name=display_name,
            value=str(value),
            low=str(low),
            high=str(high),
            unit=unit,
            result="Pass" if result.passed else "Fail"
        )
    
    def _on_worker_b_step_result(self, step_id: str, result) -> None:
        """Port B 步骤结果处理"""
        # 如果步骤返回了SN并且通过，更新PortB的SN缓存，供日志文件命名使用
        try:
            if getattr(result, "passed", False) and hasattr(result, "data") and isinstance(result.data, dict):
                sn_value = result.data.get("sn")
                if isinstance(sn_value, str) and sn_value:
                    self._sn_by_port["PortB"] = sn_value
                    # 更新Port B 面板上的 SN 显示
                    try:
                        self.port_b.lbl_sn.setText(f"SN: {sn_value}")
                    except Exception:
                        pass
        except Exception:
            pass
        
        # 将显示名设置为步骤描述（名称），不展示ID
        display_name = step_id
        if self._current_sequence:
            for step in self._current_sequence.steps:
                if step.id == step_id:
                    display_name = step.name
                    break
        
        # 从结果数据中提取测试值（如果有）
        if hasattr(result, 'data') and result.data:
            value = result.data.get('current', result.data.get('value', ''))
            low = result.data.get('expect_min', result.data.get('low', ''))
            high = result.data.get('expect_max', result.data.get('high', ''))
            unit = result.data.get('unit', '')  # 如果没有指定单位，使用空字符串
        else:
            # 如果没有数据，使用空值
            value = ""
            low = ""
            high = ""
            unit = ""
        
        # 如果是失败且有错误代码，在value列显示错误代码
        if not result.passed:
            # 获取错误代码，优先从error_code字段，其次从data中
            error_code = result.error_code if hasattr(result, 'error_code') else None
            if not error_code and result.data:
                error_code = result.data.get('error_code')
            
            if error_code:
                value = error_code
                unit = ""  # 错误代码不使用单位
        
        # 添加到测试结果表格
        self.port_b.add_test_result(
            step_name=display_name,
            value=str(value),
            low=str(low),
            high=str(high),
            unit=unit,
            result="Pass" if result.passed else "Fail"
        )
    
    def _on_worker_b_status(self, status: str) -> None:
        if status == "Completed":
            final = "Fail" if self._port_b_had_fail else "Pass"
            self.port_b.lbl_status.setText(f"Status: {final}")
            self.port_b.lbl_step.setText("-")
            self.port_b.lbl_expect.setText("期望: -")
            self.port_b.progress.setValue(100)
            if hasattr(self.port_b, "set_overall_result"):
                self.port_b.set_overall_result(final)
            # 记录测试结束日志（带端口SN）
            sn = self._sn_by_port.get("PortB", "NULL")
            self.log_test_end("PortB", sn, final, 0.0)
        else:
            self.port_b.lbl_status.setText(f"Status: {status}")
            if status in ("Idle", "Preparing", "Running", "Paused") and hasattr(self.port_b, "set_overall_result"):
                self.port_b.set_overall_result(None)
        if status in ("Idle", "Completed") and hasattr(self, "_thread_b"):
            self._running_ports.discard("B")  # 移除运行端口记录
            self._thread_b.quit()
            self._thread_b.wait()
            # 不需要移动worker，因为下次会重新创建

    def _on_worker_b_progress(self, percent: int) -> None:
        self.port_b.progress.setValue(percent)

    def _on_worker_b_step(self, step_id: str, status: str) -> None:
        # update sequence tree status for matching id (if exists) - Port B
        self.seq_model.update_step(step_id, status=status, port="B")
        
        # 记录失败状态
        if status == "Fail":
            self._port_b_had_fail = True
        
        # 更新Port B的当前测试项显示（Pass/Fail/Skipped 时清除，避免界面一直停在上一项“运行中”）
        if self._current_sequence:
            for step in self._current_sequence.steps:
                if step.id == step_id:
                    if status == "Running":
                        self.port_b.lbl_step.setText(step.name)
                        self.port_b.lbl_expect.setText(f"期望: {getattr(step, 'expect', 'N/A')}")
                    elif status == "Pass":
                        self.port_b.lbl_step.setText("-")
                        self.port_b.lbl_expect.setText("期望: -")
                    elif status == "Fail":
                        self.port_b.lbl_step.setText(f"{step.name} — 失败")
                        self.port_b.lbl_expect.setText("期望: -")
                    elif status == "Skipped":
                        self.port_b.lbl_step.setText("-")
                        self.port_b.lbl_expect.setText("期望: -")
                    break
    
    # ---- logging system ----------------------------------------------------
    def _init_logging_system(self) -> None:
        """初始化日志系统"""
        # 获取日志管理器
        logging_manager = get_logging_manager()
        if not logging_manager:
            logger.warning("日志管理器未初始化")
            return
        
        # 设置Qt处理器
        if hasattr(self, '_log_handler'):
            logging_manager.setup_qt_handler(self._log_handler)
        
        # 为端口设置日志器
        self._setup_port_loggers()
        
        # 记录系统启动日志
        system_logger = logging_manager.get_system_logger()
        if system_logger:
            system_logger.info("主窗口初始化完成", extra={"operation": "UI_INIT"})
    
    def _setup_port_loggers(self) -> None:
        """为端口设置日志器"""
        logging_manager = get_logging_manager()
        if not logging_manager:
            return
        
        # 为Port A设置日志器
        test_logger_a = logging_manager.setup_test_logger("PortA", None)  # 使用NULL作为默认值
        error_logger_a = logging_manager.setup_error_logger("PortA", None)
        
        # 为Port B设置日志器
        test_logger_b = logging_manager.setup_test_logger("PortB", None)  # 使用NULL作为默认值
        error_logger_b = logging_manager.setup_error_logger("PortB", None)
        
        # 存储日志器引用
        self._test_logger_a = test_logger_a
        self._error_logger_a = error_logger_a
        self._test_logger_b = test_logger_b
        self._error_logger_b = error_logger_b
        
        logger.info("端口日志器设置完成")
    
    def log_test_start(self, port: str, sn: str, sequence_file: str) -> None:
        """记录测试开始"""
        print(f"DEBUG: log_test_start called for {port}")
        config_info = self._get_current_config_info()
        print(f"DEBUG: log_test_start config_info = {config_info}")
        
        # 确保使用最新的配置
        self._reload_logging_config()
        
        # 重新创建TestLogger以使用最新配置
        from ...app_logging import get_logging_manager
        logging_manager = get_logging_manager()
        if not logging_manager:
            print("DEBUG: 日志管理器未初始化")
            return
        
        # 确保LoggingManager使用正确的配置类型
        if hasattr(self, '_config_service'):
            config = self._config_service.config
            logging_manager.update_config(config.logging)
        
        log_file_path = None
        
        if port == "PortA":
            # 重新创建TestLogger和ErrorLogger
            self._test_logger_a = logging_manager.setup_test_logger("PortA", sn)
            self._error_logger_a = logging_manager.setup_error_logger("PortA", sn)
            
            log_file_path = self._test_logger_a.log_test_start(sn, port, sequence_file, config_info)
            self._error_logger_a.set_product_info(
                config_info.get("product", "NULL"),
                config_info.get("station", "NULL"),
                config_info.get("version", "NULL")
            )
        elif port == "PortB":
            # 重新创建TestLogger和ErrorLogger
            self._test_logger_b = logging_manager.setup_test_logger("PortB", sn)
            self._error_logger_b = logging_manager.setup_error_logger("PortB", sn)
            
            log_file_path = self._test_logger_b.log_test_start(sn, port, sequence_file, config_info)
            self._error_logger_b.set_product_info(
                config_info.get("product", "NULL"),
                config_info.get("station", "NULL"),
                config_info.get("version", "NULL")
            )
        
        # 在界面中显示日志文件位置信息
        if log_file_path:
            print(f"DEBUG: 显示日志文件位置: {log_file_path}")
            # 直接添加到界面，不经过日志级别过滤
            self.alerts.appendPlainText(f"[{port}] 测试日志文件已创建: {log_file_path}")
            from PySide6.QtGui import QTextCursor
            self.alerts.moveCursor(QTextCursor.MoveOperation.End)
        else:
            print(f"DEBUG: 没有获取到日志文件路径")
            # 即使没有路径也显示信息
            self.alerts.appendPlainText(f"[{port}] 测试日志文件创建失败")
            from PySide6.QtGui import QTextCursor
            self.alerts.moveCursor(QTextCursor.MoveOperation.End)
    
    def log_test_end(self, port: str, sn: str, result: str, duration: float, summary: dict = None) -> None:
        """记录测试结束"""
        print(f"DEBUG: log_test_end called for {port}, result={result}")
        
        # 确保使用最新的配置和TestLogger
        self._reload_logging_config()
        
        # 重新创建TestLogger以使用最新配置
        from ...app_logging import get_logging_manager
        logging_manager = get_logging_manager()
        if not logging_manager:
            print("DEBUG: 日志管理器未初始化")
            return
        
        renamed_file_path = None
        
        # 获取当前配置信息
        config_info = self._get_current_config_info()
        
        if port == "PortA":
            # 直接使用现有的TestLogger，不重新创建
            if hasattr(self, '_test_logger_a') and self._test_logger_a:
                # 设置产品信息
                self._test_logger_a.product = config_info.get("product", "NULL")
                self._test_logger_a.station = config_info.get("station", "NULL")
                self._test_logger_a.version = config_info.get("version", "NULL")
                print(f"DEBUG: 使用现有TestLogger，产品: {self._test_logger_a.product}, 测试站: {self._test_logger_a.station}, 版本: {self._test_logger_a.version}")
                renamed_file_path = self._test_logger_a.log_test_end(sn, port, result, duration, summary)
            else:
                print("DEBUG: TestLogger A 不存在，无法记录测试结束")
                renamed_file_path = None
        elif port == "PortB":
            # 直接使用现有的TestLogger，不重新创建
            if hasattr(self, '_test_logger_b') and self._test_logger_b:
                # 设置产品信息
                self._test_logger_b.product = config_info.get("product", "NULL")
                self._test_logger_b.station = config_info.get("station", "NULL")
                self._test_logger_b.version = config_info.get("version", "NULL")
                print(f"DEBUG: 使用现有TestLogger，产品: {self._test_logger_b.product}, 测试站: {self._test_logger_b.station}, 版本: {self._test_logger_b.version}")
                renamed_file_path = self._test_logger_b.log_test_end(sn, port, result, duration, summary)
            else:
                print("DEBUG: TestLogger B 不存在，无法记录测试结束")
                renamed_file_path = None
        
        # 在界面中显示重命名后的日志文件位置信息
        if renamed_file_path:
            print(f"DEBUG: 显示重命名后的日志文件位置: {renamed_file_path}")
            # 直接添加到界面，不经过日志级别过滤
            self.alerts.appendPlainText(f"[{port}] 测试完成，日志文件已重命名: {renamed_file_path}")
            from PySide6.QtGui import QTextCursor
            self.alerts.moveCursor(QTextCursor.MoveOperation.End)
        else:
            print(f"DEBUG: 没有获取到重命名后的日志文件路径")
            # 即使没有路径也显示信息
            self.alerts.appendPlainText(f"[{port}] 测试完成，但日志文件重命名失败")
            from PySide6.QtGui import QTextCursor
            self.alerts.moveCursor(QTextCursor.MoveOperation.End)
    
    def log_error(self, port: str, error_type: str, error: str, details: str = None) -> None:
        """记录错误"""
        if port == "PortA" and hasattr(self, '_error_logger_a'):
            if error_type == "test":
                self._error_logger_a.log_test_error("unknown", error, details)
            elif error_type == "comm":
                self._error_logger_a.log_comm_error("unknown", error, details)
            elif error_type == "instrument":
                self._error_logger_a.log_instrument_error("unknown", error, details)
            elif error_type == "mes":
                self._error_logger_a.log_mes_error("unknown", error, details)
            elif error_type == "system":
                self._error_logger_a.log_system_error("unknown", error, details)
        elif port == "PortB" and hasattr(self, '_error_logger_b'):
            if error_type == "test":
                self._error_logger_b.log_test_error("unknown", error, details)
            elif error_type == "comm":
                self._error_logger_b.log_comm_error("unknown", error, details)
            elif error_type == "instrument":
                self._error_logger_b.log_instrument_error("unknown", error, details)
            elif error_type == "mes":
                self._error_logger_b.log_mes_error("unknown", error, details)
            elif error_type == "system":
                self._error_logger_b.log_system_error("unknown", error, details)
    
    def _reload_logging_config(self) -> None:
        """重新加载日志配置，确保使用最新的配置文件"""
        if not hasattr(self, '_config_service'):
            print("DEBUG: 配置服务未初始化")
            return
        
        try:
            # 重新加载配置文件
            print("DEBUG: 开始重新加载配置文件...")
            self._config_service.load()
            config = self._config_service.config
            print(f"DEBUG: 配置文件重新加载成功")
            print(f"DEBUG: 测试日志文件名格式: {config.logging.test_log.filename}")
            print(f"DEBUG: 错误日志文件名格式: {config.logging.error_log.filename}")
            
            # 更新全局日志管理器的配置
            from ...app_logging import get_logging_manager
            logging_manager = get_logging_manager()
            if logging_manager:
                print("DEBUG: 更新LoggingManager配置...")
                print(f"DEBUG: 配置类型: {type(config.logging)}")
                print(f"DEBUG: 配置对象: {config.logging}")
                logging_manager.update_config(config.logging)
                print(f"DEBUG: LoggingManager配置更新完成")
            else:
                print("DEBUG: LoggingManager未找到")
        except Exception as e:
            print(f"DEBUG: 重新加载日志配置失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _get_current_config_info(self) -> dict:
        """获取当前配置信息"""
        if not hasattr(self, '_config_service'):
            return {}
        
        config = self._config_service.config
        
        # 从当前序列中获取产品名称、测试站和版本信息
        product = "NULL"
        station = "NULL"
        version = "NULL"
        if hasattr(self, '_current_sequence') and self._current_sequence:
            product = self._current_sequence.metadata.product or "NULL"
            station = self._current_sequence.metadata.station or "NULL"
            version = self._current_sequence.metadata.version or "NULL"
        
        return {
            "product": product,
            "station": station,
            "version": version,
            "串口配置": {
                "PortA": f"{config.ports.portA.serial.port}, {config.ports.portA.serial.baudrate}, {config.ports.portA.serial.bytesize}{config.ports.portA.serial.parity}{config.ports.portA.serial.stopbits}",
                "PortB": f"{config.ports.portB.serial.port}, {config.ports.portB.serial.baudrate}, {config.ports.portB.serial.bytesize}{config.ports.portB.serial.parity}{config.ports.portB.serial.stopbits}"
            },
            "TCP配置": {
                "PortA": f"{config.ports.portA.tcp.host}:{config.ports.portA.tcp.port}",
                "PortB": f"{config.ports.portB.tcp.host}:{config.ports.portB.tcp.port}"
            },
            "MES配置": {
                "服务器": config.mes.base_url,
                "超时": f"{config.mes.timeout_ms}ms"
            },
            "测试序列": config.test_sequence.file
        }

    def _open_sequence_editor(self) -> None:
        """打开序列编辑器"""
        try:
            from ..tools.tool_launcher import launch_sequence_editor
            editor = launch_sequence_editor(self)
            
            if editor:
                # 连接信号
                if hasattr(editor, 'sig_sequence_loaded'):
                    editor.sig_sequence_loaded.connect(self._on_sequence_loaded)
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开序列编辑器: {e}")
    
    def _open_step_library(self) -> None:
        """打开步骤库管理器"""
        try:
            from ..tools.tool_launcher import launch_step_library
            library = launch_step_library(self)
            
            if library:
                # 连接信号
                if hasattr(library, 'sig_step_selected'):
                    library.sig_step_selected.connect(self._on_step_template_selected)
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开步骤库管理器: {e}")
    
    def _on_sequence_loaded(self, sequence_path: str) -> None:
        """处理序列加载事件"""
        try:
            from ...testcases.utils import load_test_sequence
            sequence = load_test_sequence(sequence_path)
            self._current_sequence = sequence
            self._update_sequence_display()
            
            # 保存最后使用的序列到配置
            self._save_last_used_sequence(sequence_path)
            
            QMessageBox.information(self, "序列加载成功", 
                                   f"已加载测试序列：{sequence_path}")
        except Exception as e:
            QMessageBox.warning(self, "序列加载失败", f"加载序列时出错：{e}")
    
    def _on_step_template_selected(self, step_config) -> None:
        """处理步骤模板选择事件"""
        try:
            # 如果有序列编辑器打开，将模板传递给它
            for child in self.findChildren(QWidget):
                if hasattr(child, 'insert_step_template'):
                    child.insert_step_template(step_config)
                    break
            else:
                QMessageBox.information(self, "模板选择", 
                                       f"已选择步骤模板：{step_config.name}\n\n请在序列编辑器中使用此模板。")
        except Exception as e:
            QMessageBox.warning(self, "模板处理失败", f"处理步骤模板时出错：{e}")
    
    def _update_sequence_display(self) -> None:
        """更新序列显示"""
        if self._current_sequence:
            # 更新序列树显示
            self._update_sequence_tree(self._current_sequence)
            # 构建显示名称
            display_name = f"{self._current_sequence.metadata.product}-{self._current_sequence.metadata.station}-{self._current_sequence.metadata.version}-{self._current_sequence.metadata.created_at[:10].replace('-', '')}"
            # 更新状态栏
            self.statusBar().showMessage(f"当前序列: {display_name}")
    
    def _load_test_sequence(self) -> None:
        """加载测试序列"""
        try:
            from ...testcases.utils import load_test_sequence
            
            # 打开文件选择对话框
            file_path, _ = QFileDialog.getOpenFileName(
                self, "加载测试序列",
                "", "YAML文件 (*.yaml *.yml);;JSON文件 (*.json);;所有文件 (*)"
            )
            
            if file_path:
                # 加载序列文件
                sequence = load_test_sequence(file_path)
                self._current_sequence = sequence  # 更新当前序列
                
                # 更新序列树显示
                self._update_sequence_tree(sequence)
                
                # 保存最后使用的序列到配置
                self._save_last_used_sequence(file_path)
                
                # 构建显示名称
                display_name = f"{sequence.metadata.product}-{sequence.metadata.station}-{sequence.metadata.version}-{sequence.metadata.created_at[:10].replace('-', '')}"
                
                # 更新状态栏
                self.status_label.setText(f"已加载序列: {display_name}")
                
                # 显示成功消息
                QMessageBox.information(self, "加载成功", f"已成功加载测试序列:\n{display_name}")
                
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法加载测试序列:\n{str(e)}")
    
    def _update_sequence_tree(self, sequence) -> None:
        """更新序列树显示"""
        try:
            print(f"DEBUG: 开始更新序列树，序列名称: {sequence.metadata.name}")
            print(f"DEBUG: 步骤数量: {len(sequence.steps)}")
            
            # 检查seq_model是否已初始化
            if not hasattr(self, 'seq_model') or self.seq_model is None:
                print("DEBUG: seq_model未初始化，跳过序列树更新")
                return
            
            # 使用seq_model来管理序列树
            self.seq_model.clear()
            
            # 构建显示名称：产品-测试站-版本-日期
            display_name = f"{sequence.metadata.product}-{sequence.metadata.station}-{sequence.metadata.version}-{sequence.metadata.created_at[:10].replace('-', '')}"
            print(f"DEBUG: 显示名称: {display_name}")
            
            # 设置根节点
            self.seq_model.set_root(display_name, "就绪")
            
            # 添加步骤
            for i, step in enumerate(sequence.steps):
                print(f"DEBUG: 处理步骤{i+1}: ID='{step.id}', Name='{step.name}'")
                
                # 如果步骤名称为空，使用步骤ID作为显示名称
                if step.name and step.name.strip():
                    display_name = step.name
                    print(f"DEBUG: 使用步骤名称: '{display_name}'")
                else:
                    display_name = step.id
                    print(f"DEBUG: 使用步骤ID: '{display_name}'")
                
                # 使用seq_model添加步骤
                step_item = self.seq_model.add_step(step.id, display_name, step)
                print(f"DEBUG: 添加步骤完成: {step_item.text(0)} - {step_item.text(1)}")
                
                # 检查断点状态
                if step.id in self._breakpoints:
                    step_item.setBackground(0, QColor(255, 200, 200))  # 浅红色背景
                    step_item.setText(1, "有断点")
                elif step.id == self._current_breakpoint:
                    step_item.setBackground(0, QColor(255, 255, 0))  # 黄色背景
                    step_item.setText(1, "断点暂停")
            
            # 展开根节点
            self.seq_model._root_item.setExpanded(True)
            
            print("DEBUG: 序列树更新完成")
            
        except Exception as e:
            print(f"更新序列树时出错: {e}")
            import traceback
            traceback.print_exc()
    
    def _load_default_sequence(self) -> None:
        """加载默认序列，优先加载最后使用的序列"""
        try:
            import os
            config = self._config_service.load()
            sequence_file = None
            
            # 优先加载最后使用的序列
            if config.test_sequence and config.test_sequence.last_used:
                sequence_file = config.test_sequence.last_used
                print(f"尝试加载最后使用的序列: {sequence_file}")
                # 检查文件是否存在
                if not os.path.exists(sequence_file):
                    print(f"最后使用的序列文件不存在，使用默认序列: {sequence_file}")
                    sequence_file = None
            elif config.test_sequence and config.test_sequence.file:
                sequence_file = config.test_sequence.file
                print(f"尝试加载默认序列: {sequence_file}")
            
            if sequence_file:
                from ...testcases.utils import load_test_sequence
                sequence = load_test_sequence(sequence_file)
                self._current_sequence = sequence
                self._update_sequence_tree(sequence)
                # 构建显示名称
                display_name = f"{sequence.metadata.product}-{sequence.metadata.station}-{sequence.metadata.version}-{sequence.metadata.created_at[:10].replace('-', '')}"
                print(f"已加载序列: {display_name}")
            else:
                print("未找到可加载的序列文件")
                self._create_empty_sequence_tree()
        except Exception as e:
            print(f"加载序列失败: {e}")
            # 如果加载失败，创建一个空的序列树
            self._create_empty_sequence_tree()
    
    def _save_last_used_sequence(self, sequence_path: str) -> None:
        """保存最后使用的序列到配置"""
        try:
            config = self._config_service.load()
            if config.test_sequence:
                config.test_sequence.last_used = sequence_path
                self._config_service.save(config)
                print(f"已保存最后使用的序列: {sequence_path}")
        except Exception as e:
            print(f"保存最后使用序列失败: {e}")
    
    def _create_empty_sequence_tree(self) -> None:
        """创建空的序列树"""
        self.seq_model.clear()
        self.seq_model.set_root("无序列", "就绪")
    
    def closeEvent(self, event):
        """窗口关闭事件，清理资源"""
        try:
            # 断开日志处理器信号
            if hasattr(self, "_qt_log_handler"):
                self._qt_log_handler.sig_log.disconnect()
            
            # 停止所有worker
            if hasattr(self, "_worker_a") and self._worker_a:
                self._worker_a.stop()
            if hasattr(self, "_worker_b") and self._worker_b:
                self._worker_b.stop()
            
            # 等待线程结束
            if hasattr(self, "_thread_a") and self._thread_a.isRunning():
                self._thread_a.quit()
                self._thread_a.wait(3000)  # 等待3秒
            if hasattr(self, "_thread_b") and self._thread_b.isRunning():
                self._thread_b.quit()
                self._thread_b.wait(3000)  # 等待3秒
                
        except Exception as e:
            print(f"清理资源时出错: {e}")
        finally:
            event.accept()
    
    def _show_sequence_context_menu(self, position):
        """显示序列树右键菜单"""
        item = self.sequence_tree.itemAt(position)
        if not item or not item.parent():  # 确保是步骤项，不是根节点
            return
            
        step_id = item.data(0, 0)
        if not step_id:
            return
            
        menu = QMenu(self)
        
        # 断点操作
        if step_id in self._breakpoints:
            clear_action = menu.addAction("清除断点")
            clear_action.triggered.connect(lambda: self._clear_breakpoint(step_id))
        else:
            set_action = menu.addAction("设置断点")
            set_action.triggered.connect(lambda: self._set_breakpoint(step_id))
            
        # 继续操作 - 根据运行端口显示
        if self._current_breakpoint == step_id:
            if "A" in self._running_ports:
                continue_action = menu.addAction("继续执行在A端口")
                continue_action.triggered.connect(lambda: self._continue_from_breakpoint("A"))
            if "B" in self._running_ports:
                continue_action = menu.addAction("继续执行在B端口")
                continue_action.triggered.connect(lambda: self._continue_from_breakpoint("B"))
                
        # 重新开始操作 - 从断点处重新开始
        if step_id in self._breakpoints:
            if "A" in self._running_ports:
                restart_action = menu.addAction("重新开始在A端口")
                restart_action.triggered.connect(lambda: self._restart_from_breakpoint("A", step_id))
            if "B" in self._running_ports:
                restart_action = menu.addAction("重新开始在B端口")
                restart_action.triggered.connect(lambda: self._restart_from_breakpoint("B", step_id))
                
        # 跳过断点操作 - 跳过当前断点，从下一个步骤开始
        if step_id in self._breakpoints and self._current_breakpoint == step_id:
            if "A" in self._running_ports:
                skip_action = menu.addAction("跳过断点在A端口")
                skip_action.triggered.connect(lambda: self._skip_breakpoint("A", step_id))
            if "B" in self._running_ports:
                skip_action = menu.addAction("跳过断点在B端口")
                skip_action.triggered.connect(lambda: self._skip_breakpoint("B", step_id))
                
        menu.exec_(self.sequence_tree.mapToGlobal(position))
    
    def _set_breakpoint(self, step_id: str):
        """设置断点"""
        self._breakpoints.add(step_id)
        if self._current_sequence:
            self._update_sequence_tree(self._current_sequence)
        print(f"设置断点: {step_id}")
        
    def _clear_breakpoint(self, step_id: str):
        """清除断点"""
        self._breakpoints.discard(step_id)
        if self._current_breakpoint == step_id:
            self._current_breakpoint = None
        if self._current_sequence:
            self._update_sequence_tree(self._current_sequence)
        print(f"清除断点: {step_id}")
        
    def _continue_from_breakpoint(self, port: str):
        """从断点继续执行"""
        if self._current_breakpoint:
            self._current_breakpoint = None
            if self._current_sequence:
                self._update_sequence_tree(self._current_sequence)
            print(f"从断点继续执行在{port}端口")
            # 这里可以添加继续执行的逻辑
    
    def _restart_from_breakpoint(self, port: str, step_id: str):
        """从断点重新开始执行"""
        if not self._current_sequence:
            QMessageBox.warning(self, "警告", "请先加载测试序列")
            return
            
        # 设置当前断点为指定步骤
        self._current_breakpoint = step_id
        if self._current_sequence:
            self._update_sequence_tree(self._current_sequence)
        
        print(f"从断点 {step_id} 重新开始执行在{port}端口")
        
        # 停止当前端口
        if port == "A":
            self._worker_a.stop()
            # 等待停止完成
            if hasattr(self, "_thread_a") and self._thread_a.isRunning():
                self._thread_a.quit()
                self._thread_a.wait()
            # 设置从指定步骤开始执行
            self._worker_a.set_start_from_step(step_id)
        elif port == "B":
            self._worker_b.stop()
            # 等待停止完成
            if hasattr(self, "_thread_b") and self._thread_b.isRunning():
                self._thread_b.quit()
                self._thread_b.wait()
            # 设置从指定步骤开始执行
            self._worker_b.set_start_from_step(step_id)
        
        # 重新启动端口
        self._start_port_with_sequence(port, self._current_sequence)
    
    def _skip_breakpoint(self, port: str, step_id: str):
        """跳过断点，从下一个步骤开始执行"""
        if not self._current_sequence:
            QMessageBox.warning(self, "警告", "请先加载测试序列")
            return
            
        # 找到当前断点在序列中的位置
        current_step_index = -1
        for i, step in enumerate(self._current_sequence.steps):
            if step.id == step_id:
                current_step_index = i
                break
                
        if current_step_index == -1:
            QMessageBox.warning(self, "警告", "未找到当前断点步骤")
            return
            
        # 检查是否有下一个步骤
        if current_step_index >= len(self._current_sequence.steps) - 1:
            QMessageBox.information(self, "提示", "当前断点是最后一个步骤，无法跳过")
            return
            
        # 获取下一个步骤
        next_step = self._current_sequence.steps[current_step_index + 1]
        next_step_id = next_step.id
        
        print(f"跳过断点 {step_id}，从下一个步骤 {next_step_id} 开始执行在{port}端口")
        
        # 清除当前断点状态
        self._current_breakpoint = None
        if self._current_sequence:
            self._update_sequence_tree(self._current_sequence)
        
        # 停止当前端口
        if port == "A":
            self._worker_a.stop()
            # 等待停止完成
            if hasattr(self, "_thread_a") and self._thread_a.isRunning():
                self._thread_a.quit()
                self._thread_a.wait()
            # 设置从下一个步骤开始执行
            self._worker_a.set_start_from_step(next_step_id)
        elif port == "B":
            self._worker_b.stop()
            # 等待停止完成
            if hasattr(self, "_thread_b") and self._thread_b.isRunning():
                self._thread_b.quit()
                self._thread_b.wait()
            # 设置从下一个步骤开始执行
            self._worker_b.set_start_from_step(next_step_id)
        
        # 重新启动端口
        self._start_port_with_sequence(port, self._current_sequence)

    def _retest_port(self, port: str) -> None:
        """复测指定端口：跳过SN扫描，使用上一轮SN重新执行当前序列。"""
        print(f"DEBUG: 复测端口 {port}")
        if not self._current_sequence:
            QMessageBox.warning(self, "警告", "请先加载测试序列")
            return
        
        full_port_name = f"Port{port}" if len(port) == 1 else port
        last_sn = self._sn_by_port.get(full_port_name, "NULL")
        if not last_sn or last_sn == "NULL":
            QMessageBox.information(self, "提示", f"{full_port_name} 当前没有上一轮SN，无法复测")
            return

        # 端口正在运行时不允许复测
        if port == "A":
            if hasattr(self, "_worker_a") and self._worker_a and self._worker_a.is_running():
                QMessageBox.information(self, "提示", "Port A 正在运行，无法复测")
                return
        elif port == "B":
            if hasattr(self, "_worker_b") and self._worker_b and self._worker_b.is_running():
                QMessageBox.information(self, "提示", "Port B 正在运行，无法复测")
                return

        # 复测时，直接从序列起始步骤开始，但在Worker中跳过SN扫描步骤
        self._start_port_with_sequence(port, self._current_sequence, retest=True)
    
    def _add_test_result(self, port: str, step_name: str, result: str, value: str = "", low: str = "", high: str = "", unit: str = "") -> None:
        """添加测试结果到PortPanel的结果表"""
        if port == "A":
            self.port_a.add_test_result(step_name, value, low, high, unit, result)
        elif port == "B":
            self.port_b.add_test_result(step_name, value, low, high, unit, result)

    def _on_alerts_context_menu(self, pos) -> None:
        """日志列表右键菜单：复制选中内容（简化）"""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QGuiApplication

        menu = QMenu(self)
        act_copy_sel = menu.addAction("复制选中内容")
        # 若无选择则默认选中光标所在行
        tc = self.alerts.textCursor()
        if not tc.hasSelection():
            cursor = self.alerts.cursorForPosition(pos)
            tc.setPosition(cursor.block().position())
            tc.movePosition(tc.EndOfBlock, tc.KeepAnchor)
            self.alerts.setTextCursor(tc)
        action = menu.exec_(self.alerts.viewport().mapToGlobal(pos))
        if action != act_copy_sel:
            return
        self._copy_selected_alerts()

    def _copy_selected_alerts(self) -> None:
        """复制 alerts 文本中选中的内容"""
        from PySide6.QtGui import QGuiApplication
        text = self.alerts.textCursor().selectedText()
        if not text:
            return
        text = text.replace("\u2029", "\n").replace("\u2028", "\n")
        QGuiApplication.clipboard().setText(text)
    
    def _on_exit(self) -> None:
        """退出应用程序"""
        reply = QMessageBox.question(
            self, "确认退出",
            "确定要退出TestTool吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.close()
    
    def _on_open_mes_config(self) -> None:
        """打开MES配置对话框"""
        try:
            from .mes_config_dialog import MESConfigDialog
            dialog = MESConfigDialog(self, self._config_service)
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开MES配置对话框: {e}")
    
    def _on_open_ports_config(self) -> None:
        """打开端口配置对话框"""
        try:
            from .config_dialog import ConfigDialog
            dialog = ConfigDialog(self, translator=self._i18n, service=self._config_service)
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开端口配置对话框: {e}")

    def _on_open_version_config(self) -> None:
        """打开版本配置对话框"""
        try:
            from .version_config_dialog import VersionConfigDialog
            dialog = VersionConfigDialog(self, self._config_service)
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开版本配置对话框: {e}")
