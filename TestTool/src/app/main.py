"""
Main application entry point for the HMI.

This module initializes logging, constructs the Qt application, and launches
the main window with a dual-port layout as specified in the README.
"""

from __future__ import annotations

import sys
import logging
from typing import Optional
import asyncio
import threading
import time

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication

# Support running as module (-m src.app.main) and as script (python src/app/main.py)
try:
    from .views.main_window import MainWindow
    from ..config import ConfigService
    from ..app_logging import LoggingManager, LoggingConfig, set_logging_manager
    from ..core import EventBus, Scheduler, RetryPolicy
except ImportError:
    import os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    from src.app.views.main_window import MainWindow
    from src.config import ConfigService
    from src.app_logging import LoggingManager, LoggingConfig, set_logging_manager
    from src.core import EventBus, Scheduler, RetryPolicy


def configure_logging(config_service: ConfigService) -> LoggingManager:
    """Configure application-wide logging using the logging module.

    Parameters
    ----------
    config_service: ConfigService
        Configuration service instance.

    Returns
    -------
    LoggingManager
        Configured logging manager instance.
    """
    # 加载配置
    config = config_service.load()
    
    # 创建日志配置
    # 使用 try-except 处理相对导入和绝对导入
    try:
        from ..app_logging.config import (
            TestLogConfig as TL,
            ErrorLogConfig as EL,
            SystemLogConfig as SL,
            RotationConfig as RC,
        )
    except ImportError:
        # PyInstaller 打包后使用绝对导入
        from src.app_logging.config import (
            TestLogConfig as TL,
            ErrorLogConfig as EL,
            SystemLogConfig as SL,
            RotationConfig as RC,
        )
    # 映射 config.models -> logging.config 的配置模型
    rotation = RC(
        when=config.logging.rotation.when,
        backup_count=getattr(config.logging.rotation, "backupCount", 14),
        max_file_size=config.logging.rotation.max_file_size,
    )
    test_log = TL(**config.logging.test_log.model_dump())
    error_log = EL(**config.logging.error_log.model_dump())
    system_log = SL(**config.logging.system_log.model_dump())

    logging_config = LoggingConfig(
        level=config.logging.level,
        base_dir=config.logging.dir,
        station_name=config.app.station_name,
        rotation=rotation,
        test_log=test_log,
        error_log=error_log,
        system_log=system_log,
    )
    
    # 创建日志管理器
    logging_manager = LoggingManager(logging_config)
    set_logging_manager(logging_manager)
    print(f"DEBUG: 程序启动时加载的测试日志文件名格式: {logging_config.test_log.filename}")
    print(f"DEBUG: 程序启动时加载的错误日志文件名格式: {logging_config.error_log.filename}")
    
    # 设置基础日志
    logging.basicConfig(
        level=getattr(logging, config.logging.level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    
    return logging_manager


def main(argv: Optional[list[str]] = None) -> int:
    """Application main function.

    Parameters
    ----------
    argv: Optional[list[str]]
        Command-line arguments list. If None, sys.argv[1:] is used.

    Returns
    -------
    int
        Exit code (0 for success).
    """
    args = argv if argv is not None else sys.argv[1:]
    
    # 解析命令行参数
    sequence_path = None
    if args:
        for i, arg in enumerate(args):
            if arg == '--sequence' and i + 1 < len(args):
                sequence_path = args[i + 1]
            elif arg.startswith('--sequence='):
                sequence_path = arg.split('=', 1)[1]
    
    QCoreApplication.setOrganizationName("Vita001")
    QCoreApplication.setApplicationName("TestTool")

    app = QApplication(sys.argv)
    # 默认切到英文输入法（Windows best-effort），尤其用于 SN 扫描/输入
    try:
        from .utils.ime import try_switch_to_english
        try_switch_to_english()
    except Exception:
        pass

    # 初始化配置服务
    # 在 exe 环境中：
    #   - 读取：优先从 _internal/Config/config.yaml（打包的默认配置）
    #   - 保存：保存到 exe 所在目录的 Config/config.yaml（用户可写）
    # 在开发环境中：使用 Config/config.yaml
    if getattr(sys, 'frozen', False):
        # exe 环境：使用 exe 所在目录
        import os
        from pathlib import Path
        exe_dir = Path(sys.executable).parent
        
        # 读取配置：优先从 _internal 读取（打包的默认配置）
        read_config_paths = [
            exe_dir / '_internal' / 'Config' / 'config.yaml',
            exe_dir / 'Config' / 'config.yaml',
            exe_dir / 'config' / 'config.yaml',
        ]
        read_config_path = None
        for path in read_config_paths:
            if path.exists():
                read_config_path = str(path)
                break
        
        # 保存配置：始终保存到 exe 所在目录的 Config 目录（用户可写）
        save_config_path = exe_dir / 'Config' / 'config.yaml'
        save_config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 如果读取路径存在且与保存路径不同，先复制默认配置
        if read_config_path and read_config_path != str(save_config_path):
            if not save_config_path.exists():
                import shutil
                shutil.copy2(read_config_path, save_config_path)
                logging.info(f"Copied default config from {read_config_path} to {save_config_path}")
        
        config_path = str(save_config_path)
    else:
        # 开发环境：使用相对路径
        config_path = "Config/config.yaml"
        from pathlib import Path
        Path(config_path).parent.mkdir(parents=True, exist_ok=True)
    
    config_service = ConfigService(config_path)
    
    # 配置日志系统
    logging_manager = configure_logging(config_service)
    
    # 记录启动信息
    system_logger = logging_manager.get_system_logger()
    if system_logger:
        system_logger.info("TestTool HMI 启动", extra={"operation": "STARTUP"})
    
    logging.getLogger(__name__).info("Starting TestTool HMI args=%s", args)

    # 初始化核心基础设施（EventBus + Scheduler）
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()

    bus = EventBus(loop=loop)
    scheduler = Scheduler(loop=loop)

    # 配置变更 -> 发布 config.changed 事件（简化：不计算 diff）
    def _on_config_saved(_cfg):
        try:
            bus.publish("config.changed", {"version": getattr(_cfg, "version", ""), "diff": {}, "at": time.time()})
        except Exception as e:  # noqa: BLE001
            logging.getLogger(__name__).warning("Failed to publish config.changed: %s", e)

    config_service.add_listener(_on_config_saved)

    # 周期性心跳（10s）
    def _heartbeat():
        bus.publish("system.heartbeat", {"name": "app", "ok": True, "latency_ms": 0, "details": {}, "ts": time.time()})

    scheduler.schedule_interval(_heartbeat, interval_ms=10_000, name="heartbeat", initial_delay_ms=5_000, retry=RetryPolicy(max_retries=0))

    window = MainWindow()
    
    # 如果通过命令行指定了序列文件，自动加载
    if sequence_path:
        try:
            from ...testcases.utils import load_test_sequence
            import os
            from pathlib import Path
            
            # 处理相对路径和绝对路径
            if not os.path.isabs(sequence_path):
                # 相对路径：从项目根目录查找
                if getattr(sys, 'frozen', False):
                    # 打包环境：使用 exe 所在目录
                    exe_dir = Path(sys.executable).parent
                    # 尝试多个可能的路径
                    possible_paths = [
                        exe_dir / sequence_path,
                        exe_dir / "Seq" / sequence_path,
                        exe_dir.parent / "Seq" / sequence_path,
                        exe_dir / "_internal" / "Seq" / sequence_path,
                    ]
                else:
                    # 开发环境：从当前文件向上查找项目根目录
                    project_root = Path(__file__).parent.parent.parent
                    possible_paths = [
                        project_root / sequence_path,
                        project_root / "Seq" / sequence_path,
                    ]
                
                # 查找第一个存在的路径
                found_path = None
                for path in possible_paths:
                    if path.exists():
                        found_path = path
                        break
                
                if found_path:
                    sequence_path = str(found_path)
                else:
                    # 如果都找不到，使用第一个路径（让后续代码报错）
                    sequence_path = str(possible_paths[0])
            
            logging.getLogger(__name__).info(f"从命令行加载序列文件: {sequence_path}")
            sequence = load_test_sequence(sequence_path)
            window._current_sequence = sequence
            
            # 更新序列显示
            if hasattr(window, '_update_sequence_display'):
                window._update_sequence_display()
            
            # 自动设置到 PortA 和 PortB worker
            if hasattr(window, '_worker_a') and window._worker_a:
                window._worker_a.set_sequence(sequence)
                logging.getLogger(__name__).info(f"序列已设置到 PortA worker: {sequence.metadata.name}")
            
            if hasattr(window, '_worker_b') and window._worker_b:
                window._worker_b.set_sequence(sequence)
                logging.getLogger(__name__).info(f"序列已设置到 PortB worker: {sequence.metadata.name}")
            
            logging.getLogger(__name__).info(f"序列文件加载成功: {sequence_path}")
        except Exception as e:
            logging.getLogger(__name__).error(f"加载序列文件失败: {e}", exc_info=True)
    
    window.show()

    code = app.exec()

    # 清理后台事件循环
    try:
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=1.0)
    except Exception:
        pass

    return code


if __name__ == "__main__":
    raise SystemExit(main())


