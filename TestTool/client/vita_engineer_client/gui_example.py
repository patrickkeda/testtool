"""
VITA Engineer Service GUI Client
Simple GUI interface for testing robot functions.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import asyncio
import threading
import time
import json
from datetime import datetime

# 支持直接运行和作为模块导入
try:
    from .engineer_client import EngineerServiceClient
    from .protocol import (LidarTestParams, CameraTestParams, TTSTestParams, HeadMotionTestParams,
                          BatteryTestParams, CalibrationTestParams, MotionSequenceTestParams)
except ImportError:
    # 直接运行时的导入方式
    from engineer_client import EngineerServiceClient
    from protocol import (LidarTestParams, CameraTestParams, TTSTestParams, HeadMotionTestParams,
                         BatteryTestParams, CalibrationTestParams, MotionSequenceTestParams)


class EngineerServiceGUI:
    """Simple GUI for Engineer Service testing."""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Engineer Service - Production Line Testing Tool")
        self.root.geometry("800x600")
        
        self.client = None
        self.is_connected = False
        self.event_loop = None  # 保持事件循环引用
        
        self.setup_ui()
        self.setup_styles()
    
    def setup_styles(self):
        """Setup GUI styles."""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure colors
        style.configure('Success.TLabel', foreground='green')
        style.configure('Error.TLabel', foreground='red')
        style.configure('Info.TLabel', foreground='blue')
    
    def setup_ui(self):
        """Setup the user interface."""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(4, weight=1)
        
        # Connection frame
        self.setup_connection_frame(main_frame)
        
        # Test controls frame
        self.setup_test_controls_frame(main_frame)
        
        # Results frame
        self.setup_results_frame(main_frame)
        
        # Status bar
        self.setup_status_bar(main_frame)
    
    def setup_connection_frame(self, parent):
        """Setup connection controls."""
        conn_frame = ttk.LabelFrame(parent, text="Connection Settings", padding="5")
        conn_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        conn_frame.columnconfigure(1, weight=1)
        
        # Robot IP
        ttk.Label(conn_frame, text="Robot IP:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.ip_var = tk.StringVar(value="192.168.126.2")
        self.ip_entry = ttk.Entry(conn_frame, textvariable=self.ip_var, width=20)
        self.ip_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))

        # Port
        ttk.Label(conn_frame, text="Port:").grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        self.port_var = tk.StringVar(value="3579")
        self.port_entry = ttk.Entry(conn_frame, textvariable=self.port_var, width=10)
        self.port_entry.grid(row=0, column=3, sticky=tk.W, padx=(0, 10))
        
        # SOC IDs
        ttk.Label(conn_frame, text="X5 SOC ID:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5))
        self.x5_soc_var = tk.StringVar(value="test_x5_id")
        self.x5_soc_entry = ttk.Entry(conn_frame, textvariable=self.x5_soc_var, width=20)
        self.x5_soc_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        
        ttk.Label(conn_frame, text="S100 SOC ID:").grid(row=1, column=2, sticky=tk.W, padx=(0, 5))
        self.s100_soc_var = tk.StringVar(value="test_s100_id")
        self.s100_soc_entry = ttk.Entry(conn_frame, textvariable=self.s100_soc_var, width=20)
        self.s100_soc_entry.grid(row=1, column=3, sticky=(tk.W, tk.E))
        
        # Connect button
        self.connect_btn = ttk.Button(conn_frame, text="Connect", command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=4, rowspan=2, padx=(10, 0), sticky=(tk.N, tk.S))
    
    def setup_test_controls_frame(self, parent):
        """Setup test control buttons."""
        test_frame = ttk.LabelFrame(parent, text="Test Controls", padding="5")
        test_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N), pady=(0, 10))
        
        # Test buttons
        ttk.Button(test_frame, text="Enter Engineer Mode",
                  command=self.enter_engineer_mode).pack(fill=tk.X, pady=2)
        ttk.Button(test_frame, text="Test Lidar",
                  command=self.test_lidar).pack(fill=tk.X, pady=2)
        ttk.Button(test_frame, text="Test Camera",
                  command=self.test_camera).pack(fill=tk.X, pady=2)
        ttk.Button(test_frame, text="Test TTS",
                  command=self.test_tts).pack(fill=tk.X, pady=2)
        ttk.Button(test_frame, text="Test Head Motion",
                  command=self.test_head_motion).pack(fill=tk.X, pady=2)
        ttk.Button(test_frame, text="Test Light",
                  command=self.test_light).pack(fill=tk.X, pady=2)
        ttk.Button(test_frame, text="Test Battery",
                  command=self.test_battery).pack(fill=tk.X, pady=2)

        # Separator for new features
        ttk.Separator(test_frame, orient='horizontal').pack(fill=tk.X, pady=5)

        # New test features
        ttk.Button(test_frame, text="🔧 Test Calibration",
                  command=self.test_calibration).pack(fill=tk.X, pady=2)
        ttk.Button(test_frame, text="🤖 Test Motion Sequence",
                  command=self.test_motion_sequence).pack(fill=tk.X, pady=2)

        ttk.Button(test_frame, text="Run All Tests",
                  command=self.run_all_tests).pack(fill=tk.X, pady=2)
    
    def setup_results_frame(self, parent):
        """Setup results display."""
        results_frame = ttk.LabelFrame(parent, text="Test Results", padding="5")
        results_frame.grid(row=1, column=1, rowspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(10, 0))
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        
        # Results text area
        self.results_text = scrolledtext.ScrolledText(results_frame, wrap=tk.WORD, width=50, height=20)
        self.results_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Clear button
        ttk.Button(results_frame, text="Clear Results", 
                  command=self.clear_results).grid(row=1, column=0, sticky=tk.E, pady=(5, 0))
    
    def setup_status_bar(self, parent):
        """Setup status bar."""
        status_frame = ttk.Frame(parent)
        status_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
        status_frame.columnconfigure(0, weight=1)
        
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, style='Info.TLabel')
        self.status_label.grid(row=0, column=0, sticky=tk.W)
        
        # Progress bar
        self.progress = ttk.Progressbar(status_frame, mode='indeterminate')
        self.progress.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(10, 0))
    
    def log_message(self, message, level="INFO"):
        """Log a message to the results area."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {level}: {message}\n"
        
        self.results_text.insert(tk.END, formatted_message)
        self.results_text.see(tk.END)
        
        # Update status
        self.status_var.set(message)
    
    def clear_results(self):
        """Clear the results text area."""
        self.results_text.delete(1.0, tk.END)
        self.status_var.set("Results cleared")
    
    def toggle_connection(self):
        """Toggle connection to robot."""
        if self.is_connected:
            self.disconnect_from_robot()
        else:
            self.connect_to_robot()
    
    def connect_to_robot(self):
        """Connect to the robot."""
        def run_connect():
            try:
                self.progress.start()
                self.connect_btn.config(state='disabled')

                # Create client if not exists or recreate if connection failed
                if not self.client or not self.is_connected:
                    self.client = EngineerServiceClient(
                        host=self.ip_var.get(),
                        port=int(self.port_var.get()),
                        x5_soc_id=self.x5_soc_var.get(),
                        s100_soc_id=self.s100_soc_var.get()
                    )

                # Create or reuse event loop
                if not self.event_loop or self.event_loop.is_closed():
                    self.event_loop = asyncio.new_event_loop()

                asyncio.set_event_loop(self.event_loop)
                success = self.event_loop.run_until_complete(self.client.connect())

                if success:
                    self.is_connected = True
                    self.root.after(0, lambda: self.log_message("Connected to robot successfully", "SUCCESS"))
                    self.root.after(0, lambda: self.connect_btn.config(text="Disconnect", state='normal'))
                else:
                    self.is_connected = False
                    self.root.after(0, lambda: self.log_message("Failed to connect to robot", "ERROR"))
                    self.root.after(0, lambda: self.connect_btn.config(text="Connect", state='normal'))

            except Exception as e:
                self.is_connected = False
                self.root.after(0, lambda: self.log_message(f"Connection error: {e}", "ERROR"))
                self.root.after(0, lambda: self.connect_btn.config(text="Connect", state='normal'))
            finally:
                self.root.after(0, lambda: self.progress.stop())

        threading.Thread(target=run_connect, daemon=True).start()
    
    def disconnect_from_robot(self):
        """Disconnect from the robot."""
        def run_disconnect():
            try:
                if self.client and self.event_loop and not self.event_loop.is_closed():
                    asyncio.set_event_loop(self.event_loop)
                    self.event_loop.run_until_complete(self.client.disconnect())

                self.is_connected = False
                self.client = None

                # Close event loop if it exists
                if self.event_loop and not self.event_loop.is_closed():
                    self.event_loop.close()
                self.event_loop = None

                self.root.after(0, lambda: self.log_message("Disconnected from robot", "INFO"))
                self.root.after(0, lambda: self.connect_btn.config(text="Connect"))

            except Exception as e:
                self.is_connected = False
                self.client = None
                self.event_loop = None
                self.root.after(0, lambda: self.log_message(f"Disconnect error: {e}", "ERROR"))
                self.root.after(0, lambda: self.connect_btn.config(text="Connect"))

        threading.Thread(target=run_disconnect, daemon=True).start()
    
    def run_async_command(self, command_func, *args, **kwargs):
        """Run an async command in a separate thread."""
        if not self.is_connected or not self.client or not self.event_loop:
            messagebox.showerror("Error", "Not connected to robot")
            return

        def run_command():
            try:
                self.progress.start()
                # Use the existing event loop
                asyncio.set_event_loop(self.event_loop)
                result = self.event_loop.run_until_complete(command_func(*args, **kwargs))
                self.root.after(0, lambda: self.handle_command_result(command_func.__name__, result))
            except Exception as e:
                error_msg = str(e)
                self.root.after(0, lambda: self.log_message(f"Command error: {error_msg}", "ERROR"))

                # Check if it's a connection error and attempt reconnection
                if "connection" in error_msg.lower() or "websocket" in error_msg.lower():
                    self.root.after(0, lambda: self.handle_connection_error())
            finally:
                self.root.after(0, lambda: self.progress.stop())

        threading.Thread(target=run_command, daemon=True).start()

    def handle_connection_error(self):
        """Handle connection errors and attempt reconnection."""
        self.log_message("Connection lost. Attempting to reconnect...", "WARNING")
        self.is_connected = False
        self.connect_btn.config(text="Connect", state='normal')

        # Ask user if they want to reconnect
        if messagebox.askyesno("Connection Lost",
                              "Connection to robot was lost. Would you like to reconnect?"):
            self.connect_to_robot()
    
    def handle_command_result(self, command_name, result):
        """Handle the result of a command."""
        if isinstance(result, tuple) and len(result) >= 2:
            success, message = result[:2]
            data = result[2] if len(result) > 2 else None
            
            level = "SUCCESS" if success else "ERROR"
            self.log_message(f"{command_name}: {message}", level)
            
            if data:
                self.log_message(f"Data received: {json.dumps(data, indent=2)}", "INFO")
        else:
            self.log_message(f"{command_name}: Unexpected result format", "ERROR")
    
    def enter_engineer_mode(self):
        """Enter engineer mode."""
        self.run_async_command(self.client.enter_engineer_mode)
    
    def test_lidar(self):
        """Test lidar functionality."""
        self.run_async_command(self.client.test_lidar,
                             frame_count=1, save_to_file=True,
                             filename="lidar_points.data")
    
    def test_camera(self):
        """Test camera functionality."""
        self.run_async_command(self.client.test_camera,
                             width=1920, height=1080, quality=90,
                             undistort=False, save_to_file=True)
    
    def test_tts(self):
        """Test TTS functionality."""
        self.run_async_command(self.client.test_tts, "Production line test message", 1)
    
    def test_head_motion(self):
        """Test head motion functionality."""
        self.run_async_command(self.client.test_head_motion,
                             action_name="HAPPY_WALK",
                             duration_ms=-1,
                             loop_enabled=False,
                             playback_rate=1.0)

    def test_light(self):
        """Test light functionality."""
        self.run_async_command(self.client.test_light)

    def test_battery(self):
        """Test battery functionality."""
        self.run_async_command(self.client.test_battery)

    def test_calibration(self):
        """Test calibration functionality.

        默认使用limit模式进行标定。
        如需切换到passive模式，请修改下面的calib_type参数：
        - "limit": 限位标定模式（默认，推荐用于生产线）
        - "passive": 被动标定模式（需要手动调整机器人姿态）
        """
        # 默认使用limit模式，如需切换请修改calib_type参数
        self.run_async_command(self.client.test_calibration,
                             config_file="/app/locomotion/config/vita01_config.json",
                             calib_type="limit")  # 可选: "passive" 或 "limit"

    def test_motion_sequence(self):
        """Test motion sequence functionality."""
        self.run_async_command(self.client.test_motion_sequence,
                             action_sequence="FIXED_STAND,FIXED_LAYDOWN,PASSIVE",
                             action_delay_ms=3000,
                             check_ready_status=False,
                             service_timeout_seconds=10)

    def run_all_tests(self):
        """Run all tests sequentially."""
        if not self.is_connected or not self.client:
            messagebox.showerror("Error", "Not connected to robot")
            return
        
        def run_all():
            try:
                self.progress.start()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                tests = [
                    ("Enter Engineer Mode", self.client.enter_engineer_mode, []),
                    ("Test TTS Start", self.client.test_tts, ["Starting production line tests", 1]),
                    ("Test Lidar", self.client.test_lidar, [1, True]),
                    ("Test Camera", self.client.test_camera, [640, 480, 80, False]),
                    ("Test Head Motion", self.client.test_head_motion, [0.1, 0.2, 2000]),
                    ("Test Light", self.client.test_light, []),
                    ("Test Battery", self.client.test_battery, []),
                    ("Test Calibration", self.client.test_calibration, ["/app/locomotion/config/vita01_config.json", "limit"]),
                    ("Test Motion Sequence", self.client.test_motion_sequence, ["FIXED_STAND,FIXED_LAYDOWN,PASSIVE", 3000, False, 10]),
                    ("Test TTS End", self.client.test_tts, ["Production line tests completed", 1]),
                ]
                
                for test_name, test_func, args in tests:
                    self.root.after(0, lambda name=test_name: self.log_message(f"Running {name}...", "INFO"))
                    result = loop.run_until_complete(test_func(*args))
                    self.root.after(0, lambda name=test_name, res=result: self.handle_command_result(name, res))
                    time.sleep(1)  # Small delay between tests
                
                self.root.after(0, lambda: self.log_message("All tests completed!", "SUCCESS"))
                
            except Exception as e:
                self.root.after(0, lambda: self.log_message(f"Test sequence error: {e}", "ERROR"))
            finally:
                self.root.after(0, lambda: self.progress.stop())
        
        threading.Thread(target=run_all, daemon=True).start()


def main():
    """Main function to run the GUI."""
    root = tk.Tk()
    app = EngineerServiceGUI(root)
    
    # Handle window close
    def on_closing():
        if app.is_connected:
            app.disconnect_from_robot()
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
