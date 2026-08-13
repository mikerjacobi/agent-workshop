"""Models for the coordinator HTTP API (POST /api/threads/messages)."""

from typing import Self

from mothership_client.client_models.api_output_model import ApiOutputModel
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RestSendMessageInput(BaseModel):
    """Client-facing input for POST /api/messages. The REST API resolves
    external_id from the thread before forwarding to the coordinator."""

    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(description="Thread to send the message to.")
    content: str = Field(default="", description="Message content. Optional when attached_file_ids is non-empty.")
    client_msg_id: str | None = Field(default=None, description="Optional idempotency key for dedup on retries; forwarded to the coordinator and echoed on the persisted row.")
    attached_file_ids: list[str] = Field(
        default_factory=list,
        description="File ids (from POST /api/files/) to attach. The coordinator mints "
        "one attachment per owned id, scoped to the message's external_id.",
    )

    @model_validator(mode="after")
    def _require_content_or_attachments(self) -> Self:
        if not self.content and not self.attached_file_ids:
            raise ValueError("message must include content or at least one attached_file_id")
        return self


class SendMessageInput(BaseModel):
    """Coordinator-internal input for POST /api/threads/messages."""

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(description="Durable owner identity for session lookup.")
    thread_id: str = Field(description="Thread to send the message to.")
    content: str = Field(default="", description="Message content. Optional when attached_file_ids is non-empty.")
    client_msg_id: str | None = Field(default=None, description="Optional idempotency key for dedup on retries.")
    attached_file_ids: list[str] = Field(
        default_factory=list,
        description="File ids (from POST /api/files/) to attach to this message.",
    )

    @model_validator(mode="after")
    def _require_content_or_attachments(self) -> Self:
        if not self.content and not self.attached_file_ids:
            raise ValueError("message must include content or at least one attached_file_id")
        return self


class SendMessageOutput(BaseModel):
    thread_id: str = Field(description="Thread the message was sent to.")
    message_id: str = Field(description="ID of the persisted user message.")


SendMessageApiOutput = ApiOutputModel[SendMessageOutput]


class CancelTurnOutput(BaseModel):
    thread_id: str = Field(description="Thread the cancel was published for.")


CancelTurnApiOutput = ApiOutputModel[CancelTurnOutput]
