"""
Normalize engineer-service version responses to the dict shape used by CompareVersionStep.

Previously provided by vita_engineer_client.response_handlers; kept in TestTool after client updates.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

# Keep in sync with CompareVersionStep._looks_like_version_payload
_DUAL_KEYS = ("S100", "X5")


def _looks_like_version_payload(data: Dict[str, Any]) -> bool:
    if any(key in data for key in _DUAL_KEYS):
        return True
    devices = data.get("devices")
    return isinstance(devices, list)


def normalize_version_payload(raw: Any) -> Optional[Dict[str, Any]]:
    """
    Unwrap JSON envelopes (status/data/response, stringified data) and return the inner
    version dict when it contains S100/X5 blocks or a devices list; otherwise None.
    """
    if raw is None:
        return None

    if isinstance(raw, str):
        text = raw.strip()
        if not text.startswith("{"):
            return None
        try:
            return normalize_version_payload(json.loads(text))
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    if not isinstance(raw, dict):
        return None

    if _looks_like_version_payload(raw):
        return raw

    for key in ("data", "payload", "result", "body"):
        inner = raw.get(key)
        if inner is None:
            continue
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        nested = normalize_version_payload(inner)
        if nested is not None:
            return nested

    resp = raw.get("response")
    if isinstance(resp, dict):
        nested = normalize_version_payload(resp)
        if nested is not None:
            return nested

    return None
