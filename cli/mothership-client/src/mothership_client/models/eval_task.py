"""Eval task models. A task is platform-authored (``spec``) or repo-authored
(``source``) — exactly one is set. Identity lives in the org-unique ``slug``."""

from datetime import datetime
from enum import StrEnum
from typing import Self

from mothership_client.client_models.api_output_model import ApiOutputModel
from mothership_client.client_models.common import DatetimeFilter, KeywordFilter
from mothership_client.client_models.pagination import PaginationInput
from mothership_client.models.eval_spec import EvalTaskSpec, TaskSource
from pydantic import BaseModel, ConfigDict, Field, model_validator

_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,98}[a-z0-9]$"  # 2-100 chars, kebab


class EvalTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    org_id: str | None = None
    agent_id: str
    slug: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    spec: EvalTaskSpec | None = None
    source: TaskSource | None = None
    expires_at: datetime | None = None
    enabled: bool = True
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CreateEvalTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    slug: str = Field(pattern=_SLUG_PATTERN)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    spec: EvalTaskSpec | None = None
    source: TaskSource | None = None
    expires_at: datetime | None = None
    enabled: bool = True
    # Server-side parameter derivation: resolve this thread's sandbox and
    # inject its declared-secret parameter values into spec.parameters at
    # save time (keys the author already set win). Secret values make one
    # trip, sandbox row to task spec, never crossing the wire — the
    # authoring UI previews names only. An instruction to the server, not
    # task content; it is not stored.
    derive_parameters_from_thread_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one_storage_mode(self) -> Self:
        if (self.spec is None) == (self.source is None):
            raise ValueError("exactly one of spec (platform-authored) or source (repo-authored) is required")
        return self


class UpdateEvalTaskInput(BaseModel):
    """Partial update. ``spec`` and ``source`` replace wholesale when present,
    and providing one switches the task's storage mode (the other is cleared).
    Omitting both leaves the stored document untouched."""

    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(default=None, pattern=_SLUG_PATTERN)
    description: str | None = None
    tags: list[str] | None = None
    spec: EvalTaskSpec | None = None
    source: TaskSource | None = None
    expires_at: datetime | None = None
    enabled: bool | None = None
    # Same contract as on create: the server reads that thread's sandbox and
    # copies its declared-secret values into the spec, so re-deriving an
    # existing task never sends secrets over the wire.
    derive_parameters_from_thread_id: str | None = None


class EvalTaskSortBy(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    SLUG = "slug"


class EvalTaskFilterFields(BaseModel, extra="forbid"):
    task_id: KeywordFilter[str] | None = None
    agent_id: KeywordFilter[str] | None = None
    slug: KeywordFilter[str] | None = None
    tags: KeywordFilter[str] | None = None
    enabled: bool | None = None
    created_at: DatetimeFilter | None = None
    updated_at: DatetimeFilter | None = None
    text_search: str | None = Field(default=None, description="Free-text match across slug, description, and tags")


class SearchEvalTaskInput(EvalTaskFilterFields, PaginationInput[EvalTaskSortBy]):
    sort_by: EvalTaskSortBy = EvalTaskSortBy.CREATED_AT


class ExportEvalTasksInput(BaseModel):
    """Selects platform-authored tasks to render as Harbor task directories
    (zip). Repo-authored tasks are skipped — their eject is a git clone."""

    model_config = ConfigDict(extra="forbid")

    task_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    agent_id: str | None = None


EvalTaskOutput = ApiOutputModel[EvalTask]
SearchEvalTaskOutput = ApiOutputModel[EvalTask]
