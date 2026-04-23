"""
变量管理器 - 管理测试过程中的变量和表达式解析
"""

from typing import Dict, Any, Callable, Optional
import re
import logging

logger = logging.getLogger(__name__)


class VariableManager:
    """变量管理器"""
    
    def __init__(self):
        self.variables = {}
        self.functions = {}
        
    def set_variable(self, name: str, value: Any):
        """设置变量
        
        Parameters
        ----------
        name : str
            变量名
        value : Any
            变量值
        """
        self.variables[name] = value
        logger.debug(f"设置变量 {name} = {value}")
        
    def get_variable(self, name: str) -> Any:
        """获取变量
        
        Parameters
        ----------
        name : str
            变量名
            
        Returns
        -------
        Any
            变量值，如果不存在返回None
        """
        return self.variables.get(name)
        
    def has_variable(self, name: str) -> bool:
        """检查变量是否存在
        
        Parameters
        ----------
        name : str
            变量名
            
        Returns
        -------
        bool
            变量是否存在
        """
        return name in self.variables
        
    def remove_variable(self, name: str) -> bool:
        """删除变量
        
        Parameters
        ----------
        name : str
            变量名
            
        Returns
        -------
        bool
            是否删除成功
        """
        if name in self.variables:
            del self.variables[name]
            logger.debug(f"删除变量 {name}")
            return True
        return False
        
    def clear_variables(self):
        """清空所有变量"""
        self.variables.clear()
        logger.debug("清空所有变量")
        
    def get_all_variables(self) -> Dict[str, Any]:
        """获取所有变量"""
        return self.variables.copy()
        
    def register_function(self, name: str, func: Callable):
        """注册函数
        
        Parameters
        ----------
        name : str
            函数名
        func : Callable
            函数对象
        """
        self.functions[name] = func
        logger.debug(f"注册函数 {name}")
        
    def get_function(self, name: str) -> Optional[Callable]:
        """获取函数
        
        Parameters
        ----------
        name : str
            函数名
            
        Returns
        -------
        Optional[Callable]
            函数对象，如果不存在返回None
        """
        return self.functions.get(name)
        
    def resolve_expression(self, expression: str) -> Any:
        """解析表达式
        
        Parameters
        ----------
        expression : str
            表达式
            
        Returns
        -------
        Any
            解析后的值
        """
        if not isinstance(expression, str):
            return expression
            
        # 处理变量替换 ${variable}
        pattern = r'\$\{([^}]+)\}'
        matches = re.findall(pattern, expression)
        
        result = expression
        for match in matches:
            value = self._resolve_variable(match)
            result = result.replace(f"${{{match}}}", str(value))
            
        # 尝试转换为数字
        try:
            if "." in result:
                return float(result)
            else:
                return int(result)
        except ValueError:
            return result
            
    def _resolve_variable(self, var_name: str) -> Any:
        """解析变量名
        
        Parameters
        ----------
        var_name : str
            变量名
            
        Returns
        -------
        Any
            变量值
        """
        # 支持嵌套变量解析
        if "." in var_name:
            parts = var_name.split(".")
            if len(parts) >= 2:
                # 处理嵌套变量，如 work_order.voltage
                base_var = parts[0]
                if base_var in self.variables:
                    value = self.variables[base_var]
                    for part in parts[1:]:
                        if isinstance(value, dict) and part in value:
                            value = value[part]
                        else:
                            return f"${{{var_name}}}"  # 无法解析，返回原表达式
                    return value
                    
        return self.variables.get(var_name, f"${{{var_name}}}")
        
    def evaluate_condition(self, condition: str) -> bool:
        """评估条件表达式
        
        Parameters
        ----------
        condition : str
            条件表达式
            
        Returns
        -------
        bool
            条件是否成立
        """
        try:
            # 简单的条件表达式评估
            # 支持基本的比较操作：==, !=, <, >, <=, >=
            # 支持逻辑操作：and, or, not
            
            # 替换变量
            resolved_condition = self.resolve_expression(condition)
            
            # 安全的表达式评估（只允许基本的比较和逻辑操作）
            allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-*/()<>=!&| ")
            if not all(c in allowed_chars for c in resolved_condition):
                logger.error(f"条件表达式包含不允许的字符: {condition}")
                return False
                
            # 替换逻辑操作符
            resolved_condition = resolved_condition.replace(" and ", " and ")
            resolved_condition = resolved_condition.replace(" or ", " or ")
            resolved_condition = resolved_condition.replace(" not ", " not ")
            
            # 评估表达式
            result = eval(resolved_condition, {"__builtins__": {}}, self.variables)
            return bool(result)
            
        except Exception as e:
            logger.error(f"条件表达式评估失败: {condition}, 错误: {e}")
            return False
            
    def set_variables_from_dict(self, variables: Dict[str, Any]):
        """从字典设置变量
        
        Parameters
        ----------
        variables : Dict[str, Any]
            变量字典
        """
        for key, value in variables.items():
            self.set_variable(key, value)
            
    def merge_variables(self, other_manager: 'VariableManager'):
        """合并另一个变量管理器的变量
        
        Parameters
        ----------
        other_manager : VariableManager
            另一个变量管理器
        """
        for key, value in other_manager.get_all_variables().items():
            self.set_variable(key, value)


# 全局变量管理器实例
_global_variable_manager = VariableManager()


def get_variable_manager() -> VariableManager:
    """获取全局变量管理器实例"""
    return _global_variable_manager


def set_variable(name: str, value: Any):
    """设置变量（便捷函数）"""
    _global_variable_manager.set_variable(name, value)


def get_variable(name: str) -> Any:
    """获取变量（便捷函数）"""
    return _global_variable_manager.get_variable(name)


def resolve_expression(expression: str) -> Any:
    """解析表达式（便捷函数）"""
    return _global_variable_manager.resolve_expression(expression)
