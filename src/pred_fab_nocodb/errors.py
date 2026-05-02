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


class SchemaMismatchError(NocoDBError):
    """The schema stored in NocoDB diverges from the expected schema.

    Raised by `SchemaValidator.assert_compatible` and at `NocoDBClient` init
    when an `expected_schema` is provided and doesn't match `studies.schema_json`.
    """

    def __init__(self, study_code: str, differences: list[str]):
        self.study_code = study_code
        self.differences = differences
        super().__init__(
            f"NocoDB schema for study {study_code!r} does not match expected; "
            f"differences:\n  - " + "\n  - ".join(differences)
        )
