"""
测试用例工具函数
"""

import json
import logging
import re
import subprocess
import sys
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import TestSequenceConfig

logger = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")


def resolve_placeholders_in_params(params: Dict[str, Any], ctx: Any) -> Dict[str, Any]:
    """将步骤 params 中字符串里的 ${var} / ${context.xxx} 替换为上下文中的值（含序列 variables 注入）。"""

    def _one_str(s: str) -> str:
        def repl(m: re.Match) -> str:
            key = m.group(1).strip()
            if key.startswith("context."):
                k = key[len("context.") :]
                v = ctx.get_data(k, None)
                return "" if v is None else str(v)
            v = ctx.get_data(key, None)
            if v is not None:
                return str(v)
            return m.group(0)

        # 多轮替换：支持 variables 中「变量引用变量」
        # 例如 script_args: '${pvt_script_args}' 展开后仍含 ${pvt_stress_loops}
        out = s
        for _ in range(32):
            nxt = _PLACEHOLDER.sub(repl, out)
            if nxt == out:
                break
            out = nxt
        return out

    def _walk(val: Any) -> Any:
        if isinstance(val, str):
            return _one_str(val)
        if isinstance(val, dict):
            return {k: _walk(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_walk(v) for v in val]
        return val

    return _walk(dict(params or {}))


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


def resolve_project_requirements_txt() -> Optional[Path]:
    """定位项目根目录下的 ``requirements.txt``（开发与打包）。"""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for candidate in (
            exe_dir / "_internal" / "requirements.txt",
            exe_dir / "requirements.txt",
        ):
            if candidate.is_file():
                return candidate
        return None
    # TestTool/src/testcases/utils.py -> parents[2] == TestTool/
    return Path(__file__).resolve().parents[2] / "requirements.txt"


def run_pip_install_project_requirements() -> tuple[bool, str]:
    """使用当前解释器执行 ``pip install -r requirements.txt``。

    Returns
    -------
    (ok, message)
        ``message`` 供界面展示（成功为简要说明，失败含尾部日志）。
    """
    if getattr(sys, "frozen", False):
        return False, "当前为打包运行环境，无法在此一键 pip 安装；请使用安装包或手动部署依赖。"

    req = resolve_project_requirements_txt()
    if req is None or not req.is_file():
        return False, f"未找到 requirements.txt（已查找打包目录与开发目录）。"

    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(req),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        tail = (err or out)[-4500:]
        if proc.returncode != 0:
            return False, f"pip 退出码 {proc.returncode}。末尾输出：\n{tail}"
        for key in list(sys.modules):
            if key == "ruamel" or key.startswith("ruamel."):
                del sys.modules[key]
        ok_msg = f"已根据文件安装依赖：\n{req}\n"
        if out:
            ok_msg += "\n" + out[-2500:]
        return True, ok_msg
    except subprocess.TimeoutExpired:
        return False, "pip 安装超时（>10 分钟）。"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _ruamel_yaml_available() -> bool:
    """是否已安装 ``ruamel.yaml``（不做自动 pip，请用菜单「一键安装依赖」或手动安装）。"""
    try:
        from ruamel.yaml import YAML  # noqa: F401
        return True
    except ImportError:
        return False


def patch_sequence_yaml_step_operational_fields(
    file_path: str,
    step_id: str,
    *,
    retries: int,
    retry_interval_ms: int,
    timeout: int,
    on_failure: str,
) -> bool:
    """仅更新序列 YAML 中某一 ``steps`` 条目的编排字段，尽量保留注释与排版。

    使用 ``ruamel.yaml`` 就地读写。成功返回 ``True``；无法使用 ``ruamel.yaml``
    或文件中找不到该 ``id`` 时返回 ``False``（由调用方决定是否全量 ``save_test_sequence``）。
    """
    if not _ruamel_yaml_available():
        return False

    from ruamel.yaml import YAML

    path = Path(file_path)
    if not path.suffix.lower() in (".yaml", ".yml"):
        return False

    yml = YAML()
    yml.preserve_quotes = True
    try:
        yml.indent(mapping=2, sequence=4, offset=2)
    except Exception:
        pass

    try:
        with path.open(encoding="utf-8") as f:
            root = yml.load(f)
    except OSError as e:
        logger.error("读取序列 YAML 失败: %s", e)
        raise

    if not isinstance(root, dict):
        return False
    steps = root.get("steps")
    if not isinstance(steps, list):
        return False

    sid = (step_id or "").strip()
    for st in steps:
        if not isinstance(st, dict):
            continue
        if str(st.get("id", "")).strip() != sid:
            continue
        st["retries"] = int(retries)
        st["retry_interval_ms"] = int(retry_interval_ms)
        st["timeout"] = int(timeout)
        st["on_failure"] = str(on_failure or "fail").lower()
        try:
            with path.open("w", encoding="utf-8") as f:
                yml.dump(root, f)
        except OSError as e:
            logger.error("写入序列 YAML 失败: %s", e)
            raise
        logger.info("已局部更新序列 YAML 步骤字段: %s id=%s", path, sid)
        return True

    logger.warning("序列 YAML 中未找到步骤 id=%s，跳过局部更新", sid)
    return False


def save_step_operational_fields_to_sequence_yaml(
    file_path: str,
    step_id: str,
    sequence: TestSequenceConfig,
    *,
    retries: int,
    retry_interval_ms: int,
    timeout: int,
    on_failure: str,
) -> None:
    """保存单步编排字段到序列文件：优先局部补丁，否则全量 ``save_test_sequence``。"""
    if patch_sequence_yaml_step_operational_fields(
        file_path,
        step_id,
        retries=retries,
        retry_interval_ms=retry_interval_ms,
        timeout=timeout,
        on_failure=on_failure,
    ):
        return
    logger.info("回退为全量保存序列: %s", file_path)
    save_test_sequence(sequence, file_path)


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
