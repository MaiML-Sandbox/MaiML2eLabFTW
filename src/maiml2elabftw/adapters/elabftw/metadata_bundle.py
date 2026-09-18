from __future__ import annotations

from typing import Any

from ...core.models import CustomFieldPlan, TemplatePlan

# Canonical group order. Only groups that actually have at least one field
# are included in the bundle, so a method with no resultTemplate simply has
# no RESULT group rather than an empty one.
_GROUP_ORDER = ("MATERIAL", "CONDITION", "RESULT")


def build_metadata_bundle(plan: TemplatePlan) -> dict[str, Any]:
    """Assemble the single metadata JSON object eLabFTW stores for a template.

    eLabFTW keeps Custom Fields (``extra_fields`` / ``elabftw.extra_fields_groups``)
    and arbitrary metadata (this project's ``maiml`` / ``conversion_warnings``
    blocks) in the same JSON blob on the template. Building it here, once,
    and sending it with a single ``set_metadata`` call avoids the read-modify
    -write race a second PATCH would otherwise risk (one write clobbering
    the other). The resulting shape is::

        {
          "extra_fields": {"<label>": {"type": ..., "value": ..., "group_id": ..., ...}},
          "elabftw": {"extra_fields_groups": [{"id": 1, "name": "MATERIAL"}, ...]},
          "maiml": {...},
          "conversion_warnings": [...],
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

    # plan.metadata already holds {"maiml": ..., "conversion_warnings": ...};
    # copy it (shallow - we only add new top-level keys, never mutate these)
    # rather than writing into the TemplatePlan's own dict.
    bundle: dict[str, Any] = dict(plan.metadata)
    # Merge into any existing "elabftw" block rather than overwriting it,
    # in case a future addition ever needs to set other elabftw.* keys
    # (e.g. display_main_text) alongside extra_fields_groups.
    elabftw_block = dict(bundle.get("elabftw", {}))
    elabftw_block["extra_fields_groups"] = extra_fields_groups
    bundle["elabftw"] = elabftw_block
    bundle["extra_fields"] = extra_fields
    return bundle


def _unique_label(extra_fields: dict[str, Any], field: CustomFieldPlan) -> str:
    """CustomFieldPlan.label is only guaranteed unique within its own
    Template (TemplatePlanner already suffixes "#2" etc. for repeated keys
    there); extra_fields is flat across every group, so guard against the
    rarer cross-group collision instead of silently overwriting one field
    with another."""
    if field.label not in extra_fields:
        return field.label
    disambiguated = f"{field.label} ({field.group_name})"
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
