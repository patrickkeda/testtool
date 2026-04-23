"""
测试步骤注册

将所有测试步骤注册到全局注册表中。
"""
from .registry import register
from .steps.common.measure_current import MeasureCurrentStep
from .steps.utility.delay import DelayStep
from .steps.utility.confirm import ConfirmStep
from .steps.utility.generate_sn import GenerateSNStep
from .steps.cases.boot_current import BootCurrentStep
from .steps.cases.scan_sn import ScanSNStep as ScanSN
from .steps.cases.sn_judgment import SNJudgmentStep
from .steps.cases.connect import ConnectStep
from .steps.cases.disconnect import DisconnectStep
from .steps.cases.engineer_command import EngineerCommandStep
from .steps.cases.engineer_test import EngineerTestStep
from .steps.cases.modbus_steps import (
    ModbusConnectStep,
    ModbusWriteCoilStep,
    ModbusWriteRegisterStep,
    ModbusRecordDataStep,
    ModbusDisconnectStep,
)
from .steps.cases.pdf_report_steps import GeneratePDFReportStep, JudgeTNCurveStep, JudgeTorqueRatioStep
from .steps.cases.modbus_steps_com import (
    PlcModbusConnectStep,
    PlcModbusWriteRegisterStep,
    PlcModbusReadRegisterStep,
    PlcModbusDisconnectStep,
)
from .steps.cases.can_steps import (
    CanConnectStep,
    CanSendFrameStep,
    CanDisconnectStep,
)
from .steps.cases.pcan import (
    PcanConnectStep,
    PcanSearchMotorStep,
    PcanEnableMotorStep,
    PcanMoveWithTorqueLogStep,
    PcanDisconnectStep,
)
from .steps.cases.create_device_json import CreateDeviceJsonStep
from .steps.cases.compare_version import CompareVersionStep
from .steps.cases.mes_steps import MESHeartbeatStep, MESGetWorkOrderStep, MESUploadResultStep
from .steps.cases.zebra_printer import ZebraPrintStep


