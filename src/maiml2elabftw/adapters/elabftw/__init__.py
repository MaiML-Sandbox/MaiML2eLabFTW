"""eLabFTW-facing adapter: writes a TemplatePlan to a real eLabFTW instance."""

from .client import ElabftwClient
from .duplicate import DuplicateDetector
from .http_client import (
    ConflictError,
    ElabftwApiError,
    HttpElabftwClient,
    NotFoundError,
    RateLimitedError,
    ServerError,
    TransportError,
    ValidationError,
)
from .metadata_bundle import MAIML_METADATA_ATTACHMENT_NAME, build_full_metadata_attachment, build_metadata_bundle
from .writer import ElabftwTemplateWriter

__all__ = [
    "ElabftwClient",
    "DuplicateDetector",
    "ElabftwTemplateWriter",
    "build_metadata_bundle",
    "build_full_metadata_attachment",
    "MAIML_METADATA_ATTACHMENT_NAME",
    "HttpElabftwClient",
    "ElabftwApiError",
    "NotFoundError",
    "ConflictError",
    "ValidationError",
    "RateLimitedError",
    "ServerError",
    "TransportError",
]
