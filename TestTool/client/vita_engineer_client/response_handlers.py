"""
响应处理器模块

包含各种测试用例的响应处理器
"""

import json
import time
import os
import struct
import base64
import io
import logging
from typing import Dict, Any
from protocol import ResponseStatus

logger = logging.getLogger(__name__)

# Lazy imports for heavy dependencies that may not be available in all environments
np = None
cv2 = None
Image = None
PointCloudProcessor = None

def _ensure_heavy_imports():
    """Lazily import heavy dependencies (numpy, cv2, PIL, matplotlib)."""
    global np, cv2, Image, PointCloudProcessor
    if np is None:
        try:
            import numpy as _np
            np = _np
        except ImportError as e:
            raise ImportError(f"numpy is required for this operation: {e}")
    if cv2 is None:
        try:
            import cv2 as _cv2
            cv2 = _cv2
        except ImportError as e:
            raise ImportError(f"opencv is required for this operation: {e}")
    if Image is None:
        try:
            from PIL import Image as _Image
            Image = _Image
        except ImportError as e:
            raise ImportError(f"Pillow is required for this operation: {e}")
    if PointCloudProcessor is None:
        try:
            from pointcloud_processor import PointCloudProcessor as _PCP
            PointCloudProcessor = _PCP
        except ImportError as e:
            raise ImportError(f"pointcloud_processor is required for this operation: {e}")

def decode_base64(data: str) -> Any:
    """解码base64数据"""
    return base64.b64decode(data)


async def handle_lidar_response(response: Dict[str, Any], params) -> bool:
    """激光雷达响应处理器"""
    print(f"处理激光雷达响应: {params.operation}")
    
    if response.get("status") != ResponseStatus.SUCCESS.value:
        print(f"激光雷达命令执行失败: {response.get('message', '')}")
        return False
    if params.operation == "0":
        print(f"激光雷达命令执行成功: {response.get('message', '')}")
        # 处理数据：可能是直接文本或 base64 编码
        data_str = response.get("data", "")
        if not data_str:
            print("激光雷达数据为空")
            return False
        
        # 如果是 base64 编码，先解码
        if response.get("encoding") == "base64" and response.get("has_binary_data", False):
            decoded_data = decode_base64(data_str)
            data_str = decoded_data.decode('utf-8')
        
        try:
            data = json.loads(data_str)
            if data:
                print(f"   返回数据: \n {json.dumps(data, indent=4)}")
            return True
        except json.JSONDecodeError as e:
            print(f"解析激光雷达数据失败: {e}")
            print(f"原始数据: {data_str[:200]}...")  # 打印前200个字符用于调试
            return False
    elif params.operation == "1":
        pointcloud_file = "lidar_points.data"
        data_str = response.get("data", "")
        if not data_str:
            print("激光雷达点云数据为空")
            return False
        
        # 解码 base64 数据
        data = decode_base64(data_str)
        if data:
            with open(pointcloud_file, "wb") as f:
                f.write(data)
            print(f"激光雷达点云数据保存到 {pointcloud_file}")
        _ensure_heavy_imports()
        processor = PointCloudProcessor()
        if not processor.parse_lidar_file(pointcloud_file):
            print("点云文件解析失败，跳过图像生成")
            return False
        lidar_file_path = params.get_param(1)
        if not lidar_file_path:
            lidar_file_path = "."
        else:
            if not os.path.exists(lidar_file_path):
                os.makedirs(lidar_file_path)
        image_filename = f"{lidar_file_path}/lidar_top_view.jpg"

        # 生成彩色俯视图（使用matplotlib，强度值着色）
        success = processor.create_top_view_image(image_filename)
        if not success:
            print("生成彩色俯视图失败，跳过图像保存")
            return False
        print(f"彩色俯视图保存到 {image_filename}")
        return True
    else:
        print(f"invalid operation: {params.operation}")
        return False

