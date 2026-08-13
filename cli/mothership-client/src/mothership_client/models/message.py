"""Message models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from mothership_client.client_models.aggregation import AggregationInput
from mothership_client.client_models.api_output_model import ApiOutputModel
from mothership_client.client_models.common import DatetimeFilter, KeywordFilter, NumericFilter
from mothership_client.client_models.pagination import PaginationInput
from mothership_client.models.attachment import Attachment
from mothership_client.models.feedback import AgentFeedback
from pydantic import BaseModel, ConfigDict, Field


class MessageType(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    EPHEMERAL = "ephemeral"


class MessageStatus(StrEnum):
    """Lifecycle of a persisted client-originated message. Written
    PENDING on receipt, ACKED when the backend first emits a frame
    for the turn, PROCESSED when the turn finalizes. INTERRUPTED marks
    an ephemeral assistant turn whose backend died mid-stream and was
    promoted on reconnect so the client can render it as incomplete."""

    PENDING = "PENDING"
    ACKED = "ACKED"
    PROCESSED = "PROCESSED"
    INTERRUPTED = "INTERRUPTED"


class AgentMessage(BaseModel):
    """A single message within a thread. Persisted by the coordinator as messages
    flow through the WebSocket bridge.
    """

    model_config = ConfigDict(extra="forbid")

    message_id: str
    thread_id: str
    external_id: str | None = None
    sender_id: str | None = None
    message_type: MessageType
    content: str
    # Snapshot of the running sandbox's model + current agent version when
    # this message was persisted. None for rows written before a sandbox
    # was resolved (e.g. legacy data).
    model: str | None = None
    model_version: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    feedback: AgentFeedback | None = None
    seq: int = 0
    client_msg_id: str | None = None
    status: MessageStatus = MessageStatus.PROCESSED
    # Always populated on REST responses.
    attachment_ids: list[str] = []
    # Hydrated on get-by-id and on search with ``include_attachments=true``.
    # ``None`` means "not hydrated" — distinct from ``[]`` ("no attachments").
    attachments: list[Attachment] | None = None


class MessageSortBy(StrEnum):
    CREATED_AT = "created_at"


class AgentMessageFilterFields(BaseModel, extra="forbid"):
    """All message filter fields. No pagination, no aggregation."""

    thread_id: KeywordFilter[str] | None = None
    external_id: KeywordFilter[str] | None = None
    message_type: KeywordFilter[MessageType] | None = None
    seq: NumericFilter[int] | None = None
    created_at: DatetimeFilter | None = None
    updated_at: DatetimeFilter | None = None


class SearchAgentMessagesInput(AgentMessageFilterFields, PaginationInput[MessageSortBy]):
    sort_by: MessageSortBy = MessageSortBy.CREATED_AT
    include_feedback: bool = False
    # When true, hydrate full ``attachments`` per message. ``attachment_ids``
    # is populated regardless.
    include_attachments: bool = False
    limit_per_thread: int = Field(default=100, ge=1, le=1_000)


class AggregateAgentMessagesInput(AgentMessageFilterFields, AggregationInput):
    _excluded_aggregatable_fields: ClassVar[set[str]] = set()


class UpdateAgentMessageInput(BaseModel):
    """PATCH body for a message; ``message_id`` is taken from the URL."""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    content: str | None = None
    model: str | None = None
    model_version: str | None = None


SearchAgentMessagesOutput = ApiOutputModel[AgentMessage]
AgentMessageOutput = ApiOutputModel[AgentMessage]
