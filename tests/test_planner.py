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

    def test_main_text_omits_headings_for_descriptions_that_are_missing(self) -> None:
        # Default fixture has no document/protocol description, so those
        # headings must not appear - "空のdescriptionに対して空見出しを大量
        # 生成しない" (design doc section 6).
        document = self._read()
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        self.assertNotIn("## 文書情報", plan.body)
        self.assertNotIn("## プロトコル概要", plan.body)
        self.assertIn("## 手法概要", plan.body)
        self.assertIn("Acquire an SEM image.", plan.body)
        # Position matters: 手法概要 heading must come with its own body text
        # right after it, not just anywhere in the string.
        self.assertIn("## 手法概要\n\nAcquire an SEM image.", plan.body)

    def test_main_text_includes_document_and_protocol_descriptions_when_present(self) -> None:
        xml = PROTOCOL_XML.replace(
            "<document id=\"document-1\">",
            "<document id=\"document-1\">\n    <description>Document level info.</description>",
        ).replace(
            "<name>MicroscopyProtocol</name>",
            "<name>MicroscopyProtocol</name>\n    <description>Protocol overview.</description>",
        )
        document = self._read(xml)
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        self.assertIn("## 文書情報\n\nDocument level info.", plan.body)
        self.assertIn("## プロトコル概要\n\nProtocol overview.", plan.body)

    def test_main_text_instrument_section_lists_document_level_instruments(self) -> None:
        document = self._read()
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        self.assertIn("## 装置情報", plan.body)
        self.assertIn("JEOL-SEM", plan.body)
        self.assertIn("MaiML ID: instrument-1", plan.body)

    def test_main_text_program_section_uses_program_title_as_subheading(self) -> None:
        xml = PROTOCOL_XML.replace(
            '<program id="program-1">',
            '<program id="program-1">\n        <name>Acquisition Program</name>'
            "\n        <description>Runs the acquisition sequence.</description>",
        )
        document = self._read(xml)
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        self.assertIn("## プログラム", plan.body)
        self.assertIn("### Acquisition Program", plan.body)
        self.assertIn("Runs the acquisition sequence.", plan.body)

    def test_party_metadata_covers_every_kind_and_keeps_creator_refs(self) -> None:
        document = self._read()
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        parties = {item["kind"]: item for item in plan.metadata["maiml"]["parties"]}
        self.assertEqual(set(parties), {"creator", "vendor", "owner", "instrument"})

        instrument = parties["instrument"]
        self.assertEqual(instrument["id"], "instrument-1")
        self.assertEqual(instrument["name"], "JEOL-SEM")
        self.assertEqual(len(instrument["data_items"]), 1)
        self.assertEqual(instrument["data_items"][0]["key"], "SerialNumber")

        creator = parties["creator"]
        self.assertEqual(creator["vendor_refs"], [{"id": "vr-1", "ref": "vendor-1"}])
        self.assertEqual(creator["instrument_refs"], [{"id": "ir-1", "ref": "instrument-1"}])

    def test_party_metadata_is_counted_as_preserved_in_conversion_summary(self) -> None:
        document = self._read()
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan_without_parties = TemplatePlanner().build(replace(document, parties=()), method, steps)
        plan_with_parties = TemplatePlanner().build(document, method, steps)

        self.assertEqual(
            plan_with_parties.metadata["maiml"]["conversion_summary"]["preserved_as_metadata"]
            - plan_without_parties.metadata["maiml"]["conversion_summary"]["preserved_as_metadata"],
            len(document.parties),
        )

    def test_entity_metadata_covers_every_material_condition_and_result_template(self) -> None:
        document = self._read()
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        entities = {item["requirement_id"]: item for item in plan.metadata["maiml"]["entities"]}
        self.assertEqual(set(entities), {"entity:material-1", "entity:condition-1", "entity:result-1"})

        material = entities["entity:material-1"]
        self.assertEqual(material["identity_policy"], "reference_protocol_entity")
        self.assertEqual(material["identity_policy_choices"], [])

        result = entities["entity:result-1"]
        self.assertEqual(result["identity_policy"], "generate_new")

        condition = entities["entity:condition-1"]
        self.assertIsNone(condition["identity_policy"])
        self.assertEqual(
            condition["identity_policy_choices"], ["generate_new", "reuse_existing", "reuse_previous_result"]
        )

    def test_entity_metadata_is_counted_as_preserved_in_conversion_summary(self) -> None:
        document = self._read()
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        self.assertEqual(
            len(plan.metadata["maiml"]["entities"]),
            3,
        )
        self.assertGreaterEqual(plan.metadata["maiml"]["conversion_summary"]["preserved_as_metadata"], 3)

    def test_identity_name_collision_is_surfaced_as_a_conversion_warning(self) -> None:
        xml = PROTOCOL_XML.replace(
            '<conditionTemplate id="condition-1">\n        <uuid>77777777-7777-4777-8777-777777777772</uuid>',
            '<conditionTemplate id="condition-1">\n        <uuid>77777777-7777-4777-8777-777777777772</uuid>'
            "\n        <name>SharedName</name>",
        ).replace(
            "</conditionTemplate>",
            "</conditionTemplate>\n      "
            '<conditionTemplate id="condition-2">'
            "<uuid>77777777-7777-4777-8777-777777777774</uuid><name>SharedName</name></conditionTemplate>",
        )
        document = self._read(xml)
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        codes = [item["code"] for item in plan.metadata["conversion_warnings"]]
        self.assertIn("IDENTITY_NAME_COLLISION_NOT_MERGED", codes)
        self.assertEqual(
            plan.metadata["maiml"]["conversion_summary"]["warnings"],
            len(plan.metadata["conversion_warnings"]),
        )

    def test_custom_field_description_is_carried_onto_the_plan(self) -> None:
        xml = PROTOCOL_XML.replace(
            '<property key="AcceleratingVoltage" xsi:type="doubleType" units="kV" '
            'formatString="0.0" scaleFactor="1.0"><value>200</value></property>',
            '<property key="AcceleratingVoltage" xsi:type="doubleType" units="kV" '
            'formatString="0.0" scaleFactor="1.0"><description>Beam accelerating voltage.</description>'
            "<value>200</value></property>",
        )
        document = self._read(xml)
        method = document.methods[0]
        steps = PnmlOrderResolver().resolve(method)
        plan = TemplatePlanner().build(document, method, steps)

        voltage_field = next(item for item in plan.fields if item.metadata["source_key"] == "AcceleratingVoltage")
        self.assertEqual(voltage_field.description, "Beam accelerating voltage.")


if __name__ == "__main__":
    unittest.main()
