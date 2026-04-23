"""
Configuration dialog skeleton for dual-port settings (no backend binding).

Includes tabs for Port A and Port B with Serial and TCP parameter groups.
"""

from __future__ import annotations

from typing import Optional
import logging
import threading
import socket

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QDialogButtonBox,
    QCheckBox,
    QToolBar,
    QPushButton,
    QSizePolicy,
    QScrollArea,
)
from PySide6.QtGui import QAction, QShortcut, QKeySequence


class _SerialGroup(QGroupBox):
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(title, parent)
        form = QFormLayout(self)
        
        # 串口选择 - 下拉框，自动检测系统端口
        self.cbo_port = _NoWheelComboBox(self)
        self.cbo_port.setEditable(True)  # 允许手动输入
        self.cbo_port.setPlaceholderText("选择或输入串口...")
        self._refresh_ports()
        
        # 波特率 - 下拉框 + 手动输入
        self.cbo_baudrate = _NoWheelComboBox(self)
        self.cbo_baudrate.setEditable(True)
        self.cbo_baudrate.addItems(["115200", "9600", "38400", "57600", "19200", "4800", "2400", "1200"])
        self.cbo_baudrate.setCurrentText("115200")
        self.cbo_baudrate.setPlaceholderText("选择或输入波特率...")
        
        # 数据位 - 下拉框
        self.cbo_bytesize = _NoWheelComboBox(self)
        self.cbo_bytesize.addItems(["5", "6", "7", "8"])
        self.cbo_bytesize.setCurrentText("8")
        
        # 校验位 - 下拉框
        self.cbo_parity = _NoWheelComboBox(self)
        self.cbo_parity.addItems(["N", "E", "O"])  # None/Even/Odd
        self.cbo_parity.setCurrentText("N")
        
        # 停止位 - 下拉框
        self.cbo_stopbits = _NoWheelComboBox(self)
        self.cbo_stopbits.addItems(["1", "1.5", "2"])
        self.cbo_stopbits.setCurrentText("1")
        
        # 超时时间 - 手动输入
        self.ed_timeout = QLineEdit(self)
        self.ed_timeout.setPlaceholderText("输入超时时间(ms)...")
        self.ed_timeout.setText("2000")
        
        # 重试次数 - 手动输入
        self.sp_retries = _NoWheelSpinBox(self)
        self.sp_retries.setRange(0, 10)
        self.sp_retries.setValue(3)
        
        # 布局
        form.addRow("串口", self.cbo_port)
        form.addRow("波特率", self.cbo_baudrate)
        form.addRow("数据位", self.cbo_bytesize)
        form.addRow("校验位", self.cbo_parity)
        form.addRow("停止位", self.cbo_stopbits)
        form.addRow("超时", self.ed_timeout)
        form.addRow("重试", self.sp_retries)
    
    def _refresh_ports(self) -> None:
        """刷新可用串口列表"""
        try:
            import serial.tools.list_ports as lp
            ports = lp.comports()
            
            # 获取当前选择的端口
            current_selection = self.cbo_port.currentData()
            
            # 清空并重新填充
            self.cbo_port.clear()
            
            if ports:
                for port in sorted(ports, key=lambda x: x.device):
                    # 显示格式: COM3 - USB Serial Port (COM3)
                    display_text = f"{port.device} - {port.description}" if port.description else port.device
                    self.cbo_port.addItem(display_text, port.device)
                
                # 尝试恢复之前的选择
                if current_selection:
                    self.set_port_name(current_selection)
                elif self.cbo_port.count() > 0:
                    # 如果没有之前的选择，选择第一个可用端口
                    self.cbo_port.setCurrentIndex(0)
            else:
                self.cbo_port.addItem("未检测到串口设备", "")
                
        except ImportError:
            self.cbo_port.clear()
            self.cbo_port.addItem("pyserial未安装，无法检测串口", "")
        except Exception as e:
            self.cbo_port.clear()
            self.cbo_port.addItem(f"检测串口失败: {str(e)}", "")
    
    def get_port_name(self) -> str:
        """获取当前选择的串口名称"""
        current_data = self.cbo_port.currentData()
        if current_data:
            return current_data
        # 如果没有数据，返回当前文本
        return self.cbo_port.currentText()
    
    def set_port_name(self, port_name: str) -> None:
        """设置串口名称"""
        # 先尝试在现有项目中查找
        for i in range(self.cbo_port.count()):
            if self.cbo_port.itemData(i) == port_name:
                self.cbo_port.setCurrentIndex(i)
                return
        # 如果没找到，直接设置文本
        self.cbo_port.setCurrentText(port_name)
    
    def get_baudrate(self) -> int:
        """获取波特率"""
        try:
            return int(self.cbo_baudrate.currentText())
        except ValueError:
            return 115200  # 默认值


class _NoWheelComboBox(QComboBox):
    """禁用滚轮更改选项，避免误触。"""
    def wheelEvent(self, event):  # noqa: N802
        event.ignore()


class _NoWheelSpinBox(QSpinBox):
    """禁用滚轮更改数值，避免误触。"""
    def wheelEvent(self, event):  # noqa: N802
        event.ignore()

