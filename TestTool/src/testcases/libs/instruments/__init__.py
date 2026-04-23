"""
仪表控制动作库

提供各种仪表控制相关的业务动作。
"""

from .psu_actions import (
    power_on,
    power_off,
    measure_current,
    measure_voltage,
    set_voltage,
    set_current_limit,
    reset_psu,
    get_psu_status,
)

from .dmm_actions import (
    measure_voltage_dc,
    measure_voltage_ac,
    measure_current_dc,
    measure_current_ac,
    measure_resistance,
    measure_frequency,
    set_measurement_range,
)

__all__ = [
    # PSU actions
    "power_on",
    "power_off",
    "measure_current",
    "measure_voltage",
    "set_voltage",
    "set_current_limit",
    "reset_psu",
    "get_psu_status",
    
    # DMM actions
    "measure_voltage_dc",
    "measure_voltage_ac",
    "measure_current_dc",
    "measure_current_ac",
    "measure_resistance",
    "measure_frequency",
    "set_measurement_range",
]
