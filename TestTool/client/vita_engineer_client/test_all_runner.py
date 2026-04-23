#!/usr/bin/env python3
"""
Test All Runner - 执行所有测试用例并生成报告

Usage:
    python test_all_runner.py [robot_ip] [port]
"""

import asyncio
import json
import os
import sys
import time
import shutil
import io
import contextlib
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

# Import test_engineer_client functions and classes
try:
    from .test_engineer_client import (
        command_handler,
        parser,
    )
    from .engineer_client import EngineerServiceClient
except ImportError:
    from test_engineer_client import (
        command_handler,
        parser,
    )
    from engineer_client import EngineerServiceClient


class TestStatus(Enum):
    """测试状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class TestResult:
    """单个测试用例结果"""
    command: str
    description: str
    test_case: str
    status: TestStatus
    duration: float = 0.0
    error_message: str = ""
    response_data: str = ""  # 成功用例的返回数据
    timestamp: str = ""
    iteration: int = 1
    total_iterations: int = 1
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        response_data_value = self.response_data
        if self.response_data:
            try:
                response_data_value = json.loads(self.response_data)
            except (json.JSONDecodeError, ValueError):
                pass
        
        return {
            "command": self.command,
            "description": self.description,
            "test_case": self.test_case,
            "status": self.status.value,
            "duration": self.duration,
            "error_message": self.error_message,
            "iteration": self.iteration,
            "total_iterations": self.total_iterations,
            "response_data": response_data_value,
            "timestamp": self.timestamp
        }


@dataclass
class TestReport:
    """测试报告"""
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    error_tests: int = 0
    total_duration: float = 0.0
    start_time: str = ""
    end_time: str = ""
    results: List[TestResult] = field(default_factory=list)
    stability_summary: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "skipped_tests": self.skipped_tests,
            "error_tests": self.error_tests,
            "total_duration": self.total_duration,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "results": [r.to_dict() for r in self.results],
            "stability_summary": self.stability_summary
        }


class TestAllRunner:
    """测试用例执行器"""
    
    def __init__(self, config_file: str = "test_cases_config.json"):
        self.config_file = config_file
        self.config_data: Optional[Dict[str, Any]] = None
        self.test_cases: List[Dict[str, Any]] = []
        self.excluded_test_cases: List[Dict[str, Any]] = []
        self.test_settings: Dict[str, Any] = {}
        self.report = TestReport()
        self.temp_files: List[str] = []  # 记录创建的临时文件，用于清理
        self.client: Optional[EngineerServiceClient] = None  # 共享的 HTTP 客户端
        
    def load_config(self) -> bool:
        """加载测试用例配置"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), self.config_file)
            
            if not os.path.exists(config_path):
                print(f"错误: 配置文件不存在: {config_path}")
                return False
            
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
            
            # 解析测试用例
            self.test_cases = []
            for test_case_config in self.config_data.get("test_cases", []):
                # 处理单个测试用例
                if "test_case" in test_case_config:
                    if test_case_config.get("enabled", True):
                        self.test_cases.append(test_case_config)
                # 处理多个测试用例
                elif "test_cases" in test_case_config:
                    for sub_test_case in test_case_config.get("test_cases", []):
                        if sub_test_case.get("enabled", True):
                            # 合并父级信息
                            merged_case = {
                                "command": test_case_config.get("command"),
                                "description": test_case_config.get("description", ""),
                                **sub_test_case
                            }
                            self.test_cases.append(merged_case)
            
            self.excluded_test_cases = self.config_data.get("excluded_test_cases", [])
            self.test_settings = self.config_data.get("test_settings", {})
            
            # 按order字段排序（如果存在）
            self.test_cases.sort(key=lambda x: x.get("order", 999))
            
            print(f"成功加载 {len(self.test_cases)} 个测试用例")
            return True
            
        except Exception as e:
            print(f"加载配置文件失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _format_response_data(self, raw_data: str) -> str:
        """
        格式化返回数据，如果是 JSON 则格式化为易读的多行格式
        
        Args:
            raw_data: 原始返回数据字符串
            
        Returns:
            格式化后的字符串
        """
        if not raw_data or not raw_data.strip():
            return raw_data
        
        try:
            parsed_json = json.loads(raw_data.strip())
            return json.dumps(parsed_json, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, ValueError):
            try:
                decoded = raw_data.encode('utf-8').decode('unicode_escape')
                parsed_json = json.loads(decoded.strip())
                return json.dumps(parsed_json, ensure_ascii=False, indent=2)
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                return raw_data
    
    def is_test_case_excluded(self, command: str, operation: str = None, test_case: str = None) -> bool:
        """检查测试用例是否被排除"""
        for excluded in self.excluded_test_cases:
            if excluded.get("command") == command:
                # 如果指定了operation，需要匹配
                if "operation" in excluded:
                    if operation and excluded["operation"] == operation:
                        return True
                # 如果指定了test_case，需要匹配
                elif "test_case" in excluded:
                    if test_case and excluded["test_case"] == test_case:
                        return True
                # 如果只指定了command，则排除所有该command的测试用例
                elif "operation" not in excluded and "test_case" not in excluded:
                    return True
        return False
    
    def setup_test_case(self, test_case_config: Dict[str, Any]) -> bool:
        """设置测试用例的前置条件（如创建临时文件）"""
        if test_case_config.get("requires_setup", False):
            setup_command = test_case_config.get("setup_command", "")
            if setup_command:
                try:
                    import subprocess
                    result = subprocess.run(setup_command, shell=True, capture_output=True, text=True)
                    if result.returncode != 0:
                        print(f"警告: 前置设置命令执行失败: {setup_command}")
                        print(f"错误输出: {result.stderr}")
                        return False
                    return True
                except Exception as e:
                    print(f"警告: 前置设置命令执行异常: {e}")
                    return False
        return True
    
    async def execute_test_case(self, test_case_config: Dict[str, Any], robot_ip: str, port: int) -> TestResult:
        """执行单个测试用例 - 直接调用 test_engineer_client.py 中的函数"""
        test_case_str = test_case_config.get("test_case", "")
        command = test_case_config.get("command", "")
        description = test_case_config.get("description", "")
        
        # 执行前置设置
        if not self.setup_test_case(test_case_config):
            return TestResult(
                command=command,
                description=description,
                test_case=test_case_str,
                status=TestStatus.SKIPPED,
                error_message="前置设置失败",
                timestamp=datetime.now().isoformat()
            )
        
        # 解析operation
        operation = None
        if test_case_str:
            parts = test_case_str.split("=")
            if len(parts) > 1:
                params = parts[1].rstrip("%").split(",")
                if params:
                    operation = params[0]
        
        # 检查是否被排除
        if self.is_test_case_excluded(command, operation, test_case_str):
            return TestResult(
                command=command,
                description=description,
                test_case=test_case_str,
                status=TestStatus.SKIPPED,
                error_message="测试用例被排除",
                timestamp=datetime.now().isoformat()
            )
        
        result = TestResult(
            command=command,
            description=description,
            test_case=test_case_str,
            status=TestStatus.RUNNING,
            timestamp=datetime.now().isoformat()
        )
        
        start_time = time.time()
        
        # Capture stdout/stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        try:
            # Parse test case parameters
            try:
                params = parser.parse_test_case(test_case_str)
            except ValueError as e:
                result.status = TestStatus.FAILED
                result.error_message = f"参数解析失败: {e}"
                result.duration = time.time() - start_time
                return result
            
            # Execute command directly using command_handler
            # Capture print output
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                async with EngineerServiceClient(host=robot_ip, port=port) as client:
                    success = await command_handler.execute_command(client, params)
            
            duration = time.time() - start_time
            result.duration = duration
            
            # Get captured output
            stdout_output = stdout_capture.getvalue()
            stderr_output = stderr_capture.getvalue()
            
            if success:
                result.status = TestStatus.PASSED
                
                # Extract response data from output
                if stdout_output:
                    lines = stdout_output.split('\n')
                    response_lines = []
                    found_data_marker = False
                    
                    for line in lines:
                        # Skip initialization messages
                        if '成功加载' in line or '注册响应处理器' in line or '注册特殊命令处理器' in line:
                            continue
                        
                        if '目标机器人' in line or '测试用例:' in line or '正在连接到' in line:
                            continue
                        
                        # Find response data
                        if '返回数据' in line:
                            found_data_marker = True
                            if '返回数据:' in line:
                                parts = line.split('返回数据:', 1)
                                if len(parts) > 1 and parts[1].strip():
                                    response_lines.append(parts[1].strip())
                            continue
                        
                        # Collect response data lines
                        if found_data_marker:
                            if '测试完成' in line or '测试失败' in line:
                                break
                            if line.strip():
                                response_lines.append(line)
                    
                    if response_lines:
                        # Clean up empty lines
                        while response_lines and not response_lines[0].strip():
                            response_lines.pop(0)
                        while response_lines and not response_lines[-1].strip():
                            response_lines.pop()
                        if response_lines:
                            raw_data = "\n".join(response_lines)
                            result.response_data = self._format_response_data(raw_data)
            else:
                result.status = TestStatus.FAILED
                result.error_message = ""
                
                # Extract error message from output
                if stdout_output:
                    lines = stdout_output.split('\n')
                    error_lines = []
                    capture_started = False
                    
                    for line in lines:
                        # Skip initialization messages
                        if '成功加载' in line or '注册响应处理器' in line or '注册特殊命令处理器' in line:
                            continue
                        
                        if '目标机器人' in line or '测试用例:' in line or '正在连接到' in line:
                            continue
                        
                        if '解析参数:' in line or '命令验证失败' in line or '未知命令' in line:
                            capture_started = True
                            error_lines.append(line)
                            continue
                        
                        # Collect error lines
                        if capture_started:
                            if '测试完成' in line or '测试失败' in line:
                                break
                            if line.strip():
                                error_lines.append(line)
                    
                    if error_lines:
                        # Clean up empty lines
                        while error_lines and not error_lines[-1].strip():
                            error_lines.pop()
                        result.error_message = "\n".join(error_lines)
                    else:
                        # Fallback: find error keywords
                        fallback_lines = []
                        for line in lines:
                            if any(keyword in line for keyword in ['失败', '错误', 'Error', 'Failed', 'Exception', '异常']):
                                if '成功加载' not in line and '注册响应处理器' not in line:
                                    fallback_lines.append(line)
                        
                        if fallback_lines:
                            result.error_message = "\n".join(fallback_lines[-10:])
                        else:
                            result.error_message = stdout_output[-500:] if len(stdout_output) > 500 else stdout_output
                
                # Check stderr
                if not result.error_message and stderr_output:
                    stderr_lines = stderr_output.split('\n')
                    error_stderr_lines = []
                    for line in stderr_lines:
                        if 'INFO' not in line and 'WARNING' not in line and 'DEBUG' not in line:
                            if line.strip():
                                error_stderr_lines.append(line)
                    
                    if error_stderr_lines:
                        result.error_message = "\n".join(error_stderr_lines[-10:])
                
                if not result.error_message:
                    result.error_message = "命令执行失败"
                
        except Exception as e:
            duration = time.time() - start_time
            result.duration = duration
            result.status = TestStatus.ERROR
            result.error_message = str(e)
            import traceback
            result.error_message += f"\n{traceback.format_exc()}"
        
        return result
    
    async def setup_prerequisites(self, robot_ip: str, port: int) -> bool:
        """执行前置条件（如进入工程模式）- 直接调用函数"""
        print("执行前置条件...")
        print("=" * 60)
        
        # 查找required=True的测试用例
        for test_case_config in self.test_cases:
            if test_case_config.get("required", False):
                test_case_str = test_case_config.get("test_case", "")
                description = test_case_config.get("description", "")
                
                print(f"\n前置条件: {description}")
                print(f"执行: {test_case_str}")
                
                try:
                    # Parse and execute directly
                    params = parser.parse_test_case(test_case_str)
                    
                    async with EngineerServiceClient(host=robot_ip, port=port) as client:
                        success = await command_handler.execute_command(client, params)
                    
                    if not success:
                        print(f"前置条件执行失败: {description}")
                        return False
                    
                    print(f"前置条件执行成功: {description}")
                    # 等待一下确保状态生效
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    print(f"前置条件执行异常: {e}")
                    return False
        
        return True
    
    def cleanup_temp_files(self):
        """清理临时文件"""
        if not self.temp_files:
            return
        
        print("\n" + "=" * 60)
        print("清理临时文件...")
        print("=" * 60)
        
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    if os.path.isdir(temp_file):
                        shutil.rmtree(temp_file)
                        print(f"删除临时目录: {temp_file}")
                    else:
                        os.remove(temp_file)
                        print(f"删除临时文件: {temp_file}")
            except Exception as e:
                print(f"警告: 删除临时文件失败 {temp_file}: {e}")
        
        self.temp_files.clear()
    
    async def cleanup(self, robot_ip: str, port: int):
        """执行清理操作（如退出工程模式）- 直接调用函数"""
        cleanup_cases = self.test_settings.get("cleanup_on_exit", [])
        
        if not cleanup_cases:
            return
        
        print("\n" + "=" * 60)
        print("执行清理操作...")
        print("=" * 60)
        
        for cleanup_case in cleanup_cases:
            if not cleanup_case.get("enabled", True):
                continue
            
            test_case_str = cleanup_case.get("test_case", "")
            description = cleanup_case.get("description", "")
            
            print(f"\n清理操作: {description}")
            print(f"执行: {test_case_str}")
            
            try:
                # Parse and execute directly
                params = parser.parse_test_case(test_case_str)
                
                async with EngineerServiceClient(host=robot_ip, port=port) as client:
                    await command_handler.execute_command(client, params)
                
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"清理操作执行异常: {e}")
    
    async def run_all_tests(self, robot_ip: str = "192.168.126.2", port: int = 3579) -> TestReport:
        """执行所有测试用例 - 直接调用 test_engineer_client.py 中的函数"""
        self.report = TestReport()
        self.report.start_time = datetime.now().isoformat()
        
        try:
            # 计算实际执行的测试用例数量（排除required的）
            actual_test_count = sum(1 for tc in self.test_cases if not tc.get("required", False))
            # Set interval between test cases
            # For sequential testing, add delay to ensure resources are properly released
            # This prevents resource accumulation and potential crashes
            case_interval_seconds = self.test_settings.get("case_interval_seconds", 1.0)
            try:
                case_interval_seconds = float(case_interval_seconds)
            except (TypeError, ValueError):
                case_interval_seconds = 1.0
            case_interval_seconds = max(0.5, case_interval_seconds)  # Minimum 500ms for sequential tests
            
            print(f"\n{'=' * 60}")
            print(f"开始执行所有测试用例")
            print(f"目标机器人: {robot_ip}:{port}")
            print(f"测试用例总数: {len(self.test_cases)}")
            print(f"实际执行数量: {actual_test_count}")
            print(f"{'=' * 60}")
            
            # 执行前置条件
            if not await self.setup_prerequisites(robot_ip, port):
                print("\n前置条件执行失败，终止测试")
                self.report.end_time = datetime.now().isoformat()
                return self.report
            
            # 执行测试用例
            print("\n" + "=" * 60)
            print("开始执行测试用例...")
            print("=" * 60)
            
            total_start_time = time.time()
            
            test_index = 0
            # repeat count for each test case
            repeat_count = int(self.test_settings.get("repeat_count", 1) or 1)
            if repeat_count < 1:
                repeat_count = 1

            stop_all = False

            for test_case_config in self.test_cases:
                # 跳过前置条件（已经在setup中执行）
                if test_case_config.get("required", False):
                    continue
                
                test_index += 1
                test_case_str = test_case_config.get("test_case", "")
                description = test_case_config.get("description", "")
                command = test_case_config.get("command", "")
                
                # 在用例之间打印分割线（第一个用例前不打印）
                if test_index > 1:
                    print("-" * 60)
                
                print(f"\n[{test_index}/{actual_test_count}] {command}: {description}")
                print(f"执行: {test_case_str}")

                # repeat this test case repeat_count times for stability
                for iter_idx in range(1, repeat_count + 1):
                    # print iteration info
                    if repeat_count > 1:
                        print(f"  -> 第 {iter_idx}/{repeat_count} 次执行")

                    result = await self.execute_test_case(test_case_config, robot_ip, port)
                    result.iteration = iter_idx
                    result.total_iterations = repeat_count
                    self.report.results.append(result)

                    # 更新统计
                    if result.status == TestStatus.PASSED:
                        self.report.passed_tests += 1
                        print(f"✓ 测试通过 (耗时: {result.duration:.2f}秒)")
                        if result.response_data:
                            print(f"返回数据:\n{result.response_data}")
                    elif result.status == TestStatus.FAILED:
                        self.report.failed_tests += 1
                        print(f"✗ 测试失败 (耗时: {result.duration:.2f}秒)")
                        if result.error_message:
                            print(f"  错误信息: {result.error_message}")
                    elif result.status == TestStatus.SKIPPED:
                        self.report.skipped_tests += 1
                        print(f"⊘ 测试跳过: {result.error_message}")
                    elif result.status == TestStatus.ERROR:
                        self.report.error_tests += 1
                        print(f"✗ 测试异常 (耗时: {result.duration:.2f}秒)")
                        if result.error_message:
                            print(f"  错误信息: {result.error_message[:200]}...")

                    # 如果设置了continue_on_failure=False，遇到失败就停止
                    if not self.test_settings.get("continue_on_failure", True):
                        if result.status in [TestStatus.FAILED, TestStatus.ERROR]:
                            print("\n遇到失败，停止执行后续测试用例")
                            stop_all = True
                            break

                    # 测试用例之间的延迟
                    await asyncio.sleep(case_interval_seconds)

                if stop_all:
                    break
            
            total_duration = time.time() - total_start_time
            self.report.total_duration = total_duration
            self.report.total_tests = len(self.report.results)

            # 生成稳定性汇总（按 command + test_case 聚合）
            stability = {}
            for r in self.report.results:
                key = f"{r.command}||{r.test_case}"
                entry = stability.setdefault(key, {
                    "command": r.command,
                    "test_case": r.test_case,
                    "runs": 0,
                    "passed": 0,
                    "failed": 0,
                    "error": 0,
                    "skipped": 0,
                    "durations": [],
                    "last_status": None
                })
                entry["runs"] += 1
                if r.status == TestStatus.PASSED:
                    entry["passed"] += 1
                elif r.status == TestStatus.FAILED:
                    entry["failed"] += 1
                elif r.status == TestStatus.ERROR:
                    entry["error"] += 1
                elif r.status == TestStatus.SKIPPED:
                    entry["skipped"] += 1
                try:
                    entry["durations"].append(float(r.duration or 0.0))
                except Exception:
                    pass
                entry["last_status"] = r.status.value

            # Compute derived metrics
            for k, v in stability.items():
                runs = v.get("runs", 1)
                passed = v.get("passed", 0)
                durations = v.get("durations", [])
                v["pass_rate"] = round(passed / runs * 100.0, 1) if runs > 0 else 0.0
                if durations:
                    v["avg_duration"] = sum(durations) / len(durations)
                    v["min_duration"] = min(durations)
                    v["max_duration"] = max(durations)
                else:
                    v["avg_duration"] = v["min_duration"] = v["max_duration"] = 0.0

            self.report.stability_summary = stability
            
            # 执行清理操作
            await self.cleanup(robot_ip, port)
            
        except Exception as e:
            print(f"\n执行测试过程发生异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # 清理临时文件
            self.cleanup_temp_files()
        
        self.report.end_time = datetime.now().isoformat()
        return self.report
    
    def generate_report(self, report: TestReport, output_file: Optional[str] = None) -> str:
        """生成测试报告"""
        report_lines = []
        
        report_lines.append("=" * 80)
        report_lines.append("测试报告")
        report_lines.append("=" * 80)
        report_lines.append("")
        report_lines.append(f"开始时间: {report.start_time}")
        report_lines.append(f"结束时间: {report.end_time}")
        report_lines.append(f"总耗时: {report.total_duration:.2f}秒")
        report_lines.append("")
        report_lines.append("-" * 80)
        report_lines.append("测试统计")
        report_lines.append("-" * 80)
        report_lines.append(f"总测试用例数: {report.total_tests}")
        report_lines.append(f"通过: {report.passed_tests} ({report.passed_tests/report.total_tests*100:.1f}%)" if report.total_tests > 0 else "通过: 0")
        report_lines.append(f"失败: {report.failed_tests}")
        report_lines.append(f"跳过: {report.skipped_tests}")
        report_lines.append(f"异常: {report.error_tests}")
        report_lines.append("")
        
        # 详细结果
        report_lines.append("-" * 80)
        report_lines.append("详细结果")
        report_lines.append("-" * 80)
        report_lines.append("")
        
        for i, result in enumerate(report.results, 1):
            status_symbol = {
                TestStatus.PASSED: "✓",
                TestStatus.FAILED: "✗",
                TestStatus.SKIPPED: "⊘",
                TestStatus.ERROR: "✗",
                TestStatus.RUNNING: "○",
                TestStatus.PENDING: "○"
            }.get(result.status, "?")
            
            report_lines.append(f"{i}. [{status_symbol}] {result.command}: {result.description}")
            report_lines.append(f"   测试用例: {result.test_case}")
            report_lines.append(f"   状态: {result.status.value}")
            report_lines.append(f"   耗时: {result.duration:.2f}秒")
            if result.status == TestStatus.PASSED and result.response_data:
                report_lines.append(f"   返回数据:")
                # 缩进返回数据
                for data_line in result.response_data.split('\n'):
                    report_lines.append(f"     {data_line}")
            elif result.error_message:
                report_lines.append(f"   错误: {result.error_message}")
            report_lines.append("")
        
        # 失败用例汇总
        failed_results = [r for r in report.results if r.status in [TestStatus.FAILED, TestStatus.ERROR]]
        if failed_results:
            report_lines.append("-" * 80)
            report_lines.append("失败用例汇总")
            report_lines.append("-" * 80)
            report_lines.append("")
            for result in failed_results:
                report_lines.append(f"✗ {result.command}: {result.description}")
                report_lines.append(f"  {result.test_case}")
                if result.error_message:
                    report_lines.append(f"  错误: {result.error_message}")
                report_lines.append("")

        # 稳定性汇总
        if report.stability_summary:
            report_lines.append("-" * 80)
            report_lines.append("稳定性汇总")
            report_lines.append("-" * 80)
            report_lines.append("")
            # 按命令排序
            for key in sorted(report.stability_summary.keys()):
                v = report.stability_summary[key]
                runs = v.get("runs", 0)
                passed = v.get("passed", 0)
                pass_rate = v.get("pass_rate", 0.0)
                avg_d = v.get("avg_duration", 0.0)
                min_d = v.get("min_duration", 0.0)
                max_d = v.get("max_duration", 0.0)
                last_status = v.get("last_status")
                flaky = "FLAKY" if 0 < pass_rate < 100 else ("OK" if pass_rate == 100 else "FAIL")

                report_lines.append(f"{v.get('command')}: {v.get('test_case')}")
                report_lines.append(f"  运行次数: {runs}, 通过: {passed}, 通过率: {pass_rate}% ({flaky})")
                report_lines.append(f"  平均耗时: {avg_d:.2f}s, 最短: {min_d:.2f}s, 最长: {max_d:.2f}s, 最近状态: {last_status}")
                report_lines.append("")
        
        report_text = "\n".join(report_lines)
        
        # 保存到文件
        if output_file:
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(report_text)
                print(f"\n测试报告已保存到: {output_file}")
                
                # 同时保存JSON格式
                json_file = output_file.replace('.txt', '.json') if output_file.endswith('.txt') else output_file + '.json'
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
                print(f"JSON格式报告已保存到: {json_file}")
            except Exception as e:
                print(f"保存报告失败: {e}")
        
        return report_text


async def main_async():
    """主函数（异步版本）"""
    robot_ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.126.2"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 3579
    
    runner = TestAllRunner()
    
    # 加载配置
    if not runner.load_config():
        print("加载配置文件失败")
        sys.exit(1)
    # 可通过第三个参数覆盖重复执行次数: python test_all_runner.py [robot_ip] [port] [repeat_count]
    if len(sys.argv) > 3:
        try:
            rc = int(sys.argv[3])
            if rc >= 1:
                runner.test_settings["repeat_count"] = rc
                print(f"使用命令行覆盖的重复次数: {rc}")
        except Exception:
            pass

    # 执行所有测试
    report = await runner.run_all_tests(robot_ip, port)
    
    # 生成报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"test_report_{timestamp}.txt"
    report_text = runner.generate_report(report, report_file)
    
    # 打印报告
    print("\n" + report_text)
    
    # 返回退出码
    if report.failed_tests > 0 or report.error_tests > 0:
        sys.exit(1)
    else:
        sys.exit(0)


def main():
    """主函数入口"""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

