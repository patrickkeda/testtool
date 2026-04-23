"""
MES配置对话框

提供MES系统配置的界面，包括厂商选择、连接参数、认证信息等。
"""

from __future__ import annotations

import json
from typing import Optional, Dict, Any
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QPushButton,
    QDialogButtonBox,
    QTabWidget,
    QWidget,
    QTextEdit,
    QLabel,
    QMessageBox,
)
from PySide6.QtGui import QFont

from ..i18n import I18n
from ...config.service import ConfigService
from ...config.models import MesConfig, MesCredentials


class MESConfigDialog(QDialog):
    """MES配置对话框"""
    _SECRET_MASK = "********"
    
    def __init__(self, parent: Optional[QWidget] = None, config_service: Optional[ConfigService] = None) -> None:
        super().__init__(parent)
        self._config_service = config_service
        self._i18n = I18n("zh_CN")
        self._logger = logging.getLogger(__name__)
        self._last_transport_mode = ""
        self._loaded_secret_enc = ""
        
        self.setWindowTitle("MES配置")
        self.setModal(True)
        self.resize(600, 500)
        
        self._init_ui()
        self._load_config()
        
    def _init_ui(self) -> None:
        """初始化UI"""
        layout = QVBoxLayout(self)
        
        # 创建标签页
        self.tabs = QTabWidget(self)
        
        # 基本配置标签页
        self.basic_tab = self._create_basic_tab()
        self.tabs.addTab(self.basic_tab, "基本配置")
        
        # 认证配置标签页
        self.auth_tab = self._create_auth_tab()
        self.tabs.addTab(self.auth_tab, "认证配置")
        
        # 端点配置标签页
        self.endpoints_tab = self._create_endpoints_tab()
        self.tabs.addTab(self.endpoints_tab, "端点配置")
        
        # 高级配置标签页
        self.advanced_tab = self._create_advanced_tab()
        self.tabs.addTab(self.advanced_tab, "高级配置")
        
        layout.addWidget(self.tabs)
        
        # 按钮
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults,
            self
        )
        self.buttons.accepted.connect(self._on_ok)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._on_restore_defaults)
        layout.addWidget(self.buttons)

        # 供应商切换时自动应用预设
        self.vendor_combo.currentTextChanged.connect(self._on_vendor_changed)
        self.transport_mode_edit.textChanged.connect(self._on_transport_mode_changed)
        self.client_secret_edit.textChanged.connect(self._on_secret_text_changed)
        
    def _create_basic_tab(self) -> QWidget:
        """创建基本配置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 基本配置组
        basic_group = QGroupBox("基本配置", widget)
        basic_layout = QFormLayout(basic_group)
        
        # 厂商选择
        self.vendor_combo = QComboBox(widget)
        self.vendor_combo.addItems(["huaqin_qmes", "sample_mes", "sap_mes", "custom_mes"])
        self.vendor_combo.setEditable(True)
        basic_layout.addRow("厂商:", self.vendor_combo)
        
        # 基础URL
        self.base_url_edit = QLineEdit(widget)
        self.base_url_edit.setPlaceholderText("https://mes.example.com/api")
        basic_layout.addRow("基础URL:", self.base_url_edit)
        
        # 工位ID
        self.station_id_edit = QLineEdit(widget)
        self.station_id_edit.setPlaceholderText("FT-1")
        basic_layout.addRow("工位ID:", self.station_id_edit)
        
        # 启用状态
        self.enabled_check = QCheckBox("启用MES连接", widget)
        self.enabled_check.setChecked(True)
        basic_layout.addRow("", self.enabled_check)
        
        layout.addWidget(basic_group)
        layout.addStretch()
        
        return widget
        
    def _create_auth_tab(self) -> QWidget:
        """创建认证配置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 认证配置组
        auth_group = QGroupBox("认证配置", widget)
        auth_layout = QFormLayout(auth_group)
        
        # 客户端ID
        self.client_id_edit = QLineEdit(widget)
        self.client_id_edit.setPlaceholderText("TEST_TOOL")
        auth_layout.addRow("客户端ID:", self.client_id_edit)
        
        # 客户端密钥
        self.client_secret_edit = QLineEdit(widget)
        self.client_secret_edit.setEchoMode(QLineEdit.Password)
        self.client_secret_edit.setPlaceholderText("输入客户端密钥")
        auth_layout.addRow("客户端密钥:", self.client_secret_edit)
        self.secret_status_label = QLabel("密码状态: 未修改", widget)
        auth_layout.addRow("", self.secret_status_label)

        self.dll_path_edit = QLineEdit(widget)
        self.dll_path_edit.setPlaceholderText(r"D:\Mes\dll_v4.0.0.3\x64\HQMES.dll")
        auth_layout.addRow("DLL路径:", self.dll_path_edit)

        self.start_api_edit = QLineEdit(widget)
        self.start_api_edit.setPlaceholderText("MesStart / MesStart2 / MesStart3")
        auth_layout.addRow("Start接口:", self.start_api_edit)

        self.extra_info_position_edit = QLineEdit(widget)
        self.extra_info_position_edit.setPlaceholderText("BATROLL")
        auth_layout.addRow("ExtraInfo位置:", self.extra_info_position_edit)

        self.extra_info_extinfo_edit = QLineEdit(widget)
        self.extra_info_extinfo_edit.setPlaceholderText("额外扩展参数，可空")
        auth_layout.addRow("ExtraInfo扩展:", self.extra_info_extinfo_edit)

        self.transport_mode_edit = QLineEdit(widget)
        self.transport_mode_edit.setPlaceholderText("默认空；JSON模式填 meshelper_json")
        auth_layout.addRow("传输模式:", self.transport_mode_edit)

        self.h_token_edit = QLineEdit(widget)
        self.h_token_edit.setPlaceholderText("HEAD.H_TOKEN")
        auth_layout.addRow("H_TOKEN:", self.h_token_edit)

        self.h_action_edit = QLineEdit(widget)
        self.h_action_edit.setPlaceholderText("HEAD.H_ACTION，如 IMEID")
        auth_layout.addRow("H_ACTION:", self.h_action_edit)

        self.op_group_edit = QLineEdit(widget)
        self.op_group_edit.setPlaceholderText("MAIN.G_GROUP")
        auth_layout.addRow("OP_GROUP:", self.op_group_edit)

        self.op_line_edit = QLineEdit(widget)
        self.op_line_edit.setPlaceholderText("MAIN.G_OP_LINE")
        auth_layout.addRow("OP_LINE:", self.op_line_edit)

        self.op_pc_edit = QLineEdit(widget)
        self.op_pc_edit.setPlaceholderText("MAIN.G_OP_PC")
        auth_layout.addRow("OP_PC:", self.op_pc_edit)

        self.op_shift_edit = QLineEdit(widget)
        self.op_shift_edit.setPlaceholderText("MAIN.G_OP_SHIFT")
        auth_layout.addRow("OP_SHIFT:", self.op_shift_edit)

        # QMES ActionName（工位动作名）
        self.action_name_edit = QLineEdit(widget)
        self.action_name_edit.setPlaceholderText("如: FT/FGT/BT_CAL")
        auth_layout.addRow("ActionName(过站开始):", self.action_name_edit)

        self.upload_action_name_edit = QLineEdit(widget)
        self.upload_action_name_edit.setPlaceholderText("空则与 ActionName 相同")
        auth_layout.addRow("ActionName(结果上传):", self.upload_action_name_edit)

        # QMES Tools 工具标识
        self.tools_name_edit = QLineEdit(widget)
        self.tools_name_edit.setPlaceholderText("工具名，如 TestTool")
        auth_layout.addRow("ToolsName:", self.tools_name_edit)

        self.tools_version_edit = QLineEdit(widget)
        self.tools_version_edit.setPlaceholderText("版本号，如 V1.0")
        auth_layout.addRow("ToolsVersion:", self.tools_version_edit)

        # QMES SNType
        self.sn_type_edit = QLineEdit(widget)
        self.sn_type_edit.setPlaceholderText("默认 1")
        auth_layout.addRow("SNType:", self.sn_type_edit)

        self.failure_error_code_edit = QLineEdit(widget)
        self.failure_error_code_edit.setPlaceholderText("失败默认 ErrorCode，默认 1")
        auth_layout.addRow("失败ErrorCode:", self.failure_error_code_edit)

        # QMES ExtInfo
        self.ext_info_edit = QLineEdit(widget)
        self.ext_info_edit.setPlaceholderText('JSON，如 {"Line":"L01","Group":"A"}')
        auth_layout.addRow("ExtInfo:", self.ext_info_edit)
        
        # 显示/隐藏密钥按钮
        self.toggle_secret_btn = QPushButton("显示", widget)
        self.toggle_secret_btn.clicked.connect(self._toggle_secret_visibility)
        auth_layout.addRow("", self.toggle_secret_btn)
        
        layout.addWidget(auth_group)
        layout.addStretch()
        
        return widget
        
    def _create_endpoints_tab(self) -> QWidget:
        """创建端点配置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 端点配置组
        endpoints_group = QGroupBox("端点配置", widget)
        endpoints_layout = QFormLayout(endpoints_group)
        
        # 认证端点
        self.auth_endpoint_edit = QLineEdit(widget)
        self.auth_endpoint_edit.setPlaceholderText("/auth/login")
        endpoints_layout.addRow("认证端点:", self.auth_endpoint_edit)
        
        # 工单查询端点
        self.workorder_endpoint_edit = QLineEdit(widget)
        self.workorder_endpoint_edit.setPlaceholderText("/workorders/{sn}")
        endpoints_layout.addRow("工单查询:", self.workorder_endpoint_edit)

        # Start2端点
        self.start2_endpoint_edit = QLineEdit(widget)
        self.start2_endpoint_edit.setPlaceholderText("/mes/start2")
        endpoints_layout.addRow("Start2端点:", self.start2_endpoint_edit)
        
        # 结果上传端点
        self.upload_endpoint_edit = QLineEdit(widget)
        self.upload_endpoint_edit.setPlaceholderText("/testresults")
        endpoints_layout.addRow("结果上传:", self.upload_endpoint_edit)

        # End端点
        self.end_endpoint_edit = QLineEdit(widget)
        self.end_endpoint_edit.setPlaceholderText("/mes/end")
        endpoints_layout.addRow("End端点:", self.end_endpoint_edit)

        # CheckFlow端点（helper_json）
        self.checkflow_endpoint_edit = QLineEdit(widget)
        self.checkflow_endpoint_edit.setPlaceholderText("/mes/checkflow")
        endpoints_layout.addRow("CheckFlow:", self.checkflow_endpoint_edit)

        # UpdateInfo端点（helper_json）
        self.updateinfo_endpoint_edit = QLineEdit(widget)
        self.updateinfo_endpoint_edit.setPlaceholderText("/mes/update_info")
        endpoints_layout.addRow("UpdateInfo:", self.updateinfo_endpoint_edit)

        # UnInit端点
        self.uninit_endpoint_edit = QLineEdit(widget)
        self.uninit_endpoint_edit.setPlaceholderText("/mes/uninit")
        endpoints_layout.addRow("UnInit端点:", self.uninit_endpoint_edit)
        
        # 心跳端点
        self.heartbeat_endpoint_edit = QLineEdit(widget)
        self.heartbeat_endpoint_edit.setPlaceholderText("/heartbeat")
        endpoints_layout.addRow("心跳端点:", self.heartbeat_endpoint_edit)
        
        # 产品参数端点
        self.product_params_endpoint_edit = QLineEdit(widget)
        self.product_params_endpoint_edit.setPlaceholderText("/products/{product_number}")
        endpoints_layout.addRow("产品参数:", self.product_params_endpoint_edit)
        
        layout.addWidget(endpoints_group)
        layout.addStretch()
        
        return widget
        
    def _create_advanced_tab(self) -> QWidget:
        """创建高级配置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 连接配置组
        conn_group = QGroupBox("连接配置", widget)
        conn_layout = QFormLayout(conn_group)
        
        # 超时时间
        self.timeout_spin = QSpinBox(widget)
        self.timeout_spin.setRange(100, 600000)
        self.timeout_spin.setValue(3000)
        self.timeout_spin.setSuffix(" ms")
        conn_layout.addRow("超时时间:", self.timeout_spin)
        
        # 重试次数
        self.retries_spin = QSpinBox(widget)
        self.retries_spin.setRange(0, 10)
        self.retries_spin.setValue(3)
        conn_layout.addRow("重试次数:", self.retries_spin)
        
        # 心跳间隔
        self.heartbeat_interval_spin = QSpinBox(widget)
        self.heartbeat_interval_spin.setRange(1000, 3600000)
        self.heartbeat_interval_spin.setValue(10000)
        self.heartbeat_interval_spin.setSuffix(" ms")
        conn_layout.addRow("心跳间隔:", self.heartbeat_interval_spin)
        
        layout.addWidget(conn_group)
        
        # 请求头配置组
        headers_group = QGroupBox("请求头配置", widget)
        headers_layout = QVBoxLayout(headers_group)
        
        self.headers_text = QTextEdit(widget)
        self.headers_text.setPlaceholderText("Content-Type: application/json\nUser-Agent: TestTool/1.0")
        self.headers_text.setMaximumHeight(100)
        headers_layout.addWidget(self.headers_text)
        
        layout.addWidget(headers_group)
        layout.addStretch()
        
        return widget
        
    def _toggle_secret_visibility(self) -> None:
        """切换密钥显示/隐藏"""
        if self.client_secret_edit.echoMode() == QLineEdit.Password:
            self.client_secret_edit.setEchoMode(QLineEdit.Normal)
            self.toggle_secret_btn.setText("隐藏")
        else:
            self.client_secret_edit.setEchoMode(QLineEdit.Password)
            self.toggle_secret_btn.setText("显示")
            
    def _load_config(self) -> None:
        """加载配置到UI"""
        if not self._config_service:
            return
            
        try:
            config = self._config_service.load()
            if hasattr(config, 'mes') and config.mes:
                mes_config = config.mes
                
                # 基本配置
                self.vendor_combo.setCurrentText(mes_config.vendor)
                self.base_url_edit.setText(mes_config.base_url)
                self.station_id_edit.setText(getattr(mes_config, 'station_id', ''))
                self.enabled_check.setChecked(getattr(mes_config, 'enabled', True))
                
                # 认证配置
                if hasattr(mes_config, 'credentials') and mes_config.credentials:
                    self.client_id_edit.setText(getattr(mes_config.credentials, 'client_id', ''))
                    self._loaded_secret_enc = str(getattr(mes_config.credentials, 'client_secret_enc', '') or '').strip()
                    # 星号占位：显示已保存状态，但不泄露真实密钥
                    self.client_secret_edit.blockSignals(True)
                    self.client_secret_edit.setText(self._SECRET_MASK if self._loaded_secret_enc else "")
                    self.client_secret_edit.blockSignals(False)
                    self.secret_status_label.setText("密码状态: 未修改")
                    self.dll_path_edit.setText(getattr(mes_config.credentials, 'dll_path', ''))
                    self.start_api_edit.setText(getattr(mes_config.credentials, 'start_api', 'MesStart'))
                    self.extra_info_position_edit.setText(getattr(mes_config.credentials, 'extra_info_position', 'BATROLL'))
                    self.extra_info_extinfo_edit.setText(getattr(mes_config.credentials, 'extra_info_extinfo', ''))
                    self.transport_mode_edit.setText(getattr(mes_config.credentials, 'transport_mode', ''))
                    self.h_token_edit.setText(getattr(mes_config.credentials, 'h_token', ''))
                    self.h_action_edit.setText(getattr(mes_config.credentials, 'h_action', ''))
                    self.op_group_edit.setText(getattr(mes_config.credentials, 'op_group', ''))
                    self.op_line_edit.setText(getattr(mes_config.credentials, 'op_line', ''))
                    self.op_pc_edit.setText(getattr(mes_config.credentials, 'op_pc', ''))
                    self.op_shift_edit.setText(getattr(mes_config.credentials, 'op_shift', ''))
                    self.action_name_edit.setText(getattr(mes_config.credentials, 'action_name', ''))
                    self.upload_action_name_edit.setText(getattr(mes_config.credentials, 'upload_action_name', ''))
                    self.tools_name_edit.setText(getattr(mes_config.credentials, 'tools_name', ''))
                    self.tools_version_edit.setText(getattr(mes_config.credentials, 'tools_version', ''))
                    self.sn_type_edit.setText(str(getattr(mes_config.credentials, 'sn_type', '1')))
                    self.failure_error_code_edit.setText(str(getattr(mes_config.credentials, 'failure_error_code', '1')))
                    ext_info = getattr(mes_config.credentials, 'ext_info', {})
                    try:
                        ext_info_text = json.dumps(ext_info or {}, ensure_ascii=False)
                    except Exception:  # noqa: BLE001
                        ext_info_text = "{}"
                    self.ext_info_edit.setText(ext_info_text)
                
                # 端点配置
                if hasattr(mes_config, 'endpoints') and mes_config.endpoints:
                    endpoints = mes_config.endpoints
                    self.auth_endpoint_edit.setText(endpoints.get('mes_init', endpoints.get('auth', '')))
                    self.workorder_endpoint_edit.setText(endpoints.get('mes_start3', endpoints.get('work_order', '')))
                    self.start2_endpoint_edit.setText(endpoints.get('mes_start2', ''))
                    self.upload_endpoint_edit.setText(endpoints.get('mes_end2', endpoints.get('upload', '')))
                    self.end_endpoint_edit.setText(endpoints.get('mes_end', ''))
                    self.checkflow_endpoint_edit.setText(endpoints.get('mes_checkflow', ''))
                    self.updateinfo_endpoint_edit.setText(endpoints.get('mes_update_info', ''))
                    self.uninit_endpoint_edit.setText(endpoints.get('mes_uninit', endpoints.get('uninit', '')))
                    self.heartbeat_endpoint_edit.setText(endpoints.get('heartbeat', ''))
                    self.product_params_endpoint_edit.setText(endpoints.get('product_params', ''))
                
                # 高级配置
                self.timeout_spin.setValue(mes_config.timeout_ms)
                self.retries_spin.setValue(mes_config.retries)
                self.heartbeat_interval_spin.setValue(mes_config.heartbeat_interval_ms)
                
                # 请求头
                if hasattr(mes_config, 'headers') and mes_config.headers:
                    headers_text = '\n'.join([f"{k}: {v}" for k, v in mes_config.headers.items()])
                    self.headers_text.setPlainText(headers_text)
                self._apply_mode_ui_state()
                    
        except Exception as e:
            self._logger.error(f"加载MES配置失败: {e}")
            QMessageBox.warning(self, "警告", f"加载配置失败: {e}")
            
    def _collect_config(self) -> MesConfig:
        """从UI收集配置"""
        # 收集端点配置
        endpoints = {
            'mes_init': self.auth_endpoint_edit.text(),
            'mes_start': self.workorder_endpoint_edit.text(),
            'mes_start2': self.start2_endpoint_edit.text(),
            'mes_start3': self.workorder_endpoint_edit.text(),
            'mes_end': self.end_endpoint_edit.text(),
            'mes_end2': self.upload_endpoint_edit.text(),
            'mes_checkflow': self.checkflow_endpoint_edit.text(),
            'mes_update_info': self.updateinfo_endpoint_edit.text(),
            'mes_uninit': self.uninit_endpoint_edit.text(),
            # 保留旧key，兼容既有读取逻辑
            'auth': self.auth_endpoint_edit.text(),
            'work_order': self.workorder_endpoint_edit.text(),
            'upload': self.upload_endpoint_edit.text(),
            'uninit': self.uninit_endpoint_edit.text(),
            'heartbeat': self.heartbeat_endpoint_edit.text(),
            'product_params': self.product_params_endpoint_edit.text(),
        }
        
        # 收集请求头配置
        headers = {}
        headers_text = self.headers_text.toPlainText().strip()
        if headers_text:
            for line in headers_text.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    headers[key.strip()] = value.strip()

        # QMES ExtInfo
        ext_info_raw = self.ext_info_edit.text().strip()
        ext_info: Dict[str, Any] = {}
        if ext_info_raw:
            try:
                parsed = json.loads(ext_info_raw)
                if isinstance(parsed, dict):
                    ext_info = parsed
            except Exception:  # noqa: BLE001
                ext_info = {}
        
        # 创建认证配置
        raw_secret = self.client_secret_edit.text().strip()
        unchanged_mask = self._loaded_secret_enc and raw_secret == self._SECRET_MASK
        effective_secret = self._loaded_secret_enc if (not raw_secret or unchanged_mask) else raw_secret
        credentials = MesCredentials(
            client_id=self.client_id_edit.text(),
            client_secret_enc=effective_secret,  # 实际应用中需要加密
            dll_path=self.dll_path_edit.text().strip(),
            transport_mode=self.transport_mode_edit.text().strip(),
            h_token=self.h_token_edit.text().strip(),
            h_action=self.h_action_edit.text().strip(),
            op_group=self.op_group_edit.text().strip(),
            op_line=self.op_line_edit.text().strip(),
            op_pc=self.op_pc_edit.text().strip(),
            op_shift=self.op_shift_edit.text().strip(),
            start_api=self.start_api_edit.text().strip() or "MesStart",
            extra_info_position=self.extra_info_position_edit.text().strip() or "BATROLL",
            extra_info_extinfo=self.extra_info_extinfo_edit.text().strip(),
            action_name=self.action_name_edit.text().strip() or self.station_id_edit.text().strip(),
            upload_action_name=self.upload_action_name_edit.text().strip(),
            tools_name=self.tools_name_edit.text().strip() or "TestTool",
            tools_version=self.tools_version_edit.text().strip() or "V1.0",
            sn_type=self.sn_type_edit.text().strip() or "1",
            failure_error_code=self.failure_error_code_edit.text().strip() or "1",
            ext_info=ext_info,
        )
        
        # 创建MES配置
        mes_config = MesConfig(
            vendor=self.vendor_combo.currentText(),
            base_url=self.base_url_edit.text(),
            timeout_ms=self.timeout_spin.value(),
            retries=self.retries_spin.value(),
            heartbeat_interval_ms=self.heartbeat_interval_spin.value(),
            credentials=credentials,
            station_id=self.station_id_edit.text(),
            enabled=self.enabled_check.isChecked(),
            endpoints=endpoints,
            headers=headers
        )
        
        return mes_config
        
    def _on_ok(self) -> None:
        """确定按钮点击"""
        try:
            # 验证配置
            mes_config = self._collect_config()
            
            # 基本验证
            if not mes_config.base_url:
                QMessageBox.warning(self, "验证失败", "基础URL不能为空")
                return
                
            if not mes_config.base_url.startswith('https://'):
                if not mes_config.base_url.startswith('http://'):
                    QMessageBox.warning(self, "验证失败", "基础URL必须使用HTTP或HTTPS协议")
                    return

            if mes_config.vendor == "huaqin_qmes":
                if not mes_config.endpoints.get("mes_init"):
                    QMessageBox.warning(self, "验证失败", "HuaqinMES 的 MesInit 端点不能为空")
                    return
                start_api = str(getattr(mes_config.credentials, "start_api", "MesStart") or "MesStart").strip().lower()
                if start_api == "messtart2":
                    if not mes_config.endpoints.get("mes_start2"):
                        QMessageBox.warning(self, "验证失败", "Start接口=MesStart2 时，MesStart2 端点不能为空")
                        return
                elif start_api == "messtart3":
                    if not mes_config.endpoints.get("mes_start3"):
                        QMessageBox.warning(self, "验证失败", "Start接口=MesStart3 时，MesStart3 端点不能为空")
                        return
                else:
                    if not (mes_config.endpoints.get("mes_start") or mes_config.endpoints.get("work_order")):
                        QMessageBox.warning(self, "验证失败", "Start接口=MesStart 时，MesStart 端点不能为空")
                        return
                if not (mes_config.endpoints.get("mes_end2") or mes_config.endpoints.get("upload")):
                    QMessageBox.warning(self, "验证失败", "MesEnd2 端点不能为空")
                    return
                
            if not mes_config.station_id:
                QMessageBox.warning(self, "验证失败", "工位ID不能为空")
                return
                
            # 保存配置
            if self._config_service:
                root = self._config_service.load()
                root.mes = mes_config
                self._config_service.save(root)
                self._loaded_secret_enc = str(getattr(mes_config.credentials, "client_secret_enc", "") or "").strip()
                self._logger.info("MES配置已更新")
                
            self.accept()
            
        except Exception as e:
            self._logger.error(f"保存MES配置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")
            
    def _on_restore_defaults(self) -> None:
        """恢复默认设置"""
        reply = QMessageBox.question(
            self, "确认恢复",
            "确定要恢复默认的MES配置吗？\n当前配置将被覆盖。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.vendor_combo.setCurrentText("huaqin_qmes")
            self._apply_vendor_preset("huaqin_qmes", force=True)

    def _on_vendor_changed(self, vendor: str) -> None:
        """供应商切换事件。"""
        self._apply_vendor_preset(vendor, force=True)

    def _on_secret_text_changed(self, value: str) -> None:
        text = (value or "").strip()
        unchanged_mask = self._loaded_secret_enc and text == self._SECRET_MASK
        self.secret_status_label.setText("密码状态: 未修改" if (not text or unchanged_mask) else "密码状态: 已修改")

    def _on_transport_mode_changed(self, value: str) -> None:
        self._last_transport_mode = value or ""
        self._apply_mode_ui_state()

    def _apply_mode_ui_state(self) -> None:
        mode = (self.transport_mode_edit.text() or "").strip().lower()
        helper_mode = mode == "meshelper_json"
        for edit in (
            self.h_token_edit,
            self.h_action_edit,
            self.op_group_edit,
            self.op_line_edit,
            self.op_pc_edit,
            self.op_shift_edit,
            self.checkflow_endpoint_edit,
            self.updateinfo_endpoint_edit,
        ):
            edit.setEnabled(helper_mode or edit in (self.h_token_edit, self.h_action_edit))

    def _apply_vendor_preset(self, vendor: str, force: bool = False) -> None:
        """按供应商应用预设配置。"""
        if vendor != "huaqin_qmes":
            return

        def _set_text_if_needed(edit: QLineEdit, value: str) -> None:
            if force or not edit.text().strip():
                edit.setText(value)

        _set_text_if_needed(self.base_url_edit, "http://localhost:8989")
        _set_text_if_needed(self.station_id_edit, "FT-1")
        self.enabled_check.setChecked(True)

        _set_text_if_needed(self.client_id_edit, "TEST_TOOL")
        if force:
            self.client_secret_edit.setText("")
        _set_text_if_needed(self.action_name_edit, self.station_id_edit.text().strip() or "FT-1")
        _set_text_if_needed(self.tools_name_edit, "TestTool")
        _set_text_if_needed(self.tools_version_edit, "V1.0")
        _set_text_if_needed(self.sn_type_edit, "1")
        _set_text_if_needed(self.ext_info_edit, "{}")

        _set_text_if_needed(self.auth_endpoint_edit, "/mes/init")
        _set_text_if_needed(self.workorder_endpoint_edit, "/mes/start3")
        _set_text_if_needed(self.start2_endpoint_edit, "/mes/start2")
        _set_text_if_needed(self.upload_endpoint_edit, "/mes/end2")
        _set_text_if_needed(self.end_endpoint_edit, "/mes/end")
        _set_text_if_needed(self.checkflow_endpoint_edit, "/mes/checkflow")
        _set_text_if_needed(self.updateinfo_endpoint_edit, "/mes/update_info")
        _set_text_if_needed(self.uninit_endpoint_edit, "/mes/uninit")
        if force:
            self.heartbeat_endpoint_edit.setText("")
            self.product_params_endpoint_edit.setText("")

        self.timeout_spin.setValue(3000 if not force else 5000)
        self.retries_spin.setValue(3)
        self.heartbeat_interval_spin.setValue(10000)
        self.headers_text.setPlainText("Content-Type: application/json")
