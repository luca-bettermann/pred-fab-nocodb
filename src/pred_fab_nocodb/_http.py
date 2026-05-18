"""Internal HTTP wrapper around the NocoDB v2 REST API.

Centralises authentication, error mapping, and table-id resolution. All
table-specific clients receive a `_NocoDBHttp` and call `.records_*` /
`.meta_*` helpers; they don't construct URLs directly.
"""
from __future__ import annotations

from typing import Any

import httpx

from .errors import ConflictError, NocoDBError, NotFoundError, ValidationError


class _NocoDBHttp:
    """httpx-based REST client for NocoDB v2.

    Public methods are split by concern: `records_*` for the table-data API,
    `meta_*` for the metadata API (table listing for ID resolution).
    """

    def __init__(self, *, base_url: str, api_token: str, timeout: float = 30.0):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"xc-token": api_token, "Content-Type": "application/json"},
            timeout=timeout,
        )

    # ─── Records API ──────────────────────────────────────────────────

    _PAGE_SIZE = 200

    def records_list(
        self,
        table_id: str,
        *,
        where: str | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        sort: str | None = None,
    ) -> list[dict[str, Any]]:
        """`GET /api/v2/tables/{tableId}/records` — auto-paginates to fetch all rows."""
        params: dict[str, Any] = {}
        if where is not None:
            params["where"] = where
        if fields is not None:
            params["fields"] = ",".join(fields)
        if sort is not None:
            params["sort"] = sort

        if limit is not None:
            params["limit"] = limit
            if offset is not None:
                params["offset"] = offset
            body = self._request("GET", f"/api/v2/tables/{table_id}/records", params=params)
            rows = body.get("list", [])
            return rows if isinstance(rows, list) else []

        all_rows: list[dict[str, Any]] = []
        current_offset = offset or 0
        while True:
            params["limit"] = self._PAGE_SIZE
            params["offset"] = current_offset
            body = self._request("GET", f"/api/v2/tables/{table_id}/records", params=params)
            page = body.get("list", [])
            if not isinstance(page, list):
                break
            all_rows.extend(page)
            if len(page) < self._PAGE_SIZE:
                break
            current_offset += self._PAGE_SIZE
        return all_rows

    def records_get(self, table_id: str, record_id: int) -> dict[str, Any]:
        """`GET /api/v2/tables/{tableId}/records/{rowId}`."""
        return self._request("GET", f"/api/v2/tables/{table_id}/records/{record_id}")

    _BATCH_LIMIT = 100

    def records_create(self, table_id: str, body: dict[str, Any] | list[dict[str, Any]]) -> Any:
        """`POST /api/v2/tables/{tableId}/records` — auto-batches lists > 100."""
        return self._batched("POST", table_id, body)

    def records_update(
        self,
        table_id: str,
        body: dict[str, Any] | list[dict[str, Any]],
    ) -> Any:
        """`PATCH /api/v2/tables/{tableId}/records` — auto-batches lists > 100."""
        return self._batched("PATCH", table_id, body)

    def records_delete(self, table_id: str, body: dict[str, Any] | list[dict[str, Any]]) -> Any:
        """`DELETE /api/v2/tables/{tableId}/records` — auto-batches lists > 100."""
        return self._batched("DELETE", table_id, body)

    def _batched(self, method: str, table_id: str, body: dict[str, Any] | list[dict[str, Any]]) -> Any:
        url = f"/api/v2/tables/{table_id}/records"
        if not isinstance(body, list) or len(body) <= self._BATCH_LIMIT:
            return self._request(method, url, json=body)
        results = []
        for i in range(0, len(body), self._BATCH_LIMIT):
            results.append(self._request(method, url, json=body[i:i + self._BATCH_LIMIT]))
        return results

    def records_count(self, table_id: str, *, where: str | None = None) -> int:
        """`GET /api/v2/tables/{tableId}/records/count` — total rows (filtered)."""
        params: dict[str, Any] = {}
        if where is not None:
            params["where"] = where
        body = self._request("GET", f"/api/v2/tables/{table_id}/records/count", params=params)
        return int(body.get("count", 0))

    # ─── Meta API ─────────────────────────────────────────────────────

    def meta_list_tables(self, base_id: str) -> list[dict[str, Any]]:
        """`GET /api/v2/meta/bases/{baseId}/tables` — list all tables in a base."""
        body = self._request("GET", f"/api/v2/meta/bases/{base_id}/tables")
        tables = body.get("list", [])
        return tables if isinstance(tables, list) else []

    def meta_get_table(self, table_id: str) -> dict[str, Any]:
        """`GET /api/v2/meta/tables/{tableId}` — full table metadata incl. columns."""
        return self._request("GET", f"/api/v2/meta/tables/{table_id}")

    def link_records(
        self,
        *,
        table_id: str,
        link_field_id: str,
        record_id: int,
        linked_record_ids: int | list[int],
    ) -> None:
        """`POST /api/v2/tables/{tableId}/links/{linkFieldId}/records/{recordId}`.

        Sets a LinkToAnotherRecord (LTAR) field. NocoDB v2's records-create
        endpoint silently drops link-field values from a bulk POST body, so
        link writes must go through this dedicated endpoint to be honoured.

        Body shape: a single int → ``{"Id": <id>}`` (single-record link);
        a list of ints → ``[{"Id": <id1>}, ...]`` (has-many / many-to-many).
        """
        body: dict[str, Any] | list[dict[str, Any]]
        if isinstance(linked_record_ids, int):
            body = {"Id": int(linked_record_ids)}
        else:
            body = [{"Id": int(rid)} for rid in linked_record_ids]
        self._request(
            "POST",
            f"/api/v2/tables/{table_id}/links/{link_field_id}/records/{record_id}",
            json=body,
        )

    # ─── Internal ──────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> dict[str, Any]:
        """Issue a request; map status codes to typed exceptions; return parsed JSON."""
        response = self._client.request(method, path, params=params or {}, json=json)
        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> dict[str, Any]:
        status = response.status_code
        if status == 404:
            raise NotFoundError(f"{response.request.method} {response.url}: not found")
        if status == 409:
            raise ConflictError(f"{response.request.method} {response.url}: conflict")
        if 400 <= status < 500:
            raise ValidationError(
                f"{response.request.method} {response.url}: {status} {response.text}"
            )
        if status >= 500:
            raise NocoDBError(
                f"{response.request.method} {response.url}: server error {status}"
            )
        if not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            raise NocoDBError(
                f"{response.request.method} {response.url}: invalid JSON response"
            ) from exc
        return data if isinstance(data, dict) else {"_": data}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "_NocoDBHttp":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
