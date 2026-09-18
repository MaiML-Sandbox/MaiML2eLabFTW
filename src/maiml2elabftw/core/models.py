from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal


class TemplateRole(StrEnum):
    MATERIAL = "material"
    CONDITION = "condition"
    RESULT = "result"


class FieldSourceKind(StrEnum):
    PROPERTY = "property"
    CONTENT = "content"


class FieldType(StrEnum):
    NUMBER = "number"
    CHECKBOX = "checkbox"
    DATE = "date"
    URL = "url"
    TEXT = "text"


class StepOrderSource(StrEnum):
    PNML = "pnml"
    YAML = "yaml"


@dataclass(frozen=True)
class SourceIdentity:
    document_uuid: str
    method_uuid: str
    schema_version: str | None = None
    source_filename: str | None = None
    source_sha256: str | None = None

    @property
    def duplicate_key(self) -> tuple[str, str]:
        return self.document_uuid, self.method_uuid


@dataclass(frozen=True)
class SourceRef:
    element_kind: str
    element_id: str | None
    xpath: str | None = None


@dataclass(frozen=True)
class FieldDefinition:
    field_id: str
    label: str
    role: TemplateRole
    source_kind: FieldSourceKind
    field_type: FieldType
    source_ref: SourceRef
    semantic_key: str | None = None
    maiml_type: str | None = None
    unit: str | None = None
    description: str | None = None
    required: bool = False
    default_value: Any | None = None
    enum_values: tuple[str, ...] = ()
    source_attributes: tuple[tuple[str, str], ...] = ()
    raw_values: tuple[str, ...] = ()

    @property
    def display_label(self) -> str:
        return f"{self.label} [{self.unit}]" if self.unit else self.label


@dataclass(frozen=True)
class PlaceRefDefinition:
    ref_id: str
    place_id: str
    initial_marking: bool | None = None
    source_ref: SourceRef | None = None


@dataclass(frozen=True)
class TemplateRefDefinition:
    ref_id: str
    template_id: str
    source_ref: SourceRef | None = None


@dataclass(frozen=True)
class TemplateDefinition:
    template_id: str
    role: TemplateRole
    source_ref: SourceRef
    fields: tuple[FieldDefinition, ...] = ()
    place_refs: tuple[PlaceRefDefinition, ...] = ()
    template_refs: tuple[TemplateRefDefinition, ...] = ()
    uuid: str | None = None
    name: str | None = None
    description: str | None = None
    annotation: str | None = None
    scope: str = "method"


@dataclass(frozen=True)
class InstructionDefinition:
    instruction_id: str
    title: str
    body: str
    transition_refs: tuple[str, ...]
    source_ref: SourceRef
    uuid: str | None = None
    annotation: str | None = None


@dataclass(frozen=True)
class PlaceNode:
    place_id: str
    source_ref: SourceRef
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class TransitionNode:
    transition_id: str
    source_ref: SourceRef
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class ArcEdge:
    arc_id: str
    source_id: str
    target_id: str
    source_ref: SourceRef
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class PnmlGraph:
    places: tuple[PlaceNode, ...]
    transitions: tuple[TransitionNode, ...]
    arcs: tuple[ArcEdge, ...]
    pnml_id: str | None = None
    uuid: str | None = None
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class ProgramDefinition:
    program_id: str
    title: str | None
    description: str | None
    instructions: tuple[InstructionDefinition, ...]
    templates: tuple[TemplateDefinition, ...]
    source_ref: SourceRef
    uuid: str | None = None
    annotation: str | None = None


@dataclass(frozen=True)
class AttachmentDefinition:
    attachment_id: str
    name: str
    # "maiml_metadata" is not something the MaiML source describes - it is
    # the eLabFTW adapter's own generated attachment (see
    # metadata_bundle.build_full_metadata_attachment), carrying the full
    # reverse-conversion JSON that used to be embedded directly in
    # eLabFTW's metadata field (see build_metadata_bundle's docstring).
    source_kind: Literal["insertion", "source_maiml", "maiml_metadata"]
    source_ref: SourceRef
    path: Path | None = None
    uri: str | None = None
    content: bytes | None = None
    sha256: str | None = None
    media_type: str | None = None
    hash_value: str | None = None
    hash_method: str | None = None

    def __post_init__(self) -> None:
        if self.path is None and self.uri is None and self.content is None:
            raise ValueError("attachment requires path, uri, or content")


@dataclass(frozen=True)
class MethodProtocolModel:
    source: SourceIdentity
    title: str
    description: str | None
    method_source_ref: SourceRef
    programs: tuple[ProgramDefinition, ...]
    pnml_graphs: tuple[PnmlGraph, ...] = ()
    templates: tuple[TemplateDefinition, ...] = ()
    attachments: tuple[AttachmentDefinition, ...] = ()
    annotation: str | None = None


@dataclass(frozen=True)
class ProtocolDocumentModel:
    document_uuid: str
    schema_version: str | None
    methods: tuple[MethodProtocolModel, ...]
    original_file: Path
    original_sha256: str
    document_id: str | None = None
    document_name: str | None = None
    document_description: str | None = None
    document_annotation: str | None = None
    document_date: str | None = None
    protocol_id: str | None = None
    protocol_uuid: str | None = None
    protocol_name: str | None = None
    protocol_description: str | None = None
    protocol_annotation: str | None = None
    features: str | None = None


@dataclass(frozen=True)
class StepDefinition:
    ordinal: int
    transition_id: str
    instruction_id: str
    title: str
    body: str
    occurrence: int


@dataclass(frozen=True)
class StepPlan:
    source: StepOrderSource
    steps: tuple[StepDefinition, ...]


@dataclass(frozen=True)
class CustomFieldPlan:
    field_id: str
    label: str
    group_name: Literal["MATERIAL", "CONDITION", "RESULT"]
    field_type: FieldType
    required: bool
    value: Any | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class TemplatePlan:
    source: SourceIdentity
    title: str
    body: str
    fields: tuple[CustomFieldPlan, ...]
    steps: StepPlan
    attachments: tuple[AttachmentDefinition, ...]
    metadata: dict[str, Any]
