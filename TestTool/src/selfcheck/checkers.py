"""
系统自检检查器实现
"""

import sys
import importlib
import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from .interfaces import IResourceChecker
from .models import CheckResult, CheckItem, CheckStatus, CheckCategory

logger = logging.getLogger(__name__)


class SoftwareEnvironmentChecker(IResourceChecker):
    """软件环境检查器"""
    
    def __init__(self):
        self.name = "软件环境检查器"
        self.category = CheckCategory.SOFTWARE_ENVIRONMENT
    
    def get_category(self) -> CheckCategory:
        return self.category
    
    def get_name(self) -> str:
        return self.name
    
    async def check(self, config: Dict[str, Any]) -> CheckResult:
        """执行软件环境检查"""
        start_time = datetime.now()
        
        if not config.get("enabled", True):
            return CheckResult(
                success=True,
                category=self.category,
                message="软件环境检查已禁用",
                summary="跳过软件环境检查"
            )
        
        result = CheckResult(
            success=True,
            category=self.category,
            message="软件环境检查完成",
            summary=""
        )
        
        try:
            # 检查Python版本
            if config.get("check_python_version", True):
                python_result = await self._check_python_version(config)
                result.add_item(python_result)
            
            # 检查依赖包
            if config.get("check_dependencies", True):
                deps_result = await self._check_dependencies(config)
                result.add_item(deps_result)
            
            # 检查环境变量
            if config.get("check_environment_variables", True):
                env_result = await self._check_environment_variables(config)
                result.add_item(env_result)
            
            # 更新结果状态
            result.success = not result.has_errors()
            result.duration = (datetime.now() - start_time).total_seconds()
            
            if result.has_errors():
                result.message = f"软件环境检查失败: {result.get_error_count()}个错误"
                result.summary = f"发现{result.get_error_count()}个错误, {result.get_warning_count()}个警告"
            elif result.has_warnings():
                result.message = f"软件环境检查完成: {result.get_warning_count()}个警告"
                result.summary = f"检查通过, 发现{result.get_warning_count()}个警告"
            else:
                result.message = "软件环境检查完全通过"
                result.summary = f"所有{result.get_total_count()}项检查通过"
            
            return result
            
        except Exception as e:
            logger.error(f"软件环境检查异常: {e}")
            error_item = CheckItem(
                name="检查异常",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"检查过程中发生异常: {e}",
                details={"exception": str(e)}
            )
            result.add_item(error_item)
            result.success = False
            result.message = f"软件环境检查异常: {e}"
            result.duration = (datetime.now() - start_time).total_seconds()
            return result
    
    async def _check_python_version(self, config: Dict[str, Any]) -> CheckItem:
        """检查Python版本"""
        start_time = datetime.now()
        
        try:
            min_version = config.get("min_python_version", "3.10")
            current_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            
            # 解析版本号
            min_major, min_minor = map(int, min_version.split(".")[:2])
            current_major, current_minor = sys.version_info.major, sys.version_info.minor
            
            if current_major < min_major or (current_major == min_major and current_minor < min_minor):
                return CheckItem(
                    name="Python版本检查",
                    category=self.category,
                    status=CheckStatus.ERROR,
                    message=f"Python版本过低: {current_version} < {min_version}",
                    details={
                        "current_version": current_version,
                        "min_version": min_version,
                        "version_info": {
                            "major": sys.version_info.major,
                            "minor": sys.version_info.minor,
                            "micro": sys.version_info.micro
                        }
                    },
                    duration=(datetime.now() - start_time).total_seconds(),
                    recommendations=[
                        f"请升级Python到{min_version}或更高版本",
                        "建议使用Python 3.10+以获得最佳性能"
                    ]
                )
            else:
                return CheckItem(
                    name="Python版本检查",
                    category=self.category,
                    status=CheckStatus.SUCCESS,
                    message=f"Python版本符合要求: {current_version} >= {min_version}",
                    details={
                        "current_version": current_version,
                        "min_version": min_version,
                        "version_info": {
                            "major": sys.version_info.major,
                            "minor": sys.version_info.minor,
                            "micro": sys.version_info.micro
                        }
                    },
                    duration=(datetime.now() - start_time).total_seconds()
                )
                
        except Exception as e:
            return CheckItem(
                name="Python版本检查",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"Python版本检查失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )
    
    async def _check_dependencies(self, config: Dict[str, Any]) -> CheckItem:
        """检查依赖包"""
        start_time = datetime.now()
        
        try:
            critical_deps = config.get("critical_dependencies", [])
            missing_packages = []
            version_issues = []
            installed_packages = []
            
            for dep in critical_deps:
                dep_name = dep["name"]
                min_version = dep["min_version"]
                
                try:
                    # 尝试导入模块
                    module = importlib.import_module(dep_name)
                    
                    # 获取版本信息
                    if hasattr(module, "__version__"):
                        current_version = module.__version__
                        if self._version_compatible(current_version, min_version):
                            installed_packages.append({
                                "name": dep_name,
                                "version": current_version,
                                "status": "ok"
                            })
                        else:
                            version_issues.append(f"{dep_name}: {current_version} < {min_version}")
                            installed_packages.append({
                                "name": dep_name,
                                "version": current_version,
                                "status": "version_mismatch",
                                "min_version": min_version
                            })
                    else:
                        version_issues.append(f"{dep_name}: 无法获取版本信息")
                        installed_packages.append({
                            "name": dep_name,
                            "version": "unknown",
                            "status": "version_unknown"
                        })
                        
                except ImportError:
                    missing_packages.append(dep_name)
                    installed_packages.append({
                        "name": dep_name,
                        "version": "not_installed",
                        "status": "missing"
                    })
            
            # 确定检查状态
            if missing_packages:
                status = CheckStatus.ERROR
                message = f"缺失关键依赖包: {', '.join(missing_packages)}"
                recommendations = [f"请安装缺失的依赖包: pip install {' '.join(missing_packages)}"]
            elif version_issues:
                status = CheckStatus.WARNING
                message = f"依赖包版本问题: {', '.join(version_issues)}"
                recommendations = ["请升级相关依赖包到推荐版本"]
            else:
                status = CheckStatus.SUCCESS
                message = f"所有{len(installed_packages)}个关键依赖包检查通过"
                recommendations = []
            
            return CheckItem(
                name="依赖包检查",
                category=self.category,
                status=status,
                message=message,
                details={
                    "installed_packages": installed_packages,
                    "missing_packages": missing_packages,
                    "version_issues": version_issues,
                    "total_checked": len(critical_deps)
                },
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=recommendations
            )
            
        except Exception as e:
            return CheckItem(
                name="依赖包检查",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"依赖包检查失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )
    
    async def _check_environment_variables(self, config: Dict[str, Any]) -> CheckItem:
        """检查环境变量"""
        start_time = datetime.now()
        
        try:
            required_vars = config.get("required_env_vars", [])
            missing_vars = []
            present_vars = []
            
            for var_name in required_vars:
                if var_name in os.environ:
                    present_vars.append(var_name)
                else:
                    missing_vars.append(var_name)
            
            if missing_vars:
                status = CheckStatus.WARNING
                message = f"缺失环境变量: {', '.join(missing_vars)}"
                recommendations = [f"请设置环境变量: {', '.join(missing_vars)}"]
            else:
                status = CheckStatus.SUCCESS
                message = f"所有{len(present_vars)}个必需环境变量已设置"
                recommendations = []
            
            return CheckItem(
                name="环境变量检查",
                category=self.category,
                status=status,
                message=message,
                details={
                    "present_vars": present_vars,
                    "missing_vars": missing_vars,
                    "total_checked": len(required_vars)
                },
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=recommendations
            )
            
        except Exception as e:
            return CheckItem(
                name="环境变量检查",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"环境变量检查失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )
    
    def _version_compatible(self, current_version: str, min_version: str) -> bool:
        """检查版本兼容性"""
        try:
            current_parts = [int(x) for x in current_version.split(".")]
            min_parts = [int(x) for x in min_version.split(".")]
            
            # 补齐版本号长度
            while len(current_parts) < len(min_parts):
                current_parts.append(0)
            while len(min_parts) < len(current_parts):
                min_parts.append(0)
            
            # 比较版本号
            for current, min_ver in zip(current_parts, min_parts):
                if current > min_ver:
                    return True
                elif current < min_ver:
                    return False
            
            return True  # 版本相等
            
        except Exception:
            return False  # 版本解析失败，认为不兼容


class HardwareResourceChecker(IResourceChecker):
    """硬件资源检查器"""
    
    def __init__(self):
        self.name = "硬件资源检查器"
        self.category = CheckCategory.HARDWARE_RESOURCES
    
    def get_category(self) -> CheckCategory:
        return self.category
    
    def get_name(self) -> str:
        return self.name
    
    async def check(self, config: Dict[str, Any]) -> CheckResult:
        """执行硬件资源检查"""
        start_time = datetime.now()
        
        if not config.get("enabled", True):
            return CheckResult(
                success=True,
                category=self.category,
                message="硬件资源检查已禁用",
                summary="跳过硬件资源检查"
            )
        
        result = CheckResult(
            success=True,
            category=self.category,
            message="硬件资源检查完成",
            summary=""
        )
        
        try:
            # 检查磁盘空间
            if config.get("check_disk_space", True):
                disk_result = await self._check_disk_space(config)
                result.add_item(disk_result)
            
            # 检查内存
            if config.get("check_memory", True):
                memory_result = await self._check_memory(config)
                result.add_item(memory_result)
            
            # 检查网络
            if config.get("check_network", True):
                network_result = await self._check_network(config)
                result.add_item(network_result)
            
            # 更新结果状态
            result.success = not result.has_errors()
            result.duration = (datetime.now() - start_time).total_seconds()
            
            if result.has_errors():
                result.message = f"硬件资源检查失败: {result.get_error_count()}个错误"
                result.summary = f"发现{result.get_error_count()}个错误, {result.get_warning_count()}个警告"
            elif result.has_warnings():
                result.message = f"硬件资源检查完成: {result.get_warning_count()}个警告"
                result.summary = f"检查通过, 发现{result.get_warning_count()}个警告"
            else:
                result.message = "硬件资源检查完全通过"
                result.summary = f"所有{result.get_total_count()}项检查通过"
            
            return result
            
        except Exception as e:
            logger.error(f"硬件资源检查异常: {e}")
            error_item = CheckItem(
                name="检查异常",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"检查过程中发生异常: {e}",
                details={"exception": str(e)}
            )
            result.add_item(error_item)
            result.success = False
            result.message = f"硬件资源检查异常: {e}"
            result.duration = (datetime.now() - start_time).total_seconds()
            return result
    
    async def _check_disk_space(self, config: Dict[str, Any]) -> CheckItem:
        """检查磁盘空间"""
        start_time = datetime.now()
        
        try:
            import shutil
            
            min_space_gb = config.get("min_disk_space_gb", 1)
            
            # 检查系统盘
            system_disk = shutil.disk_usage("C:")
            available_gb = system_disk.free / (1024**3)
            
            if available_gb < min_space_gb:
                status = CheckStatus.ERROR
                message = f"磁盘空间不足: {available_gb:.1f}GB < {min_space_gb}GB"
                recommendations = [
                    "请清理磁盘空间",
                    "删除不必要的文件",
                    "移动文件到其他磁盘"
                ]
            else:
                status = CheckStatus.SUCCESS
                message = f"磁盘空间充足: {available_gb:.1f}GB >= {min_space_gb}GB"
                recommendations = []
            
            return CheckItem(
                name="磁盘空间检查",
                category=self.category,
                status=status,
                message=message,
                details={
                    "available_gb": available_gb,
                    "min_space_gb": min_space_gb,
                    "total_gb": system_disk.total / (1024**3),
                    "used_gb": (system_disk.total - system_disk.free) / (1024**3)
                },
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=recommendations
            )
            
        except Exception as e:
            return CheckItem(
                name="磁盘空间检查",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"磁盘空间检查失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )
    
    async def _check_memory(self, config: Dict[str, Any]) -> CheckItem:
        """检查内存"""
        start_time = datetime.now()
        
        try:
            import psutil
            
            min_total_gb = config.get("min_total_memory_gb", 4)
            min_available_mb = config.get("min_available_memory_mb", 512)
            max_usage_percent = config.get("max_memory_usage_percent", 90)
            
            memory = psutil.virtual_memory()
            total_gb = memory.total / (1024**3)
            available_mb = memory.available / (1024**2)
            usage_percent = memory.percent
            
            issues = []
            recommendations = []
            
            if total_gb < min_total_gb:
                issues.append(f"总内存不足: {total_gb:.1f}GB < {min_total_gb}GB")
                recommendations.append("建议增加系统内存")
            
            if available_mb < min_available_mb:
                issues.append(f"可用内存不足: {available_mb:.1f}MB < {min_available_mb}MB")
                recommendations.append("请关闭不必要的程序释放内存")
            
            if usage_percent > max_usage_percent:
                issues.append(f"内存使用率过高: {usage_percent:.1f}% > {max_usage_percent}%")
                recommendations.append("请优化内存使用或重启系统")
            
            if issues:
                status = CheckStatus.ERROR if len(issues) > 1 else CheckStatus.WARNING
                message = "; ".join(issues)
            else:
                status = CheckStatus.SUCCESS
                message = f"内存检查通过: 总计{total_gb:.1f}GB, 可用{available_mb:.1f}MB, 使用率{usage_percent:.1f}%"
            
            return CheckItem(
                name="内存检查",
                category=self.category,
                status=status,
                message=message,
                details={
                    "total_gb": total_gb,
                    "available_mb": available_mb,
                    "usage_percent": usage_percent,
                    "min_total_gb": min_total_gb,
                    "min_available_mb": min_available_mb,
                    "max_usage_percent": max_usage_percent
                },
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=recommendations
            )
            
        except ImportError:
            return CheckItem(
                name="内存检查",
                category=self.category,
                status=CheckStatus.WARNING,
                message="psutil模块未安装，跳过内存检查",
                details={"missing_module": "psutil"},
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=["请安装psutil模块: pip install psutil"]
            )
        except Exception as e:
            return CheckItem(
                name="内存检查",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"内存检查失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )
    
    async def _check_network(self, config: Dict[str, Any]) -> CheckItem:
        """检查网络"""
        start_time = datetime.now()
        
        try:
            import socket
            
            timeout = config.get("network_test_timeout", 5000) / 1000  # 转换为秒
            
            # 检查网络接口
            try:
                import psutil
                interfaces = psutil.net_if_addrs()
                active_interfaces = []
                
                for interface, addresses in interfaces.items():
                    for addr in addresses:
                        if addr.family == socket.AF_INET and not addr.address.startswith('127.'):
                            active_interfaces.append(interface)
                            break
                
                if not active_interfaces:
                    return CheckItem(
                        name="网络检查",
                        category=self.category,
                        status=CheckStatus.ERROR,
                        message="未找到活动的网络接口",
                        details={"active_interfaces": []},
                        duration=(datetime.now() - start_time).total_seconds(),
                        recommendations=["请检查网络连接", "确保网卡正常工作"]
                    )
                
            except ImportError:
                # 如果没有psutil，使用简单的方法
                active_interfaces = ["unknown"]
            
            # 测试网络连通性
            try:
                socket.create_connection(("8.8.8.8", 53), timeout=timeout)
                network_available = True
                network_message = "外网连通正常"
            except:
                network_available = False
                network_message = "外网连通异常"
            
            status = CheckStatus.SUCCESS if network_available else CheckStatus.WARNING
            message = f"网络检查完成: 活动接口{len(active_interfaces)}个, {network_message}"
            
            return CheckItem(
                name="网络检查",
                category=self.category,
                status=status,
                message=message,
                details={
                    "active_interfaces": active_interfaces,
                    "network_available": network_available,
                    "test_timeout": timeout
                },
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=[] if network_available else ["请检查网络连接", "检查防火墙设置"]
            )
            
        except Exception as e:
            return CheckItem(
                name="网络检查",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"网络检查失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )


# 其他检查器将在后续实现
class CommunicationChecker(IResourceChecker):
    """通信接口检查器"""
    
    def __init__(self):
        self.name = "通信接口检查器"
        self.category = CheckCategory.COMMUNICATION
    
    def get_category(self) -> CheckCategory:
        return self.category
    
    def get_name(self) -> str:
        return self.name
    
    async def check(self, config: Dict[str, Any]) -> CheckResult:
        """执行通信接口检查"""
        start_time = datetime.now()
        
        if not config.get("enabled", True):
            return CheckResult(
                success=True,
                category=self.category,
                message="通信接口检查已禁用",
                summary="跳过通信接口检查"
            )
        
        result = CheckResult(
            success=True,
            category=self.category,
            message="通信接口检查完成",
            summary=""
        )
        
        try:
            # 检查串口
            if config.get("check_serial_ports", True):
                serial_result = await self._check_serial_ports(config)
                result.add_item(serial_result)
            
            # 检查TCP连接
            if config.get("check_tcp_connections", True):
                tcp_result = await self._check_tcp_connections(config)
                result.add_item(tcp_result)
            
            # 更新结果状态
            result.success = not result.has_errors()
            result.duration = (datetime.now() - start_time).total_seconds()
            
            if result.has_errors():
                result.message = f"通信接口检查失败: {result.get_error_count()}个错误"
                result.summary = f"发现{result.get_error_count()}个错误, {result.get_warning_count()}个警告"
            elif result.has_warnings():
                result.message = f"通信接口检查完成: {result.get_warning_count()}个警告"
                result.summary = f"检查通过, 发现{result.get_warning_count()}个警告"
            else:
                result.message = "通信接口检查完全通过"
                result.summary = f"所有{result.get_total_count()}项检查通过"
            
            return result
            
        except Exception as e:
            logger.error(f"通信接口检查异常: {e}")
            error_item = CheckItem(
                name="检查异常",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"检查过程中发生异常: {e}",
                details={"exception": str(e)}
            )
            result.add_item(error_item)
            result.success = False
            result.message = f"通信接口检查异常: {e}"
            result.duration = (datetime.now() - start_time).total_seconds()
            return result
    
    async def _check_serial_ports(self, config: Dict[str, Any]) -> CheckItem:
        """检查串口"""
        start_time = datetime.now()
        
        try:
            import serial.tools.list_ports
            
            test_ports = config.get("test_ports", ["COM3", "COM4"])
            available_ports = []
            unavailable_ports = []
            
            # 获取系统可用串口
            system_ports = [port.device for port in serial.tools.list_ports.comports()]
            
            for port in test_ports:
                if port in system_ports:
                    available_ports.append(port)
                else:
                    unavailable_ports.append(port)
            
            if unavailable_ports:
                status = CheckStatus.WARNING
                message = f"部分串口不可用: {', '.join(unavailable_ports)}"
                recommendations = [
                    "请检查串口设备连接",
                    "确认串口设备驱动已安装",
                    "检查设备管理器中的串口状态"
                ]
            else:
                status = CheckStatus.SUCCESS
                message = f"所有测试串口可用: {', '.join(available_ports)}"
                recommendations = []
            
            return CheckItem(
                name="串口检查",
                category=self.category,
                status=status,
                message=message,
                details={
                    "test_ports": test_ports,
                    "available_ports": available_ports,
                    "unavailable_ports": unavailable_ports,
                    "system_ports": system_ports
                },
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=recommendations
            )
            
        except ImportError:
            return CheckItem(
                name="串口检查",
                category=self.category,
                status=CheckStatus.WARNING,
                message="pyserial模块未安装，跳过串口检查",
                details={"missing_module": "pyserial"},
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=["请安装pyserial模块: pip install pyserial"]
            )
        except Exception as e:
            return CheckItem(
                name="串口检查",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"串口检查失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )
    
    async def _check_tcp_connections(self, config: Dict[str, Any]) -> CheckItem:
        """检查TCP连接"""
        start_time = datetime.now()
        
        try:
            import socket
            
            test_connections = config.get("test_tcp_connections", [])
            timeout = config.get("test_timeout", 3000) / 1000  # 转换为秒
            
            successful_connections = []
            failed_connections = []
            
            for conn in test_connections:
                host = conn.get("host", "localhost")
                port = conn.get("port", 8080)
                
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(timeout)
                    result = sock.connect_ex((host, port))
                    sock.close()
                    
                    if result == 0:
                        successful_connections.append(f"{host}:{port}")
                    else:
                        failed_connections.append(f"{host}:{port}")
                        
                except Exception as e:
                    failed_connections.append(f"{host}:{port} ({e})")
            
            if failed_connections:
                status = CheckStatus.WARNING
                message = f"部分TCP连接失败: {', '.join(failed_connections)}"
                recommendations = [
                    "请检查目标主机是否运行",
                    "确认端口是否正确",
                    "检查防火墙设置",
                    "验证网络连接"
                ]
            else:
                status = CheckStatus.SUCCESS
                message = f"所有TCP连接成功: {', '.join(successful_connections)}"
                recommendations = []
            
            return CheckItem(
                name="TCP连接检查",
                category=self.category,
                status=status,
                message=message,
                details={
                    "test_connections": test_connections,
                    "successful_connections": successful_connections,
                    "failed_connections": failed_connections,
                    "timeout": timeout
                },
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=recommendations
            )
            
        except Exception as e:
            return CheckItem(
                name="TCP连接检查",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"TCP连接检查失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )


class ConfigChecker(IResourceChecker):
    """配置文件检查器"""
    
    def __init__(self):
        self.name = "配置文件检查器"
        self.category = CheckCategory.CONFIG
    
    def get_category(self) -> CheckCategory:
        return self.category
    
    def get_name(self) -> str:
        return self.name
    
    async def check(self, config: Dict[str, Any]) -> CheckResult:
        """执行配置文件检查"""
        start_time = datetime.now()
        
        if not config.get("enabled", True):
            return CheckResult(
                success=True,
                category=self.category,
                message="配置文件检查已禁用",
                summary="跳过配置文件检查"
            )
        
        result = CheckResult(
            success=True,
            category=self.category,
            message="配置文件检查完成",
            summary=""
        )
        
        try:
            # 检查配置文件完整性
            if config.get("check_file_integrity", True):
                integrity_result = await self._check_file_integrity(config)
                result.add_item(integrity_result)
            
            # 检查配置参数
            if config.get("validate_parameters", True):
                params_result = await self._validate_parameters(config)
                result.add_item(params_result)
            
            # 更新结果状态
            result.success = not result.has_errors()
            result.duration = (datetime.now() - start_time).total_seconds()
            
            if result.has_errors():
                result.message = f"配置文件检查失败: {result.get_error_count()}个错误"
                result.summary = f"发现{result.get_error_count()}个错误, {result.get_warning_count()}个警告"
            elif result.has_warnings():
                result.message = f"配置文件检查完成: {result.get_warning_count()}个警告"
                result.summary = f"检查通过, 发现{result.get_warning_count()}个警告"
            else:
                result.message = "配置文件检查完全通过"
                result.summary = f"所有{result.get_total_count()}项检查通过"
            
            return result
            
        except Exception as e:
            logger.error(f"配置文件检查异常: {e}")
            error_item = CheckItem(
                name="检查异常",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"检查过程中发生异常: {e}",
                details={"exception": str(e)}
            )
            result.add_item(error_item)
            result.success = False
            result.message = f"配置文件检查异常: {e}"
            result.duration = (datetime.now() - start_time).total_seconds()
            return result
    
    async def _check_file_integrity(self, config: Dict[str, Any]) -> CheckItem:
        """检查配置文件完整性"""
        start_time = datetime.now()
        
        try:
            import os
            import yaml
            
            config_files = config.get("config_files", ["config.yaml"])
            existing_files = []
            missing_files = []
            invalid_files = []
            
            for file_path in config_files:
                if os.path.exists(file_path):
                    existing_files.append(file_path)
                    
                    # 检查YAML格式
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            yaml.safe_load(f)
                    except yaml.YAMLError as e:
                        invalid_files.append(f"{file_path}: {e}")
                    except Exception as e:
                        invalid_files.append(f"{file_path}: {e}")
                else:
                    missing_files.append(file_path)
            
            if missing_files or invalid_files:
                status = CheckStatus.ERROR
                message = f"配置文件问题: 缺失{len(missing_files)}个, 格式错误{len(invalid_files)}个"
                recommendations = [
                    "请检查配置文件路径",
                    "确保配置文件格式正确",
                    "参考示例配置文件创建缺失文件"
                ]
            else:
                status = CheckStatus.SUCCESS
                message = f"所有{len(existing_files)}个配置文件完整且格式正确"
                recommendations = []
            
            return CheckItem(
                name="配置文件完整性检查",
                category=self.category,
                status=status,
                message=message,
                details={
                    "config_files": config_files,
                    "existing_files": existing_files,
                    "missing_files": missing_files,
                    "invalid_files": invalid_files
                },
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=recommendations
            )
            
        except ImportError:
            return CheckItem(
                name="配置文件完整性检查",
                category=self.category,
                status=CheckStatus.WARNING,
                message="PyYAML模块未安装，跳过配置文件格式检查",
                details={"missing_module": "pyyaml"},
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=["请安装PyYAML模块: pip install pyyaml"]
            )
        except Exception as e:
            return CheckItem(
                name="配置文件完整性检查",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"配置文件完整性检查失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )
    
    async def _validate_parameters(self, config: Dict[str, Any]) -> CheckItem:
        """验证配置参数"""
        start_time = datetime.now()
        
        try:
            import os
            import yaml
            
            config_file = "config.yaml"
            if not os.path.exists(config_file):
                return CheckItem(
                    name="配置参数验证",
                    category=self.category,
                    status=CheckStatus.WARNING,
                    message="配置文件不存在，跳过参数验证",
                    details={"config_file": config_file},
                    duration=(datetime.now() - start_time).total_seconds()
                )
            
            # 加载配置文件
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            validation_errors = []
            validation_warnings = []
            
            # 检查必要的配置项
            required_sections = ["app", "logging", "ports"]
            for section in required_sections:
                if section not in config_data:
                    validation_errors.append(f"缺少必要配置节: {section}")
            
            # 检查端口配置
            if "ports" in config_data:
                ports_config = config_data["ports"]
                if "portA" not in ports_config:
                    validation_errors.append("缺少PortA配置")
                if "portB" not in ports_config:
                    validation_errors.append("缺少PortB配置")
                
                # 检查串口配置
                for port_name in ["portA", "portB"]:
                    if port_name in ports_config:
                        port_config = ports_config[port_name]
                        if "serial" in port_config:
                            serial_config = port_config["serial"]
                            if "port" not in serial_config:
                                validation_warnings.append(f"{port_name}串口配置缺少port参数")
                            if "baudrate" not in serial_config:
                                validation_warnings.append(f"{port_name}串口配置缺少baudrate参数")
            
            # 检查日志配置
            if "logging" in config_data:
                logging_config = config_data["logging"]
                if "dir" not in logging_config:
                    validation_warnings.append("日志配置缺少dir参数")
                else:
                    log_dir = logging_config["dir"]
                    if not os.path.exists(log_dir):
                        validation_warnings.append(f"日志目录不存在: {log_dir}")
            
            if validation_errors:
                status = CheckStatus.ERROR
                message = f"配置参数验证失败: {len(validation_errors)}个错误"
                recommendations = [
                    "请检查配置文件格式",
                    "参考示例配置文件",
                    "确保所有必要参数已配置"
                ]
            elif validation_warnings:
                status = CheckStatus.WARNING
                message = f"配置参数验证完成: {len(validation_warnings)}个警告"
                recommendations = [
                    "建议完善配置参数",
                    "检查配置参数的有效性"
                ]
            else:
                status = CheckStatus.SUCCESS
                message = "配置参数验证通过"
                recommendations = []
            
            return CheckItem(
                name="配置参数验证",
                category=self.category,
                status=status,
                message=message,
                details={
                    "config_file": config_file,
                    "validation_errors": validation_errors,
                    "validation_warnings": validation_warnings,
                    "required_sections": required_sections
                },
                duration=(datetime.now() - start_time).total_seconds(),
                recommendations=recommendations
            )
            
        except Exception as e:
            return CheckItem(
                name="配置参数验证",
                category=self.category,
                status=CheckStatus.ERROR,
                message=f"配置参数验证失败: {e}",
                details={"exception": str(e)},
                duration=(datetime.now() - start_time).total_seconds()
            )


# 仪器连接检查器和日志系统检查器在 checkers_ext.py 中实现
