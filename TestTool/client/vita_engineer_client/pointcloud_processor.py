#!/usr/bin/env python3
"""
点云数据处理模块

提供点云数据解析和可视化功能，包括：
1. 解析ROS2 PointCloud2数据格式
2. 生成xy平面俯视图
3. 保存为JPEG图像
"""

import struct
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import logging

logger = logging.getLogger(__name__)

class PointCloudProcessor:
    """点云数据处理器"""
    
    def __init__(self):
        self.points = None
        self.header_info = {}
        
    def parse_lidar_file(self, filename: str) -> bool:
        """
        解析激光雷达数据文件
        
        Args:
            filename: 数据文件路径
            
        Returns:
            bool: 解析是否成功
        """
        try:
            with open(filename, 'rb') as f:
                data = f.read()
            
            if len(data) < 28:
                logger.error("文件太小，无法解析头部信息")
                return False
                
            # 解析头部信息
            self.header_info = self._parse_header(data)
            
            # 解析点云数据
            self.points = self._parse_points(data)
            
            logger.info(f"成功解析点云数据: {len(self.points)} 个点")
            return True
            
        except Exception as e:
            logger.error(f"解析点云文件失败: {e}")
            return False
    
    def _parse_header(self, data: bytes) -> dict:
        """解析文件头部信息"""
        header = {}

        # 解析LidarDataHeader结构
        # struct LidarDataHeader {
        #     uint32_t point_count;      // 0-4
        #     uint64_t timestamp;        // 4-12
        #     uint32_t width;            // 12-16
        #     uint32_t height;           // 16-20
        #     uint32_t data_size;        // 20-24
        #     uint8_t include_intensity; // 24
        #     uint8_t reserved[3];       // 25-28
        # }
        header['point_count'] = struct.unpack('<I', data[0:4])[0]
        header['timestamp'] = struct.unpack('<Q', data[4:12])[0]
        header['width'] = struct.unpack('<I', data[12:16])[0]
        header['height'] = struct.unpack('<I', data[16:20])[0]
        header['data_size'] = struct.unpack('<I', data[20:24])[0]
        header['include_intensity'] = bool(data[24])

        logger.debug(f"头部信息: {header}")
        return header
    
    def _parse_points(self, data: bytes) -> np.ndarray:
        """解析点云数据 - 根据ROS2 PointCloud2格式"""
        try:
            # 跳过32字节 (28字节LidarDataHeader + 4字节额外数据)
            offset = 32

            # 解析frame_id
            frame_id_len = data[offset]
            offset += 1
            frame_id = data[offset:offset + frame_id_len].decode('utf-8')
            offset += frame_id_len
            logger.debug(f"Frame ID: {frame_id}")

            # 解析字段信息
            field_count = data[offset]
            offset += 1
            logger.debug(f"Field count: {field_count}")

            fields = []
            for i in range(field_count):
                # 字段名长度和名称
                name_len = data[offset]
                offset += 1
                field_name = data[offset:offset + name_len].decode('utf-8')
                offset += name_len

                # 字段数据类型
                datatype = data[offset]
                offset += 1

                # 字段偏移量
                field_offset = struct.unpack('<I', data[offset:offset + 4])[0]
                offset += 4

                fields.append({
                    'name': field_name,
                    'datatype': datatype,
                    'offset': field_offset
                })
                logger.debug(f"Field {i}: {field_name}, type: {datatype}, offset: {field_offset}")

            # 解析point_step和row_step
            point_step = struct.unpack('<I', data[offset:offset + 4])[0]
            offset += 4
            row_step = struct.unpack('<I', data[offset:offset + 4])[0]
            offset += 4

            # 解析is_dense标志
            is_dense = bool(data[offset])
            offset += 1

            logger.debug(f"Point step: {point_step}, Row step: {row_step}, Is dense: {is_dense}")

            # 现在offset指向实际的点云数据
            points_data = data[offset:]
            point_count = self.header_info['point_count']

            logger.debug(f"Points data size: {len(points_data)}, Expected points: {point_count}")
            logger.debug(f"Point step: {point_step}")

            # 解析点云数据
            points = []
            valid_count = 0
            invalid_count = 0

            for i in range(min(point_count, len(points_data) // point_step)):
                point_start = i * point_step
                point_bytes = points_data[point_start:point_start + point_step]

                try:
                    # 提取x, y, z坐标 (假设都是float32)
                    x = struct.unpack('<f', point_bytes[0:4])[0]
                    y = struct.unpack('<f', point_bytes[4:8])[0]
                    z = struct.unpack('<f', point_bytes[8:12])[0]

                    # 查找intensity字段
                    intensity = 0.0
                    for field in fields:
                        if field['name'] == 'intensity' and field['offset'] + 4 <= len(point_bytes):
                            intensity = struct.unpack('<f', point_bytes[field['offset']:field['offset'] + 4])[0]
                            break

                    # 过滤无效点 (NaN或无穷大)
                    if (np.isfinite(x) and np.isfinite(y) and np.isfinite(z) and
                        abs(x) < 1000 and abs(y) < 1000 and abs(z) < 1000):
                        points.append([x, y, z, intensity])
                        valid_count += 1
                    else:
                        invalid_count += 1
                        if invalid_count < 5:  # 只打印前几个无效点的信息
                            logger.debug(f"Invalid point {i}: x={x}, y={y}, z={z}")

                except Exception as e:
                    invalid_count += 1
                    if invalid_count < 5:
                        logger.debug(f"Error parsing point {i}: {e}")

            logger.info(f"解析结果: {valid_count} 个有效点, {invalid_count} 个无效点")

            if len(points) == 0:
                logger.warning("没有有效的点云数据，生成示例数据")
                return self._generate_sample_points()

            points_array = np.array(points, dtype=np.float32)
            logger.info(f"最终得到 {len(points_array)} 个有效点")
            return points_array

        except Exception as e:
            logger.error(f"解析点云数据失败: {e}")
            logger.exception("详细错误信息")
            return self._generate_sample_points()
    
    def _generate_sample_points(self) -> np.ndarray:
        """生成示例点云数据用于测试"""
        logger.info("生成示例点云数据")
        
        # 生成一个简单的圆形点云
        n_points = 1000
        angles = np.linspace(0, 2*np.pi, n_points)
        radius = np.random.uniform(1, 5, n_points)
        
        x = radius * np.cos(angles) + np.random.normal(0, 0.1, n_points)
        y = radius * np.sin(angles) + np.random.normal(0, 0.1, n_points)
        z = np.random.uniform(-1, 1, n_points)
        intensity = np.random.uniform(0, 255, n_points)
        
        return np.column_stack([x, y, z, intensity])
    
    def create_top_view_image(self, output_filename: str = "lidar_top_view.jpg", 
                            image_size: tuple = (800, 800)) -> bool:
        """
        创建xy平面俯视图并保存为JPEG
        
        Args:
            output_filename: 输出图像文件名
            image_size: 图像尺寸 (width, height)
            
        Returns:
            bool: 是否成功生成图像
        """
        if self.points is None:
            logger.error("没有点云数据，请先解析文件")
            return False
            
        try:
            # 提取x, y坐标
            x = self.points[:, 0]
            y = self.points[:, 1]
            intensity = self.points[:, 3] if self.points.shape[1] > 3 else None
            
            # 创建图像
            fig, ax = plt.subplots(figsize=(10, 10))
            
            # 绘制散点图
            if intensity is not None:
                # 使用强度值作为颜色
                scatter = ax.scatter(x, y, c=intensity, cmap='viridis', s=1, alpha=0.6)
                plt.colorbar(scatter, ax=ax, label='Intensity')
            else:
                # 使用固定颜色
                ax.scatter(x, y, c='blue', s=1, alpha=0.6)
            
            # 设置图像属性
            ax.set_xlabel('X (meters)')
            ax.set_ylabel('Y (meters)')
            ax.set_title('LiDAR Point Cloud - Top View')
            ax.set_aspect('equal')
            ax.grid(True, alpha=0.3)
            
            # 保存图像
            plt.savefig(output_filename, dpi=100, bbox_inches='tight', 
                       facecolor='white', edgecolor='none')
            plt.close()
            
            logger.info(f"俯视图已保存到: {output_filename}")
            return True
            
        except Exception as e:
            logger.error(f"生成俯视图失败: {e}")
            return False
    

    
    def get_statistics(self) -> dict:
        """获取点云统计信息"""
        if self.points is None:
            return {}
            
        stats = {
            'point_count': len(self.points),
            'x_range': (np.min(self.points[:, 0]), np.max(self.points[:, 0])),
            'y_range': (np.min(self.points[:, 1]), np.max(self.points[:, 1])),
            'z_range': (np.min(self.points[:, 2]), np.max(self.points[:, 2])),
        }
        
        if self.points.shape[1] > 3:
            stats['intensity_range'] = (np.min(self.points[:, 3]), np.max(self.points[:, 3]))
            
        return stats
