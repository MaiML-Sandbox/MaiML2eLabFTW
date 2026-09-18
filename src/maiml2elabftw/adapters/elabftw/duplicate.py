from __future__ import annotations

from ...core.models import SourceIdentity
from .client import ElabftwClient


class DuplicateDetector:
    """Decide whether a TemplatePlan's source already has a template.

    Kept separate from :class:`ElabftwTemplateWriter` so the definition of
    "duplicate" - currently document UUID + method UUID, i.e.
    ``SourceIdentity.duplicate_key`` - can change without touching the
    create/rollback orchestration, and so it can be unit-tested on its own.
    """

    def __init__(self, client: ElabftwClient) -> None:
        self._client = client

    def find_existing(self, source: SourceIdentity) -> int | None:
        document_uuid, method_uuid = source.duplicate_key
        return self._client.find_duplicate(document_uuid, method_uuid)
