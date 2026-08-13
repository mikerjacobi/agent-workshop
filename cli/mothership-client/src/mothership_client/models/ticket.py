"""Ticket models."""

from datetime import datetime

from mothership_client.client_models.api_output_model import ApiOutputModel
from pydantic import BaseModel, ConfigDict

DEFAULT_TICKET_TTL_SECONDS: int = 60
MAX_TICKET_TTL_SECONDS: int = 300


class Ticket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    ticket_val: str
    sandbox_id: str
    external_id: str
    # The org the sandbox belongs to. Bound at
    # mint time and carried through WS connect for audit + membership context.
    org_id: str | None = None
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None


class CreateTicketInput(BaseModel):
    """Issue a ticket against an existing sandbox. The ticket is the bearer at WS connect; ``external_id`` is recorded for audit, not enforced at consume. ``ttl_seconds`` is capped to keep tickets short-lived."""

    model_config = ConfigDict(extra="forbid")

    external_id: str


TicketOutput = ApiOutputModel[Ticket]
