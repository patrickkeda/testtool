"""
治具控制动作库

提供治具控制相关的业务动作。
"""

from .relay_actions import (
    relay_on,
    relay_off,
    set_relay_state,
    get_relay_state,
    toggle_relay,
)

from .clamp_actions import (
    clamp_on,
    clamp_off,
    set_clamp_force,
    get_clamp_status,
    emergency_release,
)

__all__ = [
    # Relay actions
    "relay_on",
    "relay_off",
    "set_relay_state",
    "get_relay_state",
    "toggle_relay",
    
    # Clamp actions
    "clamp_on",
    "clamp_off",
    "set_clamp_force",
    "get_clamp_status",
    "emergency_release",
]
