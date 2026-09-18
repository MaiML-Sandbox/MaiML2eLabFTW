"""TemplateContract: what an eLabFTW Experiment record must capture so a
complete MaiML experiment data file can later be reconstructed from it.

Phase 1 of ``docs/template_contract_design.md`` ("Contract基盤"): the data
model plus a schema-validated file loader. Phase 3 ("実体とUUID") adds
``derive_entity_requirements``, which builds the Material/Condition/Result
identity requirements straight from a parsed Protocol - the first actual
producer of ``CaptureRequirement`` objects. Later phases (completeness
validation, ...) build on this without changing its shape.
"""

from .entities import derive_entity_requirements, identity_choices, identity_name_collisions
from .loader import load_template_contract
from .model import (
    CaptureRequirement,
    CaptureSource,
    ElabftwBinding,
    IdentityPolicy,
    TemplateContract,
    ValidationRule,
)

__all__ = [
    "CaptureRequirement",
    "CaptureSource",
    "ElabftwBinding",
    "IdentityPolicy",
    "TemplateContract",
    "ValidationRule",
    "derive_entity_requirements",
    "identity_choices",
    "identity_name_collisions",
    "load_template_contract",
]
