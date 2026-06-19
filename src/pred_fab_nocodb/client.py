"""Public entry point — `NocoDBClient` wires up every typed sub-client."""
from __future__ import annotations

from typing import Any

from ._http import _NocoDBHttp
from ._values import ValueClient
from .datasets import DatasetsClient
from .dim_positions import DimPositionsClient
from .errors import NocoDBError, ValidationError
from .config_params import ConfigParamsClient
from .experiment_sets import ExperimentSetsClient
from .experiments import ExperimentsClient
from .schema import (
    AttributeColumns,
    FeatureColumns,
    ParamColumns,
    Tables,
)
from .hardware import HardwareClient
from .schema_validator import SchemaValidator
from .services import ServicesClient
from .studies import StudiesClient
from .study_constants import StudyConstantsClient
from .units import UnitsClient
from .use_cases import UseCasesClient
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

        Raises `ValidationError` if any of `base_url`, `api_token`, or
        `base_id` is empty / whitespace.
        """
        missing = [
            name for name, val in [
                ("base_url", base_url),
                ("api_token", api_token),
                ("base_id", base_id),
            ] if not (val or "").strip()
        ]
        if missing:
            raise ValidationError(
                f"NocoDBClient: missing required argument(s): {', '.join(missing)}"
            )
        self._http = _NocoDBHttp(
            base_url=base_url,
            api_token=api_token,
            timeout=timeout,
        )
        self._base_id = base_id
        self._table_ids = _resolve_table_ids(self._http, base_id)
        # Per-table LTAR field-id lookup. `child_side` is the table's own
        # LTAR field ids (used for child→parent link writes); `parent_side`
        # is the parent table's reverse-link metadata (used by ValueClient
        # for one-shot bulk parent→children link writes via the same
        # /links/ endpoint, ~2N calls collapsed to 1+K).
        self._link_field_ids, self._reverse_link_ids = _resolve_link_field_ids(
            self._http, self._table_ids,
        )

        def _links(table_name: str) -> dict[str, str]:
            return self._link_field_ids.get(table_name, {})

        def _reverse(table_name: str) -> dict[str, tuple[str, str]]:
            return self._reverse_link_ids.get(table_name, {})

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

        # Optional tables — provisioned during their respective rollouts; ``None`` on bases
        # that don't have them yet (non-breaking until the table exists).
        _all_ids = {t.get("title", ""): t.get("id", "") for t in self._http.meta_list_tables(base_id)}
        _es_id = _all_ids.get(Tables.EXPERIMENT_SETS)
        self.experiment_sets: ExperimentSetsClient | None = (
            ExperimentSetsClient(self._http, base_id, _es_id) if _es_id else None
        )

        # robolab config catalog (params/services/use_cases/units) — LTAR-linked, so resolve
        # their link-field ids over the subset that exists in this base.
        _cat_ids = {
            t: _all_ids[t] for t in
            (Tables.PARAMS, Tables.SERVICES, Tables.USE_CASES, Tables.UNITS, Tables.HARDWARE)
            if _all_ids.get(t)
        }
        _cat_links, _ = _resolve_link_field_ids(self._http, _cat_ids) if _cat_ids else ({}, {})
        self.config_params: ConfigParamsClient | None = (
            ConfigParamsClient(self._http, base_id, _cat_ids[Tables.PARAMS],
                               link_field_ids=_cat_links.get(Tables.PARAMS, {}))
            if Tables.PARAMS in _cat_ids else None
        )
        self.services: ServicesClient | None = (
            ServicesClient(self._http, base_id, _cat_ids[Tables.SERVICES],
                           link_field_ids=_cat_links.get(Tables.SERVICES, {}))
            if Tables.SERVICES in _cat_ids else None
        )
        self.use_cases: UseCasesClient | None = (
            UseCasesClient(self._http, base_id, _cat_ids[Tables.USE_CASES],
                           link_field_ids=_cat_links.get(Tables.USE_CASES, {}))
            if Tables.USE_CASES in _cat_ids else None
        )
        self.units: UnitsClient | None = (
            UnitsClient(self._http, base_id, _cat_ids[Tables.UNITS],
                        link_field_ids=_cat_links.get(Tables.UNITS, {}))
            if Tables.UNITS in _cat_ids else None
        )
        self.hardware: HardwareClient | None = (
            HardwareClient(self._http, base_id, _cat_ids[Tables.HARDWARE],
                           link_field_ids=_cat_links.get(Tables.HARDWARE, {}))
            if Tables.HARDWARE in _cat_ids else None
        )

        # Value clients — share `dim_positions` so the cache benefits all writes
        self.params = ValueClient(
            self._http,
            base_id,
            self._table_ids[Tables.SET_EXP_PARAMS],
            fk_code_column=ParamColumns.PARAM,
            dim_client=self.dim_positions,
            link_field_ids=_links(Tables.SET_EXP_PARAMS),
            reverse_link_ids=_reverse(Tables.SET_EXP_PARAMS),
        )
        self.features = ValueClient(
            self._http,
            base_id,
            self._table_ids[Tables.SET_EXP_FEATURES],
            fk_code_column=FeatureColumns.FEATURE,
            dim_client=self.dim_positions,
            link_field_ids=_links(Tables.SET_EXP_FEATURES),
            reverse_link_ids=_reverse(Tables.SET_EXP_FEATURES),
        )
        self.attributes = ValueClient(
            self._http,
            base_id,
            self._table_ids[Tables.SET_EXP_ATTRIBUTES],
            fk_code_column=AttributeColumns.ATTRIBUTE,
            dim_client=self.dim_positions,
            link_field_ids=_links(Tables.SET_EXP_ATTRIBUTES),
            reverse_link_ids=_reverse(Tables.SET_EXP_ATTRIBUTES),
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
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, tuple[str, str]]]]:
    """For every required table, resolve LTAR field ids in both directions.

    Returns ``(child_side, parent_side)``:

    * ``child_side[table_name][field_name] = field_id`` — the LTAR field
      id on the table itself, used to call ``http.link_records(...)``
      against NocoDB's dedicated
      ``/api/v2/tables/{tid}/links/{linkFieldId}/records/{rid}`` endpoint
      (the only place NocoDB v2 reliably honours link-field writes — the
      records-create endpoint silently drops them in bulk POSTs).

    * ``parent_side[child_table_name][field_name] =
      (parent_table_id, parent_reverse_field_id)`` — the parent table's
      reverse LTAR field id that points back at this child table's
      ``field_name``. Used to issue ONE bulk parent-side link call for N
      child rows instead of N child-side calls. Empty when the LTAR
      metadata doesn't expose ``colOptions.fk_related_model_id`` (e.g.
      in unit-test fixtures that don't seed it) — callers must fall
      back to per-row child-side linking in that case.
    """
    # First pass: for each table, harvest every LTAR's (field_id, related_table_id).
    # `colOptions.fk_related_model_id` points at the OTHER side of the link.
    table_ltars: dict[str, dict[str, dict[str, str]]] = {}
    for table_name, table_id in table_ids.items():
        meta = http.meta_get_table(table_id)
        ltars: dict[str, dict[str, str]] = {}
        for col in meta.get("columns", []):
            if col.get("uidt") != "LinkToAnotherRecord":
                continue
            title = col.get("title", "")
            field_id = col.get("id", "")
            col_options = col.get("colOptions") or {}
            related_model_id = col_options.get("fk_related_model_id") or ""
            if title and field_id:
                ltars[title] = {
                    "field_id": str(field_id),
                    "related_model_id": str(related_model_id),
                }
        table_ltars[table_id] = ltars

    # child_side: keep the existing flat {field_name → field_id} shape.
    child_side: dict[str, dict[str, str]] = {
        table_name: {fname: info["field_id"] for fname, info in table_ltars[table_id].items()}
        for table_name, table_id in table_ids.items()
    }

    # parent_side: for each child LTAR, find the parent table's reverse LTAR
    # (the field on the related model whose `related_model_id` points back).
    parent_side: dict[str, dict[str, tuple[str, str]]] = {}
    for child_name, child_tid in table_ids.items():
        reverse_map: dict[str, tuple[str, str]] = {}
        for child_field_name, child_info in table_ltars.get(child_tid, {}).items():
            parent_tid = child_info["related_model_id"]
            if not parent_tid or parent_tid not in table_ltars:
                continue
            for parent_field_name, parent_info in table_ltars[parent_tid].items():
                if parent_info["related_model_id"] == child_tid:
                    reverse_map[child_field_name] = (
                        parent_tid,
                        parent_info["field_id"],
                    )
                    break
        parent_side[child_name] = reverse_map

    return child_side, parent_side
