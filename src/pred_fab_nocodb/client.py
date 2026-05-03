"""Public entry point — `NocoDBClient` wires up every typed sub-client."""
from __future__ import annotations

from typing import Any

from ._http import _NocoDBHttp
from ._values import ValueClient
from .datasets import DatasetsClient
from .dim_positions import DimPositionsClient
from .errors import NocoDBError
from .experiments import ExperimentsClient
from .schema import (
    AttributeColumns,
    FeatureColumns,
    ParamColumns,
    Tables,
)
from .schema_validator import SchemaValidator
from .studies import StudiesClient
from .study_constants import StudyConstantsClient
from .workflows import WorkflowsClient

# Tables we expect to find in the NocoDB workspace at construction time.
_REQUIRED_TABLES = (
    Tables.STUDIES,
    Tables.EXPERIMENTS,
    Tables.DATASETS,
    Tables.DIM_POSITIONS,
    Tables.SET_STUDY_CONSTANTS,
    Tables.SET_EXP_PARAMS,
    Tables.SET_EXP_FEATURES,
    Tables.SET_EXP_ATTRIBUTES,
)


class NocoDBClient:
    """Public entry point. Holds typed sub-clients for each table.

    Construct once per session and share across components that need to
    read or write the same NocoDB workspace.

    On construction, resolves NocoDB internal table-IDs from human-readable
    table names via the meta API, so all subsequent calls use the IDs.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        base_id: str,
        timeout: float = 30.0,
        study_code: str | None = None,
        expected_schema: dict[str, Any] | None = None,
    ):
        """Construct a NocoDB client.

        If both `study_code` and `expected_schema` are supplied, the client
        pulls `studies.schema_json` for that study at init and validates it
        against `expected_schema`. Raises `SchemaMismatchError` on divergence.
        """
        self._http = _NocoDBHttp(
            base_url=base_url,
            api_token=api_token,
            timeout=timeout,
        )
        self._base_id = base_id
        self._table_ids = _resolve_table_ids(self._http, base_id)
        # Per-table LTAR field-id lookup, used by every client to set links
        # via NocoDB's dedicated `/links/` endpoint.
        self._link_field_ids = _resolve_link_field_ids(self._http, self._table_ids)

        def _links(table_name: str) -> dict[str, str]:
            return self._link_field_ids.get(table_name, {})

        # Independent table clients
        self.studies = StudiesClient(
            self._http, base_id, self._table_ids[Tables.STUDIES],
            link_field_ids=_links(Tables.STUDIES),
        )
        self.experiments = ExperimentsClient(
            self._http, base_id, self._table_ids[Tables.EXPERIMENTS],
            link_field_ids=_links(Tables.EXPERIMENTS),
        )
        self.datasets = DatasetsClient(
            self._http, base_id, self._table_ids[Tables.DATASETS],
            link_field_ids=_links(Tables.DATASETS),
        )
        self.dim_positions = DimPositionsClient(
            self._http, base_id, self._table_ids[Tables.DIM_POSITIONS],
            link_field_ids=_links(Tables.DIM_POSITIONS),
        )
        self.study_constants = StudyConstantsClient(
            self._http, base_id, self._table_ids[Tables.SET_STUDY_CONSTANTS],
            link_field_ids=_links(Tables.SET_STUDY_CONSTANTS),
        )

        # Value clients — share `dim_positions` so the cache benefits all writes
        self.params = ValueClient(
            self._http,
            base_id,
            self._table_ids[Tables.SET_EXP_PARAMS],
            fk_code_column=ParamColumns.PARAM,
            dim_client=self.dim_positions,
            link_field_ids=_links(Tables.SET_EXP_PARAMS),
        )
        self.features = ValueClient(
            self._http,
            base_id,
            self._table_ids[Tables.SET_EXP_FEATURES],
            fk_code_column=FeatureColumns.FEATURE,
            dim_client=self.dim_positions,
            link_field_ids=_links(Tables.SET_EXP_FEATURES),
        )
        self.attributes = ValueClient(
            self._http,
            base_id,
            self._table_ids[Tables.SET_EXP_ATTRIBUTES],
            fk_code_column=AttributeColumns.ATTRIBUTE,
            dim_client=self.dim_positions,
            link_field_ids=_links(Tables.SET_EXP_ATTRIBUTES),
        )

        # Workflow helpers — composed from the above
        self.workflows = WorkflowsClient(self)

        # Optional schema validation against the expected study schema
        if study_code is not None and expected_schema is not None:
            study = self.studies.get_by_code(study_code)
            actual_schema = self.studies.pull_schema(study.id)
            SchemaValidator.assert_compatible(
                expected_schema, actual_schema, study_code=study_code,
            )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "NocoDBClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _resolve_table_ids(http: _NocoDBHttp, base_id: str) -> dict[str, str]:
    """Resolve table_name → table_id for every required table in the base."""
    tables = http.meta_list_tables(base_id)
    by_name = {t.get("title", ""): t.get("id", "") for t in tables}
    missing = [name for name in _REQUIRED_TABLES if name not in by_name or not by_name[name]]
    if missing:
        raise NocoDBError(
            f"NocoDB base {base_id!r} is missing required tables: {missing}"
        )
    return {name: by_name[name] for name in _REQUIRED_TABLES}


def _resolve_link_field_ids(
    http: _NocoDBHttp,
    table_ids: dict[str, str],
) -> dict[str, dict[str, str]]:
    """For every required table, resolve {field_name → link_field_id} for its
    LinkToAnotherRecord (LTAR) columns.

    Used by sub-clients to call ``http.link_records(...)`` against NocoDB's
    dedicated `/api/v2/tables/{tid}/links/{linkFieldId}/records/{rid}`
    endpoint — the only place NocoDB v2 reliably honours link-field writes
    (the records-create endpoint silently drops them in bulk POSTs).
    """
    out: dict[str, dict[str, str]] = {}
    for table_name, table_id in table_ids.items():
        meta = http.meta_get_table(table_id)
        ltar_fields: dict[str, str] = {}
        for col in meta.get("columns", []):
            if col.get("uidt") != "LinkToAnotherRecord":
                continue
            title = col.get("title", "")
            field_id = col.get("id", "")
            if title and field_id:
                ltar_fields[title] = field_id
        out[table_name] = ltar_fields
    return out
