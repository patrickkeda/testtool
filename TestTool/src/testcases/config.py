"""
测试序列配置模型
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List, Union, Literal
from datetime import datetime


class TestMetadata(BaseModel):
    """测试序列元数据"""
    name: Optional[str] = Field(None, description="测试序列名称")
    description: str = Field("", description="测试序列描述")
    author: str = Field("TestTool", description="作者")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="创建时间")
    product: str = Field("", description="产品型号")
    station: str = Field("", description="测试站")
    version: str = Field("1.0", description="版本")


class ExpectConfig(BaseModel):
    """期望结果配置 - 仅用于测量值判定
    
    判断逻辑：
    1. 先判断测试步骤返回的状态（Pass/Fail）
    2. 再判断测量值是否在上下限范围内（如果配置了上下限）
    3. 如果未配置上下限，仅判断状态
    """
    
    unit: Optional[str] = Field(None, description="单位")
    low: Optional[float] = Field(None, description="下限")
    high: Optional[float] = Field(None, description="上限") 
    precision: Optional[int] = Field(None, description="显示小数位")
    compare_mode: Literal["inclusive"] = Field("inclusive", description="比较模式（固定为两端闭合）")


class ATExpectConfig(BaseModel):
    """AT指令期望结果配置"""
    response_type: Literal["ok", "range", "regex", "exact", "custom"] = Field(..., description="响应类型")
    expected_value: Optional[str] = Field(None, description="期望值（exact类型）")
    min_value: Optional[float] = Field(None, description="最小值（range类型）")
    max_value: Optional[float] = Field(None, description="最大值（range类型）")
    regex_pattern: Optional[str] = Field(None, description="正则表达式（regex类型）")
    data_extraction: Optional[Dict[str, str]] = Field(None, description="数据提取规则")
    custom_validator: Optional[str] = Field(None, description="自定义验证器")


class StateControlConfig(BaseModel):
    """状态控制配置"""
    type: str = Field(..., description="控制类型")
    at_command: str = Field(..., description="AT指令")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="控制参数")
    stabilization_time: int = Field(1000, description="稳定时间(ms)")


class MeasurementConfig(BaseModel):
    """测量配置"""
    type: str = Field(..., description="测量类型")
    channel: int = Field(1, description="测量通道")
    range: str = Field("auto", description="测量范围")
    samples: int = Field(1, description="采样次数")
    expect: Optional[Dict[str, Any]] = Field(None, description="期望结果")


class JudgmentConfig(BaseModel):
    """判断配置"""
    type: Literal["simple", "multi_choice", "rating", "custom"] = Field(..., description="判断类型")
    options: Optional[List[Dict[str, str]]] = Field(None, description="判断选项")
    min_rating: Optional[int] = Field(None, description="最小评分")
    max_rating: Optional[int] = Field(None, description="最大评分")


class ATCommandStepConfig(BaseModel):
    """AT指令步骤配置"""
    id: str = Field(..., description="步骤ID")
    name: str = Field(..., description="步骤名称")
    type: Literal["at.command", "at.query", "at.control"] = Field(..., description="步骤类型")
    command: str = Field(..., description="AT指令")
    timeout: int = Field(5000, description="超时时间(ms)")
    retries: int = Field(0, description="重试次数")
    expect: Optional[ATExpectConfig] = Field(None, description="期望结果配置")
    on_failure: str = Field("fail", description="失败策略")


class StateMeasurementStepConfig(BaseModel):
    """状态切换+测量步骤配置"""
    id: str = Field(..., description="步骤ID")
    name: str = Field(..., description="步骤名称")
    type: Literal["state_measurement", "at.led_test", "at.speaker_test", "at.motor_test"] = Field(..., description="步骤类型")
    state_control: StateControlConfig = Field(..., description="状态控制配置")
    measurements: List[MeasurementConfig] = Field(..., description="测量配置列表")
    pass_conditions: List[str] = Field(..., description="通过条件列表")
    timeout: int = Field(5000, description="超时时间(ms)")
    retries: int = Field(2, description="重试次数")
    on_failure: str = Field("fail", description="失败策略")


class ManualJudgmentStepConfig(BaseModel):
    """人工判断步骤配置"""
    id: str = Field(..., description="步骤ID")
    name: str = Field(..., description="步骤名称")
    type: Literal["manual_judgment", "at.manual_display_test", "at.manual_led_test", "at.manual_audio_test"] = Field(..., description="步骤类型")
    state_control: StateControlConfig = Field(..., description="状态控制配置")
    test_description: str = Field(..., description="测试描述")
    test_instructions: List[str] = Field(..., description="测试指导")
    judgment_config: JudgmentConfig = Field(..., description="判断配置")
    timeout: int = Field(30000, description="超时时间(ms)")
    retries: int = Field(0, description="重试次数")
    on_failure: str = Field("fail", description="失败策略")


class TestStepConfig(BaseModel):
    """测试步骤配置"""
    id: str = Field(..., description="步骤ID")
    name: str = Field(..., description="步骤名称")
    type: str = Field(..., description="步骤类型: comm.*, instrument.*, uut.*, mes.*, utility.*, at.*, state_measurement, manual_judgment")
    params: Dict[str, Any] = Field(default_factory=dict, description="步骤参数")
    timeout: Optional[int] = Field(None, description="超时时间(ms)")
    retries: int = Field(0, description="重试次数")
    condition: Optional[str] = Field(None, description="执行条件表达式")
    expect: Optional[Union[ExpectConfig, ATExpectConfig]] = Field(None, description="期望结果配置")
    on_failure: str = Field("fail", description="失败策略: fail, skip, retry, continue")
    
    # 新增字段支持三种测试模式
    at_config: Optional[ATCommandStepConfig] = Field(None, description="AT指令配置")
    state_measurement_config: Optional[StateMeasurementStepConfig] = Field(None, description="状态测量配置")
    manual_judgment_config: Optional[ManualJudgmentStepConfig] = Field(None, description="人工判断配置")
    
    @classmethod
    def from_yaml_data(cls, data: Dict[str, Any]) -> 'TestStepConfig':
        """从YAML数据创建TestStepConfig实例"""
        # 提取基础字段
        base_data = {
            "id": data.get("id", ""),
            "name": data.get("name", ""),
            "type": data.get("type", ""),
            "params": data.get("params", {}),
            "timeout": data.get("timeout"),
            "retries": data.get("retries", 0),
            "condition": data.get("condition"),
            "on_failure": data.get("on_failure", "fail")
        }
        
        # 处理期望结果配置
        if "expect" in data:
            if isinstance(data["expect"], dict):
                if "response_type" in data["expect"]:
                    # AT指令期望配置
                    base_data["expect"] = ATExpectConfig(**data["expect"])
                else:
                    # 传统期望配置
                    base_data["expect"] = ExpectConfig(**data["expect"])
        
        # 处理AT指令配置
        if "at_config" in data and data["at_config"]:
            at_data = data["at_config"].copy()
            # 确保AT配置有必需的字段
            if "id" not in at_data:
                at_data["id"] = base_data["id"]
            if "name" not in at_data:
                at_data["name"] = base_data["name"]
            if "type" not in at_data:
                at_data["type"] = base_data["type"]
            base_data["at_config"] = ATCommandStepConfig(**at_data)
        
        # 处理状态测量配置
        if "state_measurement_config" in data and data["state_measurement_config"]:
            sm_data = data["state_measurement_config"].copy()
            if "id" not in sm_data:
                sm_data["id"] = base_data["id"]
            if "name" not in sm_data:
                sm_data["name"] = base_data["name"]
            if "type" not in sm_data:
                sm_data["type"] = base_data["type"]
            base_data["state_measurement_config"] = StateMeasurementStepConfig(**sm_data)
        
        # 处理人工判断配置
        if "manual_judgment_config" in data and data["manual_judgment_config"]:
            mj_data = data["manual_judgment_config"].copy()
            if "id" not in mj_data:
                mj_data["id"] = base_data["id"]
            if "name" not in mj_data:
                mj_data["name"] = base_data["name"]
            if "type" not in mj_data:
                mj_data["type"] = base_data["type"]
            base_data["manual_judgment_config"] = ManualJudgmentStepConfig(**mj_data)
        
        return cls(**base_data)


class TestSequenceConfig(BaseModel):
    """测试序列配置"""
    version: str = Field("1.0", description="配置版本")
    metadata: TestMetadata = Field(default_factory=TestMetadata, description="元数据")
    variables: Dict[str, Any] = Field(default_factory=dict, description="测试变量")
    steps: List[TestStepConfig] = Field(default_factory=list, description="测试步骤列表")
    timeout: Optional[int] = Field(None, description="全局超时时间(ms)")
    retries: int = Field(0, description="全局重试次数")
    on_failure: str = Field("stop", description="全局失败策略: stop, continue, retry")
    
    @classmethod
    def from_yaml_data(cls, data: Dict[str, Any]) -> 'TestSequenceConfig':
        """从YAML数据创建TestSequenceConfig实例"""
        # 处理元数据
        metadata_data = data.get("metadata", {})
        metadata = TestMetadata(**metadata_data)
        
        # 处理步骤
        steps_data = data.get("steps", [])
        steps = []
        for step_data in steps_data:
            step = TestStepConfig.from_yaml_data(step_data)
            steps.append(step)
        
        return cls(
            version=data.get("version", "1.0"),
            metadata=metadata,
            variables=data.get("variables", {}),
            steps=steps,
            timeout=data.get("timeout"),
            retries=data.get("retries", 0),
            on_failure=data.get("on_failure", "stop")
        )
    
    def get_step_by_id(self, step_id: str) -> Optional[TestStepConfig]:
        """根据ID获取步骤配置"""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None
    
    def get_steps_by_type(self, step_type: str) -> List[TestStepConfig]:
        """根据类型获取步骤配置列表"""
        return [step for step in self.steps if step.type.startswith(step_type)]
    
    def validate(self) -> List[str]:
        """验证配置有效性"""
        errors = []
        
        # 检查步骤ID唯一性
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            errors.append("步骤ID必须唯一")
        
        # 检查步骤类型（包括别名）
        from .registry import get_registry
        try:
            registry = get_registry()
            # 获取所有已注册的步骤类型和别名
            valid_types = list(registry.list_step_types())
            aliases = registry.list_aliases()
            valid_types.extend(aliases.keys())
        except Exception:
            # 如果注册表不可用，使用硬编码的列表
            valid_types = ["comm.", "instrument.", "uut.", "mes.", "utility.", "at.", "state_measurement", "manual_judgment", "scan.", "measure.", "case.", "connect_engineer", "disconnect_engineer"]
        
        for step in self.steps:
            # 检查是否是已注册的类型或别名
            is_valid = False
            # 先检查是否是完整的类型匹配（包括别名）
            if step.type in valid_types:
                is_valid = True
            else:
                # 再检查是否匹配前缀
                for valid_type in valid_types:
                    if step.type.startswith(valid_type) or valid_type.startswith(step.type.split('.')[0] + '.'):
                        is_valid = True
                        break
            
            if not is_valid:
                errors.append(f"步骤 {step.id} 的类型 {step.type} 无效")
        
        # 检查期望结果配置
        for step in self.steps:
            if step.expect:
                if hasattr(step.expect, 'type') and step.expect.type == "range" and (step.expect.min_val is None or step.expect.max_val is None):
                    errors.append(f"步骤 {step.id} 的范围验证缺少最小值或最大值")
                elif hasattr(step.expect, 'type') and step.expect.type == "regex" and not step.expect.regex:
                    errors.append(f"步骤 {step.id} 的正则验证缺少正则表达式")
                elif hasattr(step.expect, 'response_type') and step.expect.response_type == "range" and (step.expect.min_value is None or step.expect.max_value is None):
                    errors.append(f"步骤 {step.id} 的AT范围验证缺少最小值或最大值")
                elif hasattr(step.expect, 'response_type') and step.expect.response_type == "regex" and not step.expect.regex_pattern:
                    errors.append(f"步骤 {step.id} 的AT正则验证缺少正则表达式")
        
        # 检查AT指令配置
        for step in self.steps:
            if step.type.startswith("at.") and step.at_config:
                if not step.at_config.command:
                    errors.append(f"步骤 {step.id} 的AT指令不能为空")
                if step.at_config.timeout <= 0:
                    errors.append(f"步骤 {step.id} 的AT超时时间必须大于0")
        
        # 检查状态测量配置
        for step in self.steps:
            if step.type in ["state_measurement", "at.led_test", "at.speaker_test", "at.motor_test"] and step.state_measurement_config:
                if not step.state_measurement_config.state_control.at_command:
                    errors.append(f"步骤 {step.id} 的状态控制AT指令不能为空")
                if not step.state_measurement_config.measurements:
                    errors.append(f"步骤 {step.id} 的测量配置不能为空")
                if not step.state_measurement_config.pass_conditions:
                    errors.append(f"步骤 {step.id} 的通过条件不能为空")
        
        # 检查人工判断配置
        for step in self.steps:
            if step.type in ["manual_judgment", "at.manual_display_test", "at.manual_led_test", "at.manual_audio_test"] and step.manual_judgment_config:
                if not step.manual_judgment_config.state_control.at_command:
                    errors.append(f"步骤 {step.id} 的状态控制AT指令不能为空")
                if not step.manual_judgment_config.test_description:
                    errors.append(f"步骤 {step.id} 的测试描述不能为空")
                if not step.manual_judgment_config.test_instructions:
                    errors.append(f"步骤 {step.id} 的测试指导不能为空")
                if not step.manual_judgment_config.judgment_config:
                    errors.append(f"步骤 {step.id} 的判断配置不能为空")
        
        return errors