def register_all_steps():
    """注册所有测试步骤"""
    
    # 注册测试用例
    register(
        step_type="case.boot_current",
        step_class=BootCurrentStep,
        aliases=["boot_current", "开机电流", "boot_current_test"]
    )
    
    # 保留 case 版本的实现文件作为对话框等复用，但不再注册 case.scan_sn，统一使用 scan.sn
    
    # 注册通用步骤
    register(
        step_type="measure.current",
        step_class=MeasureCurrentStep,
        aliases=["current", "measure_current", "measure.i"]
    )
    
    # 注册工具相关步骤（统一使用 cases 版本的 ScanSN 实现）
    register(
        step_type="scan.sn",
        step_class=ScanSN,
        aliases=["scan_sn", "scan_serial", "get_sn"]
    )

    # 注册生成SN步骤（无UI，按规则自动生成并写入上下文）
    register(
        step_type="utility.generate_sn",
        step_class=GenerateSNStep,
        aliases=["generate_sn", "gen_sn", "sn.generate"]
    )
    
    # 注册SN判断步骤
    register(
        step_type="utility.sn_judgment",
        step_class=SNJudgmentStep,
        aliases=["sn_judgment", "judge_sn", "sn_check"]
    )
    
    register(
        step_type="utility.delay",
        step_class=DelayStep,
        aliases=["delay", "wait", "sleep"]
    )
    
    register(
        step_type="utility.confirm",
        step_class=ConfirmStep,
        aliases=["confirm", "utility.prompt", "prompt.confirm"]
    )
    
   
    register(
        step_type="connect_engineer",
        step_class=ConnectStep,
        aliases=["connect", "connect_engineer", "connect_engineer_service"]
    )
    
    register(
        step_type="disconnect_engineer",
        step_class=DisconnectStep,
        aliases=["disconnect", "disconnect_engineer_service", "disconnect_engineer"]
    )
    
    register(
        step_type="engineer.command",
        step_class=EngineerCommandStep,
        aliases=["engineer_command", "eng_cmd", "engineer.cmd"]
    )
    
    register(
        step_type="engineer.test",
        step_class=EngineerTestStep,
        aliases=["engineer_test", "eng_test"]
    )
    
    # 注册Modbus相关步骤
    register(
        step_type="modbus.connect",
        step_class=ModbusConnectStep,
        aliases=["modbus_connect", "connect_modbus", "motor_connect"]
    )
    
    register(
        step_type="modbus.write_coil",
        step_class=ModbusWriteCoilStep,
        aliases=["modbus_write_coil", "write_coil", "motor_write_coil"]
    )
    
    register(
        step_type="modbus.write_register",
        step_class=ModbusWriteRegisterStep,
        aliases=["modbus_write_register", "write_register", "motor_write_register"]
    )
    
    register(
        step_type="modbus.record_data",
        step_class=ModbusRecordDataStep,
        aliases=["modbus_record_data", "record_motor_data", "motor_record"]
    )
    
    register(
        step_type="modbus.disconnect",
        step_class=ModbusDisconnectStep,
        aliases=["modbus_disconnect", "disconnect_modbus", "motor_disconnect"]
    )
    
    # 注册PDF报告生成步骤
    register(
        step_type="modbus.generate_report",
        step_class=GeneratePDFReportStep,
        aliases=["modbus_generate_report", "generate_pdf_report", "motor_report", "pdf_report"]
    )
    
    # 注册TN曲线判断步骤
    register(
        step_type="utility.judge_tn_curve",
        step_class=JudgeTNCurveStep,
        aliases=["judge_tn_curve", "tn_curve_judge", "judge_tn"]
    )
    
    # 注册静态扭矩比例曲线判断步骤
    register(
        step_type="utility.judge_torque_ratio",
        step_class=JudgeTorqueRatioStep,
        aliases=["judge_torque_ratio", "torque_ratio_judge", "judge_ratio"]
    )

    # 注册 PLC Modbus RTU（串口）相关步骤
    register(
        step_type="plc.modbus.connect",
        step_class=PlcModbusConnectStep,
        aliases=["plc_modbus_connect", "plc.connect", "plc_modbus_rtu_connect"],
    )

    register(
        step_type="plc.modbus.write_register",
        step_class=PlcModbusWriteRegisterStep,
        aliases=["plc_write_register", "plc.write_reg"],
    )

    register(
        step_type="plc.modbus.read_register",
        step_class=PlcModbusReadRegisterStep,
        aliases=["plc_read_register", "plc.read_reg"],
    )

    register(
        step_type="plc.modbus.disconnect",
        step_class=PlcModbusDisconnectStep,
        aliases=["plc_modbus_disconnect", "plc.disconnect"],
    )

    # 注册 CAN 总线相关步骤
    register(
        step_type="can.connect",
        step_class=CanConnectStep,
        aliases=["can_connect", "connect_can"],
    )

    register(
        step_type="can.send_frame",
        step_class=CanSendFrameStep,
        aliases=["can_send", "can.send"],
    )

    register(
        step_type="can.disconnect",
        step_class=CanDisconnectStep,
        aliases=["can_disconnect", "disconnect_can"],
    )

    # 注册 PCAN 相关步骤
    register(
        step_type="pcan.connect",
        step_class=PcanConnectStep,
        aliases=["pcan_connect", "connect_pcan", "pcan.usb1.connect"],
    )

    register(
        step_type="pcan.search_motor",
        step_class=PcanSearchMotorStep,
        aliases=["pcan_search_motor", "pcan.find_motor"],
    )

    register(
        step_type="pcan.enable_motor",
        step_class=PcanEnableMotorStep,
        aliases=["pcan_enable_motor", "pcan.motor_enable"],
    )

    register(
        step_type="pcan.move_with_torque_log",
        step_class=PcanMoveWithTorqueLogStep,
        aliases=["pcan_move_with_torque_log", "pcan.move_and_log"],
    )

    register(
        step_type="pcan.disconnect",
        step_class=PcanDisconnectStep,
        aliases=["pcan_disconnect", "disconnect_pcan"],
    )

    # 注册创建 device.json 文件步骤
    register(
        step_type="case.create_device_json",
        step_class=CreateDeviceJsonStep,
        aliases=["create_device_json", "device_json", "create_json"]
    )

    register(
        step_type="case.compare_version",
        step_class=CompareVersionStep,
        aliases=["compare_version", "version_compare", "check_version"]
    )

    register(
        step_type="mes.heartbeat",
        step_class=MESHeartbeatStep,
        aliases=["mes_heartbeat", "heartbeat.mes"],
    )

    register(
        step_type="mes.get_work_order",
        step_class=MESGetWorkOrderStep,
        aliases=["mes_get_work_order", "mes.work_order", "mes.start"],
    )

    register(
        step_type="mes.upload_result",
        step_class=MESUploadResultStep,
        aliases=["mes_upload_result", "mes.end", "mes_upload"],
    )

    register(
        step_type="printer.zebra",
        step_class=ZebraPrintStep,
        aliases=["zebra.print", "print.zebra", "zebra_printer"],
    )


# 自动注册所有步骤
register_all_steps()
