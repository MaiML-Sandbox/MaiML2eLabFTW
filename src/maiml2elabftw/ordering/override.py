from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..core.errors import ConversionError, ErrorCode
from .resolver import StepOrderOverride, TransitionOrder


def load_step_order_override(path: Path) -> StepOrderOverride:
    """Load the version-1 YAML form; semantic checks remain in the resolver."""
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("version must be 1")
        source = data["source"]
        raw_steps = data["steps"]
        if not isinstance(source, dict) or not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("source and non-empty steps are required")
        steps: list[TransitionOrder] = []
        for raw in raw_steps:
            if not isinstance(raw, dict):
                raise ValueError("each step must be an object")
            transition_id = _nonempty(raw.get("transition_id"), "transition_id")
            instruction_ids = raw.get("instruction_ids")
            if not isinstance(instruction_ids, list) or not instruction_ids:
                raise ValueError("instruction_ids must be a non-empty list")
            parsed_ids = tuple(_nonempty(item, "instruction_id") for item in instruction_ids)
            if len(parsed_ids) != len(set(parsed_ids)):
                raise ValueError("instruction_ids must be unique within a transition")
            steps.append(TransitionOrder(transition_id, parsed_ids))
        return StepOrderOverride(
            document_uuid=_nonempty(source.get("document_uuid"), "document_uuid"),
            method_uuid=_nonempty(source.get("method_uuid"), "method_uuid"),
            steps=tuple(steps),
        )
    except (KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise ConversionError(ErrorCode.INVALID_ORDER_FILE, f"invalid Step order YAML: {exc}") from exc


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()

