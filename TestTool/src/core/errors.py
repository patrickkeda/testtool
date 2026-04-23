from __future__ import annotations

class CoreError(Exception):
	"""Base class for core-layer errors."""

class RetryableError(CoreError):
	"""Transient error that may succeed on retry."""

class TimeoutError(CoreError):
	"""Operation exceeded the configured timeout."""

class ValidationError(CoreError):
	"""Input/configuration validation failed."""

class AuthError(CoreError):
	"""Authentication/authorization failure."""

class ResourceBusyError(CoreError):
	"""Resource is temporarily unavailable/busy."""

__all__ = [
	"CoreError",
	"RetryableError",
	"TimeoutError",
	"ValidationError",
	"AuthError",
	"ResourceBusyError",
]
