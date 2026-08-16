"""``mothership threads`` — browse and copy conversation threads."""

import json

from mothership_cli.client import ApiError, get_client
from mothership_cli.config import is_json_output
from mothership_cli.client_models.common import KeywordFilter, SortDirection
from mothership_cli.models.message import MessageSortBy, MessageType, SearchAgentMessagesInput
from mothership_cli.models.thread import AgentThread, SearchAgentThreadsInput, ThreadStatus, UpdateAgentThreadInput
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import CliApp, CliPositionalArg, CliSubCommand


def _print_threads(threads: list[AgentThread], total: int) -> None:
    if not threads:
        print("No threads found.")
        return
    header = f"{'THREAD_ID':<38} {'EXTERNAL_ID':<20} {'STATUS':<12} {'MSGS':<6} {'TITLE':<30} {'UPDATED_AT'}"
    print(header)
    print("─" * len(header))
    for t in threads:
        title = (t.title or "—")[:30]
        updated = str(t.updated_at or "")[:19]
        print(f"{t.thread_id:<38} {t.external_id:<20} {t.status:<12} {t.message_count:<6} {title:<30} {updated}")
    print(f"\n{len(threads)} of {total} result(s)")


class ThreadsSearch(BaseModel):
    """Search threads."""

    model_config = ConfigDict(extra="forbid")

    external_id: str | None = Field(default=None, description="Filter by owner")
    thread_id: str | None = Field(default=None, description="Filter by thread ID")
    status: str | None = Field(default=None, description="Filter by status (active, inactive, etc.)")
    limit: int = Field(default=20, description="Max results")
    msg_type: str | None = Field(default=None, description="Filter messages by type (user, assistant, ephemeral)")
    msg_thread_id: str | None = Field(default=None, description="Fetch messages only for this thread ID")
    msg_sort_by: str | None = Field(default=None, description=f"Sort messages by ({', '.join(MessageSortBy)})")
    msg_sort_direction: str | None = Field(default=None, description="Sort direction for messages (asc, desc)")
    msg_limit_per_thread: int | None = Field(default=None, description="Max messages per thread (default: 100)")
    msg_limit_global: int | None = Field(default=None, description="Global message budget across all threads (default: 100, max: 1000)")

    def cli_cmd(self) -> None:
        client = get_client()
        query = SearchAgentThreadsInput(limit=self.limit)
        if self.external_id:
            query.external_id = KeywordFilter(eq=self.external_id)
        if self.thread_id:
            query.thread_id = KeywordFilter(eq=self.thread_id)
        if self.status:
            query.status = KeywordFilter(eq=ThreadStatus(self.status))

        has_msg_opts = any([self.msg_type, self.msg_thread_id, self.msg_sort_by,
                           self.msg_sort_direction, self.msg_limit_per_thread, self.msg_limit_global])
        if has_msg_opts:
            msg_input = SearchAgentMessagesInput()
            if self.msg_type:
                msg_input.message_type = KeywordFilter(eq=MessageType(self.msg_type))
            if self.msg_thread_id:
                msg_input.thread_id = KeywordFilter(eq=self.msg_thread_id)
            if self.msg_sort_by:
                msg_input.sort_by = MessageSortBy(self.msg_sort_by)
            if self.msg_sort_direction:
                msg_input.sort_direction = SortDirection(self.msg_sort_direction)
            if self.msg_limit_per_thread:
                msg_input.limit_per_thread = self.msg_limit_per_thread
            if self.msg_limit_global:
                msg_input.limit = self.msg_limit_global
            query.messages = msg_input

        try:
            if is_json_output():
                data = client._search(client._scoped("threads", "/search"), query)
                print(json.dumps(data, indent=2, default=str))
                return
            threads, total = client.search_threads(query)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        _print_threads(threads, total)


class ThreadsCopy(BaseModel):
    """Copy a thread's messages into a new inactive thread under a different external_id."""

    model_config = ConfigDict(extra="forbid")

    thread_id: CliPositionalArg[str] = Field(description="Source thread ID to copy")
    external_id: str = Field(description="Target external_id that will own the copy")
    title: str | None = Field(default=None, description="Override the title (defaults to source title)")

    def cli_cmd(self) -> None:
        client = get_client()
        try:
            thread = client.copy_thread(self.thread_id, self.external_id, title=self.title)
        except ApiError as e:
            raise SystemExit(str(e)) from e

        print(json.dumps(thread.model_dump(mode="json"), indent=2, default=str))


class ThreadsUpdate(BaseModel):
    """Update a thread's mutable fields."""

    model_config = ConfigDict(extra="forbid")

    thread_id: CliPositionalArg[str] = Field(description="Thread to update")
    title: str | None = Field(default=None, description="Thread title")
    owner_name: str | None = Field(default=None, description="Display name of the thread owner")

    def cli_cmd(self) -> None:
        client = get_client()
        patch = self.model_dump(exclude={"thread_id"}, exclude_none=True)
        if not patch:
            raise SystemExit("Nothing to update. Pass at least one flag.")
        update = UpdateAgentThreadInput(thread_id=self.thread_id, **patch)
        try:
            thread = client.update_thread(update)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        print(json.dumps(thread.model_dump(mode="json"), indent=2, default=str))


class ThreadsCmd(BaseModel):
    """Browse, copy, and update conversation threads."""

    search: CliSubCommand[ThreadsSearch]
    copy_: CliSubCommand[ThreadsCopy] = Field(alias="copy")
    update: CliSubCommand[ThreadsUpdate]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)
