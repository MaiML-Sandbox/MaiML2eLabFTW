from pathlib import Path

import unittest

from maiml2elabftw.core.models import (
    AttachmentDefinition,
    FieldDefinition,
    FieldSourceKind,
    FieldType,
    SourceIdentity,
    SourceRef,
    TemplateRole,
)


REF = SourceRef("property", "p1")


class ModelTests(unittest.TestCase):
    def test_duplicate_key_uses_document_and_method_uuid(self) -> None:
        source = SourceIdentity("document-uuid", "method-uuid")
        self.assertEqual(source.duplicate_key, ("document-uuid", "method-uuid"))

    def test_field_display_label_appends_unit(self) -> None:
        field = FieldDefinition(
            field_id="voltage",
            label="Accelerating Voltage",
            role=TemplateRole.CONDITION,
            source_kind=FieldSourceKind.PROPERTY,
            field_type=FieldType.NUMBER,
            source_ref=REF,
            unit="kV",
        )
        self.assertEqual(field.display_label, "Accelerating Voltage [kV]")

    def test_attachment_requires_path_or_uri(self) -> None:
        with self.assertRaises(ValueError):
            AttachmentDefinition("a1", "source.maiml", "source_maiml", REF)
        attachment = AttachmentDefinition(
            "a1", "source.maiml", "source_maiml", REF, path=Path("source.maiml")
        )
        self.assertEqual(attachment.path, Path("source.maiml"))
