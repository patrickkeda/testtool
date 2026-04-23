"""
系统自检检查器扩展实现
"""

import os
import logging
from typing import Dict, Any
from datetime import datetime

from .interfaces import IResourceChecker
from .models import CheckResult, CheckItem, CheckStatus, CheckCategory

logger = logging.getLogger(__name__)


class InstrumentChecker(IResourceChecker):
    """仪器连接检查器"""
    
    def __init__(self):
        self.name = "仪器连接检查器"
        self.category = CheckCategory.INSTRUMENTS
    
    def get_category(self) -> CheckCategory:
        return self.category
    
    def get_name(self) -> str:
        return self.name
    
    async def check(self, config: Dict[str, Any]) -> CheckResult:
        """执行仪器连接检查"""
        start_time = datetime.now()
        
        if not config.get("enabled", True):
            return CheckResult(
                success=True,
                category=self.category,
                message="仪器连接检查已禁用",
                summary="跳过仪器连接检查"
            )
        
        result = CheckResult(
            success=True,
            category=self.category,
            message="仪器连接检查完成",
            summary=""
        )
        
        try:
            # 检查程控电源
            if config.get("check_power_supply", True):
                psu_result = await self._check_power_supply(config)
                result.add_item(psu_result)
            
            # 测试仪器连接
            if config.get("test_connection", True):
                connection_result = await self._test_instrument_connection(config)
                result.add_item(connection_result)
            
            # 更新结果状态
            result.success = not result.has_errors()
            result.duration = (datetime.now() - start_time).total_seconds()
            
            if result.has_errors():
                result.message = f"仪器连接检查失败: {result.get_error_count()}个错误"
                result.summary = f"发现{result.get_error_count()}个错误, {result.get_warning_count()}个警告"
            elif result.has_warnings():
                result.message = f"仪器连接检查完成: {result.get_warning_count()}个警告"
                result.summary = f"检查通过, 发现{result.get_warning_count()}个警告"
            else:
                result.message = "仪器连接检查完全通过"
                result.summary = f"所有{result.get_total_count()}项检查通过"
            
            return result
            
        except Exception as e:
            logger.error(f"仪器连接检查异常: {e}")
            error_item = CheckItem(
                name="检查异常",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"检查过程中发生异常: {e}",
                details={"exception": str(e)}
            )
            result.add_item(error_item)
            result.success = False
            result.message = f"仪器连接检查异常: {e}"
            result.duration = (datetime.now() - start_time).total_seconds()
            return result
    
    async def _check_power_supply(self, config: Dict[str, Any]) -> CheckItem:
        """检查程控电源"""
        start_time = datetime.now()
        
        try:
            # 检查VISA接口
            try:
                import pyvisa
                rm = pyvisa.ResourceManager()
                resources = rm.list_resources()
                
                if not resources:
                    return CheckItem(
                        name="程控电源检查",
                        category=self.category,
                        status=CheckStatus.WARNING,
                        message="未找到VISA设备",
                        details={"resources": resources},
                        duration=(datetime.now() - start_time).total_seconds(),
                        recommendations=[
                            "请检查程控电源连接",
                            "确认VISA驱动已安装",
                            "检查设备电源状态"
                        ]
                    )
                
                return CheckItem(
                    name="程控电源检查",
                    category=self.category,
                    status=CheckStatus.SUCCESS,
                    message=f"找到{len(resources)}个VISA设备",
                    details={"resources": resources},
                    duration=(datetime.now() - start_time).total_seconds()
                )
                
            except ImportError:
                return CheckItem(
                    name="程控电源检查",
                    category=self.category,
                    status=CheckStatus.WARNING,
                    message="pyvisa模块未安装，跳过程控电源检查",
                    details={"missing_module": "pyvisa"},
                    duration=(datetime.now() - start_time).total_seconds(),
                    recommendations=["请安装pyvisa模块: pip install pyvisa"]
                )
                
        except Exception as e:
            return CheckItem(
                name="程控电源检查",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"程控电源检查失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )
    
    async def _test_instrument_connection(self, config: Dict[str, Any]) -> CheckItem:
        """测试仪器连接"""
        start_time = datetime.now()
        
        try:
            import pyvisa
            
            test_commands = config.get("test_commands", ["*IDN?", "*STB?"])
            timeout = config.get("test_timeout", 5000) / 1000  # 转换为秒
            
            rm = pyvisa.ResourceManager()
            resources = rm.list_resources()
            
            if not resources:
                return CheckItem(
                    name="仪器连接测试",
                    category=self.category,
                    status=CheckStatus.WARNING,
                    message="无可用仪器设备进行连接测试",
                    details={"resources": resources},
                    duration=(datetime.now() - start_time).total_seconds()
                )
            
            # 测试第一个可用设备
            test_resource = resources[0]
            successful_commands = []
            failed_commands = []
            
            try:
                instrument = rm.open_resource(test_resource)
                instrument.timeout = timeout * 1000  # 转换为毫秒
                
                for command in test_commands:
                    try:
                        response = instrument.query(command)
                        successful_commands.append(f"{command}: {response.strip()}")
                    except Exception as e:
                        failed_commands.append(f"{command}: {e}")
                
                instrument.close()
                
            except Exception as e:
                return CheckItem(
                    name="仪器连接测试",
                    category=self.category,
                    status=CheckStatus.ERROR,
                    message=f"仪器连接失败: {e}",
                    details={
                        "test_resource": test_resource,
                        "exception": str(e)
                    },
                    duration=(datetime.now() - start_time).total_seconds(),
                    recommendations=[
                        "请检查仪器连接",
                        "确认仪器电源状态",
                        "检查VISA驱动配置"
                    ]
                )
            
            if failed_commands:
                status = CheckStatus.WARNING
                message = f"部分命令执行失败: {len(failed_commands)}个"
                recommendations = [
                    "请检查仪器状态",
                    "确认命令格式正确",
                    "检查仪器通信参数"
                ]
            else:
                status = CheckStatus.SUCCESS
                message = f"所有{len(successful_commands)}个测试命令执行成功"
                recommendations = []
            
            return CheckItem(
                name="仪器连接测试",
                category=self.category,
                status=status,
                message=message,
                details={
                    "test_resource": test_resource,
                    "successful_commands": successful_commands,
                    "failed_commands": failed_commands,
                    "timeout": timeout
                },
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=recommendations
            )
            
        except ImportError:
            return CheckItem(
                name="仪器连接测试",
                category=self.category,
                status=CheckStatus.WARNING,
                message="pyvisa模块未安装，跳过仪器连接测试",
                details={"missing_module": "pyvisa"},
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=["请安装pyvisa模块: pip install pyvisa"]
            )
        except Exception as e:
            return CheckItem(
                name="仪器连接测试",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"仪器连接测试失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )


class LoggingChecker(IResourceChecker):
    """日志系统检查器"""
    
    def __init__(self):
        self.name = "日志系统检查器"
        self.category = CheckCategory.LOGGING
    
    def get_category(self) -> CheckCategory:
        return self.category
    
    def get_name(self) -> str:
        return self.name
    
    async def check(self, config: Dict[str, Any]) -> CheckResult:
        """执行日志系统检查"""
        start_time = datetime.now()
        
        if not config.get("enabled", True):
            return CheckResult(
                success=True,
                category=self.category,
                message="日志系统检查已禁用",
                summary="跳过日志系统检查"
            )
        
        result = CheckResult(
            success=True,
            category=self.category,
            message="日志系统检查完成",
            summary=""
        )
        
        try:
            # 检查日志目录
            if config.get("check_directory", True):
                directory_result = await self._check_log_directories(config)
                result.add_item(directory_result)
            
            # 检查日志权限
            if config.get("check_permissions", True):
                permission_result = await self._check_log_permissions(config)
                result.add_item(permission_result)
            
            # 更新结果状态
            result.success = not result.has_errors()
            result.duration = (datetime.now() - start_time).total_seconds()
            
            if result.has_errors():
                result.message = f"日志系统检查失败: {result.get_error_count()}个错误"
                result.summary = f"发现{result.get_error_count()}个错误, {result.get_warning_count()}个警告"
            elif result.has_warnings():
                result.message = f"日志系统检查完成: {result.get_warning_count()}个警告"
                result.summary = f"检查通过, 发现{result.get_warning_count()}个警告"
            else:
                result.message = "日志系统检查完全通过"
                result.summary = f"所有{result.get_total_count()}项检查通过"
            
            return result
            
        except Exception as e:
            logger.error(f"日志系统检查异常: {e}")
            error_item = CheckItem(
                name="检查异常",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"检查过程中发生异常: {e}",
                details={"exception": str(e)}
            )
            result.add_item(error_item)
            result.success = False
            result.message = f"日志系统检查异常: {e}"
            result.duration = (datetime.now() - start_time).total_seconds()
            return result
    
    async def _check_log_directories(self, config: Dict[str, Any]) -> CheckItem:
        """检查日志目录"""
        start_time = datetime.now()
        
        try:
            log_directories = config.get("log_directories", [
                "D:/Logs/TestTool",
                "D:/Logs/TestTool/Result",
                "D:/Logs/TestTool/System"
            ])
            
            existing_dirs = []
            missing_dirs = []
            created_dirs = []
            
            for log_dir in log_directories:
                if os.path.exists(log_dir):
                    existing_dirs.append(log_dir)
                else:
                    missing_dirs.append(log_dir)
                    # 尝试创建目录
                    try:
                        os.makedirs(log_dir, exist_ok=True)
                        created_dirs.append(log_dir)
                    except Exception as e:
                        # 创建失败，保持为缺失状态
                        pass
            
            if missing_dirs and not created_dirs:
                status = CheckStatus.ERROR
                message = f"日志目录创建失败: {len(missing_dirs)}个"
                recommendations = [
                    "请检查目录路径权限",
                    "确认磁盘空间充足",
                    "手动创建缺失的日志目录"
                ]
            elif missing_dirs:
                status = CheckStatus.SUCCESS
                message = f"日志目录检查完成: 现有{len(existing_dirs)}个, 新建{len(created_dirs)}个"
                recommendations = []
            else:
                status = CheckStatus.SUCCESS
                message = f"所有{len(existing_dirs)}个日志目录已存在"
                recommendations = []
            
            return CheckItem(
                name="日志目录检查",
                category=self.category,
                status=status,
                message=message,
                details={
                    "log_directories": log_directories,
                    "existing_dirs": existing_dirs,
                    "missing_dirs": missing_dirs,
                    "created_dirs": created_dirs
                },
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=recommendations
            )
            
        except Exception as e:
            return CheckItem(
                name="日志目录检查",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"日志目录检查失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )
    
    async def _check_log_permissions(self, config: Dict[str, Any]) -> CheckItem:
        """检查日志权限"""
        start_time = datetime.now()
        
        try:
            log_directories = config.get("log_directories", [
                "D:/Logs/TestTool",
                "D:/Logs/TestTool/Result",
                "D:/Logs/TestTool/System"
            ])
            
            writable_dirs = []
            read_only_dirs = []
            permission_errors = []
            
            for log_dir in log_directories:
                if os.path.exists(log_dir):
                    try:
                        # 测试写入权限
                        test_file = os.path.join(log_dir, "test_write.tmp")
                        with open(test_file, 'w') as f:
                            f.write("test")
                        os.remove(test_file)
                        writable_dirs.append(log_dir)
                    except Exception as e:
                        read_only_dirs.append(log_dir)
                        permission_errors.append(f"{log_dir}: {e}")
            
            if read_only_dirs:
                status = CheckStatus.ERROR
                message = f"日志目录权限问题: {len(read_only_dirs)}个目录不可写"
                recommendations = [
                    "请检查目录写入权限",
                    "确认用户有足够的权限",
                    "检查目录是否被其他程序占用"
                ]
            else:
                status = CheckStatus.SUCCESS
                message = f"所有{len(writable_dirs)}个日志目录可写"
                recommendations = []
            
            return CheckItem(
                name="日志权限检查",
                category=self.category,
                status=status,
                message=message,
                details={
                    "log_directories": log_directories,
                    "writable_dirs": writable_dirs,
                    "read_only_dirs": read_only_dirs,
                    "permission_errors": permission_errors
                },
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=recommendations
            )
            
        except Exception as e:
            return CheckItem(
                name="日志权限检查",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"日志权限检查失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )
