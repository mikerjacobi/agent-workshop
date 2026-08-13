from enum import StrEnum

from mothership_client.client_models.common import SortDirection
from pydantic import BaseModel, Field

MAX_LIMIT = 10_000


class PaginationInput[S: StrEnum](BaseModel):
    limit: int = Field(default=100, ge=0, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0, le=10_000)
    sort_by: S  # default must be set on the concrete subclass
    sort_direction: SortDirection = SortDirection.DESC
