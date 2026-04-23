"""
工程师服务断开连接测试用例

功能：
1. 检查并断开与工程师服务的WebSocket连接
2. 清理连接状态和上下文
3. 支持强制断开模式
4. 更新上下文连接状态
"""

from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any


class DisconnectStep(BaseStep):
    """工程师服务断开连接测试用例"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行工程师服务断开连接测试
        
        参数示例：
        - force_disconnect: 是否强制断开连接 (默认 False)
        """
        try:
            # 1) 读取参数
            force_disconnect = bool(params.get("force_disconnect", False))
            
            ctx.log_info("开始工程师服务断开连接测试")
            ctx.log_info(f"配置参数 - force_disconnect: {force_disconnect}")
            
            # 2) 检查当前连接状态
            engineer_service_connected = ctx.get_state("engineer_service_connected", False)
            engineer_service_host = ctx.get_state("engineer_service_host", "Unknown")
            engineer_service_port = ctx.get_state("engineer_service_port", 0)
            
            ctx.log_info(f"当前连接状态: engineer_service_connected={engineer_service_connected}")
            
            if not engineer_service_connected:
                ctx.log_info("当前未连接到工程师服务")
                return StepResult(
                    passed=True,
                    message="当前未连接到工程师服务，无需断开",
                    data={"disconnected": True}
                )
            
            # 3) 获取WebSocket传输层
            websocket = ctx.get_comm_driver("engineer_service")
            
            if not websocket:
                ctx.log_warning("未找到工程师服务连接")
                # 清理状态
                ctx.set_state("engineer_service_connected", False)
                ctx.remove_comm_driver("engineer_service")
                
                return StepResult(
                    passed=True,
                    message="未找到工程师服务连接，已清理状态",
                    data={"disconnected": True}
                )
            
            # 检查连接状态
            try:
                is_open = websocket.is_open() if hasattr(websocket, 'is_open') else True
                ctx.log_info(f"WebSocket连接状态检查: is_open={is_open}")
            except Exception as e:
                ctx.log_warning(f"无法检查WebSocket状态: {e}")
                is_open = True  # 假设仍处于连接状态
            
            # 4) 断开工程师服务连接
            ctx.log_info(f"正在断开工程师服务连接: {engineer_service_host}:{engineer_service_port}")
            
            try:
                # 关闭WebSocket连接
                websocket.close()
                ctx.log_info("websocket.close() 调用完成")
                success = True
            except Exception as e:
                ctx.log_error(f"断开连接时出现异常: {e}")
                if force_disconnect:
                    ctx.log_info("强制断开模式，忽略异常并继续")
                    success = True
                else:
                    success = False
            
            if not success:
                ctx.log_error("无法断开工程师服务连接")
                return StepResult(
                    passed=False,
                    message="工程师服务断开连接失败",
                    error="无法断开工程师服务连接",
                    error_code="DISCONN_ERR_CLOSE_FAILED"
                )
            
            ctx.log_info("WebSocket连接已关闭")
            
            # 5) 清理连接状态
            ctx.set_state("engineer_service_connected", False)
            ctx.remove_state("engineer_service_host")
            ctx.remove_state("engineer_service_port")
            ctx.remove_comm_driver("engineer_service")
            
            ctx.log_info(f"工程师服务断开连接成功: {engineer_service_host}:{engineer_service_port}")
            
            return StepResult(
                passed=True,
                message=f"工程师服务断开连接成功: {engineer_service_host}:{engineer_service_port}",
                data={
                    "host": engineer_service_host,
                    "port": engineer_service_port,
                    "disconnected": True
                }
            )
            
        except Exception as e:
            ctx.log_error(f"工程师服务断开连接异常: {e}")
            return StepResult(
                passed=False,
                message=f"工程师服务断开连接异常: {e}",
                error=str(e),
                error_code="DISCONN_ERR_UNKNOWN"
            )