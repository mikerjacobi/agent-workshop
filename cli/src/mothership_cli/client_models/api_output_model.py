"""Generic API response envelope used by every endpoint — records + metadata
+ errors. Handlers return ``ApiOutputModel[T]`` subclasses directly and the
api framework's ``@handler``/``@output`` decorators serialize them to JSON."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Metadata(BaseModel):
    # Needed so ``search_after`` can accept an arbitrary list — if it
    # were typed as int or str this wouldn't be required.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    cursor_id: str | None = Field(default=None, deprecated=True)  # superseded by snapshot_id
    snapshot_id: str | None = None
    search_after: list[Any] | None = Field(default=None, deprecated=True)
    total: int | None = Field(default=None)


class Error(BaseModel):
    code: str
    message: str


# Generic error codes returned by ApiOutputModel. Services may define their
# own codes to surface in the ``errors`` field alongside these.
NOT_FOUND_ERROR = "NOT_FOUND_ERROR"
PERMISSION_ERROR = "PERMISSION_ERROR"
SERVER_ERROR = "SERVER_ERROR"
UNAUTHORIZED_ERROR = "UNAUTHORIZED_ERROR"
VALIDATION_ERROR = "VALIDATION_ERROR"


class ApiOutputModel[T](BaseModel):
    records: list[T] | None = Field(default=None)
    meta: Metadata | None = Field(default=None)
    errors: list[Error] | None = Field(default=None)


class ApiError(Exception):
    """Raised when a remote ApiOutputModel call returns errors; carries the
    parsed error list and HTTP status so callers can distinguish validation
    failures from server errors without re-parsing."""

    errors: list[Error]

    def __init__(self, message, api_output: ApiOutputModel, http_status_code: int):
        super().__init__(message)
        self.errors = api_output.errors or []
        self.http_status_code = http_status_code