async def handle_camera_response(response: Dict[str, Any], params) -> bool:
    """Camera测试响应处理器"""
    print(f"处理Camera响应: {params.operation}")
    
    if response.get("status") != ResponseStatus.SUCCESS.value:
        print(f"Camera命令 {params.operation} 执行失败: {response.get('message', '')}")
        return False
    if params.operation == "0":
        # 处理数据：可能是直接文本或 base64 编码
        data_str = response.get('data', '')
        if not data_str:
            print("Camera数据为空")
            return False
        
        # 如果是 base64 编码，先解码
        if response.get("encoding") == "base64" and response.get("has_binary_data", False):
            decoded_data = decode_base64(data_str)
            data_str = decoded_data.decode('utf-8')
        
        try:
            parsed_data = json.loads(data_str)
            print(f"查询到相机参数:\n {json.dumps(parsed_data, indent=4)}")
            return True
        except json.JSONDecodeError as e:
            print(f"解析Camera数据失败: {e}")
            print(f"原始数据: {data_str[:200]}...")  # 打印前200个字符用于调试
            return False
    elif params.operation == "1":
        data = decode_base64(response.get('data', ''))
        offset = 0
        left_size = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        left_data = data[offset:offset+left_size]
        offset += left_size
        right_size = struct.unpack_from('<I', data, offset)[0]
        offset += 4 
        right_data = data[offset:offset+right_size]
        offset += right_size
        _ensure_heavy_imports()
        left_image = Image.open(io.BytesIO(left_data))
        right_image = Image.open(io.BytesIO(right_data))
        
        address = params.get_param(1)
        if not address:
            address = "."
        elif not os.path.exists(address):
            os.makedirs(address)
        filename_suffix = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        left_image.save(f"{address}/stereo_left_{filename_suffix}.jpg")
        right_image.save(f"{address}/stereo_right_{filename_suffix}.jpg")
        left_image.show()
        right_image.show()
        return True
    return False


async def handle_infrared_response(response: Dict[str, Any], params) -> bool:
    """红外相机响应处理器"""
    print(f"处理红外相机响应: {params.operation}")
    
    if response.get("status") != ResponseStatus.SUCCESS.value:
        print(f"红外相机命令 {params.operation} 执行失败: {response.get('message', '')}")
        return False
    if params.operation == "1":
        # Step 1: Parse JSON data (JSON itself is not base64 encoded)
        data_str = response.get('data', '')
        if not data_str:
            print(f"Error: No data received")
            return False
        
        try:
            # data_str is already a JSON string, parse it
            json_data = json.loads(data_str) if isinstance(data_str, str) else data_str
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Error: Failed to parse JSON data: {e}")
            return False
        
        if not json_data:
            print(f"Error: No JSON data received")
            return False
        
        # Step 2: Extract metadata and base64-encoded image data
        width = json_data.get('width', 640)  # Default fallback
        height = json_data.get('height', 480)  # Default fallback
        encoding = json_data.get('encoding', 'mono8')
        base64_image_data = json_data.get('image_data', '')
        if encoding != "mono8":
            print(f"Error: Unsupported encoding: {encoding}")
            return False
            
        if not base64_image_data:
            print(f"Error: No image_data in JSON response")
            return False
        
        # Step 3: Decode base64 image data
        try:
            image_data = decode_base64(base64_image_data)
        except Exception as e:
            print(f"Error: Failed to decode base64 image data: {e}")
            return False
        
        address = params.get_param(1)
        if not address:
            address = "."
        elif not os.path.exists(address):
            os.makedirs(address)

        # mono8 format: single channel grayscale image
        # Data size = width * height (one byte per pixel)
        expected_size = width * height
        if len(image_data) != expected_size:
            print(f"Warning: Data size mismatch. Expected {expected_size} bytes, got {len(image_data)} bytes")
        
        _ensure_heavy_imports()
        mono8 = np.frombuffer(image_data, dtype=np.uint8).reshape((height, width))
        # Convert to PIL Image (grayscale)
        image = Image.fromarray(mono8, mode='L')
        filename_suffix = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        filename = f"{address}/infrared_{filename_suffix}.jpg"
        print(f"saving infrared image to {filename} (mono8, {width}x{height})")
        image.save(filename)
        image.show()
        return True
    elif params.operation == "2":
        print(f"命令执行成功: {response.get('message', '')}")
        data_str = response.get("data", "")
        if data_str:
            print(f"{data_str}")

    print(f"invalid operation: {params.operation}")
    return False


