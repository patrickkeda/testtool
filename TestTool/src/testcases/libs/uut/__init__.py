"""
UUT控制动作库

提供UUT通讯相关的业务动作。
"""

from .power_actions import (
    power_on_uut,
    power_off_uut,
    soft_reset_uut,
    hard_reset_uut,
    check_power_status,
)

from .mode_actions import (
    enter_test_mode,
    enter_normal_mode,
    enter_debug_mode,
    enter_factory_mode,
    get_current_mode,
)

from .status_actions import (
    get_uut_status,
    get_version_info,
    get_serial_number,
    get_temperature,
    get_voltage_levels,
)

from .custom_actions import (
    send_custom_command,
    send_at_command,
    send_binary_command,
    query_response,
    send_and_wait_response,
)

__all__ = [
    # Power actions
    "power_on_uut",
    "power_off_uut",
    "soft_reset_uut",
    "hard_reset_uut",
    "check_power_status",
    
    # Mode actions
    "enter_test_mode",
    "enter_normal_mode",
    "enter_debug_mode",
    "enter_factory_mode",
    "get_current_mode",
    
    # Status actions
    "get_uut_status",
    "get_version_info",
    "get_serial_number",
    "get_temperature",
    "get_voltage_levels",
    
    # Custom actions
    "send_custom_command",
    "send_at_command",
    "send_binary_command",
    "query_response",
    "send_and_wait_response",
]
