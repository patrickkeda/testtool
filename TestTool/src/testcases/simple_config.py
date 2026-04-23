"""
简化的测试序列配置模型

按照新架构设计，测试序列只包含核心编排参数，业务逻辑在 testcases 模块中实现。
"""
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime


class TestMetadata(BaseModel):
    """测试序列元数据"""
    name: str = Field("", description="测试序列名称")
    description: str = Field("", description="测试序列描述")
    author: str = Field("TestTool", description="作者")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="创建时间")
    product: str = Field("", description="产品型号")
    station: str = Field("", description="测试站")
    version: str = Field("1.0", description="版本")


class TestStepConfig(BaseModel):
    """
    简化的测试步骤配置
    
    只包含编排相关的参数：
    - id: 步骤唯一标识
    - name: 步骤显示名称
    - type: 步骤类型（用于注册表查找）
    - timeout: 超时时间（秒）
    - retries: 重试次数
    - on_failure: 失败策略
    - params: 业务参数（由具体步骤类使用）
    """
    id: str = Field(..., description="步骤唯一标识")
    name: str = Field(..., description="步骤显示名称")
    type: str = Field(..., description="步骤类型（用于注册表查找）")
    timeout: int = Field(30, description="超时时间（秒）")
    retries: int = Field(0, description="重试次数")
    on_failure: str = Field("fail", description="失败策略: fail/continue/stop_port/stop_all")
    params: Dict[str, Any] = Field(default_factory=dict, description="业务参数")
    
    def validate_params(self) -> List[str]:
        """验证参数有效性（子类可重写）"""
        errors = []
        
        # 基本验证
        if not self.id.strip():
            errors.append("步骤ID不能为空")
        
        if not self.name.strip():
            errors.append("步骤名称不能为空")
        
        if not self.type.strip():
            errors.append("步骤类型不能为空")
        
        if self.timeout <= 0:
            errors.append("超时时间必须大于0")
        
        if self.retries < 0:
            errors.append("重试次数不能为负数")
        
        valid_failure_strategies = ["fail", "continue", "stop_port", "stop_all"]
        if self.on_failure not in valid_failure_strategies:
            errors.append(f"失败策略必须是: {', '.join(valid_failure_strategies)}")
        
        return errors


class TestSequenceConfig(BaseModel):
    """
    简化的测试序列配置
    
    只包含编排相关的参数，设备连接信息在端口配置中。
    """
    version: str = Field("1.0", description="配置版本")
    metadata: TestMetadata = Field(default_factory=TestMetadata, description="元数据")
    steps: List[TestStepConfig] = Field(default_factory=list, description="测试步骤列表")
    
    def get_step_by_id(self, step_id: str) -> Optional[TestStepConfig]:
        """根据ID获取步骤配置"""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None
    
    def get_steps_by_type(self, step_type: str) -> List[TestStepConfig]:
        """根据类型获取步骤配置列表"""
        return [step for step in self.steps if step.type == step_type]
    
    def validate(self) -> List[str]:
        """验证配置有效性"""
        errors = []
        
        # 检查步骤ID唯一性
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            errors.append("步骤ID必须唯一")
        
        # 验证每个步骤
        for i, step in enumerate(self.steps):
            step_errors = step.validate_params()
            for error in step_errors:
                errors.append(f"步骤 {i+1} ({step.id}): {error}")
        
        return errors
    
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
            step = TestStepConfig(**step_data)
            steps.append(step)
        
        return cls(
            version=data.get("version", "1.0"),
            metadata=metadata,
            steps=steps
        )
    
    def to_yaml_data(self) -> Dict[str, Any]:
        """转换为YAML数据格式"""
        return {
            "version": self.version,
            "metadata": self.metadata.model_dump(),
            "steps": [step.model_dump() for step in self.steps]
        }
