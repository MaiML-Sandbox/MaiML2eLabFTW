import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from maiml2elabftw.adapters.elabftw import (
    MAIML_METADATA_ATTACHMENT_NAME,
    DuplicateDetector,
    ElabftwTemplateWriter,
    build_metadata_bundle,
)
from maiml2elabftw.adapters.maiml import ProtocolReader
from maiml2elabftw.core.errors import ConversionError, ErrorCode
from maiml2elabftw.ordering import PnmlOrderResolver
from maiml2elabftw.planning import TemplatePlanner

from test_reader import XML as PROTOCOL_XML


class FakeElabftwClient:
    """In-memory stand-in for the real eLabFTW v2 API client.

    ``fail_stage`` names the one call that should raise: one of
    "create_template", "set_steps", "set_metadata", or
    "upload_attachment:<attachment_id>" for a specific attachment.
    ``fail_rollback`` makes ``delete_template`` itself raise, to exercise
    ROLLBACK_FAILED.
    """

    def __init__(self, *, duplicate_id: int | None = None, fail_stage: str | None = None, fail_rollback: bool = False) -> None:
        self.duplicate_id = duplicate_id
        self.fail_stage = fail_stage
        self.fail_rollback = fail_rollback
        self._next_id = 100
        self.created: dict[int, dict] = {}
        self.deleted: list[int] = []
        self.calls: list[tuple] = []
        self.metadata_writes: dict[int, dict] = {}
        self.uploaded_attachments: dict[str, object] = {}

    def _maybe_fail(self, name: str) -> None:
        if self.fail_stage == name:
            raise RuntimeError(f"boom: {name}")

    def find_duplicate(self, document_uuid: str, method_uuid: str) -> int | None:
        self.calls.append(("find_duplicate", document_uuid, method_uuid))
        return self.duplicate_id

    def create_template(self, *, title: str, body: str) -> int:
        self.calls.append(("create_template",))
        self._maybe_fail("create_template")
        template_id = self._next_id
        self._next_id += 1
        self.created[template_id] = {"title": title, "body": body}
        return template_id

    def set_steps(self, template_id: int, steps) -> None:
        self.calls.append(("set_steps", template_id))
        self._maybe_fail("set_steps")

    def set_metadata(self, template_id: int, metadata) -> None:
        self.calls.append(("set_metadata", template_id))
        self._maybe_fail("set_metadata")
        # Recorded even on failure paths that happen before this stage never
        # get here; kept for tests to inspect exactly what was sent.
        self.metadata_writes[template_id] = metadata

    def upload_attachment(self, template_id: int, attachment) -> None:
        self.calls.append(("upload_attachment", template_id, attachment.attachment_id))
        self._maybe_fail(f"upload_attachment:{attachment.attachment_id}")
        self.uploaded_attachments[attachment.attachment_id] = attachment

    def delete_template(self, template_id: int) -> None:
        self.calls.append(("delete_template", template_id))
        if self.fail_rollback:
            raise RuntimeError("boom: delete_template")
        self.deleted.append(template_id)
        self.created.pop(template_id, None)


