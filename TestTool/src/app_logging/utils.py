"""
日志工具函数
"""

import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import json


def ensure_log_directory(log_path: Path) -> bool:
    """确保日志目录存在"""
    try:
        log_path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        print(f"创建日志目录失败: {log_path}, 错误: {e}")
        return False


def get_log_file_path(base_dir: str, log_type: str, date_format: str, 
                     filename_format: str, **kwargs) -> str:
    """生成日志文件路径"""
    base_path = Path(base_dir)
    log_type_path = base_path / log_type
    date_folder = datetime.now().strftime(date_format)
    full_path = log_type_path / date_folder
    
    # 确保目录存在
    ensure_log_directory(full_path)
    
    # 生成文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = filename_format.format(timestamp=timestamp, **kwargs)
    
    return str(full_path / filename)


def parse_log_filename(filename: str) -> Dict[str, str]:
    """解析日志文件名，提取信息"""
    try:
        # 测试结果日志格式: {SN}-{station}-{port}-{timestamp}-{result}.log
        # 错误日志格式: {SN}-{station}-{port}-{timestamp}.log
        parts = filename.replace('.log', '').split('-')
        
        if len(parts) >= 4:
            result = {
                'sn': parts[0],
                'station': parts[1],
                'port': parts[2],
                'timestamp': parts[3],
                'result': parts[4] if len(parts) > 4 else None
            }
            return result
    except Exception:
        pass
    
    return {}


def get_log_files_by_date(log_dir: Path, date: str = None) -> List[Path]:
    """获取指定日期的日志文件"""
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    
    date_path = log_dir / date
    if not date_path.exists():
        return []
    
    return list(date_path.glob("*.log"))


def get_log_files_by_sn(log_dir: Path, sn: str) -> List[Path]:
    """获取指定SN的日志文件"""
    log_files = []
    
    # 遍历所有日期文件夹
    for date_folder in log_dir.iterdir():
        if date_folder.is_dir():
            for log_file in date_folder.glob("*.log"):
                if sn in log_file.name:
                    log_files.append(log_file)
    
    return log_files


def get_log_files_by_port(log_dir: Path, port: str) -> List[Path]:
    """获取指定端口的日志文件"""
    log_files = []
    
    # 遍历所有日期文件夹
    for date_folder in log_dir.iterdir():
        if date_folder.is_dir():
            for log_file in date_folder.glob("*.log"):
                if f"-{port}-" in log_file.name:
                    log_files.append(log_file)
    
    return log_files


def cleanup_old_logs(log_dir: Path, days: int = 14) -> int:
    """清理过期日志文件"""
    cutoff_date = datetime.now() - timedelta(days=days)
    cleaned_count = 0
    
    try:
        for date_folder in log_dir.iterdir():
            if date_folder.is_dir():
                try:
                    # 解析日期文件夹名称
                    folder_date = datetime.strptime(date_folder.name, "%Y%m%d")
                    if folder_date < cutoff_date:
                        import shutil
                        shutil.rmtree(date_folder)
                        cleaned_count += 1
                        print(f"已清理过期日志文件夹: {date_folder}")
                except ValueError:
                    # 不是日期格式的文件夹，跳过
                    continue
    except Exception as e:
        print(f"清理日志文件时出错: {e}")
    
    return cleaned_count


