"""TemplateContract: what an eLabFTW Experiment record must capture so a
complete MaiML experiment data file can later be reconstructed from it.

Phase 1 of ``docs/template_contract_design.md`` ("Contract基盤"): the data
model plus a schema-validated file loader. Later phases (instrument
placement, Material/Condition/Result identity, completeness validation,
...) build on this without changing its shape.
"""

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
    "load_template_contract",
]
