from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from maiml2elabftw.adapters.maiml import ProtocolReader
from maiml2elabftw.core.errors import ConversionError, ErrorCode
from maiml2elabftw.core.models import FieldSourceKind, FieldType, TemplateRole
from maiml2elabftw.ordering import PnmlOrderResolver


XML = """<?xml version="1.0" encoding="UTF-8"?>
<maiml xmlns="http://www.maiml.org/schemas"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:type="protocolFileRootType" version="1.0">
  <document id="document-1">
    <uuid>11111111-1111-4111-8111-111111111111</uuid>
    <insertion>
      <uri>attachment.txt</uri>
      <hash>YWJjMTIz</hash>
    </insertion>
    <creator id="creator-1">
      <uuid>11111111-1111-4111-8111-111111111112</uuid>
      <name>KYL:SEM</name>
      <vendorRef id="vr-1" ref="vendor-1"/>
      <instrumentRef id="ir-1" ref="instrument-1"/>
    </creator>
    <vendor id="vendor-1"><uuid>11111111-1111-4111-8111-111111111113</uuid></vendor>
    <owner id="owner-1"><uuid>11111111-1111-4111-8111-111111111114</uuid></owner>
    <instrument id="instrument-1">
      <uuid>11111111-1111-4111-8111-111111111115</uuid>
      <name>JEOL-SEM</name>
      <description>Scanning electron microscope.</description>
      <property key="SerialNumber" xsi:type="stringType"><value>SN-001</value></property>
    </instrument>
    <date>2026-09-17T00:00:00Z</date>
  </document>
  <protocol id="protocol-1">
    <uuid>22222222-2222-4222-8222-222222222222</uuid>
    <name>MicroscopyProtocol</name>
    <method id="method-1">
      <uuid>33333333-3333-4333-8333-333333333333</uuid>
      <name>SEMAcquisition</name>
      <description>Acquire an SEM image.</description>
      <pnml id="pnml-1">
        <uuid>44444444-4444-4444-8444-444444444444</uuid>
        <place id="p0"><name>Start</name></place>
        <place id="p1"><name>Ready</name></place>
        <place id="p2"><name>Done</name></place>
        <transition id="t1"><name>Prepare</name></transition>
        <transition id="t2"><name>Acquire</name></transition>
        <arc id="a1" source="p0" target="t1">
          <name>InitialTransfer</name>
          <description>Move the specimen from the start place into preparation.</description>
        </arc>
        <arc id="a2" source="t1" target="p1"/>
        <arc id="a3" source="p1" target="t2"/>
        <arc id="a4" source="t2" target="p2"/>
      </pnml>
      <program id="program-1">
        <uuid>55555555-5555-4555-8555-555555555555</uuid>
        <instruction id="instruction-1">
          <uuid>66666666-6666-4666-8666-666666666661</uuid>
          <name>PrepareSpecimen</name>
          <description>Mount the specimen.</description>
          <transitionRef id="tr-1" ref="t1"/>
        </instruction>
        <instruction id="instruction-2">
          <uuid>66666666-6666-4666-8666-666666666662</uuid>
          <name>AcquireImage</name>
          <description>Acquire the image.</description>
          <transitionRef id="tr-2" ref="t2"/>
        </instruction>
        <resultTemplate id="result-1">
          <uuid>77777777-7777-4777-8777-777777777773</uuid>
          <property key="ImageFormat" xsi:type="stringType"><value>TIFF</value></property>
          <property key="ThumbnailBytes" xsi:type="base64BinaryType"><value>QUJD</value></property>
          <placeRef id="pr-3" ref="p2"/>
        </resultTemplate>
      </program>
      <conditionTemplate id="condition-1">
        <uuid>77777777-7777-4777-8777-777777777772</uuid>
        <property key="AcceleratingVoltage" xsi:type="doubleType" units="kV" formatString="0.0" scaleFactor="1.0"><value>200</value></property>
        <content key="AcquisitionDate" xsi:type="contentDateTimeListType"><value>2026-09-17T10:30:00+09:00</value></content>
        <placeRef id="pr-2" ref="p1"/>
        <templateRef id="tref-1" ref="material-1"/>
      </conditionTemplate>
    </method>
    <materialTemplate id="material-1">
      <uuid>77777777-7777-4777-8777-777777777771</uuid>
      <property key="SampleID" xsi:type="stringType"><value>HS-100MG001</value></property>
      <placeRef id="pr-1" ref="p0" initialMarking="true"/>
    </materialTemplate>
  </protocol>
</maiml>
"""


