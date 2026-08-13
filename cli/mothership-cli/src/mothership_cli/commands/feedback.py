"""``mothership feedback`` — search and submit feedback."""

import json

from mothership_cli.client import ApiError, get_client
from mothership_cli.config import is_json_output
from mothership_client.client_models.common import KeywordFilter
from mothership_client.models.feedback import AgentFeedback, FeedbackType, SearchAgentFeedbackPaginatedInput
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import CliApp, CliSubCommand


def _print_feedback(records: list[AgentFeedback], total: int) -> None:
    if not records:
        print("No feedback found.")
        return
    header = f"{'MESSAGE_ID':<38} {'EXTERNAL_ID':<28} {'TYPE':<12} {'COMMENT':<40} {'CREATED_AT'}"
    print(header)
    print("─" * len(header))
    for r in records:
        comment = (r.comment or "—")[:40]
        ftype = str(r.feedback_type or "—")
        created = str(r.created_at or "")[:19]
        print(f"{r.message_id:<38} {r.external_id:<28} {ftype:<12} {comment:<40} {created}")
    print(f"\n{len(records)} of {total} result(s)")


class FeedbackSearch(BaseModel):
    """Search feedback."""

    model_config = ConfigDict(extra="forbid")

    message_id: str | None = Field(default=None, description="Filter by message ID")
    external_id: str | None = Field(default=None, description="Filter by user")
    feedback_type: str | None = Field(default=None, description="Filter by type (thumbs_up, thumbs_down)")
    limit: int = Field(default=100, description="Max results")
    offset: int = Field(default=0, description="Offset for pagination")

    def cli_cmd(self) -> None:
        client = get_client()
        query = SearchAgentFeedbackPaginatedInput(limit=self.limit, offset=self.offset)
        if self.message_id:
            query.message_id = KeywordFilter(eq=self.message_id)
        if self.external_id:
            query.external_id = KeywordFilter(eq=self.external_id)
        if self.feedback_type:
            query.feedback_type = KeywordFilter(eq=FeedbackType(self.feedback_type))

        try:
            if is_json_output():
                data = client._search(client._scoped("feedback", "/search"), query)
                print(json.dumps(data, indent=2, default=str))
                return
            records, total = client.search_feedback(query)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        _print_feedback(records, total)


class FeedbackCmd(BaseModel):
    """Search user feedback (thumbs up/down)."""

    search: CliSubCommand[FeedbackSearch]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)