class _TcpGroup(QGroupBox):
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(title, parent)
        form = QFormLayout(self)
        
        # 主机地址 - 手动输入
        self.ed_host = QLineEdit(self)
        self.ed_host.setPlaceholderText("输入主机IP地址...")
        self.ed_host.setText("127.0.0.1")
        
        # 端口号 - 手动输入
        self.sp_port = _NoWheelSpinBox(self)
        self.sp_port.setRange(1, 65535)
        self.sp_port.setValue(5020)
        
        # 超时时间 - 手动输入
        self.ed_timeout = QLineEdit(self)
        self.ed_timeout.setPlaceholderText("输入超时时间(ms)...")
        self.ed_timeout.setText("2000")
        
        # 重试次数 - 手动输入
        self.sp_retries = _NoWheelSpinBox(self)
        self.sp_retries.setRange(0, 10)
        self.sp_retries.setValue(3)
        
        form.addRow("主机", self.ed_host)
        form.addRow("端口", self.sp_port)
        form.addRow("超时", self.ed_timeout)
        form.addRow("重试", self.sp_retries)


class _UutGroup(QGroupBox):
    """UUT通讯配置分组"""
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        # 创建带复选框的标题
        self.chk_enabled = QCheckBox("启用UUT通讯", self)
        self.chk_enabled.setChecked(True)
        self.setTitle("")  # 清空默认标题
        
        # 创建标题布局
        title_layout = QHBoxLayout()
        title_layout.addWidget(self.chk_enabled)
        title_layout.addStretch()
        
        # 将标题布局添加到主布局
        layout.addLayout(title_layout)
        
        # 接口选择
        iface_row = QHBoxLayout()
        self.cbo_interface = QComboBox(self)
        self.cbo_interface.addItems(["serial", "tcp"])
        self.cbo_interface.setCurrentText("serial")
        self.cbo_interface.currentTextChanged.connect(self._on_interface_changed)
        iface_row.addWidget(QLabel("接口类型:"))
        iface_row.addWidget(self.cbo_interface)
        iface_row.addStretch()
        layout.addLayout(iface_row)
        
        # Serial配置
        self.grp_serial = _SerialGroup("串口通讯", self)
        
        # TCP配置
        self.grp_tcp = _TcpGroup("TCP通讯", self)
        layout.addWidget(self.grp_serial)
        layout.addWidget(self.grp_tcp)

        # 初始化显示
        self._on_interface_changed("serial")

    def _on_interface_changed(self, value: str) -> None:
        is_serial = (value == "serial")
        self.grp_serial.setVisible(is_serial)
        self.grp_tcp.setVisible(not is_serial)



class _FixtureGroup(QGroupBox):
    """治具/夹具通讯配置分组"""
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        # 创建带复选框的标题
        self.chk_enabled = QCheckBox("启用治具通讯", self)
        self.chk_enabled.setChecked(False)
        self.chk_enabled.toggled.connect(self._on_enabled_toggled)
        self.setTitle("")  # 清空默认标题
        
        # 创建标题布局
        title_layout = QHBoxLayout()
        title_layout.addWidget(self.chk_enabled)
        title_layout.addStretch()
        
        # 将标题布局添加到主布局
        layout.addLayout(title_layout)
        
        # 配置表单
        form = QFormLayout()
        
        # 串口选择
        self.cbo_port = QComboBox(self)
        self.cbo_port.setEditable(True)
        self.cbo_port.setPlaceholderText("选择或输入串口...")
        self._refresh_ports()
        
        # 波特率
        self.cbo_baudrate = _NoWheelComboBox(self)
        self.cbo_baudrate.setEditable(True)
        self.cbo_baudrate.addItems(["115200", "9600", "38400", "57600", "19200", "4800", "2400", "1200"])
        self.cbo_baudrate.setCurrentText("115200")
        self.cbo_baudrate.setPlaceholderText("选择或输入波特率...")
        
        # 超时时间
        self.ed_timeout = QLineEdit(self)
        self.ed_timeout.setPlaceholderText("输入超时时间(ms)...")
        self.ed_timeout.setText("2000")
        
        # 重试次数
        self.sp_retries = _NoWheelSpinBox(self)
        self.sp_retries.setRange(0, 10)
        self.sp_retries.setValue(3)
        
        form.addRow("串口", self.cbo_port)
        form.addRow("波特率", self.cbo_baudrate)
        form.addRow("超时", self.ed_timeout)
        form.addRow("重试", self.sp_retries)
        
        layout.addLayout(form)

    def _on_enabled_toggled(self, enabled: bool) -> None:
        if enabled:
            self._auto_configure_if_supported(force=False)

    def _detect_preferred_fixture_port(self) -> Optional[str]:
        try:
            import serial.tools.list_ports as lp
            ports = lp.comports()
        except Exception:
            return None
        preferred = []
        for port in ports:
            desc = (getattr(port, "description", "") or "").lower()
            hwid = (getattr(port, "hwid", "") or "").lower()
            manu = (getattr(port, "manufacturer", "") or "").lower()
            text = f"{desc} {hwid} {manu}"
            if any(k in text for k in ("ch340", "ch343")):
                preferred.append(port.device)
        return sorted(preferred)[0] if preferred else None

    def _auto_configure_if_supported(self, force: bool = False) -> None:
        detected = self._detect_preferred_fixture_port()
        if not detected:
            return
        current = (self.get_port_name() or "").strip()
        if not force and current and current != detected:
            return
        self.set_port_name(detected)
        self.cbo_baudrate.setCurrentText("115200")
        self.ed_timeout.setText("2000")
        self.sp_retries.setValue(3)

    def auto_enable_if_supported(self) -> None:
        detected = self._detect_preferred_fixture_port()
        if not detected:
            return
        if not self.chk_enabled.isChecked():
            self.chk_enabled.setChecked(True)
            return
        self._auto_configure_if_supported(force=False)
    
    def _refresh_ports(self) -> None:
        """刷新可用串口列表"""
        try:
            import serial.tools.list_ports as lp
            ports = lp.comports()
            
            current_selection = self.cbo_port.currentData()
            self.cbo_port.clear()
            
            if ports:
                for port in sorted(ports, key=lambda x: x.device):
                    display_text = f"{port.device} - {port.description}" if port.description else port.device
                    self.cbo_port.addItem(display_text, port.device)
                
                if current_selection:
                    self.set_port_name(current_selection)
                elif self.cbo_port.count() > 0:
                    self.cbo_port.setCurrentIndex(0)
            else:
                self.cbo_port.addItem("未检测到串口设备", "")
                
        except ImportError:
            self.cbo_port.clear()
            self.cbo_port.addItem("pyserial未安装，无法检测串口", "")
        except Exception as e:
            self.cbo_port.clear()
            self.cbo_port.addItem(f"检测串口失败: {str(e)}", "")
    
    def get_port_name(self) -> str:
        """获取当前选择的串口名称"""
        current_data = self.cbo_port.currentData()
        if current_data:
            return current_data
        return self.cbo_port.currentText()
    
    def set_port_name(self, port_name: str) -> None:
        """设置串口名称"""
        for i in range(self.cbo_port.count()):
            if self.cbo_port.itemData(i) == port_name:
                self.cbo_port.setCurrentIndex(i)
                return
        self.cbo_port.setCurrentText(port_name)


