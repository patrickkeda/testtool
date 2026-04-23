"""
AT指令步骤实现
"""

import asyncio
import re
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from ..step import BaseStep, StepResult
from ..config import ATCommandStepConfig, ATExpectConfig
from ..context import TestContext

logger = logging.getLogger(__name__)


class ATCommunicator:
    """AT指令通信器"""
    
    def __init__(self, comm_manager):
        self.comm_manager = comm_manager
        
    async def send_command(self, command: str, port: str = "A", timeout: float = 5.0) -> str:
        """发送AT指令并接收响应
        
        Parameters
        ----------
        command : str
            AT指令
        port : str
            通信端口
        timeout : float
            超时时间
            
        Returns
        -------
        str
            响应内容
        """
        try:
            # 获取通信传输层
            transport = self.comm_manager.get_transport(port)
            if not transport:
                raise RuntimeError(f"端口 {port} 未连接")
            
            # 发送命令
            success = await transport.send(command.encode('utf-8'), timeout)
            if not success:
                raise RuntimeError("命令发送失败")
            
            # 接收响应
            response = await transport.receive(timeout)
            response_str = response.decode('utf-8', errors='ignore').strip()
            
            logger.debug(f"AT指令: {command} -> 响应: {response_str}")
            return response_str
            
        except Exception as e:
            logger.error(f"AT指令通信失败: {e}")
            raise


class ATResponseValidator:
    """AT响应验证器"""
    
    def validate_response(self, response: str, expect_config: ATExpectConfig) -> Dict[str, Any]:
        """验证AT指令响应
        
        Parameters
        ----------
        response : str
            响应内容
        expect_config : ATExpectConfig
            期望配置
            
        Returns
        -------
        Dict[str, Any]
            验证结果
        """
        result = {
            "passed": False,
            "extracted_data": {},
            "error_message": ""
        }
        
        try:
            if expect_config.response_type == "ok":
                # 简单OK验证
                if "ok" in response.lower():
                    result["passed"] = True
                else:
                    result["error_message"] = f"期望响应包含'ok'，实际响应: {response}"
                    
            elif expect_config.response_type == "exact":
                # 精确匹配验证
                if response == expect_config.expected_value:
                    result["passed"] = True
                else:
                    result["error_message"] = f"期望响应: {expect_config.expected_value}，实际响应: {response}"
                    
            elif expect_config.response_type == "range":
                # 数值范围验证
                if expect_config.data_extraction:
                    # 提取数值
                    extracted_value = self._extract_value(response, expect_config.data_extraction)
                    if extracted_value is not None:
                        if expect_config.min_value <= extracted_value <= expect_config.max_value:
                            result["passed"] = True
                            result["extracted_data"]["value"] = extracted_value
                        else:
                            result["error_message"] = f"数值 {extracted_value} 超出范围 [{expect_config.min_value}, {expect_config.max_value}]"
                    else:
                        result["error_message"] = "无法从响应中提取数值"
                else:
                    result["error_message"] = "范围验证需要数据提取规则"
                    
            elif expect_config.response_type == "regex":
                # 正则表达式验证
                if expect_config.regex_pattern:
                    if re.match(expect_config.regex_pattern, response):
                        result["passed"] = True
                        # 提取数据
                        if expect_config.data_extraction:
                            result["extracted_data"] = self._extract_data_with_regex(response, expect_config.data_extraction)
                    else:
                        result["error_message"] = f"响应不匹配正则表达式: {expect_config.regex_pattern}"
                else:
                    result["error_message"] = "正则验证需要正则表达式"
                    
            elif expect_config.response_type == "custom":
                # 自定义验证
                if expect_config.custom_validator:
                    # 这里可以扩展自定义验证逻辑
                    result["error_message"] = "自定义验证器暂未实现"
                else:
                    result["error_message"] = "自定义验证需要验证器名称"
            else:
                result["error_message"] = f"不支持的响应类型: {expect_config.response_type}"
                
        except Exception as e:
            result["error_message"] = f"验证过程出错: {e}"
            
        return result
    
    def _extract_value(self, response: str, extraction_rules: Dict[str, str]) -> Optional[float]:
        """从响应中提取数值
        
        Parameters
        ----------
        response : str
            响应内容
        extraction_rules : Dict[str, str]
            提取规则
            
        Returns
        -------
        Optional[float]
            提取的数值
        """
        try:
            # 查找第一个数值提取规则
            for key, pattern in extraction_rules.items():
                if pattern.startswith("regex:"):
                    regex_pattern = pattern[6:]  # 去掉"regex:"前缀
                    match = re.search(regex_pattern, response)
                    if match:
                        # 尝试提取第一个捕获组
                        if match.groups():
                            return float(match.group(1))
                        else:
                            return float(match.group(0))
                else:
                    # 简单的字符串匹配
                    if pattern in response:
                        # 尝试从响应中提取数值
                        numbers = re.findall(r'-?\d+\.?\d*', response)
                        if numbers:
                            return float(numbers[0])
            return None
        except (ValueError, IndexError):
            return None
    
    def _extract_data_with_regex(self, response: str, extraction_rules: Dict[str, str]) -> Dict[str, Any]:
        """使用正则表达式提取数据
        
        Parameters
        ----------
        response : str
            响应内容
        extraction_rules : Dict[str, str]
            提取规则
            
        Returns
        -------
        Dict[str, Any]
            提取的数据
        """
        extracted_data = {}
        
        for key, pattern in extraction_rules.items():
            if pattern.startswith("regex:"):
                regex_pattern = pattern[6:]  # 去掉"regex:"前缀
                match = re.search(regex_pattern, response)
                if match:
                    if match.groups():
                        # 使用第一个捕获组
                        extracted_data[key] = match.group(1)
                    else:
                        # 使用整个匹配
                        extracted_data[key] = match.group(0)
                else:
                    extracted_data[key] = None
            else:
                # 简单的字符串匹配
                extracted_data[key] = pattern if pattern in response else None
                
        return extracted_data


