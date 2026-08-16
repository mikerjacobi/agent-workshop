"""``mothership messages`` — send and search messages."""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

from mothership_cli.client import ApiError, get_client
from mothership_cli.config import ensure_sandbox, is_json_output, resolve_agent_id, resolve_external_id
from mothership_cli.client_models.common import DatetimeFilter, KeywordFilter
from mothership_cli.models.message import MessageType, SearchAgentMessagesInput
from mothership_cli.models.thread import SearchAgentThreadsInput, ThreadStatus
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import CliApp, CliPositionalArg, CliSubCommand

DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
RESET = "\033[0m"
CLEAR_LINE = "\033[2K\r"

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]



class MessagesSubmit(BaseModel):
    """Send a message to an agent via REST.

    Ensures a sandbox is running, creates a thread if needed, submits
    the message, and polls for the assistant response.
    """

    model_config = ConfigDict(extra="forbid")

    message: CliPositionalArg[str] = Field(description="Message content to send")
    external_id: str | None = Field(default=None, description="Override external_id")
    agent_id: str | None = Field(default=None, description="Agent to use (falls back to profile default)")
    agent_version_id: str | None = Field(default=None, description="Pin to a specific agent version")
    model: str | None = Field(default=None, description="LiteLLM model override")
    thread_id: str | None = Field(default=None, description="Existing thread to continue (creates new if omitted)")
    sandbox_param: list[str] = Field(default_factory=list, description="Sandbox parameter override (KEY=VALUE, repeatable)")
    force_sandbox_recreate: bool = Field(default=False, description="Stop and recreate the sandbox even if one already exists")
    fire_and_forget: bool = Field(default=False, description="Return immediately after submission without waiting for response")
    poll_interval: float = Field(default=0.5, description="Seconds between poll attempts")
    timeout: float = Field(default=300.0, description="Max seconds to wait for response")

    def cli_cmd(self) -> None:
        eid = resolve_external_id(self.external_id)
        api = get_client()

        agent_id = resolve_agent_id(self.agent_id)

        sandbox, _ = ensure_sandbox(
            api,
            agent_id=agent_id,
            external_id=eid,
            model=self.model,
            agent_version_id=self.agent_version_id,
            sandbox_param=self.sandbox_param,
            force_recreate=self.force_sandbox_recreate,
            timeout=self.timeout,
            poll_interval=self.poll_interval,
        )

        # Step 2: resolve or create thread
        if self.thread_id:
            thread_id = self.thread_id
        else:
            sys.stderr.write(f"{CYAN}Creating thread...{RESET}\n")
            try:
                thread = api.create_thread(eid, agent_id, model=self.model)
            except ApiError as e:
                raise SystemExit(str(e)) from e
            thread_id = thread.thread_id
            sys.stderr.write(f"{CYAN}Thread {thread_id} created{RESET}\n")

        # Step 3: send message
        poll_since = datetime.now(UTC)
        try:
            result = api.send_message(thread_id, self.message)
        except ApiError as e:
            raise SystemExit(str(e)) from e

        if self.fire_and_forget or is_json_output():
            if is_json_output():
                print(result.model_dump_json(indent=2))
            else:
                print(f"thread_id: {result.thread_id}")
                print(f"message_id: {result.message_id}")
            if self.fire_and_forget:
                return

        sys.stderr.write(f"{CYAN}Thread {result.thread_id} | Message {result.message_id}{RESET}\n")

        # Step 4: poll for response
        deadline = time.time() + self.timeout
        spinner_idx = 0
        last_ephemeral_len = 0

        while time.time() < deadline:
            try:
                threads, _ = api.search_threads(SearchAgentThreadsInput(
                    thread_id=KeywordFilter(eq=thread_id),
                    messages=SearchAgentMessagesInput(updated_at=DatetimeFilter(gte=poll_since)),
                    limit=1,
                ))
                polled = threads[0] if threads else None
                status = polled.status if polled else None
                msgs = (polled.messages or []) if polled else []
            except ApiError:
                status = None
                msgs = []

            ephemerals = [m for m in msgs if m.message_type == MessageType.EPHEMERAL]
            if ephemerals:
                text = ephemerals[-1].content
                new_chunk = text[last_ephemeral_len:]
                if new_chunk:
                    if last_ephemeral_len == 0:
                        sys.stderr.write(CLEAR_LINE)
                    sys.stdout.write(new_chunk)
                    sys.stdout.flush()
                    last_ephemeral_len = len(text)

            if status == ThreadStatus.ACTIVE:
                if last_ephemeral_len:
                    sys.stderr.write("\n")
                sys.stderr.write(CLEAR_LINE)
                sys.stderr.flush()

                assistants = [m for m in msgs if m.message_type == MessageType.ASSISTANT]
                if not assistants:
                    time.sleep(self.poll_interval)
                    try:
                        all_msgs, _ = api.search_messages(SearchAgentMessagesInput(
                            thread_id=KeywordFilter(eq=thread_id),
                            message_type=KeywordFilter(eq=MessageType.ASSISTANT),
                        ))
                        assistants = list(all_msgs)
                    except ApiError:
                        pass

                if not assistants:
                    sys.stderr.write("No assistant response found.\n")
                    raise SystemExit(1)

                response_text = assistants[-1].content
                if is_json_output():
                    print(json.dumps({"thread_id": thread_id, "response": response_text}, indent=2))
                elif last_ephemeral_len:
                    remainder = response_text[last_ephemeral_len:]
                    if remainder:
                        sys.stdout.write(remainder)
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                else:
                    print(response_text)
                return

            if not ephemerals:
                frame = SPINNER_FRAMES[spinner_idx % len(SPINNER_FRAMES)]
                sys.stderr.write(f"{CLEAR_LINE}{DIM}{frame} Waiting for response...{RESET}")
                sys.stderr.flush()

            spinner_idx += 1
            time.sleep(self.poll_interval)

        sys.stderr.write(f"\n{BOLD}Timed out after {self.timeout}s{RESET}\n")
        raise SystemExit(1)


