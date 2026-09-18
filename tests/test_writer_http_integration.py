"""End-to-end check: real Reader -> Resolver -> Planner -> Writer, talking to
HttpElabftwClient over a mocked transport (no real network). This is the one
test that exercises every layer together, so a future change to any of them
that breaks the wiring - not just one unit's own contract - shows up here.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

import httpx

from maiml2elabftw.adapters.elabftw import ElabftwTemplateWriter, HttpElabftwClient
from maiml2elabftw.adapters.maiml import ProtocolReader
from maiml2elabftw.ordering import PnmlOrderResolver
from maiml2elabftw.planning import TemplatePlanner

from test_reader import XML as PROTOCOL_XML


class RecordingTransport(httpx.BaseTransport):
    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self._responses.pop(0)
        return response(request) if callable(response) else response


class WriterHttpIntegrationTests(unittest.TestCase):
    def _build_plan(self, xml: str = PROTOCOL_XML):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "protocol.maiml"
        path.write_text(xml, encoding="utf-8")
        document = ProtocolReader().read(path)
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        return TemplatePlanner().build(document, method, steps)

    def test_full_pipeline_creates_template_via_http_client(self) -> None:
        # The fixture's document-level <insertion> only carries a URI, never
        # a local path (ProtocolReader has nowhere to fetch it from yet -
        # see test_insertion_without_a_local_file_fails_upload_and_rolls_back
        # below for that boundary). Drop it here so this test exercises the
        # path that already works end-to-end: uploading the one attachment
        # that *is* a real local file, the original .maiml itself.
        xml_without_insertion = PROTOCOL_XML.replace(
            "<insertion>\n      <uri>attachment.txt</uri>\n      <hash>YWJjMTIz</hash>\n    </insertion>\n    ",
            "",
        )
        plan = self._build_plan(xml_without_insertion)
        self.assertEqual(len(plan.attachments), 1)
        self.assertEqual(plan.attachments[0].source_kind, "source_maiml")
        base = "https://elab.example.test/api/v2/"

        transport = RecordingTransport(
            [
                lambda req: httpx.Response(200, json=[]),  # find_duplicate: no match
                lambda req: httpx.Response(201, headers={"Location": base + "experiments_templates/55"}),  # create
                lambda req: httpx.Response(201, headers={"Location": base + "experiments_templates/55/steps/1"}),
                lambda req: httpx.Response(201, headers={"Location": base + "experiments_templates/55/steps/2"}),
                lambda req: httpx.Response(200, json={}),  # set_metadata
                *(
                    lambda req: httpx.Response(
                        201, headers={"Location": base + "experiments_templates/55/uploads/1"}
                    )
                    for _ in plan.attachments
                ),
            ]
        )
        httpx_client = httpx.Client(transport=transport)
        client = HttpElabftwClient(httpx_client, base_url=base, api_key="test-key")
        writer = ElabftwTemplateWriter(client)

        template_id = writer.create(plan)

        self.assertEqual(template_id, 55)

        # The metadata PATCH carried the full bundle in one request. eLabFTW
        # requires the "metadata" value itself to be a JSON-encoded string,
        # not a nested object (confirmed against a real server - see
        # HttpElabftwClient.set_metadata), so it is JSON-decoded twice here.
        metadata_request = next(req for req in transport.requests if req.method == "PATCH")
        metadata_value = json.loads(metadata_request.read())["metadata"]
        self.assertIsInstance(metadata_value, str)
        sent = json.loads(metadata_value)
        self.assertIn("extra_fields", sent)
        self.assertIn("extra_fields_groups", sent["elabftw"])
        self.assertIn("maiml", sent)
        self.assertIn("conversion_warnings", sent)
        self.assertEqual(sent["maiml"]["source"]["method_uuid"], plan.source.method_uuid)

        upload_requests = [req for req in transport.requests if "/uploads" in str(req.url)]
        self.assertEqual(len(upload_requests), len(plan.attachments))

    def test_duplicate_found_over_http_stops_before_any_write(self) -> None:
        plan = self._build_plan()
        base = "https://elab.example.test/api/v2/"
        document_uuid, method_uuid = plan.source.duplicate_key

        transport = RecordingTransport(
            [
                lambda req: httpx.Response(
                    200,
                    json=[
                        {
                            "id": 9,
                            "metadata": {
                                "maiml": {"source": {"document_uuid": document_uuid, "method_uuid": method_uuid}}
                            },
                        }
                    ],
                )
            ]
        )
        httpx_client = httpx.Client(transport=transport)
        client = HttpElabftwClient(httpx_client, base_url=base, api_key="test-key")
        writer = ElabftwTemplateWriter(client)

        from maiml2elabftw.core.errors import ConversionError, ErrorCode

        with self.assertRaises(ConversionError) as caught:
            writer.create(plan)
        self.assertIs(caught.exception.code, ErrorCode.DUPLICATE_SOURCE)
        self.assertEqual(caught.exception.details["existing_template_id"], 9)
        self.assertEqual(len(transport.requests), 1)  # only the duplicate-check GET

    def test_insertion_without_a_local_file_fails_upload_and_rolls_back(self) -> None:
        # Known current boundary: ProtocolReader keeps an insertion's <uri>
        # but never fetches/downloads it to a local path, so
        # HttpElabftwClient.upload_attachment has nothing to read for it yet.
        # That failure should behave exactly like any other stage failure:
        # the template this call created gets rolled back, nothing is left
        # half-written.
        plan = self._build_plan()
        insertion = next(item for item in plan.attachments if item.source_kind == "insertion")
        self.assertIsNone(insertion.path)
        base = "https://elab.example.test/api/v2/"

        transport = RecordingTransport(
            [
                lambda req: httpx.Response(200, json=[]),
                lambda req: httpx.Response(201, headers={"Location": base + "experiments_templates/55"}),
                lambda req: httpx.Response(201, headers={"Location": base + "experiments_templates/55/steps/1"}),
                lambda req: httpx.Response(201, headers={"Location": base + "experiments_templates/55/steps/2"}),
                lambda req: httpx.Response(200, json={}),
                lambda req: httpx.Response(204),  # delete_template during rollback
            ]
        )
        httpx_client = httpx.Client(transport=transport)
        client = HttpElabftwClient(httpx_client, base_url=base, api_key="test-key")
        writer = ElabftwTemplateWriter(client)

        from maiml2elabftw.core.errors import ConversionError, ErrorCode

        with self.assertRaises(ConversionError) as caught:
            writer.create(plan)
        self.assertIs(caught.exception.code, ErrorCode.API_WRITE_FAILED)
        self.assertEqual(caught.exception.details["template_id"], 55)
        delete_requests = [req for req in transport.requests if req.method == "DELETE"]
        self.assertEqual(len(delete_requests), 1)


if __name__ == "__main__":
    unittest.main()
