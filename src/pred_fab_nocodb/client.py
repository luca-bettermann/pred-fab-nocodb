"""Public entry point — `NocoDBClient` wires up every typed sub-client."""
from __future__ import annotations

from ._http import _HttpClient
from ._values import ValueClient
from .dim_positions import DimPositionsClient
from .experiments import ExperimentsClient
from .schema import (
    AttributeColumns,
    FeatureColumns,
    ParamColumns,
    Tables,
)
from .studies import StudiesClient
from .study_constants import StudyConstantsClient


class NocoDBClient:
    """Public entry point. Holds typed sub-clients for each table.

    Construct once per session and share across components that need to
    read or write the same NocoDB workspace.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        base_id: str,
        timeout: float = 30.0,
    ):
        self._http = _HttpClient(
            base_url=base_url,
            api_token=api_token,
            timeout=timeout,
        )

        # Independent table clients
        self.studies = StudiesClient(self._http, base_id)
        self.experiments = ExperimentsClient(self._http, base_id)
        self.dim_positions = DimPositionsClient(self._http, base_id)
        self.study_constants = StudyConstantsClient(self._http, base_id)

        # Value clients — share `dim_positions` so the cache benefits all writes
        self.params = ValueClient(
            self._http,
            base_id,
            table=Tables.SET_EXP_PARAMS,
            fk_code_column=ParamColumns.PARAM,
            dim_client=self.dim_positions,
        )
        self.features = ValueClient(
            self._http,
            base_id,
            table=Tables.SET_EXP_FEATURES,
            fk_code_column=FeatureColumns.FEATURE,
            dim_client=self.dim_positions,
        )
        self.attributes = ValueClient(
            self._http,
            base_id,
            table=Tables.SET_EXP_ATTRIBUTES,
            fk_code_column=AttributeColumns.ATTRIBUTE,
            dim_client=self.dim_positions,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "NocoDBClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
