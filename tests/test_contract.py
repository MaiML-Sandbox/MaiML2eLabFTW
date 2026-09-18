from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from maiml2elabftw.adapters.maiml import ProtocolReader
from maiml2elabftw.contract import (
    CaptureRequirement,
    CaptureSource,
    ElabftwBinding,
    IdentityPolicy,
    TemplateContract,
    ValidationRule,
    derive_entity_requirements,
    identity_choices,
    identity_name_collisions,
    load_template_contract,
)
from maiml2elabftw.core.errors import ConversionError, ErrorCode

from test_reader import XML as PROTOCOL_XML


VALID_YAML = """
document_uuid: doc-uuid-1
method_uuid: method-uuid-1
mapping_version: "1"

requirements:
  - id: sample_name
    maiml_target: material/property
    semantic_key: "KYL:SampleName"
    source: user_input
    required: true
    cardinality: "1"
    elabftw_binding:
      kind: custom_field
      group: MATERIAL
      name: SampleName

  - id: instrument
    maiml_target: document/instrument
    source: user_selection
    required: true
    cardinality: "1"
    identity_policy: reuse_existing

  - id: result_image
    maiml_target: result/insertion
    source: attachment
    required: true
    cardinality: "1..*"
    validation_rules:
      - rule_type: accepted_formats
        parameters:
          formats: ["image/tiff"]
"""


class LoadTemplateContractTests(unittest.TestCase):
    def _write(self, text: str) -> Path:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "contract.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_loads_a_valid_contract(self) -> None:
        contract = load_template_contract(self._write(VALID_YAML))

        self.assertEqual(contract.document_uuid, "doc-uuid-1")
        self.assertEqual(contract.method_uuid, "method-uuid-1")
        self.assertEqual(contract.mapping_version, "1")
        self.assertEqual(len(contract.requirements), 3)

        sample_name = contract.requirement("sample_name")
        self.assertIsNotNone(sample_name)
        self.assertEqual(sample_name.source, CaptureSource.USER_INPUT)
        self.assertEqual(sample_name.cardinality, "1")
        self.assertEqual(
            sample_name.elabftw_binding, ElabftwBinding(kind="custom_field", group="MATERIAL", name="SampleName")
        )
        self.assertIsNone(sample_name.identity_policy)

        instrument = contract.requirement("instrument")
        self.assertEqual(instrument.identity_policy, IdentityPolicy.REUSE_EXISTING)

        result_image = contract.requirement("result_image")
        self.assertEqual(result_image.cardinality, "1..*")
        self.assertEqual(
            result_image.validation_rules,
            (ValidationRule(rule_type="accepted_formats", parameters={"formats": ["image/tiff"]}),),
        )

    def test_requirement_returns_none_for_an_unknown_id(self) -> None:
        contract = load_template_contract(self._write(VALID_YAML))
        self.assertIsNone(contract.requirement("does-not-exist"))

    def test_missing_required_top_level_key_is_rejected(self) -> None:
        broken = VALID_YAML.replace("mapping_version: \"1\"\n", "")
        with self.assertRaises(ConversionError) as caught:
            load_template_contract(self._write(broken))
        self.assertIs(caught.exception.code, ErrorCode.INVALID_TEMPLATE_CONTRACT)

    def test_invalid_cardinality_is_rejected(self) -> None:
        broken = VALID_YAML.replace('cardinality: "1..*"', 'cardinality: "many"')
        with self.assertRaises(ConversionError) as caught:
            load_template_contract(self._write(broken))
        self.assertIs(caught.exception.code, ErrorCode.INVALID_TEMPLATE_CONTRACT)

    def test_unknown_capture_source_is_rejected(self) -> None:
        broken = VALID_YAML.replace("source: user_input", "source: made_up_source")
        with self.assertRaises(ConversionError) as caught:
            load_template_contract(self._write(broken))
        self.assertIs(caught.exception.code, ErrorCode.INVALID_TEMPLATE_CONTRACT)

    def test_duplicate_requirement_id_is_rejected(self) -> None:
        broken = VALID_YAML.replace("id: instrument", "id: sample_name")
        with self.assertRaises(ConversionError) as caught:
            load_template_contract(self._write(broken))
        self.assertIs(caught.exception.code, ErrorCode.INVALID_TEMPLATE_CONTRACT)
        self.assertIn("sample_name", caught.exception.message)

    def test_malformed_yaml_is_rejected(self) -> None:
        with self.assertRaises(ConversionError) as caught:
            load_template_contract(self._write("not: valid: yaml: [unclosed"))
        self.assertIs(caught.exception.code, ErrorCode.INVALID_TEMPLATE_CONTRACT)

    def test_a_requirement_needs_no_optional_fields(self) -> None:
        minimal = """
        document_uuid: doc-1
        method_uuid: method-1
        mapping_version: "1"
        requirements:
          - id: r1
            maiml_target: material/property
            source: protocol
            required: false
            cardinality: "0..1"
        """
        contract = load_template_contract(self._write(minimal))
        requirement = contract.requirement("r1")
        self.assertEqual(requirement.validation_rules, ())
        self.assertIsNone(requirement.elabftw_binding)
        self.assertIsNone(requirement.semantic_key)


