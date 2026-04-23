"""
PDF报告生成步骤

从CSV文件生成PDF测试报告，包含TN曲线和扭矩比例曲线
"""
from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any
import csv
from pathlib import Path


class GeneratePDFReportStep(BaseStep):
    """PDF报告生成步骤 - 从CSV生成PDF报告"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        从CSV文件生成PDF测试报告
        
        参数：
        - csv_path: CSV文件路径（支持变量替换，如 ${sn}）
        - output_path: PDF输出路径（支持变量替换）
        - filter_window_size: 滤波窗口大小（默认9）
        - low: 下限扭矩偏移量（Nm，用于绘制TN曲线下限，参考曲线向下偏移）
        - high: 上限扭矩偏移量（Nm，用于绘制TN曲线上限，参考曲线向上偏移）
        - ratio_low: 下限比值（用于绘制静态扭矩比例曲线下限）
        - ratio_high: 上限比值（用于绘制静态扭矩比例曲线上限）
        """
        try:
            # 解析参数
            csv_path = self._resolve_str_param(params.get("csv_path", ""), ctx)
            output_path = self._resolve_str_param(params.get("output_path", ""), ctx)
            filter_window_size = self._resolve_int_param(params.get("filter_window_size", 9), ctx, default=9)
            # low和high是扭矩偏移量（Nm），用于绘制TN曲线上下限
            low_offset = self._resolve_float_param(params.get("low", None), ctx, default=None)
            high_offset = self._resolve_float_param(params.get("high", None), ctx, default=None)
            # ratio_low和ratio_high是比值，用于绘制静态扭矩比例曲线上下限
            ratio_low = self._resolve_float_param(params.get("ratio_low", None), ctx, default=None)
            ratio_high = self._resolve_float_param(params.get("ratio_high", None), ctx, default=None)
            
            if not csv_path:
                return StepResult(
                    passed=False,
                    message="CSV文件路径为空",
                    error="csv_path参数未指定",
                    error_code="REPORT_ERR_NO_CSV_PATH"
                )
            
            if not output_path:
                return StepResult(
                    passed=False,
                    message="PDF输出路径为空",
                    error="output_path参数未指定",
                    error_code="REPORT_ERR_NO_OUTPUT_PATH"
                )
            
            # 将相对路径转换为绝对路径（确保在exe环境中也能正确工作）
            import sys
            import os
            csv_file = Path(csv_path)
            if not csv_file.is_absolute():
                # 如果是相对路径，基于当前工作目录或exe所在目录
                if getattr(sys, 'frozen', False):
                    # exe环境：使用exe所在目录
                    base_dir = Path(sys.executable).parent
                else:
                    # 开发环境：使用当前工作目录
                    base_dir = Path.cwd()
                csv_file = base_dir / csv_path
                csv_path = str(csv_file)
            
            # 检查CSV文件是否存在
            if not csv_file.exists():
                return StepResult(
                    passed=False,
                    message=f"CSV文件不存在: {csv_path}",
                    error=f"文件不存在: {csv_path}",
                    error_code="REPORT_ERR_CSV_NOT_FOUND"
                )
            
            ctx.log_info(f"开始生成PDF报告: {csv_path} -> {output_path}")
            
            # 读取CSV数据
            rpm_data = []
            sensor_torque_data = []
            motor_torque_data = []
            
            # 用于检测数据开始变化的标志
            data_started = False
            velocity_threshold = 0.1  # 角速度阈值（rad/s），超过此值认为电机开始运行
            skipped_count = 0
            total_count = 0
            
            try:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        total_count += 1
                        try:
                            # 角速度(rad/s)转换为RPM: RPM = rad/s * 60 / (2*π)
                            velocity_rads = float(row.get('角速度(rad/s)', 0))
                            rpm = velocity_rads * 60 / (2 * 3.14159265359)
                            
                            # 扭矩仪(Nm) - 传感器扭矩
                            sensor_torque = float(row.get('扭矩仪(Nm)', 0))
                            
                            # 扭矩(Nm) - 电机扭矩
                            motor_torque = float(row.get('扭矩(Nm)', 0))
                            
                            # 运行状态（可选，用于辅助判断）
                            is_running = int(row.get('运行', 0)) == 1
                            
                            # 判断是否应该开始记录数据
                            # 主要依据：角速度绝对值超过阈值（电机真正开始转动）
                            # 辅助依据：运行状态为1（如果可用）
                            should_start = abs(velocity_rads) > velocity_threshold
                            
                            # 如果还没有开始记录，检查是否满足开始条件
                            if not data_started:
                                if should_start:
                                    data_started = True
                                    ctx.log_info(f"检测到电机开始运行：角速度={velocity_rads:.2f} rad/s, RPM={rpm:.2f}, 运行状态={is_running}")
                                else:
                                    skipped_count += 1
                                    continue
                            
                            # 如果数据已经开始变化，记录所有有效数据
                            # 继续使用角速度阈值过滤，确保只记录电机真正运行时的数据
                            if data_started:
                                if abs(velocity_rads) > velocity_threshold:
                                    rpm_data.append(rpm)
                                    sensor_torque_data.append(sensor_torque)
                                    motor_torque_data.append(motor_torque)
                                # 如果角速度回到阈值以下，可能电机已停止，但继续记录（可能是在减速阶段）
                                # 或者可以选择停止记录：else: break
                        except (ValueError, KeyError) as e:
                            ctx.log_warning(f"跳过无效数据行: {e}")
                            skipped_count += 1
                            continue
            except Exception as e:
                return StepResult(
                    passed=False,
                    message=f"读取CSV文件失败: {e}",
                    error=str(e),
                    error_code="REPORT_ERR_CSV_READ_FAILED"
                )
            
            ctx.log_info(f"CSV数据统计：总行数={total_count}, 跳过={skipped_count}, 有效数据点={len(rpm_data)}")
            
            if len(rpm_data) < 2:
                return StepResult(
                    passed=False,
                    message=f"CSV文件中有效数据点不足（至少需要2个点，实际只有{len(rpm_data)}个）",
                    error=f"总行数={total_count}, 跳过={skipped_count}, 有效数据点={len(rpm_data)}。可能原因：电机未运行或角速度始终低于阈值({velocity_threshold} rad/s)",
                    error_code="REPORT_ERR_INSUFFICIENT_DATA"
                )
            
            ctx.log_info(f"✓ 从CSV读取了 {len(rpm_data)} 个有效数据点（角速度阈值: {velocity_threshold} rad/s）")
            
            # 对扭矩传感器数据应用中值滤波，去除毛刺
            if len(sensor_torque_data) > 0:
                ctx.log_info(f"对扭矩传感器数据应用中值滤波（窗口大小: {filter_window_size}）")
                sensor_torque_data = self._sliding_median_filter(sensor_torque_data, filter_window_size)
                ctx.log_info(f"✓ 扭矩传感器数据中值滤波完成")
            
            # 生成PDF报告
            try:
                success = self._generate_pdf_report(
                    rpm_data, sensor_torque_data, motor_torque_data,
                    output_path, filter_window_size, ctx, low_offset, high_offset, ratio_low, ratio_high
                )
                
                if success:
                    ctx.log_info(f"✓ PDF报告生成成功: {output_path}")
                    return StepResult(
                        passed=True,
                        message=f"PDF报告生成成功: {output_path}",
                        data={
                            "csv_path": csv_path,
                            "output_path": output_path,
                            "data_points": len(rpm_data)
                        }
                    )
                else:
                    return StepResult(
                        passed=False,
                        message="PDF报告生成失败",
                        error="绘图过程出错",
                        error_code="REPORT_ERR_PDF_GENERATION_FAILED"
                    )
            except Exception as e:
                ctx.log_error(f"生成PDF报告异常: {e}", exc_info=True)
                return StepResult(
                    passed=False,
                    message=f"生成PDF报告异常: {e}",
                    error=str(e),
                    error_code="REPORT_ERR_EXCEPTION"
                )
                
        except Exception as e:
            ctx.log_error(f"PDF报告生成步骤异常: {e}", exc_info=True)
            return StepResult(
                passed=False,
                message=f"PDF报告生成步骤异常: {e}",
                error=str(e),
                error_code="REPORT_ERR_STEP_EXCEPTION"
            )
    
    def _generate_pdf_report(self, rpm_data, sensor_torque_data, motor_torque_data,
                            output_path, filter_window_size, ctx, low_offset=None, high_offset=None, 
                            ratio_low=None, ratio_high=None):
        """生成PDF报告"""
        try:
            import matplotlib
            # 在exe环境中，设置matplotlib使用非交互式后端
            import sys
            if getattr(sys, 'frozen', False):
                # 如果是打包后的exe
                matplotlib.use('Agg')
            
            import matplotlib.pyplot as plt
            import numpy as np
            from matplotlib.backends.backend_pdf import PdfPages
            
            # 设置matplotlib中文字体
            plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC", "Arial Unicode MS", "sans-serif"]
            plt.rcParams["axes.unicode_minus"] = False
            
            # 将相对路径转换为绝对路径（确保在exe环境中也能正确工作）
            output_file = Path(output_path)
            if not output_file.is_absolute():
                # 如果是相对路径，基于当前工作目录或exe所在目录
                import os
                if getattr(sys, 'frozen', False):
                    # exe环境：使用exe所在目录
                    base_dir = Path(sys.executable).parent
                else:
                    # 开发环境：使用当前工作目录
                    base_dir = Path.cwd()
                output_file = base_dir / output_path
                output_path = str(output_file)
            
            # 确保输出目录存在
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            ctx.log_info(f"PDF输出路径（绝对路径）: {output_path}")
            
            with PdfPages(output_path) as pdf:
                # 第一页：TN曲线（转速-扭矩关系）
                # 转速取绝对值，然后从小到大排序
                rpm_abs = [abs(rpm) for rpm in rpm_data]
                
                # 将数据配对并按转速绝对值排序
                data_pairs = list(zip(rpm_abs, sensor_torque_data))
                data_pairs_sorted = sorted(data_pairs, key=lambda x: x[0])
                rpm_sorted, torque_sorted = zip(*data_pairs_sorted) if data_pairs_sorted else ([], [])
                
                torque_list = list(torque_sorted)
                
                # 使用更强的滤波组合去除毛刺（数据已在读取时应用中值滤波，但排序后需要再次滤波）：
                # 1. 先应用中值滤波去除异常值和毛刺（排序后可能产生新的毛刺）
                torque_median_filtered = self._sliding_median_filter(torque_list, filter_window_size)
                # 2. 再次应用中值滤波，进一步去除毛刺
                torque_median_filtered = self._sliding_median_filter(torque_median_filtered, max(5, filter_window_size - 2))
                # 3. 应用滑动平均滤波进一步平滑
                torque_filtered = self._moving_average_filter(torque_median_filtered, filter_window_size)
                # 4. 如果数据点较多，再次应用滑动平均以进一步平滑
                if len(torque_filtered) > 100:
                    torque_filtered = self._moving_average_filter(torque_filtered, max(5, filter_window_size - 2))
                
                # 参考曲线数据点（转速, 扭矩）
                reference_rpm = [60, 200, 245, 280, 300, 320, 350, 360]
                reference_torque = [17, 17, 15, 12, 10, 8, 4, 2]
                
                # 计算上下限曲线（如果提供了low和high参数）
                reference_torque_low = None
                reference_torque_high = None
                if low_offset is not None:
                    reference_torque_low = [max(0, t - low_offset) for t in reference_torque]  # 确保不为负
                if high_offset is not None:
                    reference_torque_high = [t + high_offset for t in reference_torque]
                
                plt.figure(figsize=(10, 6))
                # 绘制滤波后的曲线（更平滑，去除毛刺）
                plt.plot(rpm_sorted, torque_filtered, 'b-', linewidth=2, label='滤波后实测TN曲线')
                # 绘制参考曲线（红色虚线，参考原始参考TN曲线）
                plt.plot(reference_rpm, reference_torque, 'r--', linewidth=2, label='参考TN曲线')
                # 绘制下限曲线（如果设置了low）
                if reference_torque_low is not None:
                    plt.plot(reference_rpm, reference_torque_low, 'g--', linewidth=1.5, alpha=0.7, label=f'下限曲线 (参考-{low_offset}Nm)')
                # 绘制上限曲线（如果设置了high）
                if reference_torque_high is not None:
                    plt.plot(reference_rpm, reference_torque_high, 'orange', linestyle='--', linewidth=1.5, alpha=0.7, label=f'上限曲线 (参考+{high_offset}Nm)')
                
                plt.title('TN曲线（转速-扭矩关系）')
                plt.xlabel('转速 (RPM)')
                plt.ylabel('扭矩传感器数据 (Nm)')
                plt.grid(True)
                plt.legend()
                plt.tight_layout()
                pdf.savefig()
                plt.close()
                
                # 第二页：静态扭矩比例曲线（电机反馈扭矩/传感器扭矩）
                # 计算扭矩比值
                valid_indices = [i for i, t in enumerate(sensor_torque_data) if abs(t) > 1e-6]
                
                if not valid_indices:
                    ctx.log_warning("无法计算扭矩比值，传感器扭矩数据全部接近零")
                    return False
                
                sensor_torque_valid = [sensor_torque_data[i] for i in valid_indices]
                motor_torque_valid = [motor_torque_data[i] for i in valid_indices]
                
                # 传感器扭矩和电机扭矩全部取绝对值
                sensor_torque_abs = [abs(t) for t in sensor_torque_valid]
                motor_torque_abs = [abs(t) for t in motor_torque_valid]
                
                # 计算比值（使用绝对值）
                torque_ratio = [motor_torque_abs[i] / sensor_torque_abs[i] 
                               if sensor_torque_abs[i] > 1e-6 else 0.0
                               for i in range(len(sensor_torque_abs))]
                
                # 对比值取绝对值
                torque_ratio_abs = [abs(ratio) for ratio in torque_ratio]
                
                # 过滤掉比值大于5的异常值（因为比值已经是绝对值，只需要过滤大于5的值）
                ratio_filtered_indices = [i for i, ratio in enumerate(torque_ratio_abs) 
                                         if ratio <= 5.0]
                
                if not ratio_filtered_indices:
                    ctx.log_warning("过滤后没有有效的扭矩比值数据（所有比值都在[-5, 5]范围外）")
                    return False
                
                # 过滤后的数据（使用绝对值）
                sensor_torque_filtered = [sensor_torque_abs[i] for i in ratio_filtered_indices]
                motor_torque_filtered = [motor_torque_abs[i] for i in ratio_filtered_indices]
                torque_ratio_filtered = [torque_ratio_abs[i] for i in ratio_filtered_indices]
                
                ctx.log_info(f"扭矩比值过滤：原始数据点={len(torque_ratio_abs)}, 过滤后={len(torque_ratio_filtered)}, 移除异常值={len(torque_ratio_abs) - len(torque_ratio_filtered)}")
                
                # 对过滤后的比值应用中值滤波，去除剩余毛刺
                torque_ratio_median = self._sliding_median_filter(torque_ratio_filtered, filter_window_size)
                # 应用滑动平均滤波进一步平滑
                filtered_ratio = self._moving_average_filter(torque_ratio_median, filter_window_size)
                
                # 确保所有比值都是绝对值（双重保险）
                torque_ratio_filtered = [abs(r) for r in torque_ratio_filtered]
                filtered_ratio = [abs(r) for r in filtered_ratio]
                
                # 获取过滤后扭矩的量程（参考图2，从0到最大扭矩值）
                min_torque = 0.0
                max_torque = max(sensor_torque_filtered) if sensor_torque_filtered else 1.0
                
                plt.figure(figsize=(10, 6))
                # 绘制过滤后的原始比值和滤波后的曲线（确保都是绝对值）
                plt.plot(sensor_torque_filtered, torque_ratio_filtered, 'r.', alpha=0.5, label='原始比值（已过滤异常值，绝对值）')
                plt.plot(sensor_torque_filtered, filtered_ratio, 'g-', linewidth=2, 
                        label=f'中值+滑动平均滤波 (窗口={filter_window_size})')
                
                # 添加理想曲线（比值为1）
                plt.plot([min_torque, max_torque], [1, 1], 'k--', linewidth=1.5, label='理想比值 (1.0)')
                
                # 绘制上下限曲线（如果提供了ratio_low和ratio_high参数）
                if ratio_low is not None:
                    # 下限曲线：水平线，y = ratio_low
                    plt.plot([min_torque, max_torque], [ratio_low, ratio_low], 'g--', linewidth=1.5, alpha=0.7, label=f'下限曲线 ({ratio_low})')
                if ratio_high is not None:
                    # 上限曲线：水平线，y = ratio_high
                    plt.plot([min_torque, max_torque], [ratio_high, ratio_high], 'orange', linestyle='--', linewidth=1.5, alpha=0.7, label=f'上限曲线 ({ratio_high})')
                
                # 设置X轴范围从0开始到最大扭矩值
                plt.xlim(min_torque, max_torque * 1.05)  # 留5%的边距
                
                plt.title('静态扭矩比例曲线（电机反馈扭矩/传感器扭矩）')
                plt.xlabel('传感器扭矩 (Nm)')
                plt.ylabel('扭矩比值')
                plt.grid(True)
                plt.legend()
                plt.tight_layout()
                pdf.savefig()
                plt.close()
            
            return True
            
        except ImportError as e:
            ctx.log_error(f"缺少必要的库: {e}，请安装 matplotlib 和 numpy")
            return False
        except Exception as e:
            ctx.log_error(f"生成PDF报告时出错: {e}", exc_info=True)
            return False
    
    def _sliding_median_filter(self, data, window_size=5):
        """滑动中值滤波器，用于去除毛刺和异常值"""
        if len(data) <= 1:
            return data.copy()
        
        # 确保窗口大小为奇数
        window_size = window_size if window_size % 2 == 1 else window_size + 1
        window_size = max(3, min(window_size, len(data)))  # 限制窗口大小范围
        
        filtered = []
        for i in range(len(data)):
            # 计算窗口边界
            start = max(0, i - window_size // 2)
            end = min(len(data), i + window_size // 2 + 1)
            window = data[start:end]
            # 计算中值
            filtered.append(sorted(window)[len(window) // 2])
        return filtered
    
    def _moving_average_filter(self, data, window_size=5):
        """滑动平均滤波器"""
        if len(data) <= window_size:
            return data.copy()
        
        # 确保窗口大小为奇数
        window_size = window_size if window_size % 2 == 1 else window_size + 1
        window_size = max(3, min(window_size, len(data)))  # 限制窗口大小范围
        
        filtered = []
        for i in range(len(data)):
            start = max(0, i - window_size // 2)
            end = min(len(data), i + window_size // 2 + 1)
            window = data[start:end]
            filtered.append(sum(window) / len(window))
        return filtered
    
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
            return default
    
    def _resolve_float_param(self, value: Any, ctx: Context, default = None):
        """解析浮点数参数，支持变量替换，支持None值"""
        if value is None:
            return default
        try:
            if isinstance(value, str):
                value = self._replace_variables(value, ctx)
                if value.lower() in ['none', 'null', '']:
                    return default
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def _replace_variables(self, text: str, ctx: Context) -> str:
        """替换文本中的变量引用"""
        import re
        pattern = r'\$\{([^}]+)\}'
        
        def replace_var(match):
            var_name = match.group(1)
            if var_name == "sn":
                value = ctx.get_sn()
                ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                return value
            elif var_name.startswith("context."):
                # 从上下文状态获取
                key = var_name[8:]  # 去掉 "context." 前缀
                value = ctx.get_data(key, "")
                if value:
                    ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                    return str(value)
            else:
                # 尝试从上下文状态直接获取
                value = ctx.get_data(var_name, "")
                if value:
                    ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                    return str(value)
            ctx.log_warning(f"未找到变量: ${{{var_name}}}")
            return match.group(0)
        
        return re.sub(pattern, replace_var, text)


class JudgeTorqueRatioStep(BaseStep):
    """静态扭矩比例曲线判断步骤 - 判断滤波后的曲线是否在指定区间内"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        判断静态扭矩比例曲线中，传感器扭矩>=5.0Nm后，滤波后的曲线是否在[Low, High]区间内
        
        参数：
        - csv_path: CSV文件路径（支持变量替换，如 ${sn}）
        - filter_window_size: 滤波窗口大小（默认9）
        - torque_threshold: 传感器扭矩阈值（默认5.0，只判断此值之后的数据）
        - low: 下限值（默认0.9）
        - high: 上限值（默认1.1）
        """
        try:
            # 解析参数
            csv_path = self._resolve_str_param(params.get("csv_path", ""), ctx)
            filter_window_size = self._resolve_int_param(params.get("filter_window_size", 9), ctx, default=9)
            torque_threshold = self._resolve_float_param(params.get("torque_threshold", 5.0), ctx, default=5.0)
            low = self._resolve_float_param(params.get("low", 0.9), ctx, default=0.9)
            high = self._resolve_float_param(params.get("high", 1.1), ctx, default=1.1)
            
            if not csv_path:
                return StepResult(
                    passed=False,
                    message="CSV文件路径为空",
                    error="csv_path参数未指定",
                    error_code="JUDGE_TORQUE_RATIO_ERR_NO_CSV_PATH"
                )
            
            # 检查CSV文件是否存在
            csv_file = Path(csv_path)
            if not csv_file.exists():
                return StepResult(
                    passed=False,
                    message=f"CSV文件不存在: {csv_path}",
                    error=f"文件不存在: {csv_path}",
                    error_code="JUDGE_TORQUE_RATIO_ERR_CSV_NOT_FOUND"
                )
            
            if low >= high:
                return StepResult(
                    passed=False,
                    message="参数错误：low必须小于high",
                    error=f"low={low}, high={high}",
                    error_code="JUDGE_TORQUE_RATIO_ERR_INVALID_RANGE"
                )
            
            ctx.log_info(f"开始判断静态扭矩比例曲线: {csv_path}, 扭矩阈值={torque_threshold}Nm, 区间=[{low}, {high}]")
            
            # 读取CSV数据
            rpm_data, sensor_torque_data, motor_torque_data = self._read_csv_data_for_ratio(csv_file, ctx)
            
            if len(sensor_torque_data) < 2:
                return StepResult(
                    passed=False,
                    message="CSV文件中有效数据点不足",
                    error=f"只有 {len(sensor_torque_data)} 个有效数据点",
                    error_code="JUDGE_TORQUE_RATIO_ERR_INSUFFICIENT_DATA"
                )
            
            # 对扭矩传感器数据应用中值滤波
            if len(sensor_torque_data) > 0:
                ctx.log_info(f"对扭矩传感器数据应用中值滤波（窗口大小: {filter_window_size}）")
                sensor_torque_data = self._sliding_median_filter(sensor_torque_data, filter_window_size)
            
            # 计算扭矩比值（与PDF生成步骤相同的逻辑）
            valid_indices = [i for i, t in enumerate(sensor_torque_data) if abs(t) > 1e-6]
            
            if not valid_indices:
                return StepResult(
                    passed=False,
                    message="无法计算扭矩比值，传感器扭矩数据全部接近零",
                    error="传感器扭矩数据无效",
                    error_code="JUDGE_TORQUE_RATIO_ERR_NO_VALID_TORQUE"
                )
            
            sensor_torque_valid = [sensor_torque_data[i] for i in valid_indices]
            motor_torque_valid = [motor_torque_data[i] for i in valid_indices]
            
            # 传感器扭矩和电机扭矩全部取绝对值
            sensor_torque_abs = [abs(t) for t in sensor_torque_valid]
            motor_torque_abs = [abs(t) for t in motor_torque_valid]
            
            # 计算比值（使用绝对值）
            torque_ratio = [motor_torque_abs[i] / sensor_torque_abs[i] 
                           if sensor_torque_abs[i] > 1e-6 else 0.0
                           for i in range(len(sensor_torque_abs))]
            
            # 对比值取绝对值
            torque_ratio_abs = [abs(ratio) for ratio in torque_ratio]
            
            # 过滤掉比值大于5的异常值
            ratio_filtered_indices = [i for i, ratio in enumerate(torque_ratio_abs) 
                                     if ratio <= 5.0]
            
            if not ratio_filtered_indices:
                return StepResult(
                    passed=False,
                    message="过滤后没有有效的扭矩比值数据",
                    error="所有比值都在[0, 5]范围外",
                    error_code="JUDGE_TORQUE_RATIO_ERR_NO_VALID_RATIO"
                )
            
            # 过滤后的数据（使用绝对值）
            sensor_torque_filtered = [sensor_torque_abs[i] for i in ratio_filtered_indices]
            motor_torque_filtered = [motor_torque_abs[i] for i in ratio_filtered_indices]
            torque_ratio_filtered = [torque_ratio_abs[i] for i in ratio_filtered_indices]
            
            # 对过滤后的比值应用中值滤波，去除剩余毛刺
            torque_ratio_median = self._sliding_median_filter(torque_ratio_filtered, filter_window_size)
            # 应用滑动平均滤波进一步平滑
            filtered_ratio = self._moving_average_filter(torque_ratio_median, filter_window_size)
            
            # 确保所有比值都是绝对值
            filtered_ratio = [abs(r) for r in filtered_ratio]
            
            # 过滤出传感器扭矩>=torque_threshold的数据点
            threshold_indices = [i for i, torque in enumerate(sensor_torque_filtered) 
                               if torque >= torque_threshold]
            
            if not threshold_indices:
                return StepResult(
                    passed=False,
                    message=f"没有传感器扭矩>={torque_threshold}Nm的数据点",
                    error=f"最大传感器扭矩={max(sensor_torque_filtered) if sensor_torque_filtered else 0:.2f}Nm",
                    error_code="JUDGE_TORQUE_RATIO_ERR_NO_THRESHOLD_DATA"
                )
            
            # 判断这些点的比值是否都在[low, high]区间内
            passed = True
            failed_points = []
            
            # 计算5Nm后的平均值（用于Value列显示）
            ratio_values_above_threshold = []
            
            for i in threshold_indices:
                ratio_value = filtered_ratio[i]
                sensor_torque_value = sensor_torque_filtered[i]
                
                # 收集所有>=5Nm的比值用于计算平均值
                ratio_values_above_threshold.append(ratio_value)
                
                if not (low <= ratio_value <= high):
                    passed = False
                    failed_points.append({
                        'sensor_torque': sensor_torque_value,
                        'ratio': ratio_value,
                        'out_of_range': 'below' if ratio_value < low else 'above'
                    })
            
            # 计算平均值
            avg_ratio_above_threshold = 0.0
            if ratio_values_above_threshold:
                avg_ratio_above_threshold = sum(ratio_values_above_threshold) / len(ratio_values_above_threshold)
            
            if passed:
                ctx.log_info(f"✓ 静态扭矩比例曲线判断通过：传感器扭矩>={torque_threshold}Nm的所有点都在[{low}, {high}]区间内，平均值={avg_ratio_above_threshold:.3f}")
                return StepResult(
                    passed=True,
                    message=f"静态扭矩比例曲线判断通过：所有点都在[{low}, {high}]区间内",
                    data={
                        "csv_path": csv_path,
                        "torque_threshold": torque_threshold,
                        "low": low,
                        "high": high,
                        "total_points": len(threshold_indices),
                        "judgment": "pass",
                        # 用于UI显示的值
                        "value": round(avg_ratio_above_threshold, 3),  # 显示5Nm后的平均值
                        "avg_ratio": avg_ratio_above_threshold
                    }
                )
            else:
                # 找到最严重的失败点
                worst_point = min(failed_points, key=lambda x: abs(x['ratio'] - (low + high) / 2))
                error_msg = f"静态扭矩比例曲线判断失败：有 {len(failed_points)} 个点不在[{low}, {high}]区间内。最严重点在传感器扭矩={worst_point['sensor_torque']:.2f}Nm，比值={worst_point['ratio']:.3f}，超出范围：{worst_point['out_of_range']}"
                ctx.log_error(f"✗ {error_msg}")
                return StepResult(
                    passed=False,
                    message=f"静态扭矩比例曲线判断失败：有 {len(failed_points)} 个点不在[{low}, {high}]区间内",
                    error=error_msg,
                    error_code="JUDGE_TORQUE_RATIO_ERR_OUT_OF_RANGE",
                    data={
                        "csv_path": csv_path,
                        "torque_threshold": torque_threshold,
                        "low": low,
                        "high": high,
                        "total_points": len(threshold_indices),
                        "failed_points_count": len(failed_points),
                        "worst_point": worst_point,
                        "judgment": "fail",
                        # 用于UI显示的值
                        "value": round(avg_ratio_above_threshold, 3),  # 失败时也显示5Nm后的平均值
                        "avg_ratio": avg_ratio_above_threshold
                    }
                )
                
        except Exception as e:
            ctx.log_error(f"静态扭矩比例曲线判断步骤异常: {e}", exc_info=True)
            return StepResult(
                passed=False,
                message=f"静态扭矩比例曲线判断步骤异常: {e}",
                error=str(e),
                error_code="JUDGE_TORQUE_RATIO_ERR_EXCEPTION"
            )
    
    def _read_csv_data_for_ratio(self, csv_file: Path, ctx: Context):
        """读取CSV数据用于扭矩比值计算（需要电机扭矩数据）"""
        rpm_data = []
        sensor_torque_data = []
        motor_torque_data = []
        
        data_started = False
        velocity_threshold = 0.1
        skipped_count = 0
        total_count = 0
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    total_count += 1
                    try:
                        velocity_rads = float(row.get('角速度(rad/s)', 0))
                        rpm = velocity_rads * 60 / (2 * 3.14159265359)
                        sensor_torque = float(row.get('扭矩仪(Nm)', 0))
                        motor_torque = float(row.get('扭矩(Nm)', 0))
                        is_running = int(row.get('运行', 0)) == 1
                        should_start = abs(velocity_rads) > velocity_threshold
                        
                        if not data_started:
                            if should_start:
                                data_started = True
                                ctx.log_info(f"检测到电机开始运行：角速度={velocity_rads:.2f} rad/s, RPM={rpm:.2f}")
                            else:
                                skipped_count += 1
                                continue
                        
                        if data_started:
                            if abs(velocity_rads) > velocity_threshold:
                                rpm_data.append(rpm)
                                sensor_torque_data.append(sensor_torque)
                                motor_torque_data.append(motor_torque)
                    except (ValueError, KeyError) as e:
                        ctx.log_warning(f"跳过无效数据行: {e}")
                        skipped_count += 1
                        continue
        except Exception as e:
            ctx.log_error(f"读取CSV文件失败: {e}", exc_info=True)
            raise
        
        ctx.log_info(f"CSV数据统计：总行数={total_count}, 跳过={skipped_count}, 有效数据点={len(rpm_data)}")
        return rpm_data, sensor_torque_data, motor_torque_data
    
    def _resolve_float_param(self, value: Any, ctx: Context, default: float = 0.0) -> float:
        """解析浮点数参数，支持变量替换"""
        try:
            if isinstance(value, str):
                value = self._replace_variables(value, ctx)
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def _sliding_median_filter(self, data, window_size=5):
        """滑动中值滤波器（复用PDF生成步骤的方法）"""
        if len(data) <= 1:
            return data.copy()
        
        window_size = window_size if window_size % 2 == 1 else window_size + 1
        window_size = max(3, min(window_size, len(data)))
        
        filtered = []
        for i in range(len(data)):
            start = max(0, i - window_size // 2)
            end = min(len(data), i + window_size // 2 + 1)
            window = data[start:end]
            filtered.append(sorted(window)[len(window) // 2])
        return filtered
    
    def _moving_average_filter(self, data, window_size=5):
        """滑动平均滤波器（复用PDF生成步骤的方法）"""
        if len(data) <= window_size:
            return data.copy()
        
        window_size = window_size if window_size % 2 == 1 else window_size + 1
        window_size = max(3, min(window_size, len(data)))
        
        filtered = []
        for i in range(len(data)):
            start = max(0, i - window_size // 2)
            end = min(len(data), i + window_size // 2 + 1)
            window = data[start:end]
            filtered.append(sum(window) / len(window))
        return filtered
    
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
            return default
    
    def _replace_variables(self, text: str, ctx: Context) -> str:
        """替换文本中的变量引用"""
        import re
        pattern = r'\$\{([^}]+)\}'
        
        def replace_var(match):
            var_name = match.group(1)
            if var_name == "sn":
                value = ctx.get_sn()
                return value if value else match.group(0)
            elif var_name.startswith("context."):
                key = var_name[8:]
                value = ctx.get_data(key, "")
                return str(value) if value else match.group(0)
            else:
                value = ctx.get_data(var_name, "")
                return str(value) if value else match.group(0)
        
        return re.sub(pattern, replace_var, text)


class JudgeTNCurveStep(BaseStep):
    """TN曲线判断步骤 - 判断滤波后的实测曲线是否在参考曲线上方"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        判断TN曲线中滤波后的实测曲线是否在参考曲线的指定范围内
        
        参数：
        - csv_path: CSV文件路径（支持变量替换，如 ${sn}）
        - filter_window_size: 滤波窗口大小（默认9）
        - low: 下限扭矩偏移量（Nm，默认0，表示参考曲线向下偏移的扭矩值）
        - high: 上限扭矩偏移量（Nm，默认None，表示参考曲线向上偏移的扭矩值）
        
        判断逻辑：
        - 当low=1时，下限曲线 = 参考曲线 - 1Nm（参考曲线向下偏移1Nm）
        - 当high=2时，上限曲线 = 参考曲线 + 2Nm（参考曲线向上偏移2Nm）
        - 判断滤波后的实测TN曲线是否在下限和上限之间
        """
        try:
            # 解析参数
            csv_path = self._resolve_str_param(params.get("csv_path", ""), ctx)
            filter_window_size = self._resolve_int_param(params.get("filter_window_size", 9), ctx, default=9)
            # low和high是扭矩偏移量（Nm），不是百分比
            low_offset = self._resolve_float_param(params.get("low", 0), ctx, default=0)
            high_offset = self._resolve_float_param(params.get("high", None), ctx, default=None)
            
            if not csv_path:
                return StepResult(
                    passed=False,
                    message="CSV文件路径为空",
                    error="csv_path参数未指定",
                    error_code="JUDGE_TN_ERR_NO_CSV_PATH"
                )
            
            # 检查CSV文件是否存在
            csv_file = Path(csv_path)
            if not csv_file.exists():
                return StepResult(
                    passed=False,
                    message=f"CSV文件不存在: {csv_path}",
                    error=f"文件不存在: {csv_path}",
                    error_code="JUDGE_TN_ERR_CSV_NOT_FOUND"
                )
            
            ctx.log_info(f"开始判断TN曲线: {csv_path}")
            
            # 读取CSV数据（复用PDF生成步骤的逻辑）
            rpm_data, sensor_torque_data = self._read_csv_data(csv_file, ctx)
            
            if len(rpm_data) < 2:
                return StepResult(
                    passed=False,
                    message="CSV文件中有效数据点不足",
                    error=f"只有 {len(rpm_data)} 个有效数据点",
                    error_code="JUDGE_TN_ERR_INSUFFICIENT_DATA"
                )
            
            # 对扭矩传感器数据应用中值滤波
            if len(sensor_torque_data) > 0:
                ctx.log_info(f"对扭矩传感器数据应用中值滤波（窗口大小: {filter_window_size}）")
                sensor_torque_data = self._sliding_median_filter(sensor_torque_data, filter_window_size)
            
            # 处理数据：转速取绝对值，排序，滤波（与PDF生成步骤相同）
            rpm_abs = [abs(rpm) for rpm in rpm_data]
            data_pairs = list(zip(rpm_abs, sensor_torque_data))
            data_pairs_sorted = sorted(data_pairs, key=lambda x: x[0])
            rpm_sorted, torque_sorted = zip(*data_pairs_sorted) if data_pairs_sorted else ([], [])
            
            torque_list = list(torque_sorted)
            rpm_list = list(rpm_sorted)
            
            # 应用滤波（与PDF生成步骤相同的处理）
            torque_median_filtered = self._sliding_median_filter(torque_list, filter_window_size)
            torque_median_filtered = self._sliding_median_filter(torque_median_filtered, max(5, filter_window_size - 2))
            torque_filtered = self._moving_average_filter(torque_median_filtered, filter_window_size)
            if len(torque_filtered) > 100:
                torque_filtered = self._moving_average_filter(torque_filtered, max(5, filter_window_size - 2))
            
            # 参考曲线数据点（与PDF生成步骤相同）
            reference_rpm = [60, 200, 245, 280, 300, 320, 350, 360]
            reference_torque = [17, 17, 15, 12, 10, 8, 4, 2]
            
            # 计算下限参考曲线（参考曲线向下偏移low_offset Nm）
            reference_torque_low = [max(0, t - low_offset) for t in reference_torque]  # 确保不为负
            
            # 计算上限参考曲线（参考曲线向上偏移high_offset Nm）
            reference_torque_high = None
            if high_offset is not None:
                reference_torque_high = [t + high_offset for t in reference_torque]
            
            ctx.log_info(f"TN曲线判断参数：low={low_offset}Nm (参考曲线向下偏移), high={'未设置' if high_offset is None else f'{high_offset}Nm (参考曲线向上偏移)'}")
            
            # 计算偏差百分比：实测点与原始参考曲线（100%）的偏差
            deviation_percentages = []
            
            # 判断实测曲线是否在参考曲线的指定范围内
            # 只判断参考曲线定义范围内的RPM点（60-360 RPM）
            # 在实测曲线的每个转速点，使用线性插值找到参考曲线对应的扭矩值，然后比较
            passed = True
            failed_points = []
            reference_rpm_min = min(reference_rpm)  # 60
            reference_rpm_max = max(reference_rpm)  # 360
            
            ctx.log_info(f"参考曲线RPM范围: {reference_rpm_min}-{reference_rpm_max} RPM，只判断此范围内的数据点")
            
            for i, rpm in enumerate(rpm_list):
                # 只判断参考曲线定义范围内的RPM点
                if rpm < reference_rpm_min or rpm > reference_rpm_max:
                    ctx.log_debug(f"跳过RPM={rpm:.2f}的判断（超出参考曲线范围 {reference_rpm_min}-{reference_rpm_max} RPM）")
                    continue
                
                measured_torque = torque_filtered[i]
                
                # 使用线性插值找到原始参考曲线（100%）在rpm处的扭矩值，用于计算偏差百分比
                reference_torque_original_at_rpm = self._interpolate_reference_curve(
                    reference_rpm, reference_torque, rpm
                )
                
                # 计算偏差百分比：偏差% = (实测扭矩 - 参考扭矩) / 参考扭矩 * 100
                if reference_torque_original_at_rpm > 1e-6:  # 避免除以零
                    deviation_percent = ((measured_torque - reference_torque_original_at_rpm) / reference_torque_original_at_rpm) * 100.0
                    deviation_percentages.append(deviation_percent)
                
                # 使用线性插值找到下限参考曲线在rpm处的扭矩值
                reference_torque_low_at_rpm = self._interpolate_reference_curve(
                    reference_rpm, reference_torque_low, rpm
                )
                
                # 判断下限：实测扭矩应该 >= 下限参考扭矩
                if measured_torque < reference_torque_low_at_rpm:
                    passed = False
                    failed_points.append({
                        'rpm': rpm,
                        'measured_torque': measured_torque,
                        'reference_torque_low': reference_torque_low_at_rpm,
                        'difference': measured_torque - reference_torque_low_at_rpm,
                        'violation': 'below_low'
                    })
                
                # 判断上限：如果high_offset设置了，实测扭矩应该 <= 上限参考扭矩
                if high_offset is not None:
                    reference_torque_high_at_rpm = self._interpolate_reference_curve(
                        reference_rpm, reference_torque_high, rpm
                    )
                    if measured_torque > reference_torque_high_at_rpm:
                        passed = False
                        failed_points.append({
                            'rpm': rpm,
                            'measured_torque': measured_torque,
                            'reference_torque_high': reference_torque_high_at_rpm,
                            'difference': measured_torque - reference_torque_high_at_rpm,
                            'violation': 'above_high'
                        })
            
            # 计算平均偏差百分比（用于Value列显示）
            avg_deviation_percent = 0.0
            if deviation_percentages:
                avg_deviation_percent = sum(deviation_percentages) / len(deviation_percentages)
            
            if passed:
                range_desc = f"在参考曲线-{low_offset}Nm上方"
                if high_offset is not None:
                    range_desc = f"在参考曲线-{low_offset}Nm和+{high_offset}Nm之间"
                ctx.log_info(f"✓ TN曲线判断通过：滤波后的实测曲线在所有点都{range_desc}")
                return StepResult(
                    passed=True,
                    message=f"TN曲线判断通过：实测曲线{range_desc}",
                    data={
                        "csv_path": csv_path,
                        "total_points": len(rpm_list),
                        "low_offset": low_offset,
                        "high_offset": high_offset,
                        "judgment": "pass",
                        "avg_deviation_percent": avg_deviation_percent,
                        # 用于UI显示的值
                        "value": round(avg_deviation_percent, 2),  # 显示平均偏差百分比
                        "low": low_offset,  # 显示YAML配置中的low值（扭矩偏移量）
                        "high": high_offset if high_offset is not None else ""  # 显示YAML配置中的high值（扭矩偏移量）
                    }
                )
            else:
                # 找到最严重的失败点
                worst_point = min(failed_points, key=lambda x: abs(x['difference']))
                violation_desc = "低于下限" if worst_point['violation'] == 'below_low' else "高于上限"
                error_msg = f"TN曲线判断失败：有 {len(failed_points)} 个点不符合要求。最严重点在RPM={worst_point['rpm']:.2f}，实测扭矩={worst_point['measured_torque']:.2f} Nm，{violation_desc}，差值={worst_point['difference']:.2f} Nm"
                ctx.log_error(f"✗ {error_msg}")
                return StepResult(
                    passed=False,
                    message=f"TN曲线判断失败：实测曲线有 {len(failed_points)} 个点不符合要求",
                    error=error_msg,
                    error_code="JUDGE_TN_ERR_OUT_OF_RANGE",
                    data={
                        "csv_path": csv_path,
                        "total_points": len(rpm_list),
                        "failed_points_count": len(failed_points),
                        "worst_point": worst_point,
                        "low_offset": low_offset,
                        "high_offset": high_offset,
                        "judgment": "fail",
                        "avg_deviation_percent": avg_deviation_percent,
                        # 用于UI显示的值
                        "value": round(avg_deviation_percent, 2),  # 显示平均偏差百分比
                        "low": low_offset,  # 显示YAML配置中的low值（扭矩偏移量）
                        "high": high_offset if high_offset is not None else ""  # 显示YAML配置中的high值（扭矩偏移量）
                    }
                )
                
        except Exception as e:
            ctx.log_error(f"TN曲线判断步骤异常: {e}", exc_info=True)
            return StepResult(
                passed=False,
                message=f"TN曲线判断步骤异常: {e}",
                error=str(e),
                error_code="JUDGE_TN_ERR_EXCEPTION"
            )
    
    def _read_csv_data(self, csv_file: Path, ctx: Context):
        """读取CSV数据（复用PDF生成步骤的逻辑）"""
        rpm_data = []
        sensor_torque_data = []
        
        data_started = False
        velocity_threshold = 0.1
        skipped_count = 0
        total_count = 0
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    total_count += 1
                    try:
                        velocity_rads = float(row.get('角速度(rad/s)', 0))
                        rpm = velocity_rads * 60 / (2 * 3.14159265359)
                        sensor_torque = float(row.get('扭矩仪(Nm)', 0))
                        is_running = int(row.get('运行', 0)) == 1
                        should_start = abs(velocity_rads) > velocity_threshold
                        
                        if not data_started:
                            if should_start:
                                data_started = True
                                ctx.log_info(f"检测到电机开始运行：角速度={velocity_rads:.2f} rad/s, RPM={rpm:.2f}")
                            else:
                                skipped_count += 1
                                continue
                        
                        if data_started:
                            if abs(velocity_rads) > velocity_threshold:
                                rpm_data.append(rpm)
                                sensor_torque_data.append(sensor_torque)
                    except (ValueError, KeyError) as e:
                        ctx.log_warning(f"跳过无效数据行: {e}")
                        skipped_count += 1
                        continue
        except Exception as e:
            ctx.log_error(f"读取CSV文件失败: {e}", exc_info=True)
            raise
        
        ctx.log_info(f"CSV数据统计：总行数={total_count}, 跳过={skipped_count}, 有效数据点={len(rpm_data)}")
        return rpm_data, sensor_torque_data
    
    def _interpolate_reference_curve(self, reference_rpm, reference_torque, rpm):
        """使用线性插值找到参考曲线在指定rpm处的扭矩值"""
        # 如果rpm在参考曲线的转速范围之外，使用边界值
        if rpm <= reference_rpm[0]:
            return reference_torque[0]
        if rpm >= reference_rpm[-1]:
            return reference_torque[-1]
        
        # 使用线性插值：找到rpm所在的两个参考点之间的位置
        for i in range(len(reference_rpm) - 1):
            if reference_rpm[i] <= rpm <= reference_rpm[i + 1]:
                # 线性插值公式：y = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
                x1, y1 = reference_rpm[i], reference_torque[i]
                x2, y2 = reference_rpm[i + 1], reference_torque[i + 1]
                if x2 == x1:
                    return y1  # 避免除零
                return y1 + (y2 - y1) * (rpm - x1) / (x2 - x1)
        
        # 如果找不到（理论上不应该发生），返回最后一个值
        return reference_torque[-1]
    
    def _sliding_median_filter(self, data, window_size=5):
        """滑动中值滤波器（复用PDF生成步骤的方法）"""
        if len(data) <= 1:
            return data.copy()
        
        window_size = window_size if window_size % 2 == 1 else window_size + 1
        window_size = max(3, min(window_size, len(data)))
        
        filtered = []
        for i in range(len(data)):
            start = max(0, i - window_size // 2)
            end = min(len(data), i + window_size // 2 + 1)
            window = data[start:end]
            filtered.append(sorted(window)[len(window) // 2])
        return filtered
    
    def _moving_average_filter(self, data, window_size=5):
        """滑动平均滤波器（复用PDF生成步骤的方法）"""
        if len(data) <= window_size:
            return data.copy()
        
        window_size = window_size if window_size % 2 == 1 else window_size + 1
        window_size = max(3, min(window_size, len(data)))
        
        filtered = []
        for i in range(len(data)):
            start = max(0, i - window_size // 2)
            end = min(len(data), i + window_size // 2 + 1)
            window = data[start:end]
            filtered.append(sum(window) / len(window))
        return filtered
    
    def _resolve_str_param(self, value: Any, ctx: Context) -> str:
        """解析字符串参数并进行变量替换（复用PDF生成步骤的方法）"""
        if isinstance(value, str):
            return self._replace_variables(value, ctx)
        return str(value)
    
    def _resolve_int_param(self, value: Any, ctx: Context, default: int = 0) -> int:
        """解析整数参数，支持变量替换（复用PDF生成步骤的方法）"""
        try:
            if isinstance(value, str):
                value = self._replace_variables(value, ctx)
            return int(value)
        except (ValueError, TypeError):
            return default
    
    def _resolve_float_param(self, value: Any, ctx: Context, default = None):
        """解析浮点数参数，支持变量替换，支持None值"""
        if value is None:
            return default
        try:
            if isinstance(value, str):
                value = self._replace_variables(value, ctx)
                if value.lower() in ['none', 'null', '']:
                    return default
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def _replace_variables(self, text: str, ctx: Context) -> str:
        """替换文本中的变量引用（复用PDF生成步骤的方法）"""
        import re
        pattern = r'\$\{([^}]+)\}'
        
        def replace_var(match):
            var_name = match.group(1)
            if var_name == "sn":
                value = ctx.get_sn()
                return value if value else match.group(0)
            elif var_name.startswith("context."):
                key = var_name[8:]
                value = ctx.get_data(key, "")
                return str(value) if value else match.group(0)
            else:
                value = ctx.get_data(var_name, "")
                return str(value) if value else match.group(0)
        
        return re.sub(pattern, replace_var, text)