class _InstrumentGroup(QGroupBox):
    """测试仪表配置分组"""
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        # 创建带复选框的标题
        self.chk_enabled = QCheckBox("启用测试仪表", self)
        self.chk_enabled.setChecked(False)
        self.setTitle("")  # 清空默认标题
        
        # 创建标题布局
        title_layout = QHBoxLayout()
        title_layout.addWidget(self.chk_enabled)
        title_layout.addStretch()
        
        # 将标题布局添加到主布局
        layout.addLayout(title_layout)
        
        # 配置表单
        form = QFormLayout()
        
        # 仪表类型
        self.cbo_type = _NoWheelComboBox(self)
        self.cbo_type.addItems(["DMM", "PSU", "ELOAD", "Scope", "Other"])
        self.cbo_type.setCurrentText("DMM")
        
        # 接口类型
        self.cbo_interface = _NoWheelComboBox(self)
        self.cbo_interface.addItems(["VISA", "TCP"])
        self.cbo_interface.setCurrentText("VISA")
        self.cbo_interface.currentTextChanged.connect(self._on_interface_changed)
        
        # VISA资源（当接口为VISA时显示）
        self.ed_visa_resource = QLineEdit(self)
        self.ed_visa_resource.setPlaceholderText("TCPIP0::192.168.1.60::INSTR")
        self.ed_visa_resource.setText("TCPIP0::192.168.1.60::INSTR")
        
        # TCP主机（当接口为TCP时显示）
        self.ed_tcp_host = QLineEdit(self)
        self.ed_tcp_host.setPlaceholderText("192.168.1.61")
        self.ed_tcp_host.setText("192.168.1.61")
        
        # TCP端口（当接口为TCP时显示）
        self.sp_tcp_port = _NoWheelSpinBox(self)
        self.sp_tcp_port.setRange(1, 65535)
        self.sp_tcp_port.setValue(5025)
        
        # 超时时间
        self.ed_timeout = QLineEdit(self)
        self.ed_timeout.setPlaceholderText("输入超时时间(ms)...")
        self.ed_timeout.setText("3000")
        
        form.addRow("仪表类型", self.cbo_type)
        form.addRow("接口类型", self.cbo_interface)
        form.addRow("VISA资源", self.ed_visa_resource)
        form.addRow("TCP主机", self.ed_tcp_host)
        form.addRow("TCP端口", self.sp_tcp_port)
        form.addRow("超时", self.ed_timeout)
        
        layout.addLayout(form)
        
        # 初始状态设置
        self._on_interface_changed("VISA")
    
    def _on_interface_changed(self, interface: str) -> None:
        """接口类型改变时的处理"""
        is_visa = interface == "VISA"
        self.ed_visa_resource.setVisible(is_visa)
        self.ed_tcp_host.setVisible(not is_visa)
        self.sp_tcp_port.setVisible(not is_visa)
        
        # 更新标签
        form = self.layout()
        if isinstance(form, QFormLayout):
            for i in range(form.rowCount()):
                item = form.itemAt(i, QFormLayout.LabelRole)
                if item and item.widget():
                    label = item.widget()
                    if label.text() == "VISA资源":
                        label.setVisible(is_visa)
                    elif label.text() == "TCP主机":
                        label.setVisible(not is_visa)
                    elif label.text() == "TCP端口":
                        label.setVisible(not is_visa)


class _PortPage(QWidget):
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        
        # 创建滚动区域
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # 创建内容容器
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # UUT通讯配置
        self.grp_uut = _UutGroup("UUT通讯", content_widget)
        
        # 治具/夹具通讯配置
        self.grp_fixture = _FixtureGroup("治具/夹具通讯", content_widget)
        
        # 测试仪表配置
        self.grp_instrument = _InstrumentGroup("测试仪表", content_widget)
        
        layout.addWidget(self.grp_uut)
        layout.addWidget(self.grp_fixture)
        layout.addWidget(self.grp_instrument)
        layout.addStretch(1)
        
        # 设置滚动区域的内容
        scroll_area.setWidget(content_widget)
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll_area)


class ConfigDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, *, translator=None, service=None) -> None:
        super().__init__(parent)
        self._i18n = translator
        self._service = service
        self.setWindowTitle(self._t("config.title"))
        self.resize(800, 600)  # 增加初始高度以更好地显示内容
        # 允许用户拖拽缩放窗口
        self.setSizeGripEnabled(True)
        # 设置最小尺寸
        self.setMinimumSize(600, 400)
        # UI缩放因子与基础字号
        self._ui_scale = 1.0
        self._base_point_size = self.font().pointSizeF()
        
        # 自动刷新定时器
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh_ports)
        self._refresh_timer.start(2000)  # 每2秒自动刷新一次
        layout = QVBoxLayout(self)
        # toolbar
        self.toolbar = QToolBar(self)
        self.act_import = QAction(self._t("config.btn.import"), self)
        self.act_reset = QAction(self._t("config.btn.reset"), self)
        self.act_validate = QAction(self._t("config.btn.validate"), self)
        self.toolbar.addAction(self.act_import)
        self.toolbar.addAction(self.act_reset)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.act_validate)
        
        # 设置工具栏按钮字体大小（加大20%）
        toolbar_font = self.toolbar.font()
        toolbar_font.setPointSize(int(toolbar_font.pointSize() * 1.2))
        self.toolbar.setFont(toolbar_font)
        
        layout.addWidget(self.toolbar)
        self.tabs = QTabWidget(self)
        # 让内容随窗口扩展
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.page_a = _PortPage(self._t("config.portA"), self)
        self.page_b = _PortPage(self._t("config.portB"), self)
        self.tabs.addTab(self.page_a, self._t("config.portA"))
        self.tabs.addTab(self.page_b, self._t("config.portB"))
        layout.addWidget(self.tabs)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self._on_ok)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        # wire actions
        self.act_import.triggered.connect(self._on_import)
        self.act_reset.triggered.connect(self._on_reset)
        self.act_validate.triggered.connect(self._on_validate)
        # initial load if service provided
        if self._service is not None:
            self._load_to_ui()
        self.page_a.grp_fixture.auto_enable_if_supported()
        self.page_b.grp_fixture.auto_enable_if_supported()

        # 缩放快捷键：Ctrl +/−/0
        self._sc_zoom_in = QShortcut(QKeySequence("Ctrl++"), self)
        self._sc_zoom_out = QShortcut(QKeySequence("Ctrl+-"), self)
        self._sc_zoom_reset = QShortcut(QKeySequence("Ctrl+0"), self)
        self._sc_zoom_in.activated.connect(self._on_zoom_in)
        self._sc_zoom_out.activated.connect(self._on_zoom_out)
        self._sc_zoom_reset.activated.connect(self._on_zoom_reset)
    
    def _auto_refresh_ports(self) -> None:
        """自动刷新端口列表"""
        try:
            # 保存当前选择的端口
            current_port_a_uut = self.page_a.grp_uut.grp_serial.get_port_name()
            current_port_a_fixture = self.page_a.grp_fixture.get_port_name()
            current_port_b_uut = self.page_b.grp_uut.grp_serial.get_port_name()
            current_port_b_fixture = self.page_b.grp_fixture.get_port_name()
            
            # 刷新端口列表
            self.page_a.grp_uut.grp_serial._refresh_ports()
            self.page_a.grp_fixture._refresh_ports()
            self.page_b.grp_uut.grp_serial._refresh_ports()
            self.page_b.grp_fixture._refresh_ports()
            
            # 尝试恢复之前选择的端口
            if current_port_a_uut:
                self.page_a.grp_uut.grp_serial.set_port_name(current_port_a_uut)
            if current_port_a_fixture:
                self.page_a.grp_fixture.set_port_name(current_port_a_fixture)
            if current_port_b_uut:
                self.page_b.grp_uut.grp_serial.set_port_name(current_port_b_uut)
            if current_port_b_fixture:
                self.page_b.grp_fixture.set_port_name(current_port_b_fixture)
            if self.page_a.grp_fixture.chk_enabled.isChecked():
                self.page_a.grp_fixture._auto_configure_if_supported(force=not bool(current_port_a_fixture))
            if self.page_b.grp_fixture.chk_enabled.isChecked():
                self.page_b.grp_fixture._auto_configure_if_supported(force=not bool(current_port_b_fixture))
                
        except Exception as e:
            # 静默处理错误，避免影响用户体验
            pass
    
    def closeEvent(self, event) -> None:
        """对话框关闭时停止定时器"""
        if hasattr(self, '_refresh_timer'):
            self._refresh_timer.stop()
        super().closeEvent(event)
    
    def _get_timeout_value(self, timeout_text: str) -> int:
        """获取并验证超时值"""
        try:
            timeout = int(timeout_text.strip())
            # 验证范围：10ms - 600000ms (10分钟)
            if 10 <= timeout <= 600000:
                return timeout
            else:
                # 超出范围时返回默认值
                return 2000
        except (ValueError, AttributeError):
            # 解析失败时返回默认值
            return 2000

    def _t(self, key: str) -> str:
        if self._i18n is None:
            return key
        return self._i18n.t(key)

    # ---- UI scaling ------------------------------------------------------
    def _apply_ui_scale(self) -> None:
        """按当前缩放因子调整本对话框及子控件的字体大小。"""
        try:
            target_size = max(7.0, self._base_point_size * self._ui_scale)
            def _apply(widget: QWidget) -> None:
                f = widget.font()
                f.setPointSizeF(target_size)
                widget.setFont(f)
                for child in widget.findChildren(QWidget):
                    cf = child.font()
                    cf.setPointSizeF(target_size)
                    child.setFont(cf)
            _apply(self)
        except Exception:
            pass

    def _on_zoom_in(self) -> None:
        self._ui_scale = min(2.0, self._ui_scale + 0.1)
        self._apply_ui_scale()

    def _on_zoom_out(self) -> None:
        self._ui_scale = max(0.6, self._ui_scale - 0.1)
        self._apply_ui_scale()

    def _on_zoom_reset(self) -> None:
        self._ui_scale = 1.0
        self._apply_ui_scale()

    def retranslate(self) -> None:
        self.setWindowTitle(self._t("config.title"))
        self.act_import.setText(self._t("config.btn.import"))
        self.act_reset.setText(self._t("config.btn.reset"))
        self.act_validate.setText(self._t("config.btn.validate"))
        self.tabs.setTabText(0, self._t("config.portA"))
        self.tabs.setTabText(1, self._t("config.portB"))

    # ---- service wiring --------------------------------------------------
    def _load_to_ui(self) -> None:
        try:
            cfg = self._service.load()
        except Exception as e:  # noqa: BLE001
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Load Config", str(e))
            return
        
        # 加载PortA配置
        self._load_port_config(self.page_a, cfg.ports.portA)
        
        # 加载PortB配置
        self._load_port_config(self.page_b, cfg.ports.portB)
    
    def _load_port_config(self, page, port_cfg) -> None:
        """加载单个端口的配置"""
        # UUT配置
        if hasattr(port_cfg, 'uut') and port_cfg.uut:
            # 启用状态
            page.grp_uut.chk_enabled.setChecked(getattr(port_cfg.uut, 'enabled', True))
            # 接口选择
            if hasattr(port_cfg.uut, 'interface'):
                page.grp_uut.cbo_interface.setCurrentText(port_cfg.uut.interface)
            
            # 串口配置
            page.grp_uut.grp_serial.set_port_name(port_cfg.uut.serial.port)
            page.grp_uut.grp_serial.cbo_baudrate.setCurrentText(str(port_cfg.uut.serial.baudrate))
            page.grp_uut.grp_serial.cbo_bytesize.setCurrentText(str(port_cfg.uut.serial.bytesize))
            page.grp_uut.grp_serial.cbo_parity.setCurrentText(port_cfg.uut.serial.parity)
            page.grp_uut.grp_serial.cbo_stopbits.setCurrentText(str(port_cfg.uut.serial.stopbits))
            page.grp_uut.grp_serial.ed_timeout.setText(str(port_cfg.uut.serial.timeout_ms))
            page.grp_uut.grp_serial.sp_retries.setValue(port_cfg.uut.serial.retries)
            
            # TCP配置
            page.grp_uut.grp_tcp.ed_host.setText(port_cfg.uut.tcp.host)
            page.grp_uut.grp_tcp.sp_port.setValue(port_cfg.uut.tcp.port)
            page.grp_uut.grp_tcp.ed_timeout.setText(str(port_cfg.uut.tcp.timeout_ms))
            page.grp_uut.grp_tcp.sp_retries.setValue(port_cfg.uut.tcp.retries)
        else:
            # 向后兼容：从旧的serial/tcp配置迁移
            page.grp_uut.chk_enabled.setChecked(port_cfg.enabled if hasattr(port_cfg, 'enabled') else True)
            page.grp_uut.cbo_interface.setCurrentText('serial')
            
            if hasattr(port_cfg, 'serial') and port_cfg.serial:
                page.grp_uut.grp_serial.set_port_name(port_cfg.serial.port)
                page.grp_uut.grp_serial.cbo_baudrate.setCurrentText(str(port_cfg.serial.baudrate))
                page.grp_uut.grp_serial.cbo_bytesize.setCurrentText(str(port_cfg.serial.bytesize))
                page.grp_uut.grp_serial.cbo_parity.setCurrentText(port_cfg.serial.parity)
                page.grp_uut.grp_serial.cbo_stopbits.setCurrentText(str(port_cfg.serial.stopbits))
                page.grp_uut.grp_serial.ed_timeout.setText(str(port_cfg.serial.timeout_ms))
                page.grp_uut.grp_serial.sp_retries.setValue(port_cfg.serial.retries)
            
            if hasattr(port_cfg, 'tcp') and port_cfg.tcp:
                page.grp_uut.grp_tcp.ed_host.setText(port_cfg.tcp.host)
                page.grp_uut.grp_tcp.sp_port.setValue(port_cfg.tcp.port)
                page.grp_uut.grp_tcp.ed_timeout.setText(str(port_cfg.tcp.timeout_ms))
                page.grp_uut.grp_tcp.sp_retries.setValue(port_cfg.tcp.retries)
        
        # 治具配置
        if hasattr(port_cfg, 'fixture') and port_cfg.fixture:
            page.grp_fixture.chk_enabled.setChecked(getattr(port_cfg.fixture, 'enabled', True))
            page.grp_fixture.set_port_name(port_cfg.fixture.serial.port)
            page.grp_fixture.cbo_baudrate.setCurrentText(str(port_cfg.fixture.serial.baudrate))
            page.grp_fixture.ed_timeout.setText(str(port_cfg.fixture.serial.timeout_ms))
            page.grp_fixture.sp_retries.setValue(port_cfg.fixture.serial.retries)
        else:
            page.grp_fixture.chk_enabled.setChecked(False)
        
        # 仪表配置
        if hasattr(port_cfg, 'instruments') and port_cfg.instruments:
            # 加载第一个仪表配置（目前只支持单个仪表）
            for inst_id, inst_cfg in port_cfg.instruments.items():
                page.grp_instrument.chk_enabled.setChecked(getattr(inst_cfg, 'enabled', True))
                page.grp_instrument.cbo_type.setCurrentText(inst_cfg.type)
                page.grp_instrument.cbo_interface.setCurrentText(inst_cfg.interface)
                page.grp_instrument.ed_visa_resource.setText(inst_cfg.resource)
                page.grp_instrument.ed_tcp_host.setText(inst_cfg.host)
                page.grp_instrument.sp_tcp_port.setValue(inst_cfg.port)
                page.grp_instrument.ed_timeout.setText(str(inst_cfg.timeout_ms))
                # 无作用域字段（恒定为端口作用域）
                break
        else:
            page.grp_instrument.chk_enabled.setChecked(False)

    def _collect_from_ui(self):
        cfg = self._service.config if getattr(self._service, "_config", None) else self._service.load()
        
        # 收集PortA配置
        self._collect_port_config(self.page_a, cfg.ports.portA)
        
        # 收集PortB配置
        self._collect_port_config(self.page_b, cfg.ports.portB)
        
        self._service._config = cfg

    def _collect_port_config(self, page, port_cfg) -> None:
        """收集单个端口的配置"""
        # UUT配置
        if hasattr(port_cfg, 'uut') and port_cfg.uut:
            port_cfg.uut.enabled = page.grp_uut.chk_enabled.isChecked()
            port_cfg.uut.interface = page.grp_uut.cbo_interface.currentText()
            port_cfg.uut.serial.port = page.grp_uut.grp_serial.get_port_name()
            port_cfg.uut.serial.baudrate = page.grp_uut.grp_serial.get_baudrate()
            port_cfg.uut.serial.bytesize = int(page.grp_uut.grp_serial.cbo_bytesize.currentText())
            port_cfg.uut.serial.parity = page.grp_uut.grp_serial.cbo_parity.currentText()
            port_cfg.uut.serial.stopbits = float(page.grp_uut.grp_serial.cbo_stopbits.currentText())
            port_cfg.uut.serial.timeout_ms = self._get_timeout_value(page.grp_uut.grp_serial.ed_timeout.text())
            port_cfg.uut.serial.retries = page.grp_uut.grp_serial.sp_retries.value()
            port_cfg.uut.tcp.host = page.grp_uut.grp_tcp.ed_host.text()
            port_cfg.uut.tcp.port = page.grp_uut.grp_tcp.sp_port.value()
            port_cfg.uut.tcp.timeout_ms = self._get_timeout_value(page.grp_uut.grp_tcp.ed_timeout.text())
            port_cfg.uut.tcp.retries = page.grp_uut.grp_tcp.sp_retries.value()
        else:
            # 向后兼容：更新旧的serial/tcp配置
            port_cfg.enabled = page.grp_uut.chk_enabled.isChecked()
            if hasattr(port_cfg, 'serial') and port_cfg.serial:
                port_cfg.serial.port = page.grp_uut.grp_serial.get_port_name()
                port_cfg.serial.baudrate = page.grp_uut.grp_serial.get_baudrate()
                port_cfg.serial.bytesize = int(page.grp_uut.grp_serial.cbo_bytesize.currentText())
                port_cfg.serial.parity = page.grp_uut.grp_serial.cbo_parity.currentText()
                port_cfg.serial.stopbits = float(page.grp_uut.grp_serial.cbo_stopbits.currentText())
                port_cfg.serial.timeout_ms = self._get_timeout_value(page.grp_uut.grp_serial.ed_timeout.text())
                port_cfg.serial.retries = page.grp_uut.grp_serial.sp_retries.value()
            
            if hasattr(port_cfg, 'tcp') and port_cfg.tcp:
                port_cfg.tcp.host = page.grp_uut.grp_tcp.ed_host.text()
                port_cfg.tcp.port = page.grp_uut.grp_tcp.sp_port.value()
                port_cfg.tcp.timeout_ms = self._get_timeout_value(page.grp_uut.grp_tcp.ed_timeout.text())
                port_cfg.tcp.retries = page.grp_uut.grp_tcp.sp_retries.value()
        
        # 治具配置
        if hasattr(port_cfg, 'fixture') and port_cfg.fixture:
            port_cfg.fixture.enabled = page.grp_fixture.chk_enabled.isChecked()
            port_cfg.fixture.serial.port = page.grp_fixture.get_port_name()
            port_cfg.fixture.serial.baudrate = int(page.grp_fixture.cbo_baudrate.currentText())
            port_cfg.fixture.serial.timeout_ms = self._get_timeout_value(page.grp_fixture.ed_timeout.text())
            port_cfg.fixture.serial.retries = page.grp_fixture.sp_retries.value()
        
        # 仪表配置
        if hasattr(port_cfg, 'instruments') and port_cfg.instruments:
            # 更新第一个仪表配置（目前只支持单个仪表）
            for inst_id, inst_cfg in port_cfg.instruments.items():
                inst_cfg.enabled = page.grp_instrument.chk_enabled.isChecked()
                inst_cfg.type = page.grp_instrument.cbo_type.currentText()
                inst_cfg.interface = page.grp_instrument.cbo_interface.currentText()
                inst_cfg.resource = page.grp_instrument.ed_visa_resource.text()
                inst_cfg.host = page.grp_instrument.ed_tcp_host.text()
                inst_cfg.port = page.grp_instrument.sp_tcp_port.value()
                inst_cfg.timeout_ms = self._get_timeout_value(page.grp_instrument.ed_timeout.text())
                # 无作用域字段（恒定为端口作用域）
                break

    def _on_ok(self) -> None:
        """确定按钮点击 - 保存配置并关闭对话框"""
        if self._service is None:
            self.accept()
            return
        from PySide6.QtWidgets import QMessageBox
        try:
            self._collect_from_ui()
            self._service.save()
            QMessageBox.information(self, "保存成功", "端口配置已保存")
            self.accept()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", f"保存配置时出错: {e}")

    def _on_reset(self) -> None:
        """重置所有配置框为默认值"""
        from PySide6.QtWidgets import QMessageBox
        
        # 显示确认对话框
        reply = QMessageBox.question(
            self, "确认重置",
            "确定要重置所有配置为默认值吗？\n当前的所有修改将被清空。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # 重置Port A
        self.page_a.chk_enabled.setChecked(True)
        self.page_a.grp_serial.set_port_name("COM3")
        self.page_a.grp_serial.cbo_baudrate.setCurrentText("115200")
        self.page_a.grp_serial.cbo_bytesize.setCurrentText("8")
        self.page_a.grp_serial.cbo_parity.setCurrentText("N")
        self.page_a.grp_serial.cbo_stopbits.setCurrentText("1")
        self.page_a.grp_serial.ed_timeout.setText("2000")
        self.page_a.grp_serial.sp_retries.setValue(3)
        self.page_a.grp_tcp.ed_host.setText("127.0.0.1")
        self.page_a.grp_tcp.sp_port.setValue(5020)
        self.page_a.grp_tcp.ed_timeout.setText("2000")
        self.page_a.grp_tcp.sp_retries.setValue(3)
        
        # 重置Port B
        self.page_b.chk_enabled.setChecked(True)
        self.page_b.grp_serial.set_port_name("COM3")
        self.page_b.grp_serial.cbo_baudrate.setCurrentText("115200")
        self.page_b.grp_serial.cbo_bytesize.setCurrentText("8")
        self.page_b.grp_serial.cbo_parity.setCurrentText("N")
        self.page_b.grp_serial.cbo_stopbits.setCurrentText("1")
        self.page_b.grp_serial.ed_timeout.setText("2000")
        self.page_b.grp_serial.sp_retries.setValue(3)
        self.page_b.grp_tcp.ed_host.setText("127.0.0.1")
        self.page_b.grp_tcp.sp_port.setValue(5020)
        self.page_b.grp_tcp.ed_timeout.setText("2000")
        self.page_b.grp_tcp.sp_retries.setValue(3)
        
        # 显示成功消息
        QMessageBox.information(self, "重置完成", "所有配置已重置为默认值")

    def _on_import(self) -> None:
        if self._service is None:
            return
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(self, self._t("config.btn.import"), "", "YAML (*.yaml *.yml)")
        if not path:
            return
        import yaml
        from pydantic import ValidationError
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            from .. import i18n as _i
            # validate using models
            from ...config.models import RootConfig
            RootConfig.parse_obj(data)
            # apply
            self._service._config = RootConfig.parse_obj(data)
            self._load_to_ui()
            QMessageBox.information(self, self._t("config.btn.import"), "OK")
        except ValidationError as e:
            QMessageBox.critical(self, self._t("config.btn.import"), str(e))
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, self._t("config.btn.import"), str(e))

    def _on_validate(self) -> None:
        """验证配置的有效性和连通性"""
        if self._service is None:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "验证失败", "配置服务不可用")
            return
            
        from PySide6.QtWidgets import QMessageBox, QProgressDialog
        from PySide6.QtCore import QThread, pyqtSignal, QObject
        import time
        
        # 创建进度对话框
        progress = QProgressDialog("正在验证配置...", "取消", 0, 100, self)
        progress.setWindowModality(2)  # Qt.WindowModal
        progress.setMinimumDuration(0)
        progress.show()
        
        class ValidationWorker(QObject):
            finished = pyqtSignal(bool, str)
            progress = pyqtSignal(int)
            
            def __init__(self, config_dialog):
                super().__init__()
                self.dialog = config_dialog
                
            def run_validation(self):
                """在后台线程中运行验证"""
                try:
                    self.progress.emit(10)
                    
                    # 1. 收集UI配置
                    self.dialog._collect_from_ui()
                    self.progress.emit(20)
                    
                    # 2. 配置模式验证
                    ok, messages = self._validate_schema()
                    self.progress.emit(40)
                    
                    # 3. 串口验证
                    serial_ok, serial_msgs = self._validate_serial()
                    ok = ok and serial_ok
                    messages.extend(serial_msgs)
                    self.progress.emit(60)
                    
                    # 4. TCP验证
                    tcp_ok, tcp_msgs = self._validate_tcp()
                    ok = ok and tcp_ok
                    messages.extend(tcp_msgs)
                    self.progress.emit(80)
                    
                    # 5. MES验证
                    mes_ok, mes_msgs = self._validate_mes()
                    ok = ok and mes_ok
                    messages.extend(mes_msgs)
                    self.progress.emit(100)
                    
                    # 返回结果
                    result_text = "\n".join(messages)
                    self.finished.emit(ok, result_text)
                    
                except Exception as e:
                    self.finished.emit(False, f"验证过程中发生错误: {str(e)}")
            
            def _validate_schema(self):
                """验证配置模式"""
                try:
                    from ...config.models import RootConfig
                    RootConfig.parse_obj(self.dialog._service.config.dict())
                    return True, ["✓ 配置模式验证: 通过"]
                except Exception as e:
                    return False, [f"✗ 配置模式验证: 失败 - {str(e)}"]
            
            def _validate_serial(self):
                """验证串口配置"""
                messages = []
                ok = True
                
                try:
                    cfg = self.dialog._service.config
                    for name, port_cfg in ("Port A", cfg.ports.portA), ("Port B", cfg.ports.portB):
                        if not port_cfg.enabled:
                            messages.append(f"• {name}: 已禁用，跳过验证")
                            continue
                            
                        port_name = port_cfg.serial.port
                        if not port_name:
                            messages.append(f"• {name}: 串口未配置")
                            ok = False
                            continue
                            
                        try:
                            import serial.tools.list_ports as lp
                            available_ports = {p.device for p in lp.comports()}
                            if port_name in available_ports:
                                messages.append(f"• {name}: 串口 {port_name} 可用")
                            else:
                                messages.append(f"• {name}: 串口 {port_name} 不可用")
                                messages.append(f"  可用串口: {', '.join(sorted(available_ports))}")
                                ok = False
                        except ImportError:
                            messages.append(f"• {name}: 无法检查串口 (pyserial未安装)")
                        except Exception as e:
                            messages.append(f"• {name}: 串口检查失败 - {str(e)}")
                            ok = False
                            
                except Exception as e:
                    messages.append(f"✗ 串口验证错误: {str(e)}")
                    ok = False
                    
                return ok, messages
            
            def _validate_tcp(self):
                """验证TCP连接"""
                messages = []
                ok = True
                
                try:
                    cfg = self.dialog._service.config
                    for name, tcp_cfg in ("Port A", cfg.ports.portA.tcp), ("Port B", cfg.ports.portB.tcp):
                        host = tcp_cfg.host
                        port = tcp_cfg.port
                        timeout = max(0.01, tcp_cfg.timeout_ms / 1000)
                        
                        if not host:
                            messages.append(f"• {name}: TCP主机未配置")
                            ok = False
                            continue
                            
                        try:
                            with socket.create_connection((host, port), timeout=timeout):
                                messages.append(f"• {name}: TCP {host}:{port} 连接成功")
                        except socket.timeout:
                            messages.append(f"• {name}: TCP {host}:{port} 连接超时")
                            ok = False
                        except ConnectionRefusedError:
                            messages.append(f"• {name}: TCP {host}:{port} 连接被拒绝")
                            ok = False
                        except Exception as e:
                            messages.append(f"• {name}: TCP {host}:{port} 连接失败 - {str(e)}")
                            ok = False
                            
                except Exception as e:
                    messages.append(f"✗ TCP验证错误: {str(e)}")
                    ok = False
                    
                return ok, messages
            
            def _validate_mes(self):
                """验证MES连接"""
                messages = []
                ok = True
                
                try:
                    mes_config = self.dialog._service.config.mes
                    if not mes_config.enabled:
                        messages.append("• MES: 已禁用，跳过验证")
                        return True, messages
                        
                    if not mes_config.base_url:
                        messages.append("• MES: 基础URL未配置")
                        return False, messages
                        
                    try:
                        import requests
                        timeout = max(0.01, mes_config.timeout_ms / 1000)
                        response = requests.get(mes_config.base_url, timeout=timeout, verify=True)
                        messages.append(f"• MES: {mes_config.base_url} 响应正常 (状态码: {response.status_code})")
                    except requests.exceptions.Timeout:
                        messages.append(f"• MES: {mes_config.base_url} 连接超时")
                        ok = False
                    except requests.exceptions.ConnectionError:
                        messages.append(f"• MES: {mes_config.base_url} 连接失败")
                        ok = False
                    except Exception as e:
                        messages.append(f"• MES: {mes_config.base_url} 验证失败 - {str(e)}")
                        ok = False
                        
                except Exception as e:
                    messages.append(f"✗ MES验证错误: {str(e)}")
                    ok = False
                    
                return ok, messages
        
        # 创建并启动验证线程
        self.worker = ValidationWorker(self)
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        
        self.worker_thread.started.connect(self.worker.run_validation)
        self.worker.finished.connect(self._show_validation_result)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(progress.close)
        self.worker.progress.connect(progress.setValue)
        
        self.worker_thread.start()
    
    def _show_validation_result(self, success: bool, details: str) -> None:
        """显示验证结果"""
        from PySide6.QtWidgets import QMessageBox
        
        title = "验证成功" if success else "验证失败"
        icon = QMessageBox.Information if success else QMessageBox.Warning
        
        msg_box = QMessageBox(icon, title, details, QMessageBox.Ok, self)
        msg_box.setDetailedText(details)
        msg_box.exec()


