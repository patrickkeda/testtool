"""
创建 device.json 文件测试用例

功能：
1. 从前面步骤的结果中提取数据（imei, sn）
2. 生成 device.json 文件
3. 保存到 Result/upload/${sn}/device.json
"""

from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any
import json
import os
from pathlib import Path
import re
import time


class CreateDeviceJsonStep(BaseStep):
    """创建 device.json 文件测试用例"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行创建 device.json 文件
        
        参数：
        - imei_step_id: 读取 IMEI 的步骤ID（默认 "step_4"）
        - output_dir: 输出目录（默认 "Result/upload"）
        
        从前面步骤提取的数据：
        - imei: 从读取 IMEI 的步骤响应中提取
        - sn: 从上下文获取（通过 ctx.get_sn()）
        """
        try:
            # 1) 读取参数
            imei_step_id = params.get("imei_step_id", "step_4")
            output_dir = params.get("output_dir", "Result/upload")

            # #region agent log
            try:
                with open(r"d:\b2test\TestTool-v0.4\.cursor\debug.log", "a", encoding="utf-8") as _f:
                    _f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "H2",
                        "location": "src/testcases/steps/cases/create_device_json.py:run_once",
                        "message": "enter",
                        "data": {
                            "imei_step_id": imei_step_id,
                            "output_dir": output_dir,
                            "ctx_has_state": hasattr(ctx, "state"),
                            "state_keys": list(getattr(ctx, "state", {}).keys())[:50],
                        },
                        "timestamp": int(time.time() * 1000),
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # #endregion
            
            ctx.log_info(f"开始创建 device.json 文件")
            
            # 2) 获取 SN
            sn = ctx.get_sn()
            if not sn or sn == "NULL":
                return self.create_failure_result(
                    "无法获取SN，请确保已执行扫描SN步骤",
                    error="SN为空"
                )
            
            ctx.log_info(f"获取SN: {sn}")
            
            # 3) 获取读取 IMEI 步骤的结果
            # 尝试从上下文获取步骤结果
            imei_step_result = None
            imei_step_data = {}
            
            # 尝试多种方式获取步骤结果
            try:
                # 方式1: 使用 get_result 方法（如果存在）
                if hasattr(ctx, 'get_result'):
                    imei_step_result = ctx.get_result(imei_step_id)
                    ctx.log_info(f"方式1: 通过 get_result('{imei_step_id}') 获取结果: {imei_step_result is not None}")
                else:
                    imei_step_result = None
                
                # 方式2: 尝试通过 {step_id}_result 键获取
                if not imei_step_result:
                    imei_step_result = ctx.get_data(f"{imei_step_id}_result")
                    ctx.log_info(f"方式2: 通过 '{imei_step_id}_result' 获取结果: {imei_step_result is not None}")
                
                # 方式3: 如果方式2失败，尝试直接通过 step_id 获取
                if not imei_step_result:
                    imei_step_result = ctx.get_data(imei_step_id)
                    ctx.log_info(f"方式3: 通过 '{imei_step_id}' 获取结果: {imei_step_result is not None}")
                
                # 方式4: 如果方式3也失败，尝试从 state 字典中直接查找
                if not imei_step_result and hasattr(ctx, 'state'):
                    imei_step_result = ctx.state.get(f"{imei_step_id}_result") or ctx.state.get(imei_step_id)
                    ctx.log_info(f"方式4: 从 state 字典获取结果: {imei_step_result is not None}")
                
                if imei_step_result:
                    ctx.log_info(f"获取到步骤结果类型: {type(imei_step_result)}")
                    ctx.log_info(f"步骤结果内容: {str(imei_step_result)[:1000]}")
                    
                    # 如果 imei_step_result 是 StepResult 对象，获取其 data 属性
                    if hasattr(imei_step_result, 'data'):
                        imei_step_data = imei_step_result.data or {}
                        ctx.log_info(f"从 StepResult.data 获取数据: {imei_step_data}")
                    elif isinstance(imei_step_result, dict):
                        imei_step_data = imei_step_result
                        ctx.log_info(f"步骤结果是字典，直接使用: {imei_step_data}")
                    else:
                        imei_step_data = {}
                        ctx.log_warning(f"步骤结果类型未知: {type(imei_step_result)}")
                else:
                    ctx.log_warning(f"无法获取步骤 {imei_step_id} 的结果，可用的 state 键: {list(ctx.state.keys()) if hasattr(ctx, 'state') else 'N/A'}")
            except Exception as e:
                ctx.log_warning(f"获取步骤结果时发生异常: {e}", exc_info=True)
            
            # 4) 解析 IMEI 数据
            imei = ""
            
            if imei_step_data:
                ctx.log_info(f"开始解析步骤数据，数据类型: {type(imei_step_data)}, 内容: {imei_step_data}")
                
                if isinstance(imei_step_data, dict):
                    imei = (
                        imei_step_data.get("imei", "")
                        or imei_step_data.get("imeiNumber", "")
                    )
                    ctx.log_info(f"第一次提取 imei={imei}")
                    
                    # 如果还没有找到，尝试从 response 字段中提取
                    if not imei:
                        response_obj = imei_step_data.get("response", {})
                        if isinstance(response_obj, dict):
                            if "data" in response_obj:
                                data_value = response_obj["data"]
                                if isinstance(data_value, dict):
                                    imei = data_value.get("imei", "") or data_value.get("imeiNumber", "")
                                    ctx.log_info(f"从 response.data 提取 imei={imei}")
                                elif isinstance(data_value, str):
                                    try:
                                        parsed_data = json.loads(data_value)
                                        if isinstance(parsed_data, dict):
                                            imei = parsed_data.get("imei", "") or parsed_data.get("imeiNumber", "")
                                            ctx.log_info(f"从 response.data (字符串) 提取 imei={imei}")
                                    except Exception as e:
                                        ctx.log_warning(f"解析 response.data 字符串失败: {e}")
                    
                    # 如果还没有找到，尝试从 response_data 字段中提取
                    if not imei:
                        response_data = imei_step_data.get("response_data", "")
                        if isinstance(response_data, str):
                            try:
                                parsed_data = json.loads(response_data)
                                if isinstance(parsed_data, dict):
                                    imei = parsed_data.get("imei", "") or parsed_data.get("imeiNumber", "")
                                    ctx.log_info(f"从 response_data(JSON) 提取 imei={imei}")
                            except Exception:
                                # 某些场景可能是纯字符串 IMEI，而不是 JSON
                                if response_data.strip():
                                    imei = response_data.strip()
                                    ctx.log_info(f"从 response_data(纯字符串) 提取 imei={imei}")
            
            # 如果仍然没有找到，记录警告
            if not imei:
                ctx.log_warning(f"无法从步骤结果中提取 IMEI，imei={imei}")
                ctx.log_warning(f"步骤数据完整内容: {json.dumps(imei_step_data, indent=2, ensure_ascii=False) if imei_step_data else 'None'}")
                # 使用默认值
                imei = "UNKNOWN"

            # #region agent log
            try:
                with open(r"d:\b2test\TestTool-v0.4\.cursor\debug.log", "a", encoding="utf-8") as _f:
                    _f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "H2",
                        "location": "src/testcases/steps/cases/create_device_json.py:run_once",
                        "message": "extracted imei",
                        "data": {
                            "imei": imei,
                            "imei_step_data_keys": list(imei_step_data.keys())[:50] if isinstance(imei_step_data, dict) else str(type(imei_step_data)),
                        },
                        "timestamp": int(time.time() * 1000),
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # #endregion
            
            ctx.log_info(f"提取的 IMEI: imei={imei}")
            
            # 6) 构建 JSON 数据
            device_data = [
                {
                    "snNumber": sn,
                    "imeiNumber": imei,
                    "name": f"pvt{sn}",
                    "parentId": "vbotPVTsample",
                    "deviceType": "direct",
                    "alias": f"vita-pvt-{sn}",
                    "factoryDownloadVersion": "V0.6.15-1~20260417030900",
                    "factoryInstallVersion": "V0.6.15-1~20260417030900",
                    "description": f"Vita robot pvt no.{sn}",
                    "status": "1",
                    "linkStatus": "offline"
                }
            ]
            
            # 7) 创建输出目录
            output_path = Path(output_dir) / sn
            output_path.mkdir(parents=True, exist_ok=True)
            
            # 8) 保存 JSON 文件
            json_file_path = output_path / "device.json"
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(device_data, f, ensure_ascii=False, indent=2)
            
            ctx.log_info(f"device.json 文件已创建: {json_file_path}")

            # #region agent log
            try:
                with open(r"d:\b2test\TestTool-v0.4\.cursor\debug.log", "a", encoding="utf-8") as _f:
                    _f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "H3",
                        "location": "src/testcases/steps/cases/create_device_json.py:run_once",
                        "message": "wrote device.json",
                        "data": {
                            "json_file_path": str(json_file_path),
                            "output_dir": output_dir,
                        },
                        "timestamp": int(time.time() * 1000),
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # #endregion
            
            # 9) 构建成功结果
            result_data = {
                "file_path": str(json_file_path),
                "imei": imei,
                "sn": sn,
            }
            
            return self.create_success_result(
                result_data,
                f"device.json 文件创建成功: {json_file_path}"
            )
            
        except Exception as e:
            ctx.log_error(f"创建 device.json 文件异常: {e}", exc_info=True)
            return self.create_failure_result(
                f"创建 device.json 文件异常: {e}",
                error=str(e)
            )
