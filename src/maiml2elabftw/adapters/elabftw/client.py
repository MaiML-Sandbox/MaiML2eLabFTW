from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ...core.models import AttachmentDefinition, StepPlan


@runtime_checkable
class ElabftwClient(Protocol):
    """The eLabFTW-facing surface that :class:`ElabftwTemplateWriter` needs.

    This is deliberately narrow and framework-agnostic: no HTTP, auth, or
    eLabFTW SDK types leak into ``maiml2elabftw.core``/``planning``. Anything
    that talks to the real eLabFTW REST API (v2 Experiment Templates
    endpoints) implements this Protocol; tests use a small in-memory fake
    instead of a real HTTP client.

    Each method call is expected to be *atomic from the caller's point of
    view*: it either fully succeeds, or raises without leaving the template
    in a half-written state that the writer would need to know the details
    of. ``ElabftwTemplateWriter`` treats any exception raised here as "this
    stage failed" and reacts by rolling back the template it created in this
    same :meth:`ElabftwTemplateWriter.create` call - never an existing one.

    There is deliberately no ``set_custom_fields``. eLabFTW stores Custom
    Fields (``extra_fields`` / ``elabftw.extra_fields_groups``) and arbitrary
    metadata (the ``maiml`` block) in the *same* JSON blob on the template,
    so writing them with two separate calls risks the second one clobbering
    the first. ``ElabftwTemplateWriter`` assembles the whole object once
    (see ``metadata_bundle.build_metadata_bundle``) and this Protocol only
    exposes a single ``set_metadata`` that writes it in one request.
    """

    def find_duplicate(self, document_uuid: str, method_uuid: str) -> int | None:
        """Return the id of an existing template for this source, or None."""
        ...

    def create_template(self, *, title: str, body: str) -> int:
        """Create a new, otherwise-empty Experiment Template and return its id."""
        ...

    def set_metadata(self, template_id: int, metadata: dict[str, Any]) -> None:
        """Write the *complete* metadata JSON (extra fields + groups + maiml
        + conversion_warnings) onto the template in a single request."""
        ...

    def set_steps(self, template_id: int, steps: StepPlan) -> None:
        """Create the template's Steps."""
        ...

    def upload_attachment(self, template_id: int, attachment: AttachmentDefinition) -> None:
        """Attach one file (source_maiml or insertion) to the template."""
        ...

    def delete_template(self, template_id: int) -> None:
        """Permanently remove a template. Used only for compensating rollback."""
        ...
