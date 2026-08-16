"""Thread models."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Self

from mothership_cli.bus_protocol import ClientStreamEvent
from mothership_cli.client_models.aggregation import AggregationInput
from mothership_cli.client_models.api_output_model import ApiOutputModel
from mothership_cli.client_models.common import DatetimeFilter, KeywordFilter, StringFilter
from mothership_cli.client_models.pagination import PaginationInput
from mothership_cli.models.attachment import BlobCopySpec
from mothership_cli.models.message import AgentMessage, SearchAgentMessagesInput
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ThreadStatus(StrEnum):
    INACTIVE = "inactive"
    ACTIVATING = "activating"
    ACTIVE = "active"
    ACTIVE_PROCESSING = "active_processing"


class AgentThread(BaseModel):
    """A conversation transcript within a session. Threads group ordered
    messages and track whether a response is currently in-flight.
    """

    model_config = ConfigDict(extra="forbid")

    thread_id: str
    external_id: str
    # The org this thread belongs to (tenancy boundary).
    # the source of truth for stamping coordinator-persisted messages on it.
    org_id: str | None = None
    # Surrogate FK into the users identity table, resolved from external_id
    # at create time. Distinct from owner_name (a denormalized display label).
    owner_id: str | None = None
    title: str | None = None
    status: ThreadStatus = ThreadStatus.INACTIVE
    agent_id: str | None = None
    model: str | None = None
    sandbox_id: str | None = None
    last_evt_id: str | None = None
    owner_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    messages: list[AgentMessage] | None = None
    message_count: int = 0
    stream: list[ClientStreamEvent] | None = None


class ThreadSortBy(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class AgentThreadFilterFields(BaseModel, extra="forbid"):
    """All thread filter fields. No pagination, no aggregation."""

    external_id: KeywordFilter[str] | None = None
    # Cross-org filter for the platform-admin views; org-scoped reads AND their
    # own org onto this server-side.
    org_id: KeywordFilter[str] | None = None
    owner_id: KeywordFilter[str] | None = None
    owner: StringFilter | None = None
    thread_id: KeywordFilter[str] | None = None
    sandbox_id: KeywordFilter[str] | None = None
    status: KeywordFilter[ThreadStatus] | None = None
    created_at: DatetimeFilter | None = None
    updated_at: DatetimeFilter | None = None


class SearchAgentThreadsInput(AgentThreadFilterFields, PaginationInput[ThreadSortBy]):
    sort_by: ThreadSortBy = ThreadSortBy.UPDATED_AT
    messages: SearchAgentMessagesInput | None = None
    include_stream: bool = False


class AggregateAgentThreadsInput(AgentThreadFilterFields, AggregationInput):
    _excluded_aggregatable_fields: ClassVar[set[str]] = {"thread_id"}


class CreateAgentThreadInput(BaseModel):
    """POST body for creating a thread. The thread is pinned to an agent +
    model at creation; ``model`` falls back to the agent's default. A
    RUNNING sandbox must already exist for the resulting
    (external_id, agent_id, model) triple — params live on the sandbox."""

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1)
    # Identify the agent by exactly one of its surrogate ``agent_id`` or its
    # human ``agent_slug`` (resolved within the caller's org). Enforced below.
    agent_id: str | None = Field(default=None, min_length=1)
    agent_slug: str | None = Field(default=None, min_length=1)
    model: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def _exactly_one_agent_ref(self) -> Self:
        if bool(self.agent_id) == bool(self.agent_slug):
            raise ValueError("provide exactly one of 'agent_id' or 'agent_slug'")
        return self


class UpdateAgentThreadInput(BaseModel):
    """PATCH body for a thread; ``thread_id`` is taken from the URL."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    thread_id: str
    title: str | None = None
    owner_name: str | None = None


class CopyThreadInput(BaseModel):
    """POST body for copying a thread's messages into a new thread.
    ``target_external_id`` may equal the source's owner (self-copy /
    fork) or differ (cross-workspace copy)."""

    model_config = ConfigDict(extra="forbid")

    target_external_id: str = Field(min_length=1)
    title: str | None = None
    model: str | None = Field(
        default=None,
        description="Override the model on the copied thread. Falls back to the source thread's model if not set.",
    )
    before_seq: int | None = Field(
        default=None,
        description="When set, only messages with seq < before_seq are copied (truncated copy).",
    )


SearchAgentThreadsOutput = ApiOutputModel[AgentThread]
AgentThreadOutput = ApiOutputModel[AgentThread]


class CopyResult(BaseModel):
    """Internal result of the copy-thread DB transaction."""

    thread: AgentThread
    messages: list[AgentMessage]
    blob_copies: list[BlobCopySpec] = Field(default_factory=list)
    file_id_map: dict[str, str] = Field(default_factory=dict)


class CopiedAgentThread(AgentThread):
    """An ``AgentThread`` extended with the file ID mapping produced by
    ``copy_thread``.  ``file_id_map`` maps source file IDs to their
    deep-copied counterparts for the message at ``before_seq``.  Empty
    when there are no attachments on that message or when the copy is
    same-owner (shallow)."""

    file_id_map: dict[str, str] = Field(default_factory=dict)


CopyThreadOutput = ApiOutputModel[CopiedAgentThread]
