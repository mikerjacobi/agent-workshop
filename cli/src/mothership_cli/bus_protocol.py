from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- shared building blocks ------------------------------------------------ #


class Media(_Wire):
    """Wire reference to stored media. Bytes live in object storage.
    ``media_id`` resolves bytes via ``GET /bus/v0/media/{media_id}``.

    When inbound, media_id is an existing Postgres File file_id.
    When outbound, no corresponding File row exists in Postgres until processed by
    the coordinator."""

    media_id: str
    mime_type: str = ""
    name: str = ""
    size_bytes: int | None = None


class ContextItem(_Wire):
    """Ambient client/UI state volunteered ON a message (push), as opposed to the
    agent pulling it via a ``client_command``. Rides a message like a ``Media`` does —
    but state, not bytes. The bus does not interpret ``data``; what a ``kind`` means
    (e.g. "map_viewport" → a center/zoom at x,y) is a client-defined contract
    documented elsewhere, not in the bus protocol."""

    kind: str  # client-namespaced, e.g. "map_viewport", "selection"
    data: dict[str, Any] = {}


class Sender(_Wire):
    """Who contributed an inbound turn. 1:1 chat uses the implicit ``{id: "user"}``"""

    id: str = "user"
    display_name: str | None = None


class HistoryTurn(_Wire):
    """One prior turn in the history document. This is not a bus message.

    The document is a bare JSON array of these (``list[HistoryTurn]`` via ``TypeAdapter``),
    fetched from ``GET /bus/v0/history/{thread_id}`` when the plugin handles a ``bind``.

    Once the history document is retrieved, individual media are downloaded using
    ``GET /bus/v0/media/{media_id}`` before rehydrating."""

    role: Literal["user", "assistant"]
    text: str
    media: list[Media] = []


# --- control (thread-level) ------------------------------------------------- #


class UserMessagePayload(_Wire):
    """A complete user turn: text, plus optional ``media`` (bytes) and ``context``
    (client/UI state). ``message_id`` is the coordinator-minted Postgres row id."""

    message_id: str
    sender: Sender = Sender()
    text: str = ""
    media: list[Media] = []
    context: list[ContextItem] = []


class UserMessage(_Wire):
    """Deliver a user turn. Inbound."""

    type: Literal["user_message"] = "user_message"
    thread_id: str
    payload: UserMessagePayload


class BindMessage(_Wire):
    """Bind the thread to a fresh harness session. This is a pointer to a thread
    history document (``GET /bus/v0/history/{thread_id}`` → ``list[HistoryTurn]``)"""

    type: Literal["bind"] = "bind"
    thread_id: str
    before_seq: int


class CancelMessage(_Wire):
    """Best-effort interrupt of the in-flight turn; does not unbind. No-op if idle."""

    type: Literal["cancel"] = "cancel"
    thread_id: str


# --- content (agent turn output) ------------------------------------------- #


class DeltaPayload(_Wire):
    text: str


class DeltaMessage(_Wire):
    """Streaming assistant text. ``text`` is cumulative for the turn (re-emit-and-
    replace, not append); the UI upserts one bubble per ``turn_id``"""

    type: Literal["delta"] = "delta"
    thread_id: str
    turn_id: str
    payload: DeltaPayload


class FinalPayload(_Wire):
    """The same ``text + media + context`` body as ``UserMessagePayload``. —
    duplicated deliberately, not shared via a base. ``media`` are agent-
    produced artifacts uploaded via ``POST /bus/v0/media``.

    Agent-generated media is stored before the outbound FinalMessage is written,
    but the Postgres File is not created until processed by the coordinator."""

    text: str = ""
    media: list[Media] = []


class FinalMessage(_Wire):
    """End-of-turn authoritative message — the outbound dual of ``user_message``.
    Outbound."""

    type: Literal["final"] = "final"
    thread_id: str
    turn_id: str
    payload: FinalPayload


class ThinkingPayload(_Wire):
    text: str


class ThinkingMessage(_Wire):
    """Extended-thinking trace, CUMULATIVE like ``delta``. Surfaced to UI, never
    persisted, never folded into ``final`` text. Outbound."""

    type: Literal["thinking"] = "thinking"
    thread_id: str
    turn_id: str
    payload: ThinkingPayload


# --- tools (informational: the agent reporting its own tool use) ------------ #


class ToolCallPayload(_Wire):
    tool: str = ""
    args: dict[str, Any] = {}
    tool_use_id: str = ""


class ToolCallMessage(_Wire):
    """The agent reporting a tool invocation it is making in the sandbox (today's
    read_file etc.) — informational display, not a request; nothing answers it on
    the bus (the harness runs the tool itself). Outbound."""

    type: Literal["tool_call"] = "tool_call"
    thread_id: str
    turn_id: str
    payload: ToolCallPayload


class ToolResultPayload(_Wire):
    tool: str = ""
    output: str = ""
    tool_use_id: str = ""
    is_error: bool = False


class ToolResultMessage(_Wire):
    """Result of a sandbox tool call the agent made, correlated by ``tool_use_id``.
    Informational display, like ``tool_call``. Outbound."""

    type: Literal["tool_result"] = "tool_result"
    thread_id: str
    turn_id: str
    payload: ToolResultPayload


