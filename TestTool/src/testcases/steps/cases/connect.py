"""
工程师服务连接测试用例

功能：
1. 建立与工程师服务的WebSocket连接
2. 验证连接状态
3. 进入工程模式
4. 保存连接状态到测试上下文
"""

from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any
import asyncio


class ConnectStep(BaseStep):
    """工程师服务连接测试用例"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行工程师服务连接测试
        
        参数优先级：params > config.yaml
        - host: 主机地址，从 config.yaml 的 ports.{port}.uut.tcp.host 读取
        - port: 端口号，从 config.yaml 的 ports.{port}.uut.tcp.port 读取
        - timeout_ms: 连接超时时间，从 config.yaml 的 ports.{port}.uut.tcp.timeout_ms 读取
        - x5_soc_id: X5 SOC ID (可选，从params传入)
        - s100_soc_id: S100 SOC ID (可选，从params传入)
        """
        try:
            # 1) 从上下文获取配置信息（从端口配置读取）
            port_config = ctx.get_port_config() if hasattr(ctx, 'get_port_config') else {}
            
            # 2) 读取参数，优先从端口配置读取
            # 工程师服务的TCP配置在 uut.tcp 下
            uut_config = port_config.get("uut", {})
            tcp_config = uut_config.get("tcp", {})
            
            # 从配置文件中读取主机地址、端口和超时
            host = params.get("host") or tcp_config.get("host", "")
            port = int(params.get("port") or tcp_config.get("port", 3579))
            timeout_ms = int(params.get("timeout_ms") or tcp_config.get("timeout_ms", 30000))
            
            # SOC IDs从params中读取（不在配置文件中）
            #x5_soc_id = params.get("x5_soc_id", "")
            #s100_soc_id = params.get("s100_soc_id", "")
            
            # 验证必要参数
            if not host:
                return StepResult(
                    passed=False,
                    message="主机地址未配置",
                    error="主机地址未配置，请在端口配置中设置TCP host",
                    error_code="CONN_ERR_NO_HOST"
                )
            
            ctx.log_info(f"开始工程师服务连接测试: {host}:{port}")
            ctx.log_info(f"配置参数 - host: {host}, port: {port}, timeout: {timeout_ms}ms")
            
            # 3) 创建WebSocket传输层
            from src.drivers.comm.websocket_transport import WebSocketTransport
            
            websocket = WebSocketTransport(
                host=host,
                port=port,
                connection_timeout_ms=timeout_ms,
                #x5_soc_id=x5_soc_id,
                #s100_soc_id=s100_soc_id
            )
            
            # 4) 建立连接
            ctx.log_info(f"正在连接工程师服务: {host}:{port}")
            
            try:
                websocket.open()
                ctx.log_info("websocket.open() 调用完成")
            except Exception as e:
                ctx.log_error(f"连接失败: {e}")
                return StepResult(
                    passed=False,
                    message="工程师服务连接失败",
                    error=str(e),
                    error_code="CONN_ERR_CONNECT_FAILED"
                )
            
            # 检查连接状态
            is_open = websocket.is_open()
            ctx.log_info(f"连接状态检查: is_open={is_open}")
            
            if not is_open:
                ctx.log_error("WebSocket连接未建立")
                return StepResult(
                    passed=False,
                    message="工程师服务连接失败",
                    error="WebSocket连接未建立",
                    error_code="CONN_ERR_NOT_OPEN"
                )
            
            ctx.log_info("WebSocket连接已建立")
            
            # 5) 进入工程模式
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    response = loop.run_until_complete(websocket.send_command("ENTER_ENGINEER_MODE"))
                    if response.get("status") != "success":
                        return StepResult(
                            passed=False,
                            message=f"进入工程模式失败: {response.get('message', 'unknown')}",
                            error=response.get('message', 'unknown'),
                            error_code="CONN_ERR_ENTER_ENGINEER_MODE_FAILED"
                        )
                finally:
                    loop.close()
            except Exception as e:
                ctx.log_error(f"进入工程模式异常: {e}")
                return StepResult(
                    passed=False,
                    message=f"进入工程模式失败: {e}",
                    error=str(e),
                    error_code="CONN_ERR_ENTER_ENGINEER_MODE_EXCEPTION"
                )
            
            ctx.log_info("已进入工程模式")
            
            # 6) 保存连接状态到上下文
            ctx.set_comm_driver("engineer_service", websocket)
            ctx.set_state("engineer_service_connected", True)
            ctx.set_state("engineer_service_host", host)
            ctx.set_state("engineer_service_port", port)
            
            ctx.log_info(f"工程师服务连接成功: {host}:{port}")
            
            return StepResult(
                passed=True,
                message=f"工程师服务连接成功: {host}:{port}",
                data={
                    "host": host,
                    "port": port,
                    "connected": True
                }
            )
            
        except Exception as e:
            ctx.log_error(f"工程师服务连接异常: {e}")
            return StepResult(
                passed=False,
                message=f"工程师服务连接异常: {e}",
                error=str(e),
                error_code="CONN_ERR_UNKNOWN"
            )