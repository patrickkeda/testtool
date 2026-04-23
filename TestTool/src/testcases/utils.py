"""
测试用例工具函数
"""

import yaml
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging

from .config import TestSequenceConfig

logger = logging.getLogger(__name__)


def load_test_sequence(file_path: str) -> TestSequenceConfig:
    """加载测试序列配置
    
    Parameters
    ----------
    file_path : str
        配置文件路径
        
    Returns
    -------
    TestSequenceConfig
        测试序列配置
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            if file_path.endswith('.yaml') or file_path.endswith('.yml'):
                data = yaml.safe_load(f)
            elif file_path.endswith('.json'):
                data = json.load(f)
            else:
                raise ValueError(f"不支持的文件格式: {file_path}")
        
        config = TestSequenceConfig.from_yaml_data(data)
        
        # 验证配置
        errors = config.validate()
        if errors:
            logger.warning(f"配置验证警告: {errors}")
        
        logger.info(f"测试序列配置加载成功: {file_path}")
        return config
        
    except Exception as e:
        logger.error(f"加载测试序列配置失败: {e}")
        raise


def save_test_sequence(config: TestSequenceConfig, file_path: str):
    """保存测试序列配置
    
    Parameters
    ----------
    config : TestSequenceConfig
        测试序列配置
    file_path : str
        保存路径
    """
    try:
        # 确保目录存在
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        
        data = config.dict()
        
        with open(file_path, 'w', encoding='utf-8') as f:
            if file_path.endswith('.yaml') or file_path.endswith('.yml'):
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
            elif file_path.endswith('.json'):
                json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                raise ValueError(f"不支持的文件格式: {file_path}")
        
        logger.info(f"测试序列配置保存成功: {file_path}")
        
    except Exception as e:
        logger.error(f"保存测试序列配置失败: {e}")
        raise


def apply_mes_debug_station_from_config(seq: TestSequenceConfig) -> None:
    """将 Config/config.yaml 的 MES 工站写入 mes-debug 序列。"""
    meta_name = (seq.metadata.name or "").strip().lower()
    if meta_name != "mes-debug":
        return
    try:
        candidates = [
            Path("Config/config.yaml"),
            Path(__file__).resolve().parents[2] / "Config" / "config.yaml",
        ]
        cfg_path = next((p for p in candidates if p.exists()), None)
        if cfg_path is None:
            logger.warning("apply_mes_debug_station_from_config: 未找到 config.yaml")
            return
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        mes = data.get("mes") or {}
        station_id = str(mes.get("station_id", "") or "").strip()
        cred = mes.get("credentials") or {}
        if not isinstance(cred, dict):
            cred = {}
        action_name = str(cred.get("action_name", "") or "").strip()
        effective = action_name or station_id
        if not effective:
            logger.warning("apply_mes_debug_station_from_config: MES 工位/ActionName 为空，跳过写入")
            return
        seq.metadata.station = effective
        for step in seq.steps:
            if step.type == "mes.get_work_order":
                p = dict(step.params or {})
                p["expected_station"] = effective
                step.params = p
    except Exception as exc:  # noqa: BLE001
        logger.warning("apply_mes_debug_station_from_config 失败: %s", exc)


def create_default_test_sequence() -> TestSequenceConfig:
    """创建默认测试序列配置
    
    Returns
    -------
    TestSequenceConfig
        默认测试序列配置
    """
    from .config import TestMetadata, TestStepConfig, ExpectConfig
    
    metadata = TestMetadata(
        name="默认测试序列",
        description="系统默认测试序列",
        author="TestTool",
        product="ABC-1000",
        station="FT-1"
    )
    
    steps = [
        TestStepConfig(
            id="get_work_order",
            name="获取工单信息",
            type="mes.get_work_order",
            params={"sn": "${context.sn}"},
            timeout=5000,
            retries=3,
            on_failure="fail"
        ),
        TestStepConfig(
            id="open_comm",
            name="打开通信连接",
            type="comm.open",
            params={
                "interface": "serial",
                "port": "COM3",
                "baudrate": 115200
            },
            timeout=5000,
            retries=3,
            on_failure="retry"
        ),
        TestStepConfig(
            id="read_sn",
            name="读取序列号",
            type="uut.read_sn",
            params={"command": "*IDN?"},
            timeout=2000,
            retries=2,
            expect=ExpectConfig(
                type="regex",
                regex="^[A-Z0-9]{10}$"
            ),
            on_failure="fail"
        ),
        TestStepConfig(
            id="set_power",
            name="设置电源电压",
            type="instrument.set_voltage",
            params={
                "channel": 1,
                "voltage": "${work_order.supply_voltage}"
            },
            timeout=1000,
            retries=2,
            on_failure="retry"
        ),
        TestStepConfig(
            id="measure_voltage",
            name="测量电压",
            type="instrument.measure_voltage",
            params={"channel": 1},
            timeout=2000,
            retries=2,
            expect=ExpectConfig(
                type="range",
                min_val=3.2,
                max_val=3.4
            ),
            on_failure="retry"
        ),
        TestStepConfig(
            id="upload_result",
            name="上传测试结果",
            type="mes.upload_result",
            params={
                "sn": "${context.sn}",
                "work_order": "${context.work_order}"
            },
            timeout=5000,
            retries=3,
            on_failure="continue"
        ),
        TestStepConfig(
            id="close_comm",
            name="关闭通信连接",
            type="comm.close",
            timeout=1000,
            on_failure="continue"
        )
    ]
    
    return TestSequenceConfig(
        version="1.0",
        metadata=metadata,
        variables={
            "supply_voltage": "${work_order.supply_voltage}",
            "current_limit": "${work_order.current_limit}",
            "test_timeout": "${work_order.test_timeout}",
            "retry_count": 3
        },
        steps=steps
    )


def validate_test_sequence(config: TestSequenceConfig) -> List[str]:
    """验证测试序列配置
    
    Parameters
    ----------
    config : TestSequenceConfig
        测试序列配置
        
    Returns
    -------
    List[str]
        验证错误列表
    """
    errors = []
    
    # 基本验证
    errors.extend(config.validate())
    
    # 检查步骤依赖
    step_ids = {step.id for step in config.steps}
    for step in config.steps:
        # 检查参数中的变量引用
        for key, value in step.params.items():
            if isinstance(value, str) and "${" in value:
                # 简单的变量引用检查
                import re
                variables = re.findall(r'\$\{([^}]+)\}', value)
                for var in variables:
                    if var.startswith("results."):
                        # 检查结果引用
                        ref_step_id = var.split(".")[1]
                        if ref_step_id not in step_ids:
                            errors.append(f"步骤 {step.id} 引用了不存在的步骤结果: {ref_step_id}")
    
    return errors


def get_step_statistics(config: TestSequenceConfig) -> Dict[str, Any]:
    """获取测试序列统计信息
    
    Parameters
    ----------
    config : TestSequenceConfig
        测试序列配置
        
    Returns
    -------
    Dict[str, Any]
        统计信息
    """
    step_types = {}
    total_timeout = 0
    total_retries = 0
    
    for step in config.steps:
        # 统计步骤类型
        step_type = step.type.split(".")[0]
        step_types[step_type] = step_types.get(step_type, 0) + 1
        
        # 统计超时时间
        if step.timeout:
            total_timeout += step.timeout
        
        # 统计重试次数
        total_retries += step.retries
    
    return {
        "total_steps": len(config.steps),
        "step_types": step_types,
        "total_timeout_ms": total_timeout,
        "total_retries": total_retries,
        "estimated_duration_ms": total_timeout + (total_retries * 1000),  # 粗略估算
        "has_mes_steps": any(step.type.startswith("mes.") for step in config.steps),
        "has_instrument_steps": any(step.type.startswith("instrument.") for step in config.steps),
        "has_comm_steps": any(step.type.startswith("comm.") for step in config.steps)
    }


def export_test_sequence(config: TestSequenceConfig, file_path: str, format: str = "yaml"):
    """导出测试序列配置
    
    Parameters
    ----------
    config : TestSequenceConfig
        测试序列配置
    file_path : str
        导出路径
    format : str
        导出格式 (yaml, json)
    """
    try:
        # 确保目录存在
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        
        data = config.dict()
        
        with open(file_path, 'w', encoding='utf-8') as f:
            if format.lower() == "yaml":
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
            elif format.lower() == "json":
                json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                raise ValueError(f"不支持的导出格式: {format}")
        
        logger.info(f"测试序列配置导出成功: {file_path}")
        
    except Exception as e:
        logger.error(f"导出测试序列配置失败: {e}")
        raise


def import_test_sequence(file_path: str) -> TestSequenceConfig:
    """导入测试序列配置
    
    Parameters
    ----------
    file_path : str
        导入文件路径
        
    Returns
    -------
    TestSequenceConfig
        测试序列配置
    """
    return load_test_sequence(file_path)
