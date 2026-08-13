"""Attachment models. An attachment is a per-message link to a ``File``: the
attachments table is a pure join, the file row holds the metadata, and the
file's bytes live in object storage. Attachments are created server-side at
chat-send time (the user passes ``attached_file_ids`` on the message) and
deleted via cascade when their parent message/thread is deleted or when the
underlying file is hard-deleted."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import uuid4

from mothership_client.client_models.aggregation import AggregationInput
from mothership_client.client_models.api_output_model import ApiOutputModel
from mothership_client.client_models.common import DatetimeFilter, KeywordFilter
from mothership_client.client_models.pagination import PaginationInput
from mothership_client.models.file import File
from pydantic import BaseModel, ConfigDict, Field


class Attachment(BaseModel):
    """A per-message reference to a file. The hydrated ``file`` carries the
    metadata clients render; the row itself is just a join."""

    model_config = ConfigDict(extra="forbid")

    attachment_id: str = Field(default_factory=lambda: str(uuid4()))
    file_id: str
    message_id: str
    created_at: datetime | None = None
    # Hydrated from ``files`` on read; ``None`` only on a missed join (a
    # referential-integrity bug).
    file: File | None = None


class AttachmentSortBy(StrEnum):
    CREATED_AT = "created_at"


class AttachmentFilterFields(BaseModel, extra="forbid"):
    attachment_id: KeywordFilter[str] | None = None
    file_id: KeywordFilter[str] | None = None
    message_id: KeywordFilter[str] | None = None
    # Joined through messages.
    thread_id: KeywordFilter[str] | None = None
    # Joined through files; ``FileAuthorRole`` value ("user" / "assistant").
    author_role: KeywordFilter[str] | None = None
    # Joined through files; scopes to a user's library.
    external_id: KeywordFilter[str] | None = None
    created_at: DatetimeFilter | None = None
    # When False (default), hide attachments whose file row is tombstoned.
    include_deleted: bool = False


class SearchAttachmentsInput(AttachmentFilterFields, PaginationInput[AttachmentSortBy]):
    sort_by: AttachmentSortBy = AttachmentSortBy.CREATED_AT


class AggregateAttachmentsInput(AttachmentFilterFields, AggregationInput):
    _excluded_aggregatable_fields: ClassVar[set[str]] = {"attachment_id"}


AttachmentOutput = ApiOutputModel[Attachment]
SearchAttachmentsOutput = ApiOutputModel[Attachment]


class BlobCopySpec(BaseModel, frozen=True):
    """A pending GCS blob copy produced by deep-copy attachment logic."""

    source_path: str
    target_path: str
    mime_type: str
