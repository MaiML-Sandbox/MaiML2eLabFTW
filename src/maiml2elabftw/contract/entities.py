from __future__ import annotations

from ..core.models import MethodProtocolModel, TemplateDefinition, TemplateRole
from .model import CaptureRequirement, CaptureSource, IdentityPolicy, ValidationRule

# design doc section 7.2's own eLabFTW UI mockup offers exactly these three
# choices for a "leaf" Material/Condition entity (an entity whose origin the
# static Protocol structure cannot pin down on its own):
#
#   試料の由来
#   ○ 新規試料              -> GENERATE_NEW
#   ○ 既存Materialを使用     -> REUSE_EXISTING
#   ○ 前工程のResultを使用   -> REUSE_PREVIOUS_RESULT
#
# REFERENCE_PROTOCOL_ENTITY is deliberately left out of this set: that
# policy only ever applies to an entity whose identity the Protocol itself
# already fixes via templateRef (see _resolve_identity below), never to a
# free choice offered to whoever records the experiment.
_LEAF_IDENTITY_CHOICES: tuple[IdentityPolicy, ...] = (
    IdentityPolicy.GENERATE_NEW,
    IdentityPolicy.REUSE_EXISTING,
    IdentityPolicy.REUSE_PREVIOUS_RESULT,
)

_IDENTITY_CHOICES_RULE_TYPE = "identity_policy_choices"


def derive_entity_requirements(method: MethodProtocolModel) -> tuple[CaptureRequirement, ...]:
    """Derive one ``CaptureRequirement`` per Material/Condition/Result
    Template in ``method``, describing how that entity's identity
    (design doc section 7, "UUIDと実体の同一性") should be resolved when the
    Template is actually recorded as an eLabFTW Experiment.

    Three cases, checked in this order:

    1. The template is the ``ref`` target of some other template's
       ``templateRef`` within this same method - its identity is already
       fixed by the Protocol's own structure (e.g. a conditionTemplate
       that carries forward the same materialTemplate instance), so no
       choice is left to make: ``REFERENCE_PROTOCOL_ENTITY`` /
       ``CaptureSource.PROTOCOL``.
    2. Otherwise, a RESULT-role template is always produced fresh by
       running this method: ``GENERATE_NEW`` / ``CaptureSource.GENERATED``.
    3. Otherwise (an unreferenced MATERIAL or CONDITION template) the
       Protocol alone cannot say whether this is a brand new sample, an
       existing Material, or the previous Result of an earlier, separate
       experiment - identity_policy is left unset and the three
       ``_LEAF_IDENTITY_CHOICES`` are attached as a ``ValidationRule`` for
       whoever records the experiment to resolve (``CaptureSource.USER_SELECTION``).

    Never inspects ``template.name`` - a shared name between two otherwise
    unrelated templates must never, by itself, imply they are the same
    entity (design doc section 7.2's closing warning, and test item 12 of
    section 16). See ``identity_name_collisions`` for surfacing that
    situation instead of silently acting on it.
    """
    referenced_ids = {ref.template_id for template in method.templates for ref in template.template_refs}
    return tuple(_resolve_identity(template, referenced_ids) for template in method.templates)


def _resolve_identity(template: TemplateDefinition, referenced_ids: set[str]) -> CaptureRequirement:
    requirement_id = f"entity:{template.template_id}"
    maiml_target = f"{template.source_ref.element_kind}/{template.template_id}"

    if template.template_id in referenced_ids:
        return CaptureRequirement(
            requirement_id=requirement_id,
            maiml_target=maiml_target,
            source=CaptureSource.PROTOCOL,
            required=True,
            cardinality="1",
            identity_policy=IdentityPolicy.REFERENCE_PROTOCOL_ENTITY,
        )
    if template.role is TemplateRole.RESULT:
        return CaptureRequirement(
            requirement_id=requirement_id,
            maiml_target=maiml_target,
            source=CaptureSource.GENERATED,
            required=True,
            cardinality="1",
            identity_policy=IdentityPolicy.GENERATE_NEW,
        )
    return CaptureRequirement(
        requirement_id=requirement_id,
        maiml_target=maiml_target,
        source=CaptureSource.USER_SELECTION,
        required=True,
        cardinality="1",
        identity_policy=None,
        validation_rules=(
            ValidationRule(
                rule_type=_IDENTITY_CHOICES_RULE_TYPE,
                parameters={"choices": [item.value for item in _LEAF_IDENTITY_CHOICES]},
            ),
        ),
    )


def identity_choices(requirement: CaptureRequirement) -> tuple[str, ...]:
    """The candidate identity_policy values a requirement built by
    ``derive_entity_requirements`` still leaves open, or ``()`` once its
    identity is already fixed (``requirement.identity_policy`` is set).
    """
    for rule in requirement.validation_rules:
        if rule.rule_type == _IDENTITY_CHOICES_RULE_TYPE:
            return tuple(rule.parameters.get("choices", ()))
    return ()


def identity_name_collisions(method: MethodProtocolModel) -> tuple[dict[str, object], ...]:
    """Flag - never merge - two or more templates whose identity is left
    to be chosen at record time (see ``derive_entity_requirements``) that
    happen to share the same ``name``.

    A shared name is exactly the kind of coincidence design doc section
    7.2 warns must never, by itself, decide identity reuse. Nothing here
    changes what ``derive_entity_requirements`` returns; this only makes
    the coincidence visible (as a conversion warning) instead of letting
    it pass unnoticed, so a human reviewing the Template can confirm two
    same-named entities really are meant to stay distinct.
    """
    referenced_ids = {ref.template_id for template in method.templates for ref in template.template_refs}
    ambiguous = [
        template
        for template in method.templates
        if template.template_id not in referenced_ids and template.role is not TemplateRole.RESULT
    ]
    by_name: dict[str, list[str]] = {}
    for template in ambiguous:
        if template.name:
            by_name.setdefault(template.name, []).append(template.template_id)

    return tuple(
        {
            "code": "IDENTITY_NAME_COLLISION_NOT_MERGED",
            "name": name,
            "template_ids": sorted(ids),
            "detail": (
                f"{len(ids)} entities are named '{name}'; they are kept as distinct "
                "identities - a shared name is never treated as proof of identity"
            ),
        }
        for name, ids in by_name.items()
        if len(ids) > 1
    )