class TemplateContractModelTests(unittest.TestCase):
    def test_template_contract_is_a_plain_frozen_dataclass(self) -> None:
        requirement = CaptureRequirement(
            requirement_id="r1",
            maiml_target="material/property",
            source=CaptureSource.PROTOCOL,
            required=True,
            cardinality="1",
        )
        contract = TemplateContract(
            document_uuid="doc-1", method_uuid="method-1", mapping_version="1", requirements=(requirement,)
        )
        self.assertEqual(contract.requirement("r1"), requirement)
        with self.assertRaises(AttributeError):
            contract.document_uuid = "changed"  # frozen


class DeriveEntityRequirementsTests(unittest.TestCase):
    """Phase 3 ("実体とUUID"): entity/UUID identity requirements derived
    straight from a parsed Protocol's Material/Condition/Result Templates.
    """

    def _read(self, xml: str = PROTOCOL_XML):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "protocol.maiml"
        path.write_text(xml, encoding="utf-8")
        return ProtocolReader().read(path)

    def test_template_referenced_by_a_templateref_gets_a_fixed_identity(self) -> None:
        # condition-1 carries <templateRef ref="material-1"/>, so
        # material-1's identity is already fixed by the Protocol's own
        # structure - no choice is left to whoever records the experiment.
        method = self._read().methods[0]
        requirements = {item.requirement_id: item for item in derive_entity_requirements(method)}

        material = requirements["entity:material-1"]
        self.assertEqual(material.maiml_target, "materialTemplate/material-1")
        self.assertEqual(material.source, CaptureSource.PROTOCOL)
        self.assertEqual(material.identity_policy, IdentityPolicy.REFERENCE_PROTOCOL_ENTITY)
        self.assertEqual(identity_choices(material), ())

    def test_result_template_is_always_generated_fresh(self) -> None:
        method = self._read().methods[0]
        requirements = {item.requirement_id: item for item in derive_entity_requirements(method)}

        result = requirements["entity:result-1"]
        self.assertEqual(result.maiml_target, "resultTemplate/result-1")
        self.assertEqual(result.source, CaptureSource.GENERATED)
        self.assertEqual(result.identity_policy, IdentityPolicy.GENERATE_NEW)
        self.assertEqual(identity_choices(result), ())

    def test_unreferenced_condition_leaves_identity_to_be_chosen_at_record_time(self) -> None:
        # condition-1 is not itself the target of any templateRef and is
        # not a resultTemplate, so the Protocol alone cannot say whether
        # it is a new sample, an existing Material, or a previous Result -
        # design doc section 7.2's own three-choice UI mockup.
        method = self._read().methods[0]
        requirements = {item.requirement_id: item for item in derive_entity_requirements(method)}

        condition = requirements["entity:condition-1"]
        self.assertEqual(condition.source, CaptureSource.USER_SELECTION)
        self.assertIsNone(condition.identity_policy)
        self.assertEqual(
            identity_choices(condition),
            (
                IdentityPolicy.GENERATE_NEW.value,
                IdentityPolicy.REUSE_EXISTING.value,
                IdentityPolicy.REUSE_PREVIOUS_RESULT.value,
            ),
        )

    def test_one_requirement_per_material_condition_and_result_template(self) -> None:
        method = self._read().methods[0]
        requirements = derive_entity_requirements(method)
        self.assertEqual(
            {item.requirement_id for item in requirements},
            {"entity:material-1", "entity:condition-1", "entity:result-1"},
        )

    def test_a_shared_name_between_two_unresolved_templates_is_flagged_but_never_merged(self) -> None:
        # Two conditionTemplates that are both left to be chosen at record
        # time (neither is templateRef'd) and happen to share a <name> -
        # design doc section 7.2's closing warning: a name match alone must
        # never decide identity, but it also must not pass unnoticed.
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
        method = self._read(xml).methods[0]

        collisions = identity_name_collisions(method)
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0]["code"], "IDENTITY_NAME_COLLISION_NOT_MERGED")
        self.assertEqual(collisions[0]["name"], "SharedName")
        self.assertEqual(collisions[0]["template_ids"], ["condition-1", "condition-2"])

        # Flagging the coincidence must not change what each entity's own
        # identity requirement looks like - they stay two distinct,
        # independently-unresolved requirements.
        requirements = {item.requirement_id: item for item in derive_entity_requirements(method)}
        self.assertIsNone(requirements["entity:condition-1"].identity_policy)
        self.assertIsNone(requirements["entity:condition-2"].identity_policy)

    def test_result_templates_sharing_a_name_are_not_flagged(self) -> None:
        # RESULT-role templates are always GENERATE_NEW regardless of name,
        # so two of them sharing a name is not the kind of ambiguity
        # identity_name_collisions exists to surface.
        xml = PROTOCOL_XML.replace(
            '<resultTemplate id="result-1">\n          <uuid>77777777-7777-4777-8777-777777777773</uuid>',
            '<resultTemplate id="result-1">\n          <uuid>77777777-7777-4777-8777-777777777773</uuid>'
            "\n          <name>SameResultName</name>",
        ).replace(
            "</resultTemplate>",
            "</resultTemplate>\n        "
            '<resultTemplate id="result-2">'
            "<uuid>77777777-7777-4777-8777-777777777775</uuid><name>SameResultName</name></resultTemplate>",
        )
        method = self._read(xml).methods[0]
        self.assertEqual(identity_name_collisions(method), ())


if __name__ == "__main__":
    unittest.main()
