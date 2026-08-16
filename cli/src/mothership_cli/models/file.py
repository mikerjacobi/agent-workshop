from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import uuid4

from mothership_cli.client_models.aggregation import AggregationInput
from mothership_cli.client_models.api_output_model import ApiOutputModel
from mothership_cli.client_models.common import DatetimeFilter, KeywordFilter
from mothership_cli.client_models.pagination import PaginationInput
from pydantic import BaseModel, ConfigDict, Field


class FileAuthorRole(StrEnum):
    """Role that produced the file. Mirrors ``MessageType`` values for the two
    interactive roles; ``system``/``ephemeral`` don't apply to files."""

    USER = "user"
    ASSISTANT = "assistant"


class File(BaseModel):
    """A first-class file object. ``file_path`` is the object-storage key."""

    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(default_factory=lambda: str(uuid4()))
    external_id: str
    author_role: FileAuthorRole = FileAuthorRole.USER
    mime_type: str = ""
    file_name: str = ""
    size_bytes: int | None = None
    file_path: str
    created_at: datetime | None = None
    # Soft-delete tombstone: bytes are gone, row remains for history rendering.
    deleted_at: datetime | None = None


class FileSortBy(StrEnum):
    CREATED_AT = "created_at"


class FileFilterFields(BaseModel, extra="forbid"):
    file_id: KeywordFilter[str] | None = None
    external_id: KeywordFilter[str] | None = None
    author_role: KeywordFilter[FileAuthorRole] | None = None
    mime_type: KeywordFilter[str] | None = None
    created_at: DatetimeFilter | None = None
    # When False (the default) the search hides tombstoned rows.
    include_deleted: bool = False


class SearchFilesInput(FileFilterFields, PaginationInput[FileSortBy]):
    sort_by: FileSortBy = FileSortBy.CREATED_AT


class AggregateFilesInput(FileFilterFields, AggregationInput):
    _excluded_aggregatable_fields: ClassVar[set[str]] = {"file_id"}


FileOutput = ApiOutputModel[File]
SearchFilesOutput = ApiOutputModel[File]
