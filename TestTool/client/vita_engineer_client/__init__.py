"""
VITA Engineer Client Package

A Python client library for communicating with VITA Robot Engineer Service.
"""

__version__ = "1.0.0"
__author__ = "VITA Robot Team"
__email__ = "robot@vita.ai"

# Import main classes for easy access
from .engineer_client import EngineerServiceClient
from .protocol import ResponseStatus
from .crypto_utils import CryptoUtils
from .pointcloud_processor import PointCloudProcessor

# Alias for backward compatibility
EngineerClient = EngineerServiceClient

__all__ = [
    "EngineerServiceClient",
    "EngineerClient",
    "ResponseStatus",
    "CryptoUtils",
    "PointCloudProcessor",
]