async def handle_transfer_response(response: Dict[str, Any], params) -> bool:
    """文件传输响应处理器"""
    print(f"处理文件传输响应: {params.operation}")
    
    if response.get("status") != ResponseStatus.SUCCESS.value:
        print(f"文件传输命令 {params.operation} 执行失败: {response.get('message', '')}")
        return False
    
    if params.operation == "1":
        print(f"接收文件数据从狗传输到电脑...")
        
        dest_path = params.get_param(2)  # addrB是第3个参数（索引2）
        if not dest_path:
            print("错误: 未指定目标路径 (addrB)")
            return False

        addrA = params.get_param(1)
        source_filename = os.path.basename(addrA)
        dest_is_dir = dest_path == "." or dest_path.endswith("/") or os.path.isdir(dest_path)
        if dest_is_dir:
            if not os.path.exists(dest_path):
                os.makedirs(dest_path)
                print(f"创建目标目录: {dest_path}")
            dest_path = os.path.join(dest_path, source_filename)
        else:
            dest_dir = os.path.dirname(dest_path) if os.path.dirname(dest_path) else "."
            if dest_dir and not os.path.exists(dest_dir):
                os.makedirs(dest_dir)
                print(f"创建目标目录: {dest_dir}")
        
        data_value = response.get("data", "")
        if response.get("encoding") == "base64" or response.get("has_binary_data", False):
            if isinstance(data_value, str):
                file_data = decode_base64(data_value)
            else:
                file_data = data_value if isinstance(data_value, bytes) else b""
        else:
            if isinstance(data_value, str):
                try:
                    file_data = decode_base64(data_value)
                except:
                    file_data = data_value.encode('utf-8')
            else:
                file_data = data_value if isinstance(data_value, bytes) else b""
        
        if not file_data:
            print("错误: 未接收到文件数据")
            return False
        
        is_zip = len(file_data) >= 4 and file_data[0:4] == b'PK\x03\x04'
        
        try:
            if is_zip:
                import zipfile
                import tempfile
                
                if not os.path.exists(dest_path):
                    os.makedirs(dest_path)
                
                tmp_zip_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_zip:
                        tmp_zip_path = tmp_zip.name
                        tmp_zip.write(file_data)
                    
                    with zipfile.ZipFile(tmp_zip_path, 'r') as zipf:
                        zipf.extractall(dest_path)
                    print(f"文件夹传输成功: 已保存到 {dest_path}")
                finally:
                    if tmp_zip_path and os.path.exists(tmp_zip_path):
                        try:
                            os.unlink(tmp_zip_path)
                        except Exception as e:
                            print(f"警告: 清理临时文件失败: {e}")
            else:
                with open(dest_path, "wb") as f:
                    f.write(file_data)
                file_size = len(file_data)
                print(f"文件传输成功: 已保存 {file_size} 字节到 {dest_path}")
            return True
        except Exception as e:
            print(f"保存/解压文件失败: {e}")
            return False
    
    elif params.operation == "2":
        print(f"文件传输成功: {response.get('message', '文件已成功传输到狗')}")
        return True
    
    else:
        print(f"无效的操作类型: {params.operation}")
        return False


def register_all_handlers(command_registry):
    """注册所有响应处理器到命令注册表"""
    command_registry.register_response_handler("lidar", handle_lidar_response)
    command_registry.register_response_handler("camera", handle_camera_response)
    command_registry.register_response_handler("ircamera", handle_infrared_response)
    command_registry.register_response_handler("transfer", handle_transfer_response)