def get_log_statistics(log_dir: Path, days: int = 7) -> Dict[str, Any]:
    """获取日志统计信息"""
    stats = {
        'total_files': 0,
        'total_size': 0,
        'by_date': {},
        'by_type': {'test': 0, 'error': 0, 'system': 0},
        'by_result': {'PASS': 0, 'FAIL': 0, 'RUNNING': 0},
        'error_count': 0
    }
    
    cutoff_date = datetime.now() - timedelta(days=days)
    
    try:
        for date_folder in log_dir.iterdir():
            if date_folder.is_dir():
                try:
                    folder_date = datetime.strptime(date_folder.name, "%Y%m%d")
                    if folder_date >= cutoff_date:
                        date_stats = {
                            'files': 0,
                            'size': 0,
                            'test_files': 0,
                            'error_files': 0,
                            'pass_count': 0,
                            'fail_count': 0
                        }
                        
                        for log_file in date_folder.glob("*.log"):
                            file_size = log_file.stat().st_size
                            date_stats['files'] += 1
                            date_stats['size'] += file_size
                            stats['total_files'] += 1
                            stats['total_size'] += file_size
                            
                            # 按类型统计
                            if "TestResult" in str(log_file.parent):
                                stats['by_type']['test'] += 1
                                date_stats['test_files'] += 1
                            elif "ErrorLog" in str(log_file.parent):
                                stats['by_type']['error'] += 1
                                date_stats['error_files'] += 1
                            elif "System" in str(log_file.parent):
                                stats['by_type']['system'] += 1
                            
                            # 按结果统计
                            filename_info = parse_log_filename(log_file.name)
                            if filename_info.get('result'):
                                result = filename_info['result']
                                if result in stats['by_result']:
                                    stats['by_result'][result] += 1
                                    if result == 'PASS':
                                        date_stats['pass_count'] += 1
                                    elif result == 'FAIL':
                                        date_stats['fail_count'] += 1
                        
                        stats['by_date'][date_folder.name] = date_stats
                        
                except ValueError:
                    continue
    except Exception as e:
        print(f"获取日志统计信息时出错: {e}")
    
    return stats


def search_logs(log_dir: Path, search_term: str, log_type: str = None, 
                date_range: Tuple[str, str] = None) -> List[Dict[str, Any]]:
    """搜索日志文件内容"""
    results = []
    
    try:
        for date_folder in log_dir.iterdir():
            if date_folder.is_dir():
                # 检查日期范围
                if date_range:
                    try:
                        folder_date = datetime.strptime(date_folder.name, "%Y%m%d")
                        start_date = datetime.strptime(date_range[0], "%Y%m%d")
                        end_date = datetime.strptime(date_range[1], "%Y%m%d")
                        if not (start_date <= folder_date <= end_date):
                            continue
                    except ValueError:
                        continue
                
                for log_file in date_folder.glob("*.log"):
                    # 检查日志类型
                    if log_type:
                        if log_type == "test" and "TestResult" not in str(log_file.parent):
                            continue
                        elif log_type == "error" and "ErrorLog" not in str(log_file.parent):
                            continue
                        elif log_type == "system" and "System" not in str(log_file.parent):
                            continue
                    
                    try:
                        with open(log_file, 'r', encoding='utf-8') as f:
                            for line_num, line in enumerate(f, 1):
                                if search_term.lower() in line.lower():
                                    results.append({
                                        'file': str(log_file),
                                        'line': line_num,
                                        'content': line.strip(),
                                        'date': date_folder.name,
                                        'filename_info': parse_log_filename(log_file.name)
                                    })
                    except Exception as e:
                        print(f"读取日志文件失败: {log_file}, 错误: {e}")
    except Exception as e:
        print(f"搜索日志时出错: {e}")
    
    return results


def export_logs_to_json(log_dir: Path, output_file: str, 
                       date_range: Tuple[str, str] = None) -> bool:
    """导出日志到JSON文件"""
    try:
        all_logs = []
        
        for date_folder in log_dir.iterdir():
            if date_folder.is_dir():
                # 检查日期范围
                if date_range:
                    try:
                        folder_date = datetime.strptime(date_folder.name, "%Y%m%d")
                        start_date = datetime.strptime(date_range[0], "%Y%m%d")
                        end_date = datetime.strptime(date_range[1], "%Y%m%d")
                        if not (start_date <= folder_date <= end_date):
                            continue
                    except ValueError:
                        continue
                
                for log_file in date_folder.glob("*.log"):
                    try:
                        with open(log_file, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                            
                        log_data = {
                            'file': str(log_file),
                            'date': date_folder.name,
                            'filename_info': parse_log_filename(log_file.name),
                            'lines': lines
                        }
                        all_logs.append(log_data)
                    except Exception as e:
                        print(f"读取日志文件失败: {log_file}, 错误: {e}")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_logs, f, ensure_ascii=False, indent=2)
        
        return True
    except Exception as e:
        print(f"导出日志到JSON失败: {e}")
        return False


def get_log_level_name(level: int) -> str:
    """获取日志级别名称"""
    level_names = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRITICAL"
    }
    return level_names.get(level, "UNKNOWN")


def format_duration(seconds: float) -> str:
    """格式化持续时间"""
    if seconds < 60:
        return f"{seconds:.3f}秒"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}分{secs:.3f}秒"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}小时{minutes}分{secs:.3f}秒"
