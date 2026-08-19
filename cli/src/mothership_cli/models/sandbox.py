"""Sandbox and related models. A sandbox is a running agent environment
for an (external_id, agent_id, model) triple — one container stack
shared by many sessions. ``external_id`` is an opaque caller identifier;
``owner_id`` is a surrogate FK into the ``users`` identity table,
resolved from ``external_id`` at create time."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Self

from mothership_cli.client_models.aggregation import AggregationInput
from mothership_cli.client_models.api_output_model import ApiOutputModel
from mothership_cli.client_models.common import DatetimeFilter, KeywordFilter, StringFilter
from mothership_cli.client_models.pagination import PaginationInput
from mothership_cli.models.harness import TransportMode
from mothership_cli.models.ticket import Ticket
from mothership_cli.validators import strip_or_reject_blank
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SandboxState(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


# Ordered on purpose: the tuple is emitted into the partial unique index
# `postgresql_where` clause, and stable ordering keeps schema comparisons
# from flapping across runs.
ACTIVE_SANDBOX_STATES: tuple[SandboxState, ...] = (
    SandboxState.CREATED,
    SandboxState.STARTING,
    SandboxState.RUNNING,
)


class Sandbox(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sandbox_id: str
    external_id: str
    # The org this sandbox belongs to (tenancy boundary), stamped from the
    # request's org context.
    org_id: str | None = None
    # Surrogate FK into the users identity table, resolved from external_id
    # at create time. None on rows created before the users table existed.
    owner_id: str | None = None
    display_name: str
    model: str
    gcs_bucket: str
    # Optional reference to the agent_catalog entry that triggered
    # this sandbox. Nullable so the legacy model-string flow and
    # direct sandbox-create calls still work without a catalog
    # entry — the orchestrator falls back to harness defaults when
    # this is unset.
    agent_id: str | None = None
    # The agent_versions row this sandbox is actually running, advanced by
    # the coordinator once a pod image change lands. Stamped to the boot
    # version at create time.
    current_agent_version_id: str | None = None
    # The agent_versions row this sandbox should be running. A PATCH sets
    # this to request an upgrade; the coordinator reconciles current →
    # desired.
    desired_agent_version_id: str | None = None
    # Display-only labels resolved on read paths (search/get): the agent's
    # slug, name, and the human-friendly ``version`` labels for the current and
    # desired version ids above. None on write responses and when the
    # referenced row no longer exists.
    agent_slug: str | None = None
    agent_name: str | None = None
    current_agent_version: str | None = None
    desired_agent_version: str | None = None
    # Harness type and image resolved from the agent catalog at creation
    # time. Stored on the sandbox so the driver can use them without a
    # second DB lookup — the catalog entry might be updated or deleted
    # after the sandbox is created, and the running sandbox should keep
    # using whatever it was launched with.
    harness_type: str | None = None
    # Transport fronting this sandbox: "relay" (lifeline dials the harness
    # gateway) or "bus" (harness runs the mothership channel against a
    # lifeline-hosted bus). Stamped at create time alongside harness_type.
    transport: str = TransportMode.RELAY.value
    harness_image: str | None = None
    # Resolved agent parameter values (key -> value) stamped onto the
    # sandbox at creation time. Injected as env vars into every
    # container in the sandbox stack. Stamped at create-time rather
    # than looked up from the agent catalog each launch so mutating
    # or deleting the catalog entry later doesn't change what a
    # running sandbox sees.
    parameters: dict[str, str] = {}
    # Snapshot of `parameters` from the last container (re)boot. Lets a caller
    # tell whether the current `parameters` (and derived channel_config) are
    # still pending a restart to take effect. Empty until the first boot.
    booted_parameters: dict[str, str] = {}
    # Resolved system parameter values (key -> value) stamped at creation
    # alongside `parameters`. Mothership-owned tuning knobs (log level, pod
    # resource requests) defined in code, not agent-declared. See
    # models/system_parameters.py.
    system_parameters: dict[str, str] = {}
    # Read-only: the per-connector routing config decoded from the stamped
    # OPENCLAW_CHANNELS param, keyed by connector type, with the token SecretRef
    # stripped. Populated on read paths for display; not persisted as a column.
    channel_config: dict[str, dict] = {}
    # Read-only: true when the stamped parameters differ from what the running
    # pod booted with (a restart would apply them). Computed server-side from
    # unmasked values so it catches rotated secrets that a client-side diff of
    # masked params can't. False for a never-booted sandbox.
    restart_pending: bool = False
    state: SandboxState = SandboxState.CREATED
    harness_metadata: dict | None = None
    litellm_key: str | None = None
    # When set, the coordinator's pod reconciler re-provisions this
    # sandbox if its pod vanishes while still RUNNING, rather than
    # stopping it.
    auto_restart: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SandboxSortBy(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class SandboxFilterFields(BaseModel, extra="forbid"):
    external_id: KeywordFilter[str] | None = None
    # Cross-org filter for the platform-admin views; org-scoped reads AND their
    # own org onto this server-side.
    org_id: KeywordFilter[str] | None = None
    owner_id: KeywordFilter[str] | None = None
    owner: StringFilter | None = None
    sandbox_id: KeywordFilter[str] | None = None
    model: KeywordFilter[str] | None = None
    agent_id: KeywordFilter[str] | None = None
    # Filter by the version a sandbox is actually running.
    current_agent_version_id: KeywordFilter[str] | None = None
    state: KeywordFilter[SandboxState] | None = None
    created_at: DatetimeFilter | None = None
    updated_at: DatetimeFilter | None = None


class SearchSandboxesInput(SandboxFilterFields, PaginationInput[SandboxSortBy]):
    sort_by: SandboxSortBy = SandboxSortBy.CREATED_AT


class AggregateSandboxesInput(SandboxFilterFields, AggregationInput):
    # sandbox_id stays aggregatable: the admin UI groups by it to build a
    # distinct-value typeahead for the sandbox filter. Bounded by the
    # group_by num_buckets cap (<=1000), so it's not an unbounded scan.
    _excluded_aggregatable_fields: ClassVar[set[str]] = set()
    # display_name is groupable but deliberately not filterable: the `owner`
    # StringFilter already matches external_id OR display_name. The admin UI's
    # owner typeahead unions distinct values of both, so display_name has to be
    # declared here — there is no filter field for the walker to discover.
    _extra_aggregatable_fields: ClassVar[dict[str, type]] = {"display_name": KeywordFilter}


class CreateSandboxInput(BaseModel):
    """Find-or-create a sandbox for ``(external_id, agent_id, model)``; optionally mint a WS-connect ticket."""

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, description="End user's stable identity, supplied by the calling service.")
    # Identify the agent by exactly one of its surrogate ``agent_id`` or its
    # human ``agent_slug`` (resolved within the caller's org). Enforced below.
    agent_id: str | None = Field(default=None, min_length=1, description="Agent catalog entry by surrogate id; stamps harness + image onto the sandbox. Mutually exclusive with agent_slug.")
    agent_slug: str | None = Field(default=None, min_length=1, description="Agent catalog entry by human slug (resolved within the caller's org). Mutually exclusive with agent_id.")
    agent_version_id: str | None = Field(
        default=None,
        min_length=1,
        description="Agent version to launch with. Omit to use the agent's current_version. Must belong to the agent and be enabled. Ignored when an existing sandbox is reused.",
    )
    model: str | None = Field(
        default=None,
        min_length=1,
        description="LiteLLM model string. Omit to fall back to the agent's default_model; blank is rejected.",
    )
    display_name: str | None = Field(default=None, description="Admin-UI label. Defaults to external_id.")
    parameters: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Agent parameter overrides, keyed by AgentParameter.key. Unknown keys are rejected; "
            "missing required keys (no default in the catalog) are rejected. Ignored when an existing "
            "sandbox is reused — its stamped parameters win."
        ),
    )
    system_parameters: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "System parameter overrides (LOG_LEVEL, RESOURCE_MEMORY_GB, RESOURCE_CPU_QTY, "
            "RESOURCE_DISK_GB). Unknown keys are rejected; empty or omitted values fall back to "
            "defaults. Ignored when an existing sandbox is reused — its stamped values win."
        ),
    )
    channel_config: dict[str, dict] = Field(
        default_factory=dict,
        description=(
            "Per-connector routing config for the channels the agent enables, keyed by connector type "
            "(e.g. {\"discord\": {\"groupPolicy\": \"allowlist\", \"guilds\": {...}}}). The token SecretRef is "
            "injected from the registry; don't hand-write it. Config for a channel the agent doesn't enable is "
            "rejected. Ignored when an existing sandbox is reused — its stamped config wins."
        ),
    )
    issue_ticket: bool = Field(default=False, description="If true, mint a WS-connect ticket and include it in the response.")
    auto_restart: bool = Field(default=False, description="If true, the pod reconciler re-provisions this sandbox when its pod vanishes while still RUNNING. Ignored when an existing sandbox is reused.")

    @field_validator("model", mode="before")
    @classmethod
    def _strip_model(cls, v: str | None) -> str | None:
        return strip_or_reject_blank(v)

    @model_validator(mode="after")
    def _exactly_one_agent_ref(self) -> Self:
        if bool(self.agent_id) == bool(self.agent_slug):
            raise ValueError("provide exactly one of 'agent_id' or 'agent_slug'")
        return self


class UpdateSandboxInput(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    sandbox_id: str
    state: SandboxState | None = None
    harness_metadata: dict | None = None
    auto_restart: bool | None = None
    # Editable agent + system parameter overrides. Validated in the API
    # route against the sandbox's agent and the system-parameter registry
    # before persisting; a running container keeps its stamped values
    # until its next boot.
    parameters: dict[str, str] | None = None
    system_parameters: dict[str, str] | None = None
    # Per-connector routing config (guilds, streaming, …), keyed by connector
    # type. Rebuilt into bindings and re-stamped on patch; the token SecretRef
    # is re-injected from the registry, so callers never send it. Sentinel:
    # omit to leave channel config unchanged. Takes effect on the next boot.
    channel_config: dict[str, dict] | None = None
    # Repoint the sandbox at a different desired version. The runtime
    # upgrade (update the pod image, then advance current_agent_version_id)
    # is handled by the coordinator reconciler; setting this only records
    # intent. TODO(#195): wire the reconciler + ?force_upgrade immediate
    # restart.
    desired_agent_version_id: str | None = None


SearchSandboxesOutput = ApiOutputModel[Sandbox]
SandboxOutput = ApiOutputModel[Sandbox]


class CreateSandboxOutput(ApiOutputModel[Sandbox]):
    """SandboxOutput envelope plus the ticket minted when ``issue_ticket=True``."""

    ticket: Ticket | None = None


class SandboxStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sandbox_id: str
    status: str


SandboxStatusOutput = ApiOutputModel[SandboxStatus]
