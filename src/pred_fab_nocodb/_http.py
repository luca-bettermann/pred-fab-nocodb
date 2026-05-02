"""Internal HTTP wrapper around the NocoDB REST API."""
from __future__ import annotations

from typing import Any

import httpx

from .errors import ConflictError, NocoDBError, NotFoundError, ValidationError


class _HttpClient:
    """Thin httpx-based client for NocoDB's REST API.

    Centralises authentication, error mapping, and response parsing.
    """

    def __init__(self, *, base_url: str, api_token: str, timeout: float = 30.0):
        self._client = httpx.Client(
            base_url=base_url,
            headers={"xc-token": api_token},
            timeout=timeout,
        )

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        """GET — returns parsed JSON body."""
        return self._parse(self._client.get(path, params=params))

    def post(self, path: str, body: Any) -> dict[str, Any]:
        """POST — returns parsed JSON body."""
        return self._parse(self._client.post(path, json=body))

    def patch(self, path: str, body: Any) -> dict[str, Any]:
        """PATCH — returns parsed JSON body."""
        return self._parse(self._client.patch(path, json=body))

    def delete(self, path: str) -> None:
        """DELETE — returns None."""
        self._parse(self._client.delete(path), expect_body=False)

    @staticmethod
    def _parse(response: httpx.Response, expect_body: bool = True) -> dict[str, Any]:
        """Map HTTP status to typed exceptions; return JSON body if expected."""
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
        return response.json() if expect_body else {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "_HttpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