class ATCommandStep(BaseStep):
    """AT指令步骤"""
    
    def __init__(self, step_id: str, step_name: str, params: Dict[str, Any]):
        super().__init__(step_id, step_name, params)
        self.at_comm = None
        self.validator = ATResponseValidator()
        
    async def prepare(self, context: TestContext) -> bool:
        """准备AT指令步骤"""
        if not await super().prepare(context):
            return False
            
        # 初始化AT通信器
        self.at_comm = ATCommunicator(context.comm_manager)
        
        # 检查必要参数
        if not self.get_param("command"):
            self.log_error("AT指令不能为空")
            return False
            
        return True
    
    async def execute(self, context: TestContext) -> StepResult:
        """执行AT指令步骤"""
        try:
            command = self.get_param("command")
            port = self.get_param("port", "A")
            timeout = self.get_param("timeout", 5.0)
            expect_config = self.get_param("expect")
            
            # 发送AT指令
            response = await self.at_comm.send_command(command, port, timeout)
            
            # 验证响应
            validation_result = None
            if expect_config:
                validation_result = self.validator.validate_response(response, expect_config)
                if not validation_result["passed"]:
                    return self.create_result(
                        success=False,
                        value=response,
                        message=f"AT指令响应验证失败: {validation_result['error_message']}",
                        metadata={"validation_result": validation_result}
                    )
            
            # 提取数据
            extracted_data = validation_result.get("extracted_data", {}) if validation_result else {}
            
            return self.create_result(
                success=True,
                value=response,
                message="AT指令执行成功",
                metadata={
                    "response": response,
                    "extracted_data": extracted_data,
                    "validation_result": validation_result
                }
            )
            
        except Exception as e:
            self.log_error(f"AT指令执行失败: {e}", e)
            return self.create_result(
                success=False,
                error=str(e),
                message="AT指令执行失败"
            )
    
    async def validate(self, result: StepResult, expect: ATExpectConfig) -> bool:
        """验证AT指令结果"""
        if not result.success:
            return False
            
        validation_result = self.validator.validate_response(result.value, expect)
        return validation_result["passed"]
    
    async def cleanup(self, context: TestContext):
        """清理AT指令步骤"""
        await super().cleanup(context)


def create_at_step(step_config) -> ATCommandStep:
    """创建AT指令步骤实例
    
    Parameters
    ----------
    step_config : TestStepConfig
        步骤配置
        
    Returns
    -------
    ATCommandStep
        AT指令步骤实例
    """
    # 从配置中提取参数
    params = {
        "command": step_config.at_config.command if step_config.at_config else step_config.params.get("command", ""),
        "port": step_config.params.get("port", "A"),
        "timeout": step_config.at_config.timeout if step_config.at_config else step_config.params.get("timeout", 5.0),
        "expect": step_config.at_config.expect if step_config.at_config else step_config.expect
    }
    
    return ATCommandStep(
        step_id=step_config.id,
        step_name=step_config.name,
        params=params
    )
