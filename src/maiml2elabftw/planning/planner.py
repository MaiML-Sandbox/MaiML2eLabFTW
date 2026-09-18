from __future__ import annotations

from datetime import datetime, timezone
from importlib.resources import files
import json
import re
from typing import Any

import jsonschema
import yaml

from ..core.errors import ConversionError, ErrorCode
from ..core.models import (
    AttachmentDefinition,
    CustomFieldPlan,
    FieldDefinition,
    FieldSourceKind,
    MethodProtocolModel,
    PartyDefinition,
    ProtocolDocumentModel,
    SourceRef,
    StepPlan,
    TemplateDefinition,
    TemplatePlan,
    TemplateRole,
)


GROUP_BY_ROLE = {
    TemplateRole.MATERIAL: "MATERIAL",
    TemplateRole.CONDITION: "CONDITION",
    TemplateRole.RESULT: "RESULT",
}

KIND_BY_ROLE = {
    TemplateRole.MATERIAL: "materialTemplate",
    TemplateRole.CONDITION: "conditionTemplate",
    TemplateRole.RESULT: "resultTemplate",
}

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[3-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")


class TemplatePlanner:
    """Build one eLabFTW-facing TemplatePlan from a resolved method + StepPlan.

    Ordering is intentionally not decided here: the caller runs
    ``PnmlOrderResolver`` first (with a Step order override when the PNML is
    not a simple linear graph) and only calls :meth:`build` once a StepPlan
    exists. That keeps "never silently linearize a branching PNML" a
    property of the resolver, not something this class has to re-check.
    """

    def __init__(
        self,
        *,
        generator_version: str = "0.1.0.dev0",
        mapping_version: str = "1",
        validate_metadata: bool = True,
    ) -> None:
        self._generator_version = generator_version
        self._mapping_version = mapping_version
        self._metadata_schema: dict[str, Any] | None = None
        if validate_metadata:
            schema_path = files("maiml2elabftw.resources").joinpath("maiml_metadata.schema.json")
            self._metadata_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        type_mapping_path = files("maiml2elabftw.resources").joinpath("maiml_to_elabftw_types.yaml")
        self._type_mapping = yaml.safe_load(type_mapping_path.read_text(encoding="utf-8"))

    def build(
        self,
        document: ProtocolDocumentModel,
        method: MethodProtocolModel,
        steps: StepPlan,
        *,
        step_order_file_sha256: str | None = None,
        now: datetime | None = None,
    ) -> TemplatePlan:
        if document.document_uuid != method.source.document_uuid:
            raise ConversionError(
                ErrorCode.INVALID_TEMPLATE_PLAN, "method does not belong to the given document"
            )
        if not steps.steps:
            raise ConversionError(ErrorCode.INVALID_TEMPLATE_PLAN, "step plan has no steps")

        attachments = method.attachments
        if not any(item.source_kind == "source_maiml" for item in attachments):
            raise ConversionError(
                ErrorCode.MISSING_SOURCE_ATTACHMENT, "method has no source_maiml attachment"
            )

        program_by_instruction, program_by_template = self._index_programs(method)
        instructions = {
            item.instruction_id: item for program in method.programs for item in program.instructions
        }

        fields, field_metadata, field_warnings = self._build_fields(method, program_by_template)
        body = self._build_main_text(document, method)
        step_metadata = self._build_step_metadata(steps, instructions, program_by_instruction)
        pnml_metadata = [self._pnml_to_metadata(graph) for graph in method.pnml_graphs]
        attachment_metadata = [self._attachment_to_metadata(item) for item in attachments]
        reference_metadata = self._build_reference_metadata(method)
        party_metadata = [self._party_to_metadata(item) for item in document.parties]

        attachment_warnings = [
            warning for attachment in attachments for warning in self._attachment_warnings(attachment)
        ]
        warnings = field_warnings + attachment_warnings

        conversion_summary = {
            "mapped": len(fields) + len(steps.steps),
            "preserved_as_metadata": len(reference_metadata)
            + sum(len(graph.places) + len(graph.transitions) + len(graph.arcs) for graph in method.pnml_graphs)
            + len(party_metadata),
            "attached": len(attachments),
            "warnings": len(warnings),
        }

        generated_at = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        metadata = {
            "maiml": {
                "source": self._source_metadata(document, method),
                "generator": {
                    "name": "MaiML2eLabFTW",
                    "version": self._generator_version,
                    "mapping_version": self._mapping_version,
                    "generated_at": generated_at,
                    "step_order_source": steps.source.value,
                    "step_order_file_sha256": step_order_file_sha256,
                },
                "pnml": pnml_metadata,
                "steps": step_metadata,
                "fields": field_metadata,
                "attachments": attachment_metadata,
                "references": reference_metadata,
                "parties": party_metadata,
                "conversion_summary": conversion_summary,
            },
            # Detailed warning entries are kept outside "maiml" (the schema only
            # requires a count there; see metadata_schema_spec.md section 10) so a
            # human or the future conversion report can see *what* was warned
            # about without that detail becoming part of the validated contract.
            "conversion_warnings": warnings,
        }
        self._validate(metadata)

        # Anything wrong above raises before this point, so a TemplatePlan
        # is only ever returned once the whole plan has validated cleanly.
        return TemplatePlan(
            source=method.source,
            title=method.title,
            body=body,
            fields=tuple(fields),
            steps=steps,
            attachments=attachments,
            metadata=metadata,
        )

    @staticmethod
    def _index_programs(method: MethodProtocolModel) -> tuple[dict[str, str], dict[str, str]]:
        program_by_instruction: dict[str, str] = {}
        program_by_template: dict[str, str] = {}
        for program in method.programs:
            for instruction in program.instructions:
                program_by_instruction[instruction.instruction_id] = program.program_id
            for template in program.templates:
                program_by_template[template.template_id] = program.program_id
        return program_by_instruction, program_by_template

    def _build_fields(
        self,
        method: MethodProtocolModel,
        program_by_template: dict[str, str],
    ) -> tuple[list[CustomFieldPlan], list[dict[str, Any]], list[dict[str, Any]]]:
        fields: list[CustomFieldPlan] = []
        field_metadata: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for template in method.templates:
            group_name = GROUP_BY_ROLE[template.role]
            occurrence_by_key: dict[str, int] = {}
            for field in template.fields:
                key = field.semantic_key or field.field_id
                occurrence_by_key[key] = occurrence_by_key.get(key, 0) + 1
                occurrence = occurrence_by_key[key]

                base_label = field.label if occurrence == 1 else f"{field.label} #{occurrence}"
                elabftw_name = f"{base_label} [{field.unit}]" if field.unit else base_label
                format_string = self._source_attribute(field, "formatString")
                scale_factor = self._parse_scale_factor(self._source_attribute(field, "scaleFactor"))

                fields.append(
                    CustomFieldPlan(
                        field_id=field.field_id,
                        label=elabftw_name,
                        group_name=group_name,
                        field_type=field.field_type,
                        required=field.required,
                        value=field.default_value,
                        description=field.description,
                        metadata={
                            "role": template.role.value,
                            "template_id": template.template_id,
                            "template_scope": template.scope,
                            "source_kind": field.source_kind.value,
                            "source_key": field.semantic_key,
                            "xsi_type": field.maiml_type,
                            "format_string": format_string,
                            "scale_factor": scale_factor,
                        },
                    )
                )
                field_metadata.append(
                    {
                        "field_id": field.field_id,
                        "elabftw_name": elabftw_name,
                        "group": group_name,
                        "role": template.role.value,
                        "template_kind": KIND_BY_ROLE[template.role],
                        "template_id": template.template_id,
                        "template_uuid": template.uuid,
                        "template_scope": template.scope,
                        "program_id": program_by_template.get(template.template_id)
                        if template.scope == "program"
                        else None,
                        "source_kind": field.source_kind.value,
                        "source_key": field.semantic_key or field.field_id,
                        "xsi_type": field.maiml_type or "unknown",
                        "elabftw_type": field.field_type.value,
                        "unit": field.unit,
                        "format_string": format_string,
                        "scale_factor": scale_factor,
                        "required": field.required,
                        "occurrence": occurrence,
                        "source": self._source_location(field.source_ref),
                    }
                )
                warnings.extend(self._field_warnings(field, occurrence))
        return fields, field_metadata, warnings

    @staticmethod
    def _source_attribute(field: FieldDefinition, name: str) -> str | None:
        for attr_name, value in field.source_attributes:
            if attr_name == name:
                return value
        return None

    @staticmethod
    def _parse_scale_factor(raw: str | None) -> float | None:
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _field_rule(self, field: FieldDefinition) -> dict[str, Any] | None:
        section = "property_types" if field.source_kind is FieldSourceKind.PROPERTY else "content_types"
        return self._type_mapping.get(section, {}).get(field.maiml_type or "")

    def _field_warnings(self, field: FieldDefinition, occurrence: int) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        rule = self._field_rule(field)
        if rule is not None:
            if rule.get("warning_code"):
                warnings.append(
                    {
                        "code": rule["warning_code"],
                        "field_id": field.field_id,
                        "detail": f"{field.maiml_type} value kept as text ({rule['warning_code']})",
                    }
                )
            if rule.get("strategy") == "date_part":
                warnings.append(
                    {
                        "code": "DATE_TIME_TRUNCATED",
                        "field_id": field.field_id,
                        "detail": "only the date part is shown; the full dateTime is kept in metadata",
                    }
                )
            if rule.get("strategy") == "json_array_text":
                warnings.append(
                    {
                        "code": "LIST_AS_JSON_TEXT",
                        "field_id": field.field_id,
                        "detail": "list value stored as a JSON array string",
                    }
                )
        if occurrence > 1:
            warnings.append(
                {
                    "code": "DUPLICATE_KEY_LABEL_SUFFIXED",
                    "field_id": field.field_id,
                    "detail": f"label suffixed '#{occurrence}' because the key repeats within the same template",
                }
            )
        return warnings

    @staticmethod
    def _attachment_warnings(attachment: AttachmentDefinition) -> list[dict[str, Any]]:
        if attachment.source_kind == "insertion" and attachment.hash_value and not attachment.hash_method:
            return [
                {
                    "code": "INSERTION_HASH_METHOD_UNKNOWN",
                    "attachment_id": attachment.attachment_id,
                    "detail": "insertion has a hash value but no hash method attribute",
                }
            ]
        return []

    @staticmethod
    def _build_main_text(document: ProtocolDocumentModel, method: MethodProtocolModel) -> str:
        """Build the eLabFTW Template's Main Text as headed sections.

        Follows design doc section 6 ("descriptionの配置"): document,
        protocol, method and per-program descriptions each get their own
        heading, and instrument info (section 5) gets "## 装置情報". A
        heading is only emitted for a section that actually has content -
        "空のdescriptionに対して空見出しを大量生成しない" - so a Protocol
        with no protocol-level description simply has no "## プロトコル概要"
        section rather than an empty one.
        """
        parts: list[str] = []
        if document.document_description:
            parts.append("## 文書情報")
            parts.append(document.document_description)
        if document.protocol_description:
            parts.append("## プロトコル概要")
            parts.append(document.protocol_description)
        if method.description:
            parts.append("## 手法概要")
            parts.append(method.description)

        # document/instrument is a document-level definition, not
        # necessarily the device actually used by this method - without a
        # confirmed reference this only ever surfaces as generic "装置情報"
        # (device info), never asserted as "使用装置" (device used) - see
        # design doc section 5.1.
        instruments = [item for item in document.parties if item.element_kind == "instrument"]
        if instruments:
            parts.append("## 装置情報")
            lines: list[str] = []
            for item in instruments:
                lines.append(f"- {item.name or item.party_id}")
                lines.append(f"  - MaiML ID: {item.party_id}")
            parts.append("\n".join(lines))

        program_parts: list[str] = []
        for program in method.programs:
            if program.title:
                program_parts.append(f"### {program.title}")
            if program.description:
                program_parts.append(program.description)
        if program_parts:
            parts.append("## プログラム")
            parts.extend(program_parts)

        return "\n\n".join(parts)

    @staticmethod
    def _source_metadata(document: ProtocolDocumentModel, method: MethodProtocolModel) -> dict[str, Any]:
        return {
            "source_type": "protocolFileRootType",
            "document_id": document.document_id,
            "document_uuid": document.document_uuid,
            "protocol_id": document.protocol_id,
            "protocol_uuid": document.protocol_uuid,
            "method_id": method.method_source_ref.element_id,
            "method_uuid": method.source.method_uuid,
            "schema_version": document.schema_version or "1.0",
            "features": document.features,
            "filename": method.source.source_filename,
            "sha256": method.source.source_sha256,
        }

    def _build_step_metadata(
        self,
        steps: StepPlan,
        instructions: dict[str, Any],
        program_by_instruction: dict[str, str],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for step in steps.steps:
            instruction = instructions.get(step.instruction_id)
            result.append(
                {
                    "ordinal": step.ordinal,
                    "elabftw_step_id": None,
                    "transition_id": step.transition_id,
                    "program_id": program_by_instruction.get(step.instruction_id),
                    "instruction_id": step.instruction_id,
                    "instruction_uuid": instruction.uuid if instruction else None,
                    "occurrence": step.occurrence,
                    "order_source": steps.source.value,
                    "source": self._source_location(instruction.source_ref if instruction else None),
                }
            )
        return result

    @staticmethod
    def _pnml_to_metadata(graph: Any) -> dict[str, Any]:
        return {
            "id": graph.pnml_id,
            "uuid": graph.uuid,
            "name": graph.name,
            "places": [
                {"id": place.place_id, "name": place.name, "description": place.description}
                for place in graph.places
            ],
            "transitions": [
                {"id": item.transition_id, "name": item.name, "description": item.description}
                for item in graph.transitions
            ],
            "arcs": [
                {
                    "id": arc.arc_id,
                    "source": arc.source_id,
                    "target": arc.target_id,
                    "name": arc.name,
                    "description": arc.description,
                }
                for arc in graph.arcs
            ],
        }

    def _attachment_to_metadata(self, attachment: AttachmentDefinition) -> dict[str, Any]:
        return {
            "attachment_id": attachment.attachment_id,
            "elabftw_upload_id": None,
            "source_kind": attachment.source_kind,
            "name": attachment.name,
            "uri": attachment.uri,
            "uuid": attachment.attachment_id if _looks_like_uuid(attachment.attachment_id) else None,
            "hash_method": attachment.hash_method,
            "hash_value": attachment.hash_value,
            "sha256": attachment.sha256,
            "format": attachment.media_type,
            "source": self._source_location(attachment.source_ref),
        }

    def _party_to_metadata(self, party: PartyDefinition) -> dict[str, Any]:
        # Generalizes the design doc's own "instruments" example (section
        # 5.3) to every kind of party (creator/vendor/owner/instrument),
        # since all four are parsed the same way and none of them become a
        # Custom Field - filtering this list by kind == "instrument"
        # reproduces exactly the doc's own shape.
        return {
            "kind": party.element_kind,
            "id": party.party_id,
            "uuid": party.uuid,
            "name": party.name,
            "description": party.description,
            "annotation": party.annotation,
            "data_items": [
                {
                    "key": item.key,
                    "source_kind": item.source_kind.value,
                    "xsi_type": item.xsi_type,
                    "unit": item.unit,
                    "description": item.description,
                    "raw_values": list(item.raw_values),
                }
                for item in party.data_items
            ],
            "vendor_refs": [
                {"id": item.ref_id, "ref": item.target_id} for item in party.vendor_refs
            ],
            "instrument_refs": [
                {"id": item.ref_id, "ref": item.target_id} for item in party.instrument_refs
            ],
        }

    def _build_reference_metadata(self, method: MethodProtocolModel) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for template in self._templates_with_refs(method):
            for place_ref in template.place_refs:
                result.append(
                    {
                        "kind": "placeRef",
                        "id": place_ref.ref_id,
                        "ref": place_ref.place_id,
                        "initial_marking": place_ref.initial_marking,
                        "source": self._source_location(place_ref.source_ref),
                    }
                )
            for template_ref in template.template_refs:
                result.append(
                    {
                        "kind": "templateRef",
                        "id": template_ref.ref_id,
                        "ref": template_ref.template_id,
                        "source": self._source_location(template_ref.source_ref),
                    }
                )
        return result

    @staticmethod
    def _templates_with_refs(method: MethodProtocolModel) -> tuple[TemplateDefinition, ...]:
        return method.templates

    @staticmethod
    def _source_location(source_ref: SourceRef | None) -> dict[str, Any]:
        if source_ref is None:
            return {"element_kind": "unknown", "element_id": None, "xpath": None}
        return {
            "element_kind": source_ref.element_kind,
            "element_id": source_ref.element_id,
            "xpath": source_ref.xpath,
        }

    def _validate(self, metadata: dict[str, Any]) -> None:
        if self._metadata_schema is None:
            return
        try:
            jsonschema.validate(instance=metadata, schema=self._metadata_schema)
        except jsonschema.ValidationError as exc:
            raise ConversionError(
                ErrorCode.INVALID_TEMPLATE_PLAN,
                f"metadata failed schema validation: {exc.message}",
                {"path": [str(item) for item in exc.path]},
            ) from exc


def _looks_like_uuid(value: str) -> bool:
    return bool(_UUID_RE.match(value))
