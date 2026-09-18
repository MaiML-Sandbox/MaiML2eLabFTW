from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CaptureSource(StrEnum):
    """Where a CaptureRequirement's value is expected to come from.

    See ``docs/template_contract_design.md`` section 4 ("情報の取得元") for
    the full description and examples of each source.
    """

    PROTOCOL = "protocol"
    ELN_SYSTEM = "eln_system"
    USER_INPUT = "user_input"
    USER_SELECTION = "user_selection"
    ATTACHMENT = "attachment"
    GENERATED = "generated"
    REUSED_IDENTITY = "reused_identity"
    DERIVED = "derived"


class IdentityPolicy(StrEnum):
    """How a requirement's UUID/entity identity is decided when recorded.

    See ``docs/template_contract_design.md`` section 7 ("UUIDと実体の同一性").
    A name match alone must never be enough to decide this - see that
    section's warning against reusing or fabricating an identity from a
    label coincidence.
    """

    GENERATE_NEW = "generate_new"
    REUSE_EXISTING = "reuse_existing"
    REFERENCE_PROTOCOL_ENTITY = "reference_protocol_entity"
    REUSE_PREVIOUS_RESULT = "reuse_previous_result"


@dataclass(frozen=True)
class ValidationRule:
    """One extra constraint on a requirement's value beyond its basic type.

    ``rule_type`` is an open vocabulary (e.g. "accepted_formats",
    "min_value", "regex") rather than a closed enum, since the set of
    constraints a Protocol author might need is not fixed - see design doc
    section 3 ("値の型と検証規則").
    """

    rule_type: str
    parameters: dict[str, object]


@dataclass(frozen=True)
class ElabftwBinding:
    """Where a requirement's value is captured on the eLabFTW side.

    ``kind`` is intentionally an open string (e.g. "custom_field",
    "main_text_section", "metadata_only") rather than an enum: new binding
    kinds are expected as later phases add more of the design doc's
    sections (instrument, description placement, insertions, ...), and nothing
    here should have to change just to name a new one.
    """

    kind: str
    group: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class CaptureRequirement:
    """One piece of information a TemplateContract requires to be captured.

    Field names and shape follow ``docs/template_contract_design.md``
    section 11 ("推奨モデル") - the design's own recommended model - as-is.
    """

    requirement_id: str
    maiml_target: str
    source: CaptureSource
    required: bool
    cardinality: str
    semantic_key: str | None = None
    identity_policy: IdentityPolicy | None = None
    validation_rules: tuple[ValidationRule, ...] = ()
    elabftw_binding: ElabftwBinding | None = None


@dataclass(frozen=True)
class TemplateContract:
    """Everything a MaiML Protocol's method requires an eLabFTW Experiment
    record to capture, so that a complete MaiML experiment data file can
    later be reconstructed from it (design doc section 3, "Template
    Contract").

    Deliberately holds no behaviour of its own yet (no completeness check,
    no eLabFTW wiring) - that is Phase 5 ("完全性検証") and later phases in
    the design doc's own implementation order (section 15). This is only
    the Phase 1 data model plus the ability to load one from a file
    (``maiml2elabftw.contract.load_template_contract``).
    """

    document_uuid: str
    method_uuid: str
    mapping_version: str
    requirements: tuple[CaptureRequirement, ...]

    def requirement(self, requirement_id: str) -> CaptureRequirement | None:
        return next(
            (item for item in self.requirements if item.requirement_id == requirement_id), None
        )
