from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dataclasses import replace

from maiml2elabftw.adapters.maiml import ProtocolReader
from maiml2elabftw.core.errors import ConversionError, ErrorCode
from maiml2elabftw.ordering import PnmlOrderResolver, StepOrderOverride, TransitionOrder
from maiml2elabftw.planning import TemplatePlanner

from test_reader import XML as PROTOCOL_XML


class TemplatePlannerTests(unittest.TestCase):
    def _read(self, xml: str = PROTOCOL_XML):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "protocol.maiml"
        path.write_text(xml, encoding="utf-8")
        return ProtocolReader().read(path)

    def test_builds_plan_with_fields_steps_and_metadata(self) -> None:
        document = self._read()
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)

        plan = TemplatePlanner().build(document, method, steps)

        self.assertEqual(plan.title, "SEMAcquisition")
        self.assertEqual(plan.steps.steps, steps.steps)
        self.assertTrue(any(item.source_kind == "source_maiml" for item in plan.attachments))

        groups = {item.group_name for item in plan.fields}
        self.assertEqual(groups, {"MATERIAL", "CONDITION", "RESULT"})

        meta = plan.metadata["maiml"]
        self.assertEqual(meta["source"]["document_uuid"], document.document_uuid)
        self.assertEqual(meta["source"]["method_uuid"], method.source.method_uuid)
        self.assertEqual(len(meta["steps"]), len(steps.steps))
        self.assertEqual(meta["generator"]["step_order_source"], "pnml")

        # placeRef/templateRef keep their own id + initialMarking in metadata,
        # matching the reference shape the reader now preserves.
        references = {(item["kind"], item["id"]): item for item in meta["references"]}
        self.assertEqual(references[("placeRef", "pr-1")]["initial_marking"], True)
        self.assertEqual(references[("templateRef", "tref-1")]["ref"], "material-1")

    def test_step_order_source_yaml_is_reflected_in_metadata(self) -> None:
        document = self._read()
        method = document.methods[0]
        override = StepOrderOverride(
            method.source.document_uuid,
            method.source.method_uuid,
            (TransitionOrder("t1", ("instruction-1",)), TransitionOrder("t2", ("instruction-2",))),
        )
        steps = PnmlOrderResolver().resolve(method, override)

        plan = TemplatePlanner().build(document, method, steps)
        self.assertEqual(plan.metadata["maiml"]["generator"]["step_order_source"], "yaml")

    def test_rejects_plan_for_mismatched_document(self) -> None:
        document = self._read()
        other_document = self._read(
            PROTOCOL_XML.replace(
                "11111111-1111-4111-8111-111111111111", "99999999-9999-4999-8999-999999999999"
            )
        )
        method = other_document.methods[0]
        steps = PnmlOrderResolver().resolve(method)

        with self.assertRaises(ConversionError) as caught:
            TemplatePlanner().build(document, method, steps)
        self.assertIs(caught.exception.code, ErrorCode.INVALID_TEMPLATE_PLAN)

    def test_same_key_repeated_fields_get_suffixed_labels(self) -> None:
        xml = PROTOCOL_XML.replace(
            '<property key="SampleID" xsi:type="stringType"><value>HS-100MG001</value></property>',
            '<property key="SampleID" xsi:type="stringType"><value>HS-100MG001</value></property>'
            '<property key="SampleID" xsi:type="stringType"><value>HS-100MG002</value></property>',
        )
        document = self._read(xml)
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        labels = [item.label for item in plan.fields if item.metadata["source_key"] == "SampleID"]
        self.assertEqual(labels, ["SampleID", "SampleID #2"])

    def test_rejects_plan_without_source_maiml_attachment_and_builds_nothing(self) -> None:
        document = self._read()
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)

        stripped = replace(
            method, attachments=tuple(a for a in method.attachments if a.source_kind != "source_maiml")
        )
        with self.assertRaises(ConversionError) as caught:
            TemplatePlanner().build(document, stripped, steps)
        self.assertIs(caught.exception.code, ErrorCode.MISSING_SOURCE_ATTACHMENT)

    def test_schema_violation_is_raised_and_plan_is_never_returned(self) -> None:
        # Corrupt a required-but-not-yet-XSD-enforced field (template uuid) to
        # confirm the Planner's own metadata schema check catches it, and that
        # no TemplatePlan escapes when it does (item 10 of the spec).
        document = self._read()
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)

        broken_templates = tuple(replace(t, uuid=None) for t in method.templates)
        broken_method = replace(method, templates=broken_templates)

        planner = TemplatePlanner()
        with self.assertRaises(ConversionError) as caught:
            planner.build(document, broken_method, steps)
        self.assertIs(caught.exception.code, ErrorCode.INVALID_TEMPLATE_PLAN)

    def test_format_string_and_scale_factor_come_from_source_attributes(self) -> None:
        document = self._read()
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        voltage_meta = next(
            item for item in plan.metadata["maiml"]["fields"] if item["source_key"] == "AcceleratingVoltage"
        )
        self.assertEqual(voltage_meta["format_string"], "0.0")
        self.assertEqual(voltage_meta["scale_factor"], 1.0)

        voltage_plan = next(item for item in plan.fields if item.metadata["source_key"] == "AcceleratingVoltage")
        self.assertEqual(voltage_plan.metadata["format_string"], "0.0")
        self.assertEqual(voltage_plan.metadata["scale_factor"], 1.0)

    def test_arc_name_and_description_reach_pnml_metadata(self) -> None:
        document = self._read()
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        arc = next(item for item in plan.metadata["maiml"]["pnml"][0]["arcs"] if item["id"] == "a1")
        self.assertEqual(arc["name"], "InitialTransfer")
        self.assertEqual(arc["description"], "Move the specimen from the start place into preparation.")

    def test_conversion_summary_warnings_cover_the_documented_cases(self) -> None:
        document = self._read()
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        codes = {item["code"] for item in plan.metadata["conversion_warnings"]}
        # From the fixture: ThumbnailBytes (base64BinaryType), AcquisitionDate
        # (a *list* dateTime -> json_array_text) and the document-level insertion
        # with a hash but no hash method.
        self.assertIn("BINARY_AS_TEXT", codes)
        self.assertIn("LIST_AS_JSON_TEXT", codes)
        self.assertIn("INSERTION_HASH_METHOD_UNKNOWN", codes)
        self.assertEqual(
            plan.metadata["maiml"]["conversion_summary"]["warnings"],
            len(plan.metadata["conversion_warnings"]),
        )

    def test_duplicate_key_warning_is_counted(self) -> None:
        xml = PROTOCOL_XML.replace(
            '<property key="SampleID" xsi:type="stringType"><value>HS-100MG001</value></property>',
            '<property key="SampleID" xsi:type="stringType"><value>HS-100MG001</value></property>'
            '<property key="SampleID" xsi:type="stringType"><value>HS-100MG002</value></property>',
        )
        document = self._read(xml)
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        codes = [item["code"] for item in plan.metadata["conversion_warnings"]]
        self.assertIn("DUPLICATE_KEY_LABEL_SUFFIXED", codes)


if __name__ == "__main__":
    unittest.main()
