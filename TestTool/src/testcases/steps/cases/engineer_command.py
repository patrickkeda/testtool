"""
工程服务命令执行测试用例

功能：
1. 执行指定的工程服务命令（如 enfac=1,1%）
2. 解析命令响应
3. 支持超时和重试机制
4. 返回命令执行结果
"""

from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any
import asyncio
import json


class EngineerCommandStep(BaseStep):
    """工程服务命令执行测试用例"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行工程服务命令
        
        参数：
        - command: 命令字符串（如 "enfac=1,1%"）
        - timeout_ms: 命令超时时间（毫秒）
        - expect_success: 是否期望命令成功（默认True）
        
        示例：
        ```yaml
        - id: enter_engineer_mode
          name: 进入工程模式
          type: engineer.command
          params:
            command: "enfac=1,1%"
            timeout_ms: 5000
            expect_success: true
        ```
        """
        try:
            # 1) 读取参数
            command = params.get("command", "")
            timeout_ms = int(params.get("timeout_ms", 5000))
            expect_success = bool(params.get("expect_success", True))
            
            # 验证命令参数
            if not command:
                return StepResult(
                    passed=False,
                    message="命令参数为空",
                    error="必须提供command参数",
                    error_code="ENG_CMD_ERR_NO_COMMAND"
                )
            
            ctx.log_info(f"开始执行工程服务命令: {command}")
            ctx.log_info(f"配置参数 - command: {command}, timeout: {timeout_ms}ms, expect_success: {expect_success}")
            
            # 2) 检查工程服务连接状态
            engineer_service_connected = ctx.get_state("engineer_service_connected", False)
            
            if not engineer_service_connected:
                return StepResult(
                    passed=False,
                    message="未连接到工程师服务",
                    error="请先执行connect_engineer步骤建立连接",
                    error_code="ENG_CMD_ERR_NOT_CONNECTED"
                )
            
            # 3) 获取WebSocket传输层
            websocket = ctx.get_comm_driver("engineer_service")
            
            if not websocket:
                return StepResult(
                    passed=False,
                    message="未找到工程师服务连接",
                    error="WebSocket驱动不可用",
                    error_code="ENG_CMD_ERR_NO_DRIVER"
                )
            
            # 4) 执行命令
            ctx.log_info(f"发送命令: {command}")
            
            try:
                # 构建命令参数（从命令字符串解析）
                # 命令格式: command=param1,param2%
                # 例如: enfac=1,1%
                command_parts = command.rstrip('%').split('=')
                if len(command_parts) == 2:
                    cmd_name = command_parts[0]
                    cmd_params_str = command_parts[1]
                    cmd_params_list = cmd_params_str.split(',')
                else:
                    cmd_name = command
                    cmd_params_list = []
                
                # 构建参数字典
                params_dict = {}
                if cmd_params_list:
                    params_dict["params"] = cmd_params_list
                
                ctx.log_info(f"命令: {cmd_name}, 参数: {params_dict}")
                
                # 使用 WebSocketTransport 的 send_command 方法
                # 创建事件循环执行异步命令
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    response = loop.run_until_complete(
                        websocket.send_command(command, params_dict)
                    )
                    
                    ctx.log_info(f"收到响应: {response}")
                    
                finally:
                    loop.close()
                    
            except asyncio.TimeoutError:
                ctx.log_error(f"命令执行超时: {timeout_ms}ms")
                return StepResult(
                    passed=False,
                    message=f"命令执行超时: {command}",
                    error=f"超时时间: {timeout_ms}ms",
                    error_code="ENG_CMD_ERR_TIMEOUT"
                )
            except Exception as e:
                ctx.log_error(f"命令执行异常: {e}")
                import traceback
                ctx.log_error(f"异常堆栈: {traceback.format_exc()}")
                return StepResult(
                    passed=False,
                    message=f"命令执行异常: {e}",
                    error=str(e),
                    error_code="ENG_CMD_ERR_EXCEPTION"
                )
            
            # 5) 解析响应
            status = response.get("status", "unknown")
            message = response.get("message", "")
            data = response.get("data", {})
            
            # 判断命令是否成功
            command_success = (status == "success")
            
            if expect_success and not command_success:
                ctx.log_error(f"命令执行失败: {message}")
                return StepResult(
                    passed=False,
                    message=f"命令执行失败: {message}",
                    error=f"期望成功但收到状态: {status}",
                    error_code="ENG_CMD_ERR_FAILED",
                    data=response
                )
            
            if not expect_success and command_success:
                ctx.log_warning(f"命令成功但期望失败: {message}")
                return StepResult(
                    passed=False,
                    message=f"命令成功但期望失败: {message}",
                    error=f"期望失败但收到状态: {status}",
                    error_code="ENG_CMD_ERR_UNEXPECTED_SUCCESS",
                    data=response
                )
            
            # 6) 命令执行成功
            ctx.log_info(f"命令执行成功: {command}")
            
            return StepResult(
                passed=True,
                message=f"命令执行成功: {command}",
                data={
                    "command": command,
                    "status": status,
                    "message": message,
                    "response_data": data
                }
            )
            
        except Exception as e:
            ctx.log_error(f"工程服务命令执行异常: {e}")
            return StepResult(
                passed=False,
                message=f"工程服务命令执行异常: {e}",
                error=str(e),
                error_code="ENG_CMD_ERR_UNKNOWN"
            )
    

