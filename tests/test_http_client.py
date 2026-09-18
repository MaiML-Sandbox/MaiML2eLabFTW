import json as _json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import httpx

from maiml2elabftw.adapters.elabftw import http_client as http_client_module
from maiml2elabftw.adapters.elabftw.http_client import (
    ConflictError,
    ElabftwApiError,
    HttpElabftwClient,
    NotFoundError,
    ServerError,
    ValidationError,
)
from maiml2elabftw.core.models import AttachmentDefinition, SourceRef, StepDefinition, StepOrderSource, StepPlan


class RecordingTransport(httpx.BaseTransport):
    """A queue of canned responses, consumed one per request, recording every request made."""

    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("no more canned responses configured for this test")
        response = self._responses.pop(0)
        return response(request) if callable(response) else response


def make_client(transport: RecordingTransport, *, api_key: str = "secret-key-123") -> HttpElabftwClient:
    httpx_client = httpx.Client(transport=transport)
    return HttpElabftwClient(httpx_client, base_url="https://elab.example.test/api/v2", api_key=api_key)


class HttpElabftwClientTests(unittest.TestCase):
    def setUp(self) -> None:
        # Retry-on-failure tests would otherwise really sleep for seconds.
        self._orig_sleep = http_client_module.time.sleep
        http_client_module.time.sleep = lambda _seconds: None
        self.addCleanup(setattr, http_client_module.time, "sleep", self._orig_sleep)

    # -- create_template --------------------------------------------------

    def test_create_template_reads_id_from_location_header(self) -> None:
        transport = RecordingTransport(
            [lambda req: httpx.Response(201, headers={"Location": "https://elab.example.test/api/v2/experiments_templates/42"})]
        )
        client = make_client(transport)

        template_id = client.create_template(title="T", body="B")

        self.assertEqual(template_id, 42)
        request = transport.requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.headers["Authorization"], "secret-key-123")

    def test_create_template_without_location_header_raises(self) -> None:
        transport = RecordingTransport([lambda req: httpx.Response(201)])
        client = make_client(transport)

        with self.assertRaises(ElabftwApiError):
            client.create_template(title="T", body="B")

    def test_create_template_never_retries_on_5xx(self) -> None:
        transport = RecordingTransport([lambda req: httpx.Response(503)])
        client = make_client(transport)

        with self.assertRaises(ServerError):
            client.create_template(title="T", body="B")
        self.assertEqual(len(transport.requests), 1)

    # -- retry behaviour (set_metadata is PATCH: idempotent, so retryable) --

    def test_set_metadata_retries_on_503_then_succeeds(self) -> None:
        transport = RecordingTransport(
            [
                lambda req: httpx.Response(503),
                lambda req: httpx.Response(503),
                lambda req: httpx.Response(200, json={}),
            ]
        )
        client = make_client(transport)

        client.set_metadata(1, {"maiml": {}})

        self.assertEqual(len(transport.requests), 3)

    def test_set_metadata_exhausts_retries_and_raises_server_error(self) -> None:
        transport = RecordingTransport([lambda req: httpx.Response(500)] * 3)
        client = make_client(transport)

        with self.assertRaises(ServerError):
            client.set_metadata(1, {"maiml": {}})
        self.assertEqual(len(transport.requests), 3)

    def test_set_metadata_respects_retry_after_header_on_429(self) -> None:
        transport = RecordingTransport(
            [
                lambda req: httpx.Response(429, headers={"Retry-After": "2"}),
                lambda req: httpx.Response(200, json={}),
            ]
        )
        client = make_client(transport)

        client.set_metadata(1, {})  # should not raise; second attempt succeeds

        self.assertEqual(len(transport.requests), 2)

    def test_set_metadata_does_not_retry_on_422(self) -> None:
        transport = RecordingTransport([lambda req: httpx.Response(422)])
        client = make_client(transport)

        with self.assertRaises(ValidationError):
            client.set_metadata(1, {})
        self.assertEqual(len(transport.requests), 1)

    def test_set_metadata_sends_the_metadata_value_as_a_json_encoded_string(self) -> None:
        # Confirmed against a real eLabFTW server: sending "metadata" as a
        # nested JSON object is rejected with a 500 (the DB column expects
        # an already-JSON-encoded string, MySQL/MariaDB error 3140). Only a
        # string value is accepted, so that is what must go over the wire.
        transport = RecordingTransport([lambda req: httpx.Response(200, json={})])
        client = make_client(transport)

        client.set_metadata(1, {"maiml": {"source": {"document_uuid": "doc-a"}}})

        sent_body = _json.loads(transport.requests[0].read())
        self.assertIsInstance(sent_body["metadata"], str)
        self.assertEqual(_json.loads(sent_body["metadata"]), {"maiml": {"source": {"document_uuid": "doc-a"}}})

    # -- status -> exception type mapping ----------------------------------

    def test_status_codes_map_to_distinct_exception_types(self) -> None:
        cases = {404: NotFoundError, 409: ConflictError, 422: ValidationError}
        for status, expected in cases.items():
            with self.subTest(status=status):
                transport = RecordingTransport([lambda req, status=status: httpx.Response(status)])
                client = make_client(transport)
                with self.assertRaises(expected):
                    client.delete_template(1)

    def test_error_carries_the_response_body_and_includes_it_in_str(self) -> None:
        # The server's own explanation of a 400/422/etc is invaluable for
        # debugging against a real target and contains nothing secret (it's
        # authored by the server, never an echo of the request), so it
        # should show up directly in a traceback without extra code.
        transport = RecordingTransport(
            [lambda req: httpx.Response(400, json={"message": "title is required"})]
        )
        client = make_client(transport)

        with self.assertRaises(ElabftwApiError) as caught:
            client.create_template(title="", body="B")

        self.assertIn("title is required", caught.exception.response_body)
        self.assertIn("title is required", str(caught.exception))

    def test_long_response_body_is_truncated(self) -> None:
        long_body = "x" * 5000
        transport = RecordingTransport([lambda req: httpx.Response(400, text=long_body)])
        client = make_client(transport)

        with self.assertRaises(ElabftwApiError) as caught:
            client.create_template(title="T", body="B")

        self.assertLess(len(caught.exception.response_body), len(long_body))
        self.assertTrue(caught.exception.response_body.endswith("... (truncated)"))

    def test_delete_template_calls_expected_path(self) -> None:
        transport = RecordingTransport([lambda req: httpx.Response(204)])
        client = make_client(transport)

        client.delete_template(7)

        request = transport.requests[0]
        self.assertEqual(request.method, "DELETE")
        self.assertTrue(str(request.url).endswith("/experiments_templates/7"))

    # -- find_duplicate -----------------------------------------------------

    def test_find_duplicate_matches_document_and_method_uuid(self) -> None:
        payload = [
            {"id": 1, "metadata": {"maiml": {"source": {"document_uuid": "doc-a", "method_uuid": "m-a"}}}},
            {"id": 2, "metadata": {"maiml": {"source": {"document_uuid": "doc-b", "method_uuid": "m-b"}}}},
        ]
        transport = RecordingTransport([lambda req: httpx.Response(200, json=payload)])
        client = make_client(transport)

        self.assertEqual(client.find_duplicate("doc-b", "m-b"), 2)

    def test_find_duplicate_returns_none_when_no_candidate_matches(self) -> None:
        transport = RecordingTransport([lambda req: httpx.Response(200, json=[])])
        client = make_client(transport)

        self.assertIsNone(client.find_duplicate("doc-x", "m-x"))

    def test_find_duplicate_parses_metadata_given_as_a_json_string(self) -> None:
        payload = [{"id": 5, "metadata": '{"maiml": {"source": {"document_uuid": "doc-z", "method_uuid": "m-z"}}}'}]
        transport = RecordingTransport([lambda req: httpx.Response(200, json=payload)])
        client = make_client(transport)

        self.assertEqual(client.find_duplicate("doc-z", "m-z"), 5)

    # -- set_steps: one POST per step, never retried -------------------------

    def test_set_steps_posts_once_per_step_in_order(self) -> None:
        steps = StepPlan(
            source=StepOrderSource.PNML,
            steps=(
                StepDefinition(1, "t1", "i1", "First", "Do the first thing", 1),
                StepDefinition(2, "t2", "i2", "Second", "", 1),
            ),
        )
        transport = RecordingTransport(
            [
                lambda req: httpx.Response(
                    201, headers={"Location": "https://elab.example.test/api/v2/experiments_templates/1/steps/1"}
                ),
                lambda req: httpx.Response(
                    201, headers={"Location": "https://elab.example.test/api/v2/experiments_templates/1/steps/2"}
                ),
            ]
        )
        client = make_client(transport)

        client.set_steps(1, steps)

        self.assertEqual(len(transport.requests), 2)
        self.assertIn(b"First: Do the first thing", transport.requests[0].read())
        self.assertIn(b"Second", transport.requests[1].read())

    def test_set_steps_stops_without_retrying_when_one_step_fails(self) -> None:
        steps = StepPlan(
            source=StepOrderSource.PNML,
            steps=(
                StepDefinition(1, "t1", "i1", "First", "", 1),
                StepDefinition(2, "t2", "i2", "Second", "", 1),
            ),
        )
        transport = RecordingTransport([lambda req: httpx.Response(503)])
        client = make_client(transport)

        with self.assertRaises(ServerError):
            client.set_steps(1, steps)
        # Only the first step's single, non-retried POST was ever attempted;
        # a duplicate step is worse than a failure the caller can retry.
        self.assertEqual(len(transport.requests), 1)

    # -- upload_attachment ----------------------------------------------------

    def test_upload_attachment_sends_the_file_contents(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "note.txt"
        path.write_text("hello attachment", encoding="utf-8")
        attachment = AttachmentDefinition(
            attachment_id="a1",
            name="note.txt",
            source_kind="insertion",
            source_ref=SourceRef("insertion", "a1"),
            path=path,
        )
        transport = RecordingTransport(
            [
                lambda req: httpx.Response(
                    201, headers={"Location": "https://elab.example.test/api/v2/experiments_templates/1/uploads/9"}
                )
            ]
        )
        client = make_client(transport)

        client.upload_attachment(1, attachment)

        self.assertIn(b"hello attachment", transport.requests[0].read())

    def test_upload_attachment_without_local_path_raises_without_any_network_call(self) -> None:
        attachment = AttachmentDefinition(
            attachment_id="a1",
            name="note.txt",
            source_kind="insertion",
            source_ref=SourceRef("insertion", "a1"),
            uri="https://example.test/note.txt",
        )
        transport = RecordingTransport([])
        client = make_client(transport)

        with self.assertRaises(ElabftwApiError):
            client.upload_attachment(1, attachment)
        self.assertEqual(transport.requests, [])

    def test_upload_attachment_is_never_retried_on_503(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "note.txt"
        path.write_text("x", encoding="utf-8")
        attachment = AttachmentDefinition(
            attachment_id="a1",
            name="note.txt",
            source_kind="insertion",
            source_ref=SourceRef("insertion", "a1"),
            path=path,
        )
        transport = RecordingTransport([lambda req: httpx.Response(503)])
        client = make_client(transport)

        with self.assertRaises(ServerError):
            client.upload_attachment(1, attachment)
        self.assertEqual(len(transport.requests), 1)

    # -- the API key must never leak ------------------------------------------

    def test_api_key_never_appears_in_any_raised_error_or_repr(self) -> None:
        transport = RecordingTransport([lambda req: httpx.Response(404)])
        client = make_client(transport, api_key="super-secret-do-not-leak")

        with self.assertRaises(NotFoundError) as caught:
            client.delete_template(1)

        self.assertNotIn("super-secret-do-not-leak", str(caught.exception))
        self.assertNotIn("super-secret-do-not-leak", repr(client))


if __name__ == "__main__":
    unittest.main()
