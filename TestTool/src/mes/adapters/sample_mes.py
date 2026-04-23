"""
示例MES适配器实现
"""

import asyncio
import logging
from typing import Any, Dict, Optional
from datetime import datetime

from .base import MESAdapter
from ..models import WorkOrder, TestResult, MESResponse, MESConfig, WorkOrderStatus

logger = logging.getLogger(__name__)


class SampleMESAdapter(MESAdapter):
    """示例MES适配器实现"""
    
    def __init__(self):
        super().__init__("sample_mes")
        # 模拟数据存储
        self._work_orders = self._init_sample_work_orders()
        self._products = self._init_sample_products()
        self._auth_tokens = {}
    
    def _init_sample_work_orders(self) -> Dict[str, Dict[str, Any]]:
        """初始化示例工单数据"""
        return {
            "SN001": {
                "work_order": "WO2024001",
                "product_number": "ABC-1000",
                "revision": "Rev-A",
                "batch": "B2024001",
                "quantity": 100,
                "station_id": "FT-1",
                "status": "ACTIVE",
                "parameters": {
                    "voltage": 3.3,
                    "current_limit": 0.5,
                    "test_timeout": 30
                },
                "created_at": "2024-01-15T08:00:00Z",
                "description": "示例产品测试工单"
            },
            "SN002": {
                "work_order": "WO2024002", 
                "product_number": "ABC-2000",
                "revision": "Rev-B",
                "batch": "B2024002",
                "quantity": 50,
                "station_id": "FT-2",
                "status": "ACTIVE",
                "parameters": {
                    "voltage": 5.0,
                    "current_limit": 1.0,
                    "test_timeout": 45
                },
                "created_at": "2024-01-15T09:00:00Z",
                "description": "示例产品测试工单2"
            }
        }
    
    def _init_sample_products(self) -> Dict[str, Dict[str, Any]]:
        """初始化示例产品数据"""
        return {
            "ABC-1000": {
                "product_number": "ABC-1000",
                "name": "示例产品A",
                "parameters": {
                    "voltage": 3.3,
                    "current_limit": 0.5,
                    "test_timeout": 30,
                    "temperature_range": [-10, 60],
                    "humidity_range": [10, 90]
                },
                "test_sequence": "ft1_abc1000.yaml",
                "description": "示例产品A规格"
            },
            "ABC-2000": {
                "product_number": "ABC-2000",
                "name": "示例产品B",
                "parameters": {
                    "voltage": 5.0,
                    "current_limit": 1.0,
                    "test_timeout": 45,
                    "temperature_range": [-20, 70],
                    "humidity_range": [5, 95]
                },
                "test_sequence": "ft1_abc2000.yaml",
                "description": "示例产品B规格"
            }
        }
    
    async def authenticate(self, config: MESConfig) -> MESResponse:
        """认证适配器"""
        try:
            self._log_request("POST", "authenticate", {"vendor": self.vendor})
            
            # 模拟认证延迟
            await asyncio.sleep(0.1)
            
            # 检查凭据
            client_id = config.credentials.get("client_id", "")
            client_secret = (
                config.credentials.get("client_secret", "")
                or config.credentials.get("client_secret_enc", "")
            )
            
            if not client_id or not client_secret:
                return self._create_error_response("缺少认证凭据", "AUTH_MISSING_CREDENTIALS", 401)
            
            # 模拟认证成功
            token = f"token_{client_id}_{int(datetime.now().timestamp())}"
            self._auth_tokens[client_id] = {
                "token": token,
                "expires_at": datetime.now().timestamp() + 3600  # 1小时过期
            }
            
            response = self._create_success_response(
                data={"token": token, "expires_in": 3600},
                message="认证成功"
            )
            
            self._log_response(response)
            return response
            
        except Exception as e:
            self.logger.error(f"认证异常: {e}")
            return self._create_error_response(f"认证异常: {e}", "AUTH_EXCEPTION", 500)
    
    async def get_work_order(self, config: MESConfig, sn: str) -> MESResponse:
        """获取工单适配器"""
        try:
            self._log_request("GET", "get_work_order", {"sn": sn})
            
            # 模拟网络延迟
            await asyncio.sleep(0.05)
            
            # 检查认证
            if not self._check_auth(config):
                return self._create_error_response("未认证或认证已过期", "AUTH_REQUIRED", 401)
            
            # 查找工单
            work_order_data = self._work_orders.get(sn)
            if not work_order_data:
                return self._create_error_response(f"工单不存在: {sn}", "WORK_ORDER_NOT_FOUND", 404)
            
            response = self._create_success_response(
                data=work_order_data,
                message="获取工单成功"
            )
            
            self._log_response(response)
            return response
            
        except Exception as e:
            self.logger.error(f"获取工单异常: {e}")
            return self._create_error_response(f"获取工单异常: {e}", "GET_WORK_ORDER_EXCEPTION", 500)
    
    async def upload_result(self, config: MESConfig, test_result: TestResult) -> MESResponse:
        """上传结果适配器"""
        try:
            self._log_request("POST", "upload_result", {"sn": test_result.sn})
            
            # 模拟网络延迟
            await asyncio.sleep(0.1)
            
            # 检查认证
            if not self._check_auth(config):
                return self._create_error_response("未认证或认证已过期", "AUTH_REQUIRED", 401)
            
            # 验证测试结果
            if not test_result.sn:
                return self._create_error_response("产品序列号不能为空", "INVALID_SN", 400)
            
            if not test_result.work_order:
                return self._create_error_response("工单号不能为空", "INVALID_WORK_ORDER", 400)
            
            # 模拟上传成功
            upload_id = f"upload_{test_result.sn}_{int(datetime.now().timestamp())}"
            
            response = self._create_success_response(
                data={
                    "upload_id": upload_id,
                    "sn": test_result.sn,
                    "result": test_result.overall_result.value,
                    "uploaded_at": datetime.now().isoformat()
                },
                message="上传测试结果成功"
            )
            
            self._log_response(response)
            return response
            
        except Exception as e:
            self.logger.error(f"上传结果异常: {e}")
            return self._create_error_response(f"上传结果异常: {e}", "UPLOAD_RESULT_EXCEPTION", 500)
    
    async def heartbeat(self, config: MESConfig) -> MESResponse:
        """心跳适配器"""
        try:
            self._log_request("GET", "heartbeat")
            
            # 模拟网络延迟
            await asyncio.sleep(0.02)
            
            # 检查认证
            if not self._check_auth(config):
                return self._create_error_response("未认证或认证已过期", "AUTH_REQUIRED", 401)
            
            response = self._create_success_response(
                data={
                    "status": "alive",
                    "timestamp": datetime.now().isoformat(),
                    "vendor": self.vendor
                },
                message="心跳成功"
            )
            
            self._log_response(response)
            return response
            
        except Exception as e:
            self.logger.error(f"心跳异常: {e}")
            return self._create_error_response(f"心跳异常: {e}", "HEARTBEAT_EXCEPTION", 500)
    
    async def get_product_params(self, config: MESConfig, product_number: str) -> MESResponse:
        """获取产品参数适配器"""
        try:
            self._log_request("GET", "get_product_params", {"product_number": product_number})
            
            # 模拟网络延迟
            await asyncio.sleep(0.03)
            
            # 检查认证
            if not self._check_auth(config):
                return self._create_error_response("未认证或认证已过期", "AUTH_REQUIRED", 401)
            
            # 查找产品
            product_data = self._products.get(product_number)
            if not product_data:
                return self._create_error_response(f"产品不存在: {product_number}", "PRODUCT_NOT_FOUND", 404)
            
            response = self._create_success_response(
                data=product_data,
                message="获取产品参数成功"
            )
            
            self._log_response(response)
            return response
            
        except Exception as e:
            self.logger.error(f"获取产品参数异常: {e}")
            return self._create_error_response(f"获取产品参数异常: {e}", "GET_PRODUCT_PARAMS_EXCEPTION", 500)
    
    def parse_work_order(self, response_data: Any) -> Optional[WorkOrder]:
        """解析工单数据"""
        try:
            if not response_data:
                return None
            
            # 解析工单数据
            work_order = WorkOrder(
                work_order=response_data.get("work_order", ""),
                product_number=response_data.get("product_number", ""),
                revision=response_data.get("revision", ""),
                batch=response_data.get("batch", ""),
                quantity=response_data.get("quantity", 0),
                station_id=response_data.get("station_id", ""),
                status=WorkOrderStatus(response_data.get("status", "ACTIVE")),
                parameters=response_data.get("parameters", {}),
                description=response_data.get("description", "")
            )
            
            # 解析时间
            if "created_at" in response_data:
                work_order.created_at = datetime.fromisoformat(response_data["created_at"].replace("Z", "+00:00"))
            if "updated_at" in response_data:
                work_order.updated_at = datetime.fromisoformat(response_data["updated_at"].replace("Z", "+00:00"))
            
            return work_order
            
        except Exception as e:
            self.logger.error(f"解析工单数据异常: {e}")
            return None
    
    def parse_product_params(self, response_data: Any) -> Dict[str, Any]:
        """解析产品参数"""
        try:
            if not response_data:
                return {}
            
            return response_data.get("parameters", {})
            
        except Exception as e:
            self.logger.error(f"解析产品参数异常: {e}")
            return {}
    
    def _check_auth(self, config: MESConfig) -> bool:
        """检查认证状态"""
        client_id = config.credentials.get("client_id", "")
        if not client_id or client_id not in self._auth_tokens:
            return False
        
        token_info = self._auth_tokens[client_id]
        if datetime.now().timestamp() > token_info["expires_at"]:
            # 令牌过期
            del self._auth_tokens[client_id]
            return False
        
        return True
    
    def __str__(self) -> str:
        return f"SampleMESAdapter(vendor={self.vendor})"
