"""
MES数据上传动作库

提供MES数据上传相关的业务动作，可被测试用例调用。
"""
from typing import Optional, Dict, Any
from ...context import Context


def upload_test_result(ctx: Context, test_data: Dict[str, Any]) -> bool:
    """
    上传测试结果到MES
    
    Args:
        ctx: 测试上下文
        test_data: 测试数据
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.mes:
            ctx.log_warning("MES通讯不可用，跳过数据上传")
            return True
            
        # 构建上传数据
        upload_data = {
            "sn": ctx.get_sn(),
            "port": ctx.port,
            "timestamp": ctx.get_data("test_start_time"),
            "test_data": test_data
        }
        
        # 上传到MES
        result = ctx.mes.upload_test_result(upload_data)
        
        if result:
            ctx.log_info(f"测试结果上传成功: SN={ctx.get_sn()}")
            return True
        else:
            ctx.log_error("测试结果上传失败")
            return False
        
    except Exception as e:
        ctx.log_error(f"测试结果上传异常: {e}")
        return False


def upload_measurement_data(ctx: Context, measurement_type: str, value: float, unit: str = "") -> bool:
    """
    上传测量数据到MES
    
    Args:
        ctx: 测试上下文
        measurement_type: 测量类型
        value: 测量值
        unit: 单位
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.mes:
            ctx.log_warning("MES通讯不可用，跳过数据上传")
            return True
            
        # 构建测量数据
        measurement_data = {
            "sn": ctx.get_sn(),
            "port": ctx.port,
            "measurement_type": measurement_type,
            "value": value,
            "unit": unit,
            "timestamp": ctx.get_data("test_start_time")
        }
        
        # 上传到MES
        result = ctx.mes.upload_measurement(measurement_data)
        
        if result:
            ctx.log_info(f"测量数据上传成功: {measurement_type}={value}{unit}")
            return True
        else:
            ctx.log_error("测量数据上传失败")
            return False
        
    except Exception as e:
        ctx.log_error(f"测量数据上传异常: {e}")
        return False


def upload_error_log(ctx: Context, error_message: str, error_code: str = "") -> bool:
    """
    上传错误日志到MES
    
    Args:
        ctx: 测试上下文
        error_message: 错误信息
        error_code: 错误代码
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.mes:
            ctx.log_warning("MES通讯不可用，跳过错误日志上传")
            return True
            
        # 构建错误日志数据
        error_data = {
            "sn": ctx.get_sn(),
            "port": ctx.port,
            "error_message": error_message,
            "error_code": error_code,
            "timestamp": ctx.get_data("test_start_time")
        }
        
        # 上传到MES
        result = ctx.mes.upload_error_log(error_data)
        
        if result:
            ctx.log_info(f"错误日志上传成功: {error_code}")
            return True
        else:
            ctx.log_error("错误日志上传失败")
            return False
        
    except Exception as e:
        ctx.log_error(f"错误日志上传异常: {e}")
        return False


def upload_test_start(ctx: Context, test_sequence: str) -> bool:
    """
    上传测试开始信息到MES
    
    Args:
        ctx: 测试上下文
        test_sequence: 测试序列名称
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.mes:
            ctx.log_warning("MES通讯不可用，跳过测试开始信息上传")
            return True
            
        # 构建测试开始数据
        start_data = {
            "sn": ctx.get_sn(),
            "port": ctx.port,
            "test_sequence": test_sequence,
            "timestamp": ctx.get_data("test_start_time")
        }
        
        # 上传到MES
        result = ctx.mes.upload_test_start(start_data)
        
        if result:
            ctx.log_info(f"测试开始信息上传成功: {test_sequence}")
            return True
        else:
            ctx.log_error("测试开始信息上传失败")
            return False
        
    except Exception as e:
        ctx.log_error(f"测试开始信息上传异常: {e}")
        return False


def upload_test_end(ctx: Context, test_result: str, summary: Dict[str, Any]) -> bool:
    """
    上传测试结束信息到MES
    
    Args:
        ctx: 测试上下文
        test_result: 测试结果 (PASS/FAIL)
        summary: 测试摘要
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ctx.mes:
            ctx.log_warning("MES通讯不可用，跳过测试结束信息上传")
            return True
            
        # 构建测试结束数据
        end_data = {
            "sn": ctx.get_sn(),
            "port": ctx.port,
            "test_result": test_result,
            "summary": summary,
            "timestamp": ctx.get_data("test_end_time")
        }
        
        # 上传到MES
        result = ctx.mes.upload_test_end(end_data)
        
        if result:
            ctx.log_info(f"测试结束信息上传成功: {test_result}")
            return True
        else:
            ctx.log_error("测试结束信息上传失败")
            return False
        
    except Exception as e:
        ctx.log_error(f"测试结束信息上传异常: {e}")
        return False
