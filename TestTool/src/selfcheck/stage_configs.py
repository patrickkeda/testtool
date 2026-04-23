"""
分阶段检查配置
"""

from typing import Dict, Any
from .models import CheckConfig, CheckCategory


class StageConfigs:
    """分阶段检查配置"""
    
    @staticmethod
    def get_system_startup_config() -> CheckConfig:
        """获取系统启动检查配置"""
        config = CheckConfig()
        
        # 只启用系统启动必需的检查
        config.software_environment["enabled"] = True
        config.hardware_resources["enabled"] = True
        config.logging["enabled"] = True
        
        # 禁用其他检查
        config.communication["enabled"] = False
        config.instruments["enabled"] = False
        config.config["enabled"] = False
        
        return config
    
    @staticmethod
    def get_config_completed_config() -> CheckConfig:
        """获取配置完成检查配置"""
        config = CheckConfig()
        
        # 只启用配置完成后的检查
        config.communication["enabled"] = True
        config.instruments["enabled"] = True
        
        # 禁用其他检查
        config.software_environment["enabled"] = False
        config.hardware_resources["enabled"] = False
        config.logging["enabled"] = False
        config.config["enabled"] = False
        
        return config
    
    @staticmethod
    def get_test_ready_config() -> CheckConfig:
        """获取测试前检查配置"""
        config = CheckConfig()
        
        # 只启用测试前必需的检查
        config.config["enabled"] = True
        
        # 禁用其他检查
        config.software_environment["enabled"] = False
        config.hardware_resources["enabled"] = False
        config.logging["enabled"] = False
        config.communication["enabled"] = False
        config.instruments["enabled"] = False
        
        return config
    
    @staticmethod
    def get_full_config() -> CheckConfig:
        """获取完整检查配置"""
        return CheckConfig()
    
    @staticmethod
    def get_quick_config() -> CheckConfig:
        """获取快速检查配置（仅关键项目）"""
        config = CheckConfig()
        
        # 启用关键检查
        config.software_environment["enabled"] = True
        config.hardware_resources["enabled"] = True
        
        # 简化硬件检查
        config.hardware_resources["check_memory"] = False
        config.hardware_resources["check_network"] = False
        
        # 禁用其他检查
        config.logging["enabled"] = False
        config.communication["enabled"] = False
        config.instruments["enabled"] = False
        config.config["enabled"] = False
        
        return config


class StageConfigManager:
    """阶段配置管理器"""
    
    def __init__(self):
        self.configs = {
            "system_startup": StageConfigs.get_system_startup_config(),
            "config_completed": StageConfigs.get_config_completed_config(),
            "test_ready": StageConfigs.get_test_ready_config(),
            "full": StageConfigs.get_full_config(),
            "quick": StageConfigs.get_quick_config()
        }
    
    def get_config(self, stage: str) -> CheckConfig:
        """获取指定阶段的配置"""
        return self.configs.get(stage, CheckConfig())
    
    def update_config(self, stage: str, config: CheckConfig):
        """更新指定阶段的配置"""
        self.configs[stage] = config
    
    def get_available_stages(self) -> list[str]:
        """获取可用的阶段列表"""
        return list(self.configs.keys())
    
    def get_stage_description(self, stage: str) -> str:
        """获取阶段描述"""
        descriptions = {
            "system_startup": "系统启动检查 - 检查软件环境、硬件资源、日志系统",
            "config_completed": "配置完成检查 - 检查通信接口、仪器连接",
            "test_ready": "测试前检查 - 检查配置文件完整性",
            "full": "完整检查 - 检查所有项目",
            "quick": "快速检查 - 仅检查关键项目"
        }
        return descriptions.get(stage, "未知阶段")
