from __future__ import annotations

import json as _json
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from ...core.models import AttachmentDefinition, StepPlan


class ElabftwApiError(Exception):
    """Base class for every error :class:`HttpElabftwClient` can raise.

    Carries the HTTP method, request path, status code (when there is
    one), and the server's own response body via ``response_body`` -
    never the request/response HEADERS, so the API key can never end up in
    a log line or an exception's ``str()``. The response body is safe to
    include: it is authored by the server, not an echo of the request, so
    it never contains the Authorization header. It is truncated to a
    reasonable length and included in ``str(exc)`` so it shows up directly
    in a traceback without extra code at the call site.
    """

    def __init__(
        self,
        message: str,
        *,
        method: str,
        path: str,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.method = method
        self.path = path
        self.status_code = status_code
        self.response_body = response_body

    def __str__(self) -> str:
        base = super().__str__()
        if self.response_body:
            return f"{base} | response body: {self.response_body}"
        return base


class NotFoundError(ElabftwApiError):
    """404: the template (or sub-resource) does not exist."""


class ConflictError(ElabftwApiError):
    """409: the server refused because of a conflicting existing resource."""


class ValidationError(ElabftwApiError):
    """422: the server rejected the request body/shape."""


class RateLimitedError(ElabftwApiError):
    """429: rate limited. Only ever retried for idempotent methods."""

    def __init__(
        self,
        message: str,
        *,
        method: str,
        path: str,
        status_code: int | None = None,
        response_body: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, method=method, path=path, status_code=status_code, response_body=response_body)
        self.retry_after = retry_after


class ServerError(ElabftwApiError):
    """5xx: transient or persistent server-side failure."""


class TransportError(ElabftwApiError):
    """A connection, timeout, or other transport-level failure (no response)."""


# GET/PATCH/DELETE are safe to retry on a transient failure (no new resource
# is created by re-sending them). POST is never retried here, regardless of
# this set, because create_template/set_steps/upload_attachment always pass
# retryable=False explicitly - duplicate creation is worse than a failed
# call the caller can retry deliberately.
_RETRYABLE_STATUS_TYPES = ("RateLimitedError", "ServerError")
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (0.5, 1.5, 3.0)
_MAX_RESPONSE_BODY_CHARS = 2000


def _truncated_body(response: httpx.Response) -> str | None:
    """The server's response text, safe to surface in an error message (it
    is server-authored, never an echo of the request headers), capped so a
    large HTML error page doesn't flood a traceback."""
    try:
        text = response.text
    except Exception:  # noqa: BLE001 - decoding a body should never itself crash error handling
        return None
    if not text:
        return None
    if len(text) <= _MAX_RESPONSE_BODY_CHARS:
        return text
    return text[:_MAX_RESPONSE_BODY_CHARS] + "... (truncated)"


class HttpElabftwClient:
    """``ElabftwClient`` implementation that talks to a real eLabFTW server.

    Deliberately not built on a generated SDK: the OpenAPI-declared shape of
    the ``metadata`` field has been reported to drift from what a real
    server actually returns/accepts (elabapi-python#35), so this talks to
    the documented REST surface directly with a thin httpx wrapper, which
    makes it easy to inspect real request/response bodies while the target
    server's exact contract is being confirmed against its own OpenAPI spec.

    Field/endpoint names here follow eLabFTW's publicly documented v2 API
    (Authorization header carrying the raw API key, ``/api/v2/...`` paths,
    created-id via the ``Location`` header on ``201 Created``). Treat them
    as the starting assumption, not a guarantee, for any specific target
    server/version - confirm against that server's own OpenAPI spec before
    relying on this in production (see the project's implementation-order
    notes: pin the target version and its OpenAPI spec first).
    """

    def __init__(self, client: httpx.Client, *, base_url: str, api_key: str) -> None:
        # "Private" by convention only within this module: never read back
        # into a message this class raises, logs, or repr()s.
        self._client = client
        self._base_url = base_url.rstrip("/") + "/"
        self._api_key = api_key

    @classmethod
    def create(
        cls,
        base_url: str,
        api_key: str,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
    ) -> "HttpElabftwClient":
        """Build a client with TLS verification on and explicit timeouts.

        There is intentionally no ``verify=False`` escape hatch on this
        convenience constructor. A target that needs a custom CA bundle (or
        a test that needs a MockTransport) should build its own
        ``httpx.Client`` and use the main constructor instead.
        """
        timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout)
        client = httpx.Client(timeout=timeout, verify=True)
        return cls(client, base_url=base_url, api_key=api_key)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpElabftwClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:  # never leak the api key via repr/logging
        return f"HttpElabftwClient(base_url={self._base_url!r})"

    # -- ElabftwClient Protocol ----------------------------------------

    def find_duplicate(self, document_uuid: str, method_uuid: str) -> int | None:
        # eLabFTW's generic search matches against metadata text, so it can
        # only narrow candidates - the document/method UUID match itself is
        # re-checked here rather than trusted from the search result.
        response = self._request(
            "GET", "experiments_templates", params={"q": method_uuid, "extended": "1"}, retryable=True
        )
        for item in response.json():
            metadata = self._parse_metadata_field(item.get("metadata"))
            source = metadata.get("maiml", {}).get("source", {})
            if source.get("document_uuid") == document_uuid and source.get("method_uuid") == method_uuid:
                return int(item["id"])
        return None

    def create_template(self, *, title: str, body: str) -> int:
        response = self._request(
            "POST", "experiments_templates", json={"title": title, "body": body}, retryable=False
        )
        return self._id_from_location(response, method="POST", path="experiments_templates")

    def set_metadata(self, template_id: int, metadata: dict[str, Any]) -> None:
        # Confirmed empirically against a real eLabFTW server: the
        # `experiments_templates.metadata` column is JSON-typed, and the API
        # requires the *value* it is given to already be a JSON-encoded
        # string - sending a nested JSON object for "metadata" is rejected
        # with a 500 ("Invalid JSON text: 'Invalid value.' ... for column
        # 'experiments_templates.metadata'", MySQL/MariaDB error 3140).
        # Sending `_json.dumps(metadata)` as the string value succeeds. This
        # matches how GET responses always return metadata as a string too
        # (see _parse_metadata_field) - eLabFTW treats this column as an
        # opaque string end-to-end, never a structured JSON value at the API
        # boundary, despite the OpenAPI spec's own ambiguity here
        # (elabapi-python#35 / elabftw/elabftw#5721).
        self._request(
            "PATCH",
            f"experiments_templates/{template_id}",
            json={"metadata": _json.dumps(metadata)},
            retryable=True,
        )

    def set_steps(self, template_id: int, steps: StepPlan) -> None:
        for step in steps.steps:
            step_body = f"{step.title}: {step.body}" if step.body else step.title
            # Each step is its own creation (POST) - never retried, so a
            # transient failure can't leave a duplicated step behind. If
            # this raises partway through, ElabftwTemplateWriter rolls the
            # whole template back rather than trying to undo individual
            # steps here.
            self._request(
                "POST", f"experiments_templates/{template_id}/steps", json={"body": step_body}, retryable=False
            )

    def upload_attachment(self, template_id: int, attachment: AttachmentDefinition) -> None:
        content, filename = self._read_attachment_content(attachment)
        self._request(
            "POST",
            f"experiments_templates/{template_id}/uploads",
            files={"file": (filename, content)},
            retryable=False,
        )

    def delete_template(self, template_id: int) -> None:
        self._request("DELETE", f"experiments_templates/{template_id}", retryable=True)

    # -- internals -------------------------------------------------------

    @staticmethod
    def _read_attachment_content(attachment: AttachmentDefinition) -> tuple[bytes, str]:
        if attachment.path is not None:
            return attachment.path.read_bytes(), attachment.name
        raise ElabftwApiError(
            f"attachment {attachment.attachment_id!r} has no local file to read "
            "(uri-only attachments are not fetched by this client)",
            method="POST",
            path=f"uploads:{attachment.attachment_id}",
        )

    @staticmethod
    def _id_from_location(response: httpx.Response, *, method: str, path: str) -> int:
        location = response.headers.get("Location")
        if not location:
            raise ElabftwApiError(
                f"{method} {path} returned {response.status_code} without a Location header",
                method=method,
                path=path,
                status_code=response.status_code,
                response_body=_truncated_body(response),
            )
        try:
            return int(location.rstrip("/").rsplit("/", 1)[-1])
        except ValueError as exc:
            raise ElabftwApiError(
                f"could not parse an id out of Location header {location!r}",
                method=method,
                path=path,
                status_code=response.status_code,
                response_body=_truncated_body(response),
            ) from exc

    @staticmethod
    def _parse_metadata_field(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return _json.loads(raw)
            except ValueError:
                return {}
        return {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        retryable: bool,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = urljoin(self._base_url, path)
        headers = {"Authorization": self._api_key}
        attempts = _MAX_ATTEMPTS if retryable else 1

        last_error: ElabftwApiError | None = None
        for attempt in range(attempts):
            try:
                response = self._client.request(method, url, headers=headers, params=params, json=json, files=files)
            except httpx.TimeoutException as exc:
                last_error = TransportError(f"{method} {path} timed out: {exc}", method=method, path=path)
            except httpx.TransportError as exc:
                last_error = TransportError(f"{method} {path} failed to connect: {exc}", method=method, path=path)
            else:
                error = self._error_for_status(response, method=method, path=path)
                if error is None:
                    return response
                last_error = error
                if not retryable or type(error).__name__ not in _RETRYABLE_STATUS_TYPES:
                    raise error

            if attempt + 1 < attempts:
                delay = _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
                if isinstance(last_error, RateLimitedError) and last_error.retry_after is not None:
                    delay = last_error.retry_after
                time.sleep(delay)

        assert last_error is not None
        raise last_error

    @staticmethod
    def _error_for_status(response: httpx.Response, *, method: str, path: str) -> ElabftwApiError | None:
        status = response.status_code
        if status < 400:
            return None
        message = f"{method} {path} returned {status}"
        body = _truncated_body(response)
        if status == 404:
            return NotFoundError(message, method=method, path=path, status_code=status, response_body=body)
        if status == 409:
            return ConflictError(message, method=method, path=path, status_code=status, response_body=body)
        if status == 422:
            return ValidationError(message, method=method, path=path, status_code=status, response_body=body)
        if status == 429:
            retry_after_header = response.headers.get("Retry-After")
            retry_after = (
                float(retry_after_header)
                if retry_after_header and retry_after_header.replace(".", "", 1).isdigit()
                else None
            )
            return RateLimitedError(
                message, method=method, path=path, status_code=status, response_body=body, retry_after=retry_after
            )
        if status >= 500:
            return ServerError(message, method=method, path=path, status_code=status, response_body=body)
        return ElabftwApiError(message, method=method, path=path, status_code=status, response_body=body)
