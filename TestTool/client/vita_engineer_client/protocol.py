"""
Communication protocol definitions for Engineer Service client.
"""

import json
import time
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
class ResponseStatus(Enum):
    """Response status codes."""
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    UNAUTHORIZED = "unauthorized"
    INVALID_COMMAND = "invalid_command"


@dataclass
class BaseMessage:
    """Base message structure."""
    timestamp: int
    auth_token: str = ""


@dataclass
class CommandMessage(BaseMessage):
    """Command message structure."""
    command: str = ""
    params: Dict[str, Any] = None

    def __post_init__(self):
        if self.params is None:
            self.params = {}

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, json_str: str) -> 'CommandMessage':
        """Create from JSON string."""
        data = json.loads(json_str)
        return cls(**data)


@dataclass
class ResponseMessage(BaseMessage):
    """Response message structure."""
    status: str = ""
    message: str = ""
    data: Optional[str] = None  # Base64 encoded string or JSON string
    data_size: Optional[int] = None
    has_binary_data: bool = False
    encoding: Optional[str] = None  # e.g., "base64"

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, json_str: str) -> 'ResponseMessage':
        """Create from JSON string."""
        data = json.loads(json_str)
        # Only use fields that are defined in the dataclass
        # This allows the server to send additional fields without breaking compatibility
        field_names = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered_data)


# Protocol constants
DEFAULT_PORT = 3579  # Match server configuration
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10MB
CONNECTION_TIMEOUT_MS = 30000  # 30 seconds
COMMAND_TIMEOUT_MS = 180000    # 180 seconds to match client wait_for
TOKEN_LENGTH = 64  # SHA256 hex string length
DEVICE_ID_LENGTH = 40  # SHA1 hex string length