class ProtocolReaderTests(unittest.TestCase):
    def _read(self, xml: str = XML):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "protocol.maiml"
        path.write_text(xml, encoding="utf-8")
        return ProtocolReader().read(path)

    def test_title_falls_back_to_the_bare_method_id_without_any_name(self) -> None:
        # method_id (e.g. "MethodSEM") already reads as a name; a fallback
        # of "Method MethodSEM" would just repeat itself.
        no_names = XML.replace("<name>SEMAcquisition</name>\n      ", "").replace(
            "<name>MicroscopyProtocol</name>\n    ", ""
        )
        method = self._read(no_names).methods[0]
        self.assertEqual(method.title, "method-1")

    def test_title_falls_back_to_protocol_name_dash_method_id_when_protocol_is_named(self) -> None:
        no_method_name = XML.replace("<name>SEMAcquisition</name>\n      ", "")
        method = self._read(no_method_name).methods[0]
        self.assertEqual(method.title, "MicroscopyProtocol - method-1")

    def test_reads_method_pnml_programs_and_scoped_templates(self) -> None:
        document = self._read()
        self.assertEqual(document.document_uuid, "11111111-1111-4111-8111-111111111111")
        method = document.methods[0]
        self.assertEqual(method.title, "SEMAcquisition")
        self.assertEqual(len(method.pnml_graphs), 1)
        self.assertEqual(len(method.programs), 1)
        self.assertEqual({item.scope for item in method.templates}, {"protocol", "method", "program"})
        roles = {item.template_id: item.role for item in method.templates}
        self.assertIs(roles["material-1"], TemplateRole.MATERIAL)
        self.assertIs(roles["condition-1"], TemplateRole.CONDITION)
        self.assertIs(roles["result-1"], TemplateRole.RESULT)

    def test_maps_field_types_values_and_units(self) -> None:
        method = self._read().methods[0]
        fields = {field.semantic_key: field for template in method.templates for field in template.fields}
        voltage = fields["AcceleratingVoltage"]
        self.assertIs(voltage.field_type, FieldType.NUMBER)
        self.assertEqual(voltage.default_value, 200)
        self.assertEqual(voltage.display_label, "AcceleratingVoltage [kV]")
        self.assertEqual(fields["SampleID"].default_value, "HS-100MG001")
        self.assertEqual(fields["AcquisitionDate"].raw_values, ("2026-09-17T10:30:00+09:00",))

    def test_reader_output_connects_to_order_resolver(self) -> None:
        method = self._read().methods[0]
        plan = PnmlOrderResolver().resolve(method)
        self.assertEqual([item.instruction_id for item in plan.steps], ["instruction-1", "instruction-2"])

    def test_rejects_non_protocol_root_type(self) -> None:
        with self.assertRaises(ConversionError) as caught:
            self._read(XML.replace('xsi:type="protocolFileRootType"', 'xsi:type="maimlRootType"'))
        self.assertIs(caught.exception.code, ErrorCode.INVALID_SOURCE_TYPE)

    def test_rejects_broken_transition_reference(self) -> None:
        with self.assertRaises(ConversionError) as caught:
            self._read(XML.replace('ref="t2"', 'ref="missing-transition"', 1))
        self.assertIs(caught.exception.code, ErrorCode.BROKEN_REFERENCE)

    def test_place_ref_and_template_ref_keep_their_own_id_and_marking(self) -> None:
        method = self._read().methods[0]
        templates = {item.template_id: item for item in method.templates}

        material_place_ref = templates["material-1"].place_refs[0]
        self.assertEqual(material_place_ref.ref_id, "pr-1")
        self.assertEqual(material_place_ref.place_id, "p0")
        self.assertTrue(material_place_ref.initial_marking)

        condition_place_ref = templates["condition-1"].place_refs[0]
        self.assertEqual(condition_place_ref.ref_id, "pr-2")
        self.assertIsNone(condition_place_ref.initial_marking)

        template_ref = templates["condition-1"].template_refs[0]
        self.assertEqual(template_ref.ref_id, "tref-1")
        self.assertEqual(template_ref.template_id, "material-1")

    def test_rejects_broken_template_reference(self) -> None:
        with self.assertRaises(ConversionError) as caught:
            self._read(XML.replace('ref="material-1"', 'ref="missing-template"'))
        self.assertIs(caught.exception.code, ErrorCode.BROKEN_REFERENCE)

    def test_arc_keeps_its_own_name_and_description(self) -> None:
        method = self._read().methods[0]
        arc = next(item for item in method.pnml_graphs[0].arcs if item.arc_id == "a1")
        self.assertEqual(arc.name, "InitialTransfer")
        self.assertEqual(arc.description, "Move the specimen from the start place into preparation.")

    def test_document_level_insertion_without_hash_method_is_kept(self) -> None:
        method = self._read().methods[0]
        insertion = next(item for item in method.attachments if item.source_kind == "insertion")
        self.assertEqual(insertion.name, "attachment.txt")
        self.assertEqual(insertion.hash_value, "YWJjMTIz")
        self.assertIsNone(insertion.hash_method)

    def test_insertion_with_relative_uri_resolves_to_sibling_file_when_present(self) -> None:
        # Real MaiML files commonly ship an insertion's actual bytes as a
        # sibling file next to the .maiml itself, referenced by a plain
        # relative path (e.g. "./photo.tif") - the reader should find it
        # so HttpElabftwClient can actually upload it, without needing any
        # separate download/resolution step.
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        maiml_path = Path(directory.name) / "protocol.maiml"
        maiml_path.write_text(XML, encoding="utf-8")
        sibling = Path(directory.name) / "attachment.txt"
        sibling.write_text("real attachment bytes", encoding="utf-8")

        method = ProtocolReader().read(maiml_path).methods[0]
        insertion = next(item for item in method.attachments if item.source_kind == "insertion")

        self.assertEqual(insertion.path, sibling.resolve())
        self.assertEqual(insertion.path.read_text(encoding="utf-8"), "real attachment bytes")

    def test_insertion_with_missing_sibling_file_is_left_unresolved(self) -> None:
        # Same relative URI as above, but nothing actually exists at that
        # path - path must stay None so upload_attachment's existing,
        # documented error still fires instead of guessing.
        method = self._read().methods[0]
        insertion = next(item for item in method.attachments if item.source_kind == "insertion")
        self.assertIsNone(insertion.path)

    def test_insertion_with_network_uri_is_never_resolved_to_a_local_file(self) -> None:
        # Even if a same-named local file happens to exist, a network URI
        # must never be treated as a local path.
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        maiml_path = Path(directory.name) / "protocol.maiml"
        maiml_path.write_text(
            XML.replace("<uri>attachment.txt</uri>", "<uri>https://example.test/attachment.txt</uri>"),
            encoding="utf-8",
        )
        (Path(directory.name) / "attachment.txt").write_text("decoy", encoding="utf-8")

        method = ProtocolReader().read(maiml_path).methods[0]
        insertion = next(item for item in method.attachments if item.source_kind == "insertion")

        self.assertIsNone(insertion.path)
        self.assertEqual(insertion.uri, "https://example.test/attachment.txt")

    def test_binary_property_is_kept_as_text_with_source_attributes(self) -> None:
        method = self._read().methods[0]
        fields = {field.semantic_key: field for template in method.templates for field in template.fields}
        thumbnail = fields["ThumbnailBytes"]
        self.assertIs(thumbnail.field_type, FieldType.TEXT)
        self.assertEqual(thumbnail.default_value, "QUJD")

        voltage = fields["AcceleratingVoltage"]
        attrs = dict(voltage.source_attributes)
        self.assertEqual(attrs["formatString"], "0.0")
        self.assertEqual(attrs["scaleFactor"], "1.0")

    def test_parses_creator_vendor_owner_and_instrument_parties(self) -> None:
        document = self._read()
        parties_by_kind = {}
        for party in document.parties:
            parties_by_kind.setdefault(party.element_kind, []).append(party)

        self.assertEqual({item.party_id for item in parties_by_kind["creator"]}, {"creator-1"})
        self.assertEqual({item.party_id for item in parties_by_kind["vendor"]}, {"vendor-1"})
        self.assertEqual({item.party_id for item in parties_by_kind["owner"]}, {"owner-1"})
        self.assertEqual({item.party_id for item in parties_by_kind["instrument"]}, {"instrument-1"})

        instrument = parties_by_kind["instrument"][0]
        self.assertEqual(instrument.uuid, "11111111-1111-4111-8111-111111111115")
        self.assertEqual(instrument.name, "JEOL-SEM")
        self.assertEqual(instrument.description, "Scanning electron microscope.")
        self.assertEqual(len(instrument.data_items), 1)
        item = instrument.data_items[0]
        self.assertEqual(item.key, "SerialNumber")
        self.assertIs(item.source_kind, FieldSourceKind.PROPERTY)
        self.assertEqual(item.xsi_type, "stringType")
        self.assertEqual(item.raw_values, ("SN-001",))

    def test_creator_keeps_its_own_vendor_ref_and_instrument_ref(self) -> None:
        document = self._read()
        creator = next(item for item in document.parties if item.element_kind == "creator")
        self.assertEqual(creator.name, "KYL:SEM")
        self.assertEqual([item.target_id for item in creator.vendor_refs], ["vendor-1"])
        self.assertEqual([item.target_id for item in creator.instrument_refs], ["instrument-1"])

    def test_rejects_dangling_vendor_ref(self) -> None:
        with self.assertRaises(ConversionError) as caught:
            self._read(XML.replace('ref="vendor-1"', 'ref="missing-vendor"', 1))
        self.assertIs(caught.exception.code, ErrorCode.BROKEN_REFERENCE)

    def test_rejects_dangling_instrument_ref(self) -> None:
        with self.assertRaises(ConversionError) as caught:
            self._read(XML.replace('ref="instrument-1"', 'ref="missing-instrument"', 1))
        self.assertIs(caught.exception.code, ErrorCode.BROKEN_REFERENCE)
