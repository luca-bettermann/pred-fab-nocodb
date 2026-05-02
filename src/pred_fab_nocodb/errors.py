"""Exception types raised by pred-fab-nocodb."""
from __future__ import annotations


class NocoDBError(Exception):
    """Base class for all pred-fab-nocodb errors."""


class NotFoundError(NocoDBError):
    """A requested record was not found (HTTP 404)."""


class ValidationError(NocoDBError):
    """A request was rejected as invalid (HTTP 4xx other than 404/409)."""


class ConflictError(NocoDBError):
    """A unique-constraint conflict (HTTP 409) — e.g. duplicate code or axes."""
