from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from maiml2elabftw.contract import (
    CaptureRequirement,
    CaptureSource,
    ElabftwBinding,
    IdentityPolicy,
    TemplateContract,
    ValidationRule,
    load_template_contract,
)
from maiml2elabftw.core.errors import ConversionError, ErrorCode


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


if __name__ == "__main__":
    unittest.main()