class ElabftwTemplateWriterTests(unittest.TestCase):
    def _read(self, xml: str = PROTOCOL_XML):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "protocol.maiml"
        path.write_text(xml, encoding="utf-8")
        return ProtocolReader().read(path)

    def _build_plan(self, xml: str = PROTOCOL_XML):
        document = self._read(xml)
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        return TemplatePlanner().build(document, method, steps)

    def test_creates_template_and_writes_every_stage_on_success(self) -> None:
        plan = self._build_plan()
        client = FakeElabftwClient()
        writer = ElabftwTemplateWriter(client)

        template_id = writer.create(plan)

        self.assertEqual(template_id, 100)
        self.assertEqual(client.created[100]["title"], plan.title)
        self.assertEqual(client.deleted, [])

        stage_names = [call[0] for call in client.calls]
        self.assertEqual(stage_names[0], "find_duplicate")
        self.assertEqual(stage_names[1], "create_template")
        for stage in ("set_steps", "set_metadata"):
            self.assertIn(stage, stage_names)
        attachment_ids = {call[2] for call in client.calls if call[0] == "upload_attachment"}
        # Every MaiML-described attachment, plus the generated
        # maiml-metadata.json carrying the full reverse-conversion record.
        expected_ids = {item.attachment_id for item in plan.attachments}
        self.assertEqual(attachment_ids - expected_ids, {f"maiml-metadata:{plan.source.method_uuid}"})
        self.assertTrue(expected_ids.issubset(attachment_ids))

    def test_set_metadata_receives_one_slim_bundle_plus_a_full_metadata_attachment(self) -> None:
        # This is the exact hazard the original design fix addressed:
        # Custom Fields and the pointer to the full record must travel in
        # the same set_metadata() call, never two separate PATCHes that
        # could race or clobber each other. The full reverse-conversion
        # record itself now travels separately, as its own attachment,
        # because embedding it directly in eLabFTW's metadata field dumped
        # 12+ pages of internal bookkeeping into every generated PDF.
        plan = self._build_plan()
        client = FakeElabftwClient()
        writer = ElabftwTemplateWriter(client)

        template_id = writer.create(plan)

        sent = client.metadata_writes[template_id]
        self.assertEqual(sent, build_metadata_bundle(plan))
        self.assertIn("extra_fields", sent)
        self.assertIn("elabftw", sent)
        self.assertIn("extra_fields_groups", sent["elabftw"])
        self.assertNotIn("maiml", sent)
        self.assertNotIn("conversion_warnings", sent)
        self.assertEqual(sent["maiml_source"]["document_uuid"], plan.source.document_uuid)
        self.assertEqual(sent["maiml_source"]["method_uuid"], plan.source.method_uuid)
        self.assertEqual(sent["maiml_source"]["metadata_attachment"], MAIML_METADATA_ATTACHMENT_NAME)
        self.assertEqual(
            {group["name"] for group in sent["elabftw"]["extra_fields_groups"]}, {"MATERIAL", "CONDITION", "RESULT"}
        )
        voltage = sent["extra_fields"]["AcceleratingVoltage [kV]"]
        self.assertEqual(voltage["type"], "number")
        self.assertEqual(voltage["value"], "200")

        metadata_attachment = client.uploaded_attachments[f"maiml-metadata:{plan.source.method_uuid}"]
        self.assertEqual(metadata_attachment.name, MAIML_METADATA_ATTACHMENT_NAME)
        full_metadata = json.loads(metadata_attachment.content)
        self.assertEqual(full_metadata, plan.metadata)
        self.assertIn("maiml", full_metadata)
        self.assertIn("conversion_warnings", full_metadata)

    def test_extra_fields_groups_lives_under_the_elabftw_key_not_top_level(self) -> None:
        # Confirmed against a real eLabFTW server (5.6.10) and the official
        # docs (doc.elabftw.net/docs/usage/user-guide/custom-fields/): a
        # top-level "extra_fields_groups" key is silently ignored, and every
        # field renders under eLabFTW's own "default group" instead of its
        # real one - even though each field's own group_id was correct all
        # along. Group definitions must be nested under "elabftw".
        plan = self._build_plan()
        client = FakeElabftwClient()
        writer = ElabftwTemplateWriter(client)

        template_id = writer.create(plan)

        sent = client.metadata_writes[template_id]
        self.assertNotIn("extra_fields_groups", sent)
        self.assertEqual(
            sent["elabftw"]["extra_fields_groups"],
            [{"id": 1, "name": "MATERIAL"}, {"id": 2, "name": "CONDITION"}, {"id": 3, "name": "RESULT"}],
        )

    def test_duplicate_source_is_rejected_and_nothing_is_created(self) -> None:
        plan = self._build_plan()
        client = FakeElabftwClient(duplicate_id=42)
        writer = ElabftwTemplateWriter(client)

        with self.assertRaises(ConversionError) as caught:
            writer.create(plan)

        self.assertIs(caught.exception.code, ErrorCode.DUPLICATE_SOURCE)
        self.assertEqual(caught.exception.details["existing_template_id"], 42)
        self.assertEqual(client.created, {})
        self.assertEqual(client.calls, [("find_duplicate", *plan.source.duplicate_key)])

    def test_duplicate_detector_reads_document_and_method_uuid(self) -> None:
        plan = self._build_plan()
        client = FakeElabftwClient(duplicate_id=7)
        detector = DuplicateDetector(client)

        self.assertEqual(detector.find_existing(plan.source), 7)
        self.assertEqual(client.calls, [("find_duplicate", *plan.source.duplicate_key)])

    def test_failure_in_create_template_is_reported_without_any_rollback(self) -> None:
        plan = self._build_plan()
        client = FakeElabftwClient(fail_stage="create_template")
        writer = ElabftwTemplateWriter(client)

        with self.assertRaises(ConversionError) as caught:
            writer.create(plan)

        self.assertIs(caught.exception.code, ErrorCode.API_WRITE_FAILED)
        self.assertEqual(caught.exception.details["stage"], "create_template")
        self.assertEqual(client.deleted, [])
        self.assertNotIn("delete_template", [call[0] for call in client.calls])

    def test_failure_in_each_later_stage_rolls_back_the_new_template(self) -> None:
        plan = self._build_plan()
        for stage in ("set_steps", "set_metadata"):
            with self.subTest(stage=stage):
                client = FakeElabftwClient(fail_stage=stage)
                writer = ElabftwTemplateWriter(client)

                with self.assertRaises(ConversionError) as caught:
                    writer.create(plan)

                self.assertIs(caught.exception.code, ErrorCode.API_WRITE_FAILED)
                self.assertEqual(caught.exception.details["stage"], stage)
                self.assertEqual(caught.exception.details["template_id"], 100)
                self.assertEqual(client.deleted, [100])
                self.assertEqual(client.created, {})

    def test_failure_uploading_an_attachment_rolls_back_and_stops_remaining_uploads(self) -> None:
        plan = self._build_plan()
        first_attachment = plan.attachments[0]
        self.assertGreaterEqual(len(plan.attachments), 2, "fixture should exercise more than one attachment")
        client = FakeElabftwClient(fail_stage=f"upload_attachment:{first_attachment.attachment_id}")
        writer = ElabftwTemplateWriter(client)

        with self.assertRaises(ConversionError) as caught:
            writer.create(plan)

        self.assertIs(caught.exception.code, ErrorCode.API_WRITE_FAILED)
        self.assertEqual(caught.exception.details["stage"], f"upload_attachment:{first_attachment.attachment_id}")
        self.assertEqual(client.deleted, [100])
        uploaded = [call[2] for call in client.calls if call[0] == "upload_attachment"]
        self.assertEqual(uploaded, [first_attachment.attachment_id])

    def test_rollback_failure_raises_rollback_failed_with_template_id(self) -> None:
        plan = self._build_plan()
        client = FakeElabftwClient(fail_stage="set_steps", fail_rollback=True)
        writer = ElabftwTemplateWriter(client)

        with self.assertRaises(ConversionError) as caught:
            writer.create(plan)

        self.assertIs(caught.exception.code, ErrorCode.ROLLBACK_FAILED)
        self.assertEqual(caught.exception.details["template_id"], 100)
        self.assertEqual(caught.exception.details["stage"], "set_steps")
        # delete_template was attempted but failed, so the orphaned template
        # is still there for a human to clean up - never silently dropped.
        self.assertIn(100, client.created)
        self.assertEqual(client.deleted, [])

    def test_existing_templates_are_never_touched_by_rollback(self) -> None:
        first_plan = self._build_plan()
        other_xml = PROTOCOL_XML.replace(
            "11111111-1111-4111-8111-111111111111", "99999999-9999-4999-8999-999999999999"
        )
        second_plan = self._build_plan(other_xml)

        client = FakeElabftwClient()
        writer = ElabftwTemplateWriter(client)
        first_id = writer.create(first_plan)
        self.assertEqual(first_id, 100)

        client.fail_stage = "set_steps"
        with self.assertRaises(ConversionError) as caught:
            writer.create(second_plan)
        self.assertIs(caught.exception.code, ErrorCode.API_WRITE_FAILED)

        # Only the template created *in this failing call* (101) was rolled
        # back; the earlier, successfully-created template (100) is untouched.
        self.assertEqual(client.deleted, [101])
        self.assertIn(100, client.created)
        self.assertNotIn(101, client.created)

    def test_public_rollback_deletes_the_given_template(self) -> None:
        client = FakeElabftwClient()
        writer = ElabftwTemplateWriter(client)
        client.created[100] = {"title": "x", "body": "y"}

        writer.rollback(100)

        self.assertEqual(client.deleted, [100])
        self.assertNotIn(100, client.created)

    def test_public_rollback_raises_rollback_failed_on_delete_error(self) -> None:
        client = FakeElabftwClient(fail_rollback=True)
        writer = ElabftwTemplateWriter(client)

        with self.assertRaises(ConversionError) as caught:
            writer.rollback(100)

        self.assertIs(caught.exception.code, ErrorCode.ROLLBACK_FAILED)
        self.assertEqual(caught.exception.details["template_id"], 100)


if __name__ == "__main__":
    unittest.main()
