from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from ..core.errors import ConversionError, ErrorCode
from .model import CaptureRequirement, CaptureSource, ElabftwBinding, IdentityPolicy, TemplateContract, ValidationRule


def load_template_contract(path: Path) -> TemplateContract:
    """Load and validate a TemplateContract file (YAML or JSON).

    Structural validation (required keys, enum membership, cardinality
    pattern) is delegated to ``schemas/template_contract.schema.json`` via
    jsonschema - the same approach ``TemplatePlanner`` already uses for
    ``maiml_metadata.schema.json``. On top of that, this rejects a
    requirement id that repeats within the same contract, since the schema
    itself cannot express "unique by one key of each array item".

    Any problem - malformed YAML, a schema violation, or a duplicate
    requirement id - raises ``ConversionError(INVALID_TEMPLATE_CONTRACT)``
    rather than propagating the underlying exception type, matching
    ``load_step_order_override``'s contract.
    """
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConversionError(
            ErrorCode.INVALID_TEMPLATE_CONTRACT, f"invalid Template Contract YAML: {exc}"
        ) from exc

    schema = _schema()
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ConversionError(
            ErrorCode.INVALID_TEMPLATE_CONTRACT,
            f"Template Contract failed schema validation: {exc.message}",
            {"path": [str(item) for item in exc.path]},
        ) from exc

    requirements = [_build_requirement(raw) for raw in data["requirements"]]
    ids = [item.requirement_id for item in requirements]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ConversionError(
            ErrorCode.INVALID_TEMPLATE_CONTRACT,
            f"duplicate requirement id(s) in Template Contract: {duplicates}",
        )

    return TemplateContract(
        document_uuid=data["document_uuid"],
        method_uuid=data["method_uuid"],
        mapping_version=data["mapping_version"],
        requirements=tuple(requirements),
    )


def _build_requirement(raw: dict[str, Any]) -> CaptureRequirement:
    binding_raw = raw.get("elabftw_binding")
    binding = (
        ElabftwBinding(kind=binding_raw["kind"], group=binding_raw.get("group"), name=binding_raw.get("name"))
        if binding_raw is not None
        else None
    )
    identity_policy_raw = raw.get("identity_policy")
    return CaptureRequirement(
        requirement_id=raw["id"],
        maiml_target=raw["maiml_target"],
        source=CaptureSource(raw["source"]),
        required=raw["required"],
        cardinality=raw["cardinality"],
        semantic_key=raw.get("semantic_key"),
        identity_policy=IdentityPolicy(identity_policy_raw) if identity_policy_raw is not None else None,
        validation_rules=tuple(
            ValidationRule(rule_type=item["rule_type"], parameters=item["parameters"])
            for item in raw.get("validation_rules", [])
        ),
        elabftw_binding=binding,
    )


def _schema() -> dict[str, Any]:
    schema_path = files("maiml2elabftw.resources").joinpath("template_contract.schema.json")
    return json.loads(schema_path.read_text(encoding="utf-8"))