# --- client commands (agent → client request / response) -------------------- #


class ClientCommandPayload(_Wire):
    command: str  # e.g. "set_map_view"
    args: dict[str, Any] = {}
    command_id: str  # correlates the client_command_result


class ClientCommandMessage(_Wire):
    """Emitted by an agent tool call directed at the browser/client
    (e.g. get_map_viewport) that the client is meant to execute, answering with
    a matching ``client_command_result``.

    What any given command means is a client command contract documented elsewhere.
    The bus supports forwarding the command and returning the result, but does not
    interpret.

    Schema-only at this point, not implemented by any tools."""

    type: Literal["client_command"] = "client_command"
    thread_id: str
    turn_id: str
    payload: ClientCommandPayload


class ClientCommandResultPayload(_Wire):
    command: str = ""
    output: str = ""
    command_id: str
    is_error: bool = False


class ClientCommandResultMessage(_Wire):
    """The client answering a ``client_command``, correlated by ``command_id``.
    Inbound — turn-scoped, since it belongs to the agent turn that asked.

    Schema-only at this point, not implemented."""

    type: Literal["client_command_result"] = "client_command_result"
    thread_id: str
    turn_id: str
    payload: ClientCommandResultPayload


# --- approval (gated client command; the human is the executor) ------------- #


class ApprovalRequiredPayload(_Wire):
    request_id: str
    tool: str = ""
    args: dict[str, Any] = {}


class ApprovalRequiredMessage(_Wire):
    """Agent paused on a gated tool call. A human user provides consent, triggering
    an inbound ``ApproveMessage`` response."""

    type: Literal["approval_required"] = "approval_required"
    thread_id: str
    turn_id: str
    payload: ApprovalRequiredPayload


class ApprovePayload(_Wire):
    request_id: str
    approved: bool = False


class ApproveMessage(_Wire):
    """Inbound response to ``approval_required``, correlated by ``request_id``."""

    type: Literal["approve"] = "approve"
    thread_id: str
    turn_id: str
    payload: ApprovePayload


# --- lifecycle / passthrough ----------------------------------------------- #


class StatusPayload(_Wire):
    phase: str = ""
    data: dict[str, Any] = {}


class StatusMessage(_Wire):
    """Lifecycle (``turn_started``, ``turn_ended``, ``thread_bound``, …). Outbound."""

    type: Literal["status"] = "status"
    thread_id: str
    turn_id: str = ""
    payload: StatusPayload


class ErrorPayload(_Wire):
    message: str = ""
    data: dict[str, Any] = {}


class ErrorMessage(_Wire):
    type: Literal["error"] = "error"
    thread_id: str
    turn_id: str = ""
    payload: ErrorPayload


class OtherPayload(_Wire):
    """``raw`` carries the original wire bytes for diagnostics."""

    data: dict[str, Any] = {}
    raw: str = ""


class OtherMessage(_Wire):
    """Unrecognized passthrough. Outbound."""

    type: Literal["other"] = "other"
    thread_id: str
    turn_id: str = ""
    payload: OtherPayload = OtherPayload()


# Unions represent valid directions for each message type
InboundBusMessage = Annotated[
    UserMessage | BindMessage | CancelMessage | ClientCommandResultMessage | ApproveMessage,
    Field(discriminator="type"),
]

OutboundBusMessage = Annotated[
    DeltaMessage | FinalMessage | ThinkingMessage | ToolCallMessage | ToolResultMessage | ClientCommandMessage | ApprovalRequiredMessage | StatusMessage | ErrorMessage | OtherMessage,
    Field(discriminator="type"),
]

# The full vocabulary, for code handling a message whose direction is known from context.
BusMessage = InboundBusMessage | OutboundBusMessage

INBOUND_ADAPTER: TypeAdapter[InboundBusMessage] = TypeAdapter(InboundBusMessage)
OUTBOUND_ADAPTER: TypeAdapter[OutboundBusMessage] = TypeAdapter(OutboundBusMessage)
BUS_MESSAGE_ADAPTER: TypeAdapter[BusMessage] = TypeAdapter(BusMessage)
HISTORY_ADAPTER: TypeAdapter[list[HistoryTurn]] = TypeAdapter(list[HistoryTurn])


class ClientStreamEvent(BaseModel):
    """
    BusMessage envelope exposed to the client via POST /threads/search or SSE streaming in the future.
    Written to client:{thread_id} and can carry both inbound and outbound bus messages.
    """

    # Unique ID generated per event, used by the client to track the same event across multiple REST queries
    id: str = Field(default_factory=lambda: str(uuid4()))
    # Database-backed Message ID, populated if this event corresponds to one
    message_id: str | None = None
    # Database ``seq`` of the backing Message, populated whenever ``message_id`` is. Carries the SSE resume
    # cursor (``Last-Event-ID``/``after_seq``) and lets clients dedupe an event against its Postgres-history twin.
    seq: int | None = None
    # ``client_msg_id`` of the backing user Message, when this event is a user turn — lets a client reconcile its
    # optimistic echo (keyed by client_msg_id) to the durable message.
    client_msg_id: str | None = None
    data: BusMessage
    # Matches updated_at on the database-backed Message if this event corresponds to one
    created_at: datetime
