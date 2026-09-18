from __future__ import annotations

import json
from typing import Any

from ...core.models import AttachmentDefinition, CustomFieldPlan, SourceRef, TemplatePlan

# Canonical group order. Only groups that actually have at least one field
# are included in the bundle, so a method with no resultTemplate simply has
# no RESULT group rather than an empty one.
_GROUP_ORDER = ("MATERIAL", "CONDITION", "RESULT")

# Filename used for the generated attachment carrying the full
# reverse-conversion metadata. Referenced back from the slim eLabFTW
# metadata bundle's "maiml_source.metadata_attachment" so a human (or a
# future tool) can find it without guessing.
MAIML_METADATA_ATTACHMENT_NAME = "maiml-metadata.json"


def build_metadata_bundle(plan: TemplatePlan) -> dict[str, Any]:
    """Assemble the metadata JSON object eLabFTW stores directly on the
    template (its Custom Fields, plus just enough to find the full
    reverse-conversion record).

    eLabFTW keeps Custom Fields (``extra_fields`` / ``elabftw.extra_fields_groups``)
    and arbitrary metadata in the same JSON blob on the template, and its
    own PDF export renders that whole blob. The full reverse-conversion
    record this project builds (PNML, steps, every field's source
    location, ...) is tens of fields deep and dwarfs everything else in
    the resulting PDF - a real conversion produced 12+ pages of it. So it
    is never embedded here: it is written once as its own attachment (see
    ``build_full_metadata_attachment``) and this bundle keeps only what
    duplicate detection and a human skimming the PDF actually need. The
    resulting shape is::

        {
          "extra_fields": {"<label>": {"type": ..., "value": ..., "group_id": ..., ...}},
          "elabftw": {"extra_fields_groups": [{"id": 1, "name": "MATERIAL"}, ...]},
          "maiml_source": {
            "document_uuid": ..., "method_uuid": ..., "mapping_version": ...,
            "metadata_attachment": "maiml-metadata.json",
          },
        }

    Group definitions live under ``elabftw.extra_fields_groups`` - NOT a
    top-level ``extra_fields_groups`` key - confirmed against both the
    official docs (doc.elabftw.net/docs/usage/user-guide/custom-fields/)
    and a real server: a top-level key is silently ignored and every field
    renders under eLabFTW's "default group" instead of its real one, even
    though each field's own ``group_id`` was already correct. Each field's
    ``group_id`` refers to an ``id`` inside that ``elabftw.extra_fields_groups``
    array.
    """
    present_groups = [name for name in _GROUP_ORDER if any(field.group_name == name for field in plan.fields)]
    group_id_by_name = {name: index + 1 for index, name in enumerate(present_groups)}
    extra_fields_groups = [{"id": group_id_by_name[name], "name": name} for name in present_groups]

    extra_fields: dict[str, Any] = {}
    position_by_group: dict[str, int] = {}
    for field in plan.fields:
        position_by_group[field.group_name] = position_by_group.get(field.group_name, 0) + 1
        label = _unique_label(extra_fields, field)
        extra_fields[label] = {
            "type": field.field_type.value,
            "value": _serialize_field_value(field.field_type.value, field.value),
            "group_id": group_id_by_name[field.group_name],
            "position": position_by_group[field.group_name],
            "required": field.required,
        }

    generator = plan.metadata.get("maiml", {}).get("generator", {})
    return {
        "extra_fields": extra_fields,
        "elabftw": {"extra_fields_groups": extra_fields_groups},
        "maiml_source": {
            "document_uuid": plan.source.document_uuid,
            "method_uuid": plan.source.method_uuid,
            "mapping_version": generator.get("mapping_version"),
            "metadata_attachment": MAIML_METADATA_ATTACHMENT_NAME,
        },
    }


def build_full_metadata_attachment(plan: TemplatePlan) -> AttachmentDefinition:
    """Build the ``maiml-metadata.json`` attachment carrying the complete
    reverse-conversion record (``plan.metadata``: PNML, steps, every
    field's source location, attachments, references, conversion_summary,
    and conversion_warnings) that used to be embedded directly in
    eLabFTW's own metadata field. See ``build_metadata_bundle`` for why
    that moved out.

    The data itself is unchanged - this is purely about *where* eLabFTW
    stores it - so anything that consumed the old embedded ``maiml`` block
    can get the same content back by downloading this attachment.
    """
    content = json.dumps(plan.metadata, ensure_ascii=False, indent=2).encode("utf-8")
    return AttachmentDefinition(
        attachment_id=f"maiml-metadata:{plan.source.method_uuid}",
        name=MAIML_METADATA_ATTACHMENT_NAME,
        source_kind="maiml_metadata",
        source_ref=SourceRef("generated", None),
        content=content,
        media_type="application/json",
    )


def _unique_label(extra_fields: dict[str, Any], field: CustomFieldPlan) -> str:
    """CustomFieldPlan.label is only guaranteed unique within its own
    Template (TemplatePlanner already suffixes "#2" etc. for repeated keys
    there); extra_fields is flat across every group, so guard against a
    cross-Template collision instead of silently overwriting one field
    with another.

    The disambiguator is the source Template's own id, not its group name:
    two Templates can (and commonly do) share both a group and a key -
    e.g. a materialTemplate for the input sample and another for the
    measured/output sample both using "SampleName" - and a "(MATERIAL)"
    suffix on both would say nothing about which is which.
    """
    if field.label not in extra_fields:
        return field.label
    template_id = field.metadata.get("template_id")
    disambiguated = f"{field.label} ({template_id})" if template_id else f"{field.label} ({field.group_name})"
    if disambiguated not in extra_fields:
        return disambiguated
    return f"{disambiguated} [{field.field_id}]"


def _serialize_field_value(elabftw_type: str, value: Any) -> str:
    # eLabFTW extra_fields values are strings regardless of "type"; checkbox
    # fields use the "on" / "off" convention.
    if elabftw_type == "checkbox":
        return "on" if value else "off"
    if value is None:
        return ""
    return str(value)
