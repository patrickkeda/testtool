"""
Pydantic models for application configuration.
"""

from __future__ import annotations

from typing import Optional, Dict, Any

from pydantic import BaseModel, Field, ConfigDict, validator


class AppConfig(BaseModel):
    language: str = Field("zh_CN")
    station_name: str = Field("FT-1")
    theme: str = Field("light")


class LoggingRotation(BaseModel):
    when: str = Field("midnight")
    backupCount: int = Field(14, alias="backupCount")
    max_file_size: int = Field(100 * 1024 * 1024, description="最大文件大小(字节)")


class TestLogConfig(BaseModel):
    enabled: bool = Field(True)
    base_dir: str = Field("Result/TestResult")
    date_format: str = Field("%Y%m%d")
    filename: str = Field("{SN}-{station}-{port}-{timestamp}-{result}.log")
    level: str = Field("INFO")
    include_config: bool = Field(True)
    include_measurements: bool = Field(True)


class ErrorLogConfig(BaseModel):
    enabled: bool = Field(True)
    base_dir: str = Field("Result/ErrorLog")
    date_format: str = Field("%Y%m%d")
    filename: str = Field("{SN}-{station}-{port}-{timestamp}.log")
    level: str = Field("ERROR")
    include_stack_trace: bool = Field(True)


class SystemLogConfig(BaseModel):
    enabled: bool = Field(True)
    base_dir: str = Field("System")
    date_format: str = Field("%Y%m%d")
    config_filename: str = Field("CONFIG-{station}-{timestamp}.log")
    system_filename: str = Field("SYSTEM-{station}-{timestamp}.log")
    level: str = Field("INFO")


class LoggingConfig(BaseModel):
    level: str = Field("INFO")
    dir: str = Field("D:/Logs/TestTool")
    station_name: str = Field("FT-1")
    rotation: LoggingRotation = Field(default_factory=LoggingRotation)
    test_log: TestLogConfig = Field(default_factory=TestLogConfig)
    error_log: ErrorLogConfig = Field(default_factory=ErrorLogConfig)
    system_log: SystemLogConfig = Field(default_factory=SystemLogConfig)
    remote_enabled: bool = Field(False, alias="enabled")
    endpoint: Optional[str] = None


class SerialConfig(BaseModel):
    port: str = Field("COM3")
    baudrate: int = Field(115200, ge=1200, le=10_000_000)
    bytesize: int = Field(8, ge=5, le=8)
    parity: str = Field("N")
    stopbits: float = Field(1.0)
    timeout_ms: int = Field(2000, ge=10, le=600_000)
    retries: int = Field(3, ge=0, le=10)
    retry_backoff_ms: int = Field(200, ge=0, le=60_000)


class TcpConfig(BaseModel):
    host: str = Field("127.0.0.1")
    port: int = Field(5020, ge=1, le=65535)
    timeout_ms: int = Field(2000, ge=10, le=600_000)
    retries: int = Field(3, ge=0, le=10)


class UutConfig(BaseModel):
    """UUT通讯配置"""
    enabled: bool = Field(True, description="是否启用UUT通讯")
    interface: str = Field("serial", description="使用的通讯接口: serial 或 tcp")
    serial: SerialConfig = Field(default_factory=SerialConfig)
    tcp: TcpConfig = Field(default_factory=TcpConfig)


class FixtureConfig(BaseModel):
    """治具/夹具通讯配置"""
    enabled: bool = Field(False, description="是否启用治具通讯")
    serial: SerialConfig = Field(default_factory=SerialConfig)


class InstrumentConfig(BaseModel):
    """测试仪表配置"""
    enabled: bool = Field(False, description="是否启用测试仪表")
    id: str = Field("dmm1", description="仪表ID")
    type: str = Field("DMM", description="仪表类型: DMM/PSU/ELOAD/Scope/Other")
    interface: str = Field("VISA", description="接口类型: VISA/TCP")
    resource: str = Field("TCPIP0::192.168.1.60::INSTR", description="VISA资源字符串")
    host: str = Field("192.168.1.61", description="TCP主机地址")
    port: int = Field(5025, ge=1, le=65535, description="TCP端口")
    timeout_ms: int = Field(3000, ge=10, le=600_000, description="超时时间(ms)")


class PortConfig(BaseModel):
    enabled: bool = Field(True)
    uut: UutConfig = Field(default_factory=UutConfig)
    fixture: FixtureConfig = Field(default_factory=FixtureConfig)
    instruments: Dict[str, InstrumentConfig] = Field(default_factory=dict)
    
    # 保持向后兼容性
    serial: Optional[SerialConfig] = Field(None, description="向后兼容的串口配置")
    tcp: Optional[TcpConfig] = Field(None, description="向后兼容的TCP配置")


class MesCredentials(BaseModel):
    client_id: str = Field("TEST_TOOL")
    client_secret_enc: str = Field("{ENCRYPTED}...")
    dll_path: str = Field("bin/HQMES.dll", description="HQMES.dll路径，配置后优先走DLL模式")
    transport_mode: str = Field("", description="传输模式：空(默认)/meshelper_json")
    h_token: str = Field("", description="Json报文模式HEAD.H_TOKEN")
    h_action: str = Field("", description="Json报文模式HEAD.H_ACTION")
    op_group: str = Field("", description="Json报文模式MAIN.G_GROUP")
    op_line: str = Field("", description="Json报文模式MAIN.G_OP_LINE")
    op_pc: str = Field("", description="Json报文模式MAIN.G_OP_PC")
    op_shift: str = Field("", description="Json报文模式MAIN.G_OP_SHIFT")
    start_api: str = Field("MesStart3", description="过站开始接口：MesStart/MesStart2/MesStart3")
    extra_info_position: str = Field("BATROLL", description="MesSaveAndGetExtraInfo 的 G_POSITION")
    extra_info_extinfo: str = Field("", description="MesSaveAndGetExtraInfo 的 G_EXTINFO")
    action_name: str = Field("FT-1", description="QMES ActionName/工位动作")
    upload_action_name: str = Field("", description="QMES 结果上传 ActionName；空则沿用 action_name")
    tools_name: str = Field("TestTool", description="QMES Tools工具名")
    tools_version: str = Field("V1.0", description="QMES Tools版本号")
    sn_type: str = Field("1", description="QMES SNType，默认1")
    failure_error_code: str = Field("1", description="上传失败默认 ErrorCode（PASS 固定 0）")
    ext_info: Dict[str, Any] = Field(default_factory=dict, description="QMES MesStart3 ExtInfo")

    model_config = ConfigDict(extra="allow")


class MesConfig(BaseModel):
    vendor: str = Field("huaqin_qmes")
    base_url: str = Field("http://localhost:8989")
    timeout_ms: int = Field(3000, ge=10, le=600_000)
    retries: int = Field(3, ge=0, le=10)
    heartbeat_interval_ms: int = Field(10_000, ge=100, le=3_600_000)
    credentials: MesCredentials = Field(default_factory=MesCredentials)
    endpoints: Dict[str, str] = Field(default_factory=lambda: {
        "mes_init": "/mes/init",
        "mes_start": "/mes/start",
        "mes_start2": "/mes/start2",
        "mes_start3": "/mes/start3",
        "mes_checkflow": "/mes/checkflow",
        "mes_end": "/mes/end",
        "mes_end2": "/mes/end2",
        "mes_update_info": "/mes/update_info",
        "mes_uninit": "/mes/uninit",
        # 与旧逻辑保持兼容
        "auth": "/mes/init",
        "work_order": "/mes/start3",
        "upload": "/mes/end2",
        "uninit": "/mes/uninit",
    })
    headers: Dict[str, str] = Field(default_factory=lambda: {
        "Content-Type": "application/json",
    })
    station_id: str = Field("FT-1")
    enabled: bool = Field(True)

    @validator("base_url")
    def _https_only(cls, v: str) -> str:
        if not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("MES base_url must use http or https")
        return v


class TestSequenceConfig(BaseModel):
    file: str = Field("D:/TestSequences/ft1.yaml")
    last_used: Optional[str] = Field(None, description="最后使用的测试序列文件路径")


class SelfCheckConfig(BaseModel):
    checklist: str = Field("D:/Configs/selfcheck.yaml")


class ProductDualVersionConfig(BaseModel):
    app_version: str = Field("", description="App版本号")
    sys_version: str = Field("", description="Sys版本号")


class ProductSingleVersionConfig(BaseModel):
    sw_version: str = Field("", description="软件版本号")


class VersionConfig(BaseModel):
    S100: ProductDualVersionConfig = Field(default_factory=ProductDualVersionConfig)
    X5: ProductDualVersionConfig = Field(default_factory=ProductDualVersionConfig)
    MOTOR: ProductSingleVersionConfig = Field(default_factory=ProductSingleVersionConfig)
    SERVO: ProductSingleVersionConfig = Field(default_factory=ProductSingleVersionConfig)
    UWB: ProductSingleVersionConfig = Field(default_factory=ProductSingleVersionConfig)
    LIDAR: ProductSingleVersionConfig = Field(default_factory=ProductSingleVersionConfig)
    BMS: ProductSingleVersionConfig = Field(default_factory=ProductSingleVersionConfig)

    @validator("S100", "X5", pre=True)
    def _coerce_app_version_fields(cls, value):  # noqa: N805
        if isinstance(value, str):
            return {"app_version": value, "sys_version": ""}
        return value

    @validator("MOTOR", "SERVO", "UWB", "LIDAR", "BMS", pre=True)
    def _coerce_sw_version_fields(cls, value):  # noqa: N805
        if isinstance(value, str):
            return {"sw_version": value}
        return value


class PortsConfig(BaseModel):
    portA: PortConfig = Field(default_factory=PortConfig)
    portB: PortConfig = Field(default_factory=PortConfig)


class PrinterConfig(BaseModel):
    enabled: bool = Field(True, description="是否启用打印机")
    channel: str = Field("tcp", description="打印通道: tcp/local")
    printer_name: str = Field("", description="本地打印队列名")
    host: str = Field("", description="打印机 IP")
    port: int = Field(9100, ge=1, le=65535, description="TCP 端口")
    timeout_ms: int = Field(3000, ge=10, le=600_000)
    copies: int = Field(1, ge=1, le=999)
    encoding: str = Field("utf-8")
    preview: bool = Field(False)
    preview_only: bool = Field(False)
    save_preview: bool = Field(True)
    preview_dir: str = Field("Result/print_preview")
    zpl_file: str = Field("", description="默认 ZPL 模板路径")


class RootConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    ports: PortsConfig = Field(default_factory=PortsConfig)
    mes: MesConfig = Field(default_factory=MesConfig)
    printer: PrinterConfig = Field(default_factory=PrinterConfig)
    versions: VersionConfig = Field(default_factory=VersionConfig)
    test_sequence: TestSequenceConfig = Field(default_factory=TestSequenceConfig)
    selfcheck: SelfCheckConfig = Field(default_factory=SelfCheckConfig)