class MessagesSearch(BaseModel):
    """Search messages."""

    model_config = ConfigDict(extra="forbid")

    thread_id: str | None = Field(default=None, description="Filter by thread")
    message_type: str | None = Field(default=None, description="Filter by type (user, assistant)")
    external_id: str | None = Field(default=None, description="Filter by owner")
    limit: int = Field(default=20, description="Max results")

    def cli_cmd(self) -> None:
        client = get_client()
        query = SearchAgentMessagesInput()
        if self.thread_id:
            query.thread_id = KeywordFilter(eq=self.thread_id)
        if self.message_type:
            query.message_type = KeywordFilter(eq=MessageType(self.message_type))
        if self.external_id:
            query.external_id = KeywordFilter(eq=self.external_id)
        if self.limit != 20:
            query.limit = self.limit
        try:
            if is_json_output():
                data = client._search(client._scoped("messages", "/search"), query)
                print(json.dumps(data, indent=2, default=str))
                return
            msgs, total = client.search_messages(query)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        if not msgs:
            print("No messages found.")
            return
        for m in msgs:
            ts = str(m.created_at or "")[:19]
            print(f"[{ts}] {m.message_type}: {m.content[:200]}")
        print(f"\n{len(msgs)} of {total} result(s)")


class MessagesRegenerate(BaseModel):
    """Regenerate an assistant message in-place.

    Clones the thread up to the target, sends the preceding user
    message, waits for a fresh agent response, and patches the
    original message with the result.
    """

    model_config = ConfigDict(extra="forbid")

    message_id: CliPositionalArg[str] = Field(description="ID of the assistant message to regenerate")

    def cli_cmd(self) -> None:
        api = get_client()
        sys.stderr.write(f"{CYAN}Regenerating message {self.message_id}...{RESET}\n")
        try:
            updated = api.regenerate_message(self.message_id)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        if is_json_output():
            print(json.dumps(updated.model_dump(mode="json"), indent=2, default=str))
        else:
            sys.stderr.write(f"{CYAN}Regeneration complete{RESET}\n")
            print(updated.content)


class MessagesCmd(BaseModel):
    """Send, search, and regenerate messages."""

    submit: CliSubCommand[MessagesSubmit]
    search: CliSubCommand[MessagesSearch]
    regenerate: CliSubCommand[MessagesRegenerate]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)
