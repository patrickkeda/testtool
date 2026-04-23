"""
MES适配器基类
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from datetime import datetime

from ..interfaces import IMESAdapter
from ..models import WorkOrder, TestResult, MESResponse, MESConfig, MESError

logger = logging.getLogger(__name__)


class MESAdapter(IMESAdapter):
    """MES适配器基类"""
    
    def __init__(self, vendor: str):
        self.vendor = vendor
        self.logger = logging.getLogger(f"{__name__}.{vendor}")
    
    async def authenticate(self, config: MESConfig) -> MESResponse:
        """认证适配器 - 子类需要实现"""
        raise NotImplementedError("子类必须实现authenticate方法")
    
    async def get_work_order(self, config: MESConfig, sn: str) -> MESResponse:
        """获取工单适配器 - 子类需要实现"""
        raise NotImplementedError("子类必须实现get_work_order方法")
    
    async def upload_result(self, config: MESConfig, test_result: TestResult) -> MESResponse:
        """上传结果适配器 - 子类需要实现"""
        raise NotImplementedError("子类必须实现upload_result方法")
    
    async def heartbeat(self, config: MESConfig) -> MESResponse:
        """心跳适配器 - 子类需要实现"""
        raise NotImplementedError("子类必须实现heartbeat方法")
    
    async def get_product_params(self, config: MESConfig, product_number: str) -> MESResponse:
        """获取产品参数适配器 - 子类需要实现"""
        raise NotImplementedError("子类必须实现get_product_params方法")

    async def uninitialize(self, config: MESConfig) -> MESResponse:
        """反初始化适配器（可选实现）。"""
        return self._create_success_response({"status": "noop"}, "未实现MesUnInit，使用本地释放")
    
    def parse_work_order(self, response_data: Any) -> Optional[WorkOrder]:
        """解析工单数据 - 子类需要实现"""
        raise NotImplementedError("子类必须实现parse_work_order方法")
    
    def parse_product_params(self, response_data: Any) -> Dict[str, Any]:
        """解析产品参数 - 子类需要实现"""
        raise NotImplementedError("子类必须实现parse_product_params方法")
    
    def _create_error_response(self, message: str, error_code: str = None, status_code: int = 500) -> MESResponse:
        """创建错误响应"""
        return MESResponse(
            success=False,
            status_code=status_code,
            message=message,
            error_code=error_code
        )
    
    def _create_success_response(self, data: Any = None, message: str = "Success") -> MESResponse:
        """创建成功响应"""
        return MESResponse(
            success=True,
            status_code=200,
            data=data,
            message=message
        )
    
    def _log_request(self, method: str, endpoint: str, params: Dict[str, Any] = None):
        """记录请求日志"""
        self.logger.debug(f"{method} {endpoint}")
        if params:
            self.logger.debug(f"参数: {params}")
    
    def _log_response(self, response: MESResponse):
        """记录响应日志"""
        if response.is_success():
            self.logger.debug(f"响应成功: {response.message}")
        else:
            self.logger.warning(f"响应失败: {response.status_code} - {response.message}")
    
    def __str__(self) -> str:
        return f"MESAdapter(vendor={self.vendor})"
