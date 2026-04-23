"""
命令管理器
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from .interfaces import ICommandManager
from .models import UUTCommand, UUTConfig

logger = logging.getLogger(__name__)


class CommandManager(ICommandManager):
    """命令管理器实现"""
    
    def __init__(self):
        self.commands: Dict[str, UUTCommand] = {}
        self.command_history: List[UUTCommand] = []
        self.max_history = 1000  # 最大历史记录数
        
    async def load_commands(self, config: UUTConfig) -> None:
        """加载命令配置
        
        Parameters
        ----------
        config : UUTConfig
            UUT配置
        """
        try:
            # 清空现有命令
            self.commands.clear()
            
            # 加载配置中的命令
            for command in config.commands:
                self.commands[command.name] = command
                logger.debug(f"加载命令: {command.name}")
            
            # 添加默认命令
            await self._add_default_commands()
            
            logger.info(f"命令加载完成，共 {len(self.commands)} 个命令")
            
        except Exception as e:
            logger.error(f"命令加载失败: {e}")
            raise
    
    async def get_command(self, name: str) -> Optional[UUTCommand]:
        """获取命令
        
        Parameters
        ----------
        name : str
            命令名称
            
        Returns
        -------
        Optional[UUTCommand]
            命令对象
        """
        return self.commands.get(name)
    
    async def add_command(self, command: UUTCommand) -> None:
        """添加命令
        
        Parameters
        ----------
        command : UUTCommand
            命令对象
        """
        try:
            # 验证命令
            if not command.name:
                raise ValueError("命令名称不能为空")
            if not command.command:
                raise ValueError("命令内容不能为空")
            
            # 添加命令
            self.commands[command.name] = command
            logger.info(f"添加命令: {command.name}")
            
        except Exception as e:
            logger.error(f"添加命令失败: {e}")
            raise
    
    async def remove_command(self, name: str) -> bool:
        """删除命令
        
        Parameters
        ----------
        name : str
            命令名称
            
        Returns
        -------
        bool
            是否删除成功
        """
        try:
            if name in self.commands:
                del self.commands[name]
                logger.info(f"删除命令: {name}")
                return True
            else:
                logger.warning(f"命令不存在: {name}")
                return False
                
        except Exception as e:
            logger.error(f"删除命令失败: {e}")
            return False
    
    async def list_commands(self) -> List[str]:
        """列出所有命令名称
        
        Returns
        -------
        List[str]
            命令名称列表
        """
        return list(self.commands.keys())
    
    async def execute_command(self, name: str, parameters: Optional[Dict] = None) -> UUTCommand:
        """执行命令（创建命令实例）
        
        Parameters
        ----------
        name : str
            命令名称
        parameters : Optional[Dict]
            命令参数
            
        Returns
        -------
        UUTCommand
            命令实例
        """
        try:
            # 获取命令模板
            template = await self.get_command(name)
            if not template:
                raise ValueError(f"命令不存在: {name}")
            
            # 创建命令实例
            command = UUTCommand(
                name=template.name,
                command=template.command,
                parameters=parameters or template.parameters.copy(),
                timeout=template.timeout,
                retries=template.retries,
                response_format=template.response_format,
                expected_response=template.expected_response,
                metadata=template.metadata.copy()
            )
            
            # 记录命令历史
            await self._record_command(command)
            
            return command
            
        except Exception as e:
            logger.error(f"执行命令失败: {e}")
            raise
    
    async def get_command_info(self, name: str) -> Optional[Dict]:
        """获取命令信息
        
        Parameters
        ----------
        name : str
            命令名称
            
        Returns
        -------
        Optional[Dict]
            命令信息
        """
        command = await self.get_command(name)
        if not command:
            return None
        
        return {
            "name": command.name,
            "command": command.command,
            "timeout": command.timeout,
            "retries": command.retries,
            "response_format": command.response_format,
            "parameters": command.parameters,
            "metadata": command.metadata
        }
    
    async def update_command(self, name: str, updates: Dict) -> bool:
        """更新命令
        
        Parameters
        ----------
        name : str
            命令名称
        updates : Dict
            更新内容
            
        Returns
        -------
        bool
            是否更新成功
        """
        try:
            command = await self.get_command(name)
            if not command:
                return False
            
            # 更新命令属性
            for key, value in updates.items():
                if hasattr(command, key):
                    setattr(command, key, value)
            
            logger.info(f"更新命令: {name}")
            return True
            
        except Exception as e:
            logger.error(f"更新命令失败: {e}")
            return False
    
    async def get_command_history(self, limit: Optional[int] = None) -> List[UUTCommand]:
        """获取命令历史
        
        Parameters
        ----------
        limit : Optional[int]
            限制数量
            
        Returns
        -------
        List[UUTCommand]
            命令历史列表
        """
        if limit is None:
            return self.command_history.copy()
        else:
            return self.command_history[-limit:]
    
    async def clear_history(self) -> None:
        """清空命令历史"""
        self.command_history.clear()
        logger.info("命令历史已清空")
    
    async def search_commands(self, keyword: str) -> List[str]:
        """搜索命令
        
        Parameters
        ----------
        keyword : str
            搜索关键词
            
        Returns
        -------
        List[str]
            匹配的命令名称列表
        """
        results = []
        keyword_lower = keyword.lower()
        
        for name, command in self.commands.items():
            if (keyword_lower in name.lower() or 
                keyword_lower in command.command.lower()):
                results.append(name)
        
        return results
    
    async def _add_default_commands(self) -> None:
        """添加默认命令"""
        default_commands = [
            UUTCommand(
                name="identify",
                command="*IDN?",
                timeout=2000,
                retries=2,
                response_format="string",
                metadata={"description": "设备识别", "category": "system"}
            ),
            UUTCommand(
                name="reset",
                command="*RST",
                timeout=5000,
                retries=1,
                response_format="string",
                metadata={"description": "设备重置", "category": "system"}
            ),
            UUTCommand(
                name="status",
                command="*STB?",
                timeout=1000,
                retries=2,
                response_format="int",
                metadata={"description": "状态查询", "category": "system"}
            ),
            UUTCommand(
                name="error",
                command="SYST:ERR?",
                timeout=1000,
                retries=2,
                response_format="string",
                metadata={"description": "错误查询", "category": "system"}
            )
        ]
        
        for command in default_commands:
            if command.name not in self.commands:
                self.commands[command.name] = command
                logger.debug(f"添加默认命令: {command.name}")
    
    async def _record_command(self, command: UUTCommand) -> None:
        """记录命令到历史"""
        self.command_history.append(command)
        
        # 限制历史记录数量
        if len(self.command_history) > self.max_history:
            self.command_history = self.command_history[-self.max_history:]
    
    async def get_statistics(self) -> Dict:
        """获取命令统计信息
        
        Returns
        -------
        Dict
            统计信息
        """
        return {
            "total_commands": len(self.commands),
            "history_count": len(self.command_history),
            "command_categories": self._get_categories(),
            "most_used_commands": self._get_most_used_commands()
        }
    
    def _get_categories(self) -> Dict[str, int]:
        """获取命令分类统计"""
        categories = {}
        for command in self.commands.values():
            category = command.metadata.get("category", "unknown")
            categories[category] = categories.get(category, 0) + 1
        return categories
    
    def _get_most_used_commands(self) -> List[Dict]:
        """获取最常用的命令"""
        # 简单的使用频率统计（基于历史记录）
        command_usage = {}
        for command in self.command_history:
            name = command.name
            command_usage[name] = command_usage.get(name, 0) + 1
        
        # 按使用次数排序
        sorted_commands = sorted(command_usage.items(), key=lambda x: x[1], reverse=True)
        
        return [{"name": name, "count": count} for name, count in sorted_commands[:10]]
