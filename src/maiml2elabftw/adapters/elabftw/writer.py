from __future__ import annotations

from typing import NoReturn

from ...core.errors import ConversionError, ErrorCode
from ...core.models import TemplatePlan
from .client import ElabftwClient
from .duplicate import DuplicateDetector
from .metadata_bundle import build_full_metadata_attachment, build_metadata_bundle


class ElabftwTemplateWriter:
    """Turn a validated TemplatePlan into one eLabFTW Experiment Template.

    Responsibility split (see ``docs/protocol_model_design.md`` section 13):

        TemplatePlan
            -> DuplicateDetector   (reject if source already has a template)
            -> ElabftwTemplateWriter
                 - create_template
                 - set_steps
                 - set_metadata (Custom Fields + a pointer to the full
                   metadata attachment, ONE call - see
                   metadata_bundle.build_metadata_bundle for why these
                   can't be two separate PATCHes)
                 - upload_attachment (source_maiml, insertions, then the
                   generated maiml-metadata.json carrying the full
                   reverse-conversion record)
                 - rollback on failure

    Every stage after ``create_template`` is guarded: if any of them raises,
    the *one* template this call just created is deleted (compensating
    rollback) and the failure is re-raised as ``API_WRITE_FAILED``. If the
    rollback delete itself fails, that is re-raised as ``ROLLBACK_FAILED``
    with the orphaned template's id attached, so a human can clean it up.

    Nothing here ever calls ``delete_template`` on a template id other than
    the one this ``create()`` call produced - an existing template found by
    the DuplicateDetector is rejected, never touched.
    """

    def __init__(self, client: ElabftwClient, *, duplicate_detector: DuplicateDetector | None = None) -> None:
        self._client = client
        self._duplicate_detector = duplicate_detector or DuplicateDetector(client)

    def create(self, plan: TemplatePlan) -> int:
        existing_template_id = self._duplicate_detector.find_existing(plan.source)
        if existing_template_id is not None:
            document_uuid, method_uuid = plan.source.duplicate_key
            raise ConversionError(
                ErrorCode.DUPLICATE_SOURCE,
                f"a template for document {document_uuid} / method {method_uuid} already exists",
                {"existing_template_id": existing_template_id},
            )

        template_id = self._create_template(plan)
        metadata_bundle = build_metadata_bundle(plan)

        for stage, action in (
            ("set_steps", lambda: self._client.set_steps(template_id, plan.steps)),
            ("set_metadata", lambda: self._client.set_metadata(template_id, metadata_bundle)),
        ):
            try:
                action()
            except Exception as exc:  # noqa: BLE001 - any client failure means "roll back this stage"
                self._fail_and_rollback(template_id, stage=stage, original=exc)

        # The generated maiml-metadata.json attachment travels alongside the
        # MaiML-described ones (source_maiml, insertions) - same upload
        # call, same rollback-on-failure treatment - it's just not
        # something method.attachments itself knows about, since deciding
        # to split it out is an eLabFTW-storage concern (see
        # metadata_bundle.build_metadata_bundle), not a MaiML-domain one.
        for attachment in (*plan.attachments, build_full_metadata_attachment(plan)):
            try:
                self._client.upload_attachment(template_id, attachment)
            except Exception as exc:  # noqa: BLE001
                self._fail_and_rollback(
                    template_id, stage=f"upload_attachment:{attachment.attachment_id}", original=exc
                )

        return template_id

    def _create_template(self, plan: TemplatePlan) -> int:
        # Nothing exists yet if this call fails, so there is nothing to roll
        # back - just report the failure.
        try:
            return self._client.create_template(title=plan.title, body=plan.body)
        except Exception as exc:  # noqa: BLE001
            raise ConversionError(
                ErrorCode.API_WRITE_FAILED,
                f"create_template failed: {exc}",
                {"template_id": None, "stage": "create_template", "original_error": str(exc)},
            ) from exc

    def rollback(self, template_id: int) -> None:
        """Delete a template this writer created. Raises ROLLBACK_FAILED on failure."""
        try:
            self._client.delete_template(template_id)
        except Exception as exc:  # noqa: BLE001
            raise ConversionError(
                ErrorCode.ROLLBACK_FAILED,
                f"failed to delete template {template_id} during rollback: {exc}",
                {"template_id": template_id},
            ) from exc

    def _fail_and_rollback(self, template_id: int, *, stage: str, original: Exception) -> NoReturn:
        try:
            self.rollback(template_id)
        except ConversionError as rollback_error:
            raise ConversionError(
                ErrorCode.ROLLBACK_FAILED,
                f"{stage} failed and rollback of template {template_id} also failed: {original}",
                {"template_id": template_id, "stage": stage, "original_error": str(original)},
            ) from rollback_error
        raise ConversionError(
            ErrorCode.API_WRITE_FAILED,
            f"{stage} failed; template {template_id} was rolled back: {original}",
            {"template_id": template_id, "stage": stage, "original_error": str(original)},
        ) from original
