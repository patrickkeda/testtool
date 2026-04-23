"""
工程师测试步骤 - 直接调用 engineer test client

功能：
1. 使用 client/vita_engineer_client 执行测试
2. 自动管理连接和断开
3. 解析测试结果
4. 支持所有 test_engineer_client.py 的测试用例
"""

from ...base import BaseStep, StepResult
from ...context import Context
from ..utility.version_payload import normalize_version_payload
from typing import Dict, Any
import asyncio
import sys
import os
import json
import time
from pathlib import Path
from types import MethodType


class EngineerTestStep(BaseStep):
    """工程师测试步骤 - 调用 test_engineer_client.py"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行工程师测试
        
        参数：
        - test_case: 测试用例名称 (如 "light", "battery", "version" 等)
        - robot_ip: 机器人IP地址 (默认 "192.168.125.2")
        - port: 端口 (默认 3579)
        - timeout: 超时时间(秒) (默认 30)
        - command: 完整命令（可选，如 "enfac=1,1%"，优先于 test_case）
        
        示例1 - 使用测试用例名:
        ```yaml
        - id: test_light
          type: engineer.test
          params:
            test_case: "light"
            robot_ip: "192.168.125.2"
        ```
        
        示例2 - 使用完整命令:
        ```yaml
        - id: enter_engineer
          type: engineer.test
          params:
            command: "enfac=1,1%"
            robot_ip: "192.168.125.2"
        ```
        """
        try:
            # 1) 读取参数
            test_case = params.get("test_case", "")
            command = params.get("command", "")
            robot_ip = self._resolve_str_param(params.get("robot_ip", "192.168.125.2"), ctx)
            port = self._resolve_int_param(params.get("port", 3579), ctx, default=3579)
            # 默认超时时间改为 180 秒，与 test_engineer_client.py 中的 _send_command 默认超时一致
            # 这样可以避免外层超时（asyncio.wait_for）比内层 HTTP 请求超时短导致的连接中断问题
            timeout = self._resolve_int_param(params.get("timeout", 180), ctx, default=180)
            skip_log_response = params.get("skip_log_response", False)  # 是否跳过日志记录响应
            
            # 优先使用 command，如果没有则使用 test_case
            if command:
                # 替换命令中的变量
                command = self._replace_variables(command, ctx)
                test_arg = command
                ctx.log_info(f"开始执行工程命令测试: {command}")
                
                # 对于某些需要长时间执行的命令，自动调整超时时间
                # 这些命令可能需要 60 秒以上的执行时间
                long_running_commands = ['sensorcal', 'servo', 'motor_ota', 'transfer']
                command_name = command.split('=')[0] if '=' in command else command.split('%')[0]
                if any(cmd in command_name for cmd in long_running_commands):
                    if timeout < 180:
                        ctx.log_info(f"检测到长时间运行的命令 '{command_name}'，自动将超时时间从 {timeout} 秒调整为 180 秒")
                        timeout = 180
                # 检查是否是 testinfo=1,calib,1% 命令，如果是则自动跳过日志记录
                if "testinfo=1,calib,1%" in command:
                    skip_log_response = True
                    ctx.log_info("检测到 testinfo=1,calib,1% 命令，将跳过响应日志记录")
            elif test_case:
                test_arg = test_case
                ctx.log_info(f"开始执行工程测试用例: {test_case}")
            else:
                return StepResult(
                    passed=False,
                    message="未指定测试用例或命令",
                    error="必须提供 test_case 或 command 参数",
                    error_code="ENG_TEST_ERR_NO_TEST"
                )
            
            ctx.log_info(f"目标机器人: {robot_ip}:{port}, 超时: {timeout}秒")
            
            # 2) 查找 test_engineer_client.py 路径
            # 处理打包环境和开发环境的路径差异
            if getattr(sys, 'frozen', False):
                # 打包环境：使用 exe 所在目录
                exe_dir = Path(sys.executable).parent
                # 尝试多个可能的路径
                possible_paths = [
                    exe_dir / "_internal" / "client" / "vita_engineer_client" / "test_engineer_client.py",
                    exe_dir / "client" / "vita_engineer_client" / "test_engineer_client.py",
                    exe_dir.parent / "client" / "vita_engineer_client" / "test_engineer_client.py",
                ]
            else:
                # 开发环境：从当前文件向上查找项目根目录
                current_file = Path(__file__)
                project_root = current_file.parent.parent.parent.parent.parent  # 到达项目根目录
                possible_paths = [
                    project_root / "client" / "vita_engineer_client" / "test_engineer_client.py",
                    Path("client/vita_engineer_client/test_engineer_client.py"),
                ]
            
            client_path = None
            for path in possible_paths:
                if path.exists():
                    client_path = path
                    break
            
            if not client_path:
                ctx.log_error(f"找不到 test_engineer_client.py，已尝试的路径: {possible_paths}")
                return StepResult(
                    passed=False,
                    message="找不到工程测试客户端",
                    error=f"路径不存在，已尝试: {[str(p) for p in possible_paths]}",
                    error_code="ENG_TEST_ERR_CLIENT_NOT_FOUND"
                )
            
            ctx.log_info(f"使用测试客户端: {client_path}")
            
            # 3) 导入并运行测试
            try:
                # 将工程客户端目录加入 Python 路径
                pkg_dir = client_path.parent          # client/vita_engineer_client
                root_dir = pkg_dir.parent            # client
                for path in (str(root_dir), str(pkg_dir)):
                    if path not in sys.path:
                        sys.path.insert(0, path)
                
                # 导入测试函数和必要的模块
                from vita_engineer_client.test_engineer_client import (
                    command_handler, parser
                )
                from vita_engineer_client.engineer_client import EngineerServiceClient

                ctx.log_info(f"执行测试: {test_arg} @ {robot_ip}:{port}")
                
                # 创建事件循环并运行测试，同时捕获 JSON 响应
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                json_response = None
                try:
                    # 直接调用底层函数以获取 JSON 响应
                    async def execute_with_json_capture():
                        nonlocal json_response
                        async with EngineerServiceClient(host=robot_ip, port=port) as client:
                            try:
                                # 解析测试用例
                                test_params = parser.parse_test_case(test_arg)
                                
                                # 保存原始的 _send_command 方法
                                original_send_command = command_handler._send_command
                                
                                # 创建包装函数来捕获 JSON 响应
                                # 注意：新的 API 中 _send_command 的签名是: async def _send_command(self, client, command, timeout=180.0)
                                # 使用外层传入的 timeout 参数，确保超时时间一致
                                # 从外层作用域获取 timeout 值，并确保内层超时比外层超时短 5 秒，避免外层先超时
                                #
                                # 重要：部分特殊命令处理器（如 uwb）会以关键字参数形式调用：
                                # command_handler._send_command(client, command, timeout=timeout)
                                # 因此包装函数必须能接收 timeout 关键字参数；加 **kwargs 以兼容未来扩展。
                                outer_timeout = max(float(timeout), 180.0)
                                async def wrapped_send_command(self, client, command, timeout=180.0, **kwargs):
                                    # 使用外层传入的 timeout（至少 180s），确保内外层超时时间一致
                                    # 内层超时应比外层超时短 5 秒，这样可以先触发内层超时，返回更清晰的错误信息
                                    # 如果调用方传入了更短的 timeout（例如 uwb 某些 op），尊重该值，但不超过外层超时 - 5 秒
                                    inner_timeout = max(min(float(timeout), float(outer_timeout) - 5.0), 10.0)  # 至少 10 秒
                                    # 调用原始方法（original_send_command 已经是绑定方法，不需要 self）
                                    response_str = await original_send_command(client, command, timeout=inner_timeout)
                                    nonlocal json_response
                                    json_response = response_str
                                    
                                    # 检查响应大小，如果太大则跳过 JSON 格式化（避免阻塞）
                                    try:
                                        response = json.loads(response_str)
                                        data_size = 0
                                        if "data" in response:
                                            data_value = response["data"]
                                            if isinstance(data_value, str):
                                                data_size = len(data_value)
                                            elif isinstance(data_value, (dict, list)):
                                                # 估算大小
                                                data_size = len(str(data_value))
                                        
                                        # 如果数据超过 1MB，跳过 JSON 格式化（避免阻塞主线程）
                                        if data_size > 1024 * 1024:
                                            ctx.log_info(f"工程测试返回的响应: 数据大小约 {data_size / (1024 * 1024):.2f} MB，跳过 JSON 格式化以避免阻塞")
                                        elif not skip_log_response:
                                            # 格式化 JSON 以便阅读（小数据才格式化）
                                            formatted_json = json.dumps(response, indent=2, ensure_ascii=False)
                                            ctx.log_info(f"工程测试返回的 JSON 响应:\n{formatted_json}")
                                        else:
                                            ctx.log_info("已跳过响应日志记录（skip_log_response=True）")
                                    except Exception as e:
                                        # 如果解析失败，只记录基本信息
                                        if not skip_log_response:
                                            ctx.log_info(f"工程测试返回的响应 (无法解析 JSON): {str(e)[:200]}")
                                        else:
                                            ctx.log_info("已跳过响应日志记录（skip_log_response=True）")
                                    
                                    return response_str
                                
                                # 使用 MethodType 创建绑定方法，确保 self 正确传递
                                command_handler._send_command = MethodType(wrapped_send_command, command_handler)
                                
                                try:
                                    # 创建一个自定义的 stdout 包装器，将输出同时发送到原始 stdout 和日志
                                    class LoggingStdout:
                                        def __init__(self, original_stdout, logger_func):
                                            self.original_stdout = original_stdout
                                            self.logger_func = logger_func
                                            self.buffer = ""
                                        
                                        def write(self, text):
                                            # 写入原始 stdout（如果存在且可用）
                                            if self.original_stdout is not None:
                                                try:
                                                    self.original_stdout.write(text)
                                                    if hasattr(self.original_stdout, 'flush'):
                                                        self.original_stdout.flush()
                                                except (AttributeError, OSError, ValueError):
                                                    # 如果 stdout 不可用，忽略错误
                                                    pass
                                            
                                            # 累积到缓冲区
                                            self.buffer += text
                                            
                                            # 如果遇到换行符，记录到日志
                                            if '\n' in self.buffer:
                                                lines = self.buffer.split('\n')
                                                # 保留最后一行（可能不完整）
                                                self.buffer = lines[-1]
                                                # 记录完整的行
                                                for line in lines[:-1]:
                                                    if line.strip():
                                                        try:
                                                            self.logger_func(line.strip())
                                                        except Exception:
                                                            # 如果日志记录失败，继续执行
                                                            pass
                                        
                                        def flush(self):
                                            # 刷新原始 stdout（如果存在且可用）
                                            if self.original_stdout is not None and hasattr(self.original_stdout, 'flush'):
                                                try:
                                                    self.original_stdout.flush()
                                                except (AttributeError, OSError, ValueError):
                                                    # 如果 stdout 不可用，忽略错误
                                                    pass
                                            
                                            # 如果有剩余内容，也记录
                                            if self.buffer.strip():
                                                try:
                                                    self.logger_func(self.buffer.strip())
                                                    self.buffer = ""
                                                except Exception:
                                                    # 如果日志记录失败，继续执行
                                                    self.buffer = ""
                                    
                                    # 保存原始 stdout（确保不为 None）
                                    original_stdout = sys.stdout
                                    if original_stdout is None:
                                        # 如果原始 stdout 为 None，尝试创建一个默认的
                                        try:
                                            import io
                                            original_stdout = io.TextIOWrapper(io.BufferedWriter(io.FileIO(1, 'w')))
                                        except Exception:
                                            # 如果创建失败，使用一个安全的占位符
                                            class NullStdout:
                                                def write(self, text): pass
                                                def flush(self): pass
                                            original_stdout = NullStdout()
                                    
                                    # 创建日志包装器
                                    logging_stdout = LoggingStdout(original_stdout, ctx.log_info)
                                    
                                    # 临时替换 stdout
                                    sys.stdout = logging_stdout
                                    
                                    try:
                                        # 使用 execute_command 执行测试（它会处理所有情况，包括特殊处理器）
                                        result = await command_handler.execute_command(client, test_params)
                                        return result
                                    finally:
                                        # 恢复原始的 stdout（确保总是能恢复）
                                        try:
                                            # 确保所有输出都被记录
                                            if sys.stdout is not None:
                                                try:
                                                    sys.stdout.flush()
                                                except (AttributeError, OSError, ValueError):
                                                    pass
                                        except Exception:
                                            pass
                                        finally:
                                            # 无论如何都要恢复原始的 stdout
                                            sys.stdout = original_stdout
                                finally:
                                    # 恢复原始的 _send_command 方法
                                    command_handler._send_command = original_send_command
                                    
                            except ValueError as e:
                                ctx.log_error(f"参数解析失败: {e}")
                                return False
                            except Exception as e:
                                ctx.log_error(f"测试执行异常: {e}")
                                import traceback
                                ctx.log_error(f"异常堆栈: {traceback.format_exc()}")
                                return False
                    
                    # 确保超时时间足够长，至少 180 秒（与 HTTP 客户端默认超时一致）
                    # 如果用户设置的超时时间太短，自动调整为 180 秒
                    effective_timeout = max(float(timeout), 180.0)
                    if timeout < 180:
                        ctx.log_warning(f"超时时间 {timeout} 秒可能太短，已自动调整为 {effective_timeout} 秒以避免连接中断")
                    
                    result = loop.run_until_complete(
                        asyncio.wait_for(
                            execute_with_json_capture(),
                            timeout=effective_timeout
                        )
                    )
                    
                    ctx.log_info(f"测试执行完成: 结果={result}")
                
                finally:
                    loop.close()
                
                # 4) 处理结果
                # 构建结果数据，包含响应信息
                result_data = {
                    "test_case": test_case or command,
                    "robot_ip": robot_ip,
                    "port": port,
                    "result": "success"
                }
                
                # 如果捕获到了 JSON 响应，尝试解析并存储
                if json_response:
                    try:
                        response_obj = json.loads(json_response)
                        normalized_version = None
                        if command_name == "version" or test_arg == "version":
                            normalized_version = normalize_version_payload(response_obj)

                        if normalized_version is not None:
                            result_data.update(normalized_version)
                            result_data["response"] = response_obj
                        # 如果响应包含 data 字段，将其合并到结果数据中
                        elif "data" in response_obj:
                            data_value = response_obj["data"]
                            if isinstance(data_value, dict):
                                # 直接合并字典数据（如 x5, s100 等）
                                result_data.update(data_value)
                            elif isinstance(data_value, str):
                                # 尝试解析字符串形式的 JSON
                                try:
                                    parsed_data = json.loads(data_value)
                                    if isinstance(parsed_data, dict):
                                        result_data.update(parsed_data)
                                except:
                                    result_data["response_data"] = data_value
                        else:
                            # 如果没有 data 字段，直接存储整个响应
                            result_data["response"] = response_obj
                    except Exception as e:
                        ctx.log_warning(f"解析 JSON 响应失败: {e}")
                        result_data["raw_response"] = json_response[:500]  # 只存储前500字符
                
                if result:
                    return StepResult(
                        passed=True,
                        message=f"工程测试通过: {test_arg}",
                        data=result_data
                    )
                else:
                    return StepResult(
                        passed=False,
                        message=f"工程测试失败: {test_arg}",
                        error="测试执行失败",
                        error_code="ENG_TEST_ERR_TEST_FAILED",
                        data={
                            "test_case": test_case or command,
                            "robot_ip": robot_ip,
                            "port": port,
                            "result": "failed"
                        }
                    )
                    
            except asyncio.TimeoutError:
                ctx.log_error(f"测试超时: {timeout}秒")
                return StepResult(
                    passed=False,
                    message=f"工程测试超时: {test_arg}",
                    error=f"超时时间: {timeout}秒",
                    error_code="ENG_TEST_ERR_TIMEOUT"
                )
            except ImportError as e:
                ctx.log_error(f"导入测试客户端失败: {e}")
                return StepResult(
                    passed=False,
                    message="无法导入工程测试客户端",
                    error=str(e),
                    error_code="ENG_TEST_ERR_IMPORT_FAILED"
                )
            except Exception as e:
                ctx.log_error(f"测试执行异常: {e}")
                import traceback
                ctx.log_error(f"异常堆栈: {traceback.format_exc()}")
                return StepResult(
                    passed=False,
                    message=f"工程测试异常: {e}",
                    error=str(e),
                    error_code="ENG_TEST_ERR_EXCEPTION"
                )
                
        except Exception as e:
            ctx.log_error(f"工程测试步骤异常: {e}")
            import traceback
            ctx.log_error(f"异常堆栈: {traceback.format_exc()}")
            return StepResult(
                passed=False,
                message=f"工程测试步骤异常: {e}",
                error=str(e),
                error_code="ENG_TEST_ERR_UNKNOWN"
            )
    
    def _replace_variables(self, text: str, ctx: Context) -> str:
        """
        替换文本中的变量引用
        
        支持的变量格式:
        - ${sn} - 产品序列号
        - ${sn_last9} - 产品序列号后 9 位（不足 9 位则取全部）
        - ${port} - 测试端口
        - ${context.key} - 上下文中的任意键值
        
        Args:
            text: 原始文本
            ctx: 测试上下文
            
        Returns:
            str: 替换后的文本
        """
        import re
        
        # 查找所有 ${...} 格式的变量
        pattern = r'\$\{([^}]+)\}'
        
        def replace_var(match):
            var_name = match.group(1)
            
            # 特殊变量处理
            if var_name == "sn":
                value = ctx.get_sn()
                ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                return value
            elif var_name == "sn_last9":
                full = ctx.get_sn() or ""
                value = full[-9:]
                ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                return value
            elif var_name == "port":
                return ctx.port
            elif var_name.startswith("context."):
                # 从上下文状态获取
                key = var_name[8:]  # 去掉 "context." 前缀
                value = ctx.get_data(key, "")
                ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                return str(value)
            else:
                # 尝试从上下文状态直接获取
                value = ctx.get_data(var_name, "")
                if value:
                    ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                    return str(value)
                else:
                    ctx.log_warning(f"未找到变量: ${{{var_name}}}")
                    return match.group(0)  # 保持原样
        
        result = re.sub(pattern, replace_var, text)
        return result

    def _resolve_str_param(self, value: Any, ctx: Context) -> str:
        """解析字符串参数并进行变量替换"""
        if isinstance(value, str):
            return self._replace_variables(value, ctx)
        return str(value)

    def _resolve_int_param(self, value: Any, ctx: Context, default: int = 0) -> int:
        """解析整数参数，支持变量替换"""
        try:
            if isinstance(value, str):
                value = self._replace_variables(value, ctx)
            return int(value)
        except (ValueError, TypeError):
            ctx.log_warning(f"整数参数解析失败，使用默认值 {default}")
            return default

