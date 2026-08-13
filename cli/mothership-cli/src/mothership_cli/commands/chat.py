"""``mothership chat`` — interactive or one-shot agent conversation."""

from __future__ import annotations

import asyncio
import json
import signal
import sys
import time
import typing as _t
import uuid

from mothership_cli.client import ApiError, MothershipClient, MothershipWS, get_client
from mothership_cli.config import ensure_sandbox, is_json_output, resolve_agent_id, resolve_external_id, resolve_ws_url
from mothership_client.models.sandbox import SandboxState
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import CliPositionalArg

# ANSI helpers
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
CLEAR_LINE = "\033[2K\r"

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class ChatCmd(BaseModel):
    """Chat with an agent via WebSocket streaming.

    Provisions a sandbox, opens a thread, connects via ticket-auth WS,
    and streams responses.

    TUI mode (default): interactive back-and-forth.
    One-shot (--print): send a single message, print the response, exit.

    Verbosity: -v boot status, -vv thinking/tools, -vvv raw frames.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: str | None = Field(default=None, description="Agent catalog entry to chat with (falls back to profile default)")
    message: CliPositionalArg[str | None] = Field(default=None, description="Message to send (required with --print)")
    external_id: str | None = Field(default=None, description="Override external_id (falls back to profile default)")
    model: str | None = Field(default=None, description="LiteLLM model override")
    agent_version_id: str | None = Field(default=None, description="Pin to a specific agent version")
    sandbox_id: str | None = Field(default=None, description="Reconnect to an existing sandbox instead of creating one")
    thread_id: str | None = Field(default=None, description="Resume an existing thread instead of creating a new one")
    sandbox_param: list[str] = Field(default_factory=list, description="Sandbox parameter override (KEY=VALUE, repeatable)")
    force_sandbox_recreate: bool = Field(default=False, description="Stop and recreate the sandbox even if one already exists")
    print_mode: bool = Field(default=False, alias="print", description="One-shot: send message, print response, exit")
    verbose: int = Field(default=0, alias="v", description="Verbosity: -v status, -vv thinking/tools, -vvv raw frames")

    def cli_cmd(self) -> None:
        if self.print_mode and not self.message:
            raise SystemExit("--print requires a message argument.")
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            sys.stderr.write(f"\n{CYAN}Disconnected.{RESET}\n")
            raise SystemExit(0) from None
        except ConnectionError as e:
            raise SystemExit(str(e)) from None

    def _log(self, level: int, text: str, *, color: str = DIM, stream: str = "err") -> None:
        if self.verbose < level:
            return
        out = sys.stderr if stream == "err" else sys.stdout
        out.write(f"{color}{text}{RESET}\n")
        out.flush()

    def _wait_for_sandbox_sync(self, client: MothershipClient, sandbox_id: str, timeout: float = 120.0) -> None:
        """Synchronous poll until sandbox is running."""
        deadline = time.time() + timeout
        spinner_idx = 0
        while time.time() < deadline:
            try:
                sandbox = client.get_sandbox(sandbox_id)
            except (ApiError, ConnectionError):
                time.sleep(0.5)
                continue
            if sandbox.state == SandboxState.RUNNING:
                sys.stderr.write(CLEAR_LINE)
                sys.stderr.flush()
                return
            if sandbox.state in (SandboxState.STOPPED, SandboxState.STOPPING):
                raise SystemExit(f"Sandbox {sandbox_id} is {sandbox.state}")
            frame = SPINNER_FRAMES[spinner_idx % len(SPINNER_FRAMES)]
            sys.stderr.write(f"{CLEAR_LINE}{DIM}{frame} Waiting for sandbox ({sandbox.state})...{RESET}")
            sys.stderr.flush()
            spinner_idx += 1
            time.sleep(0.5)
        raise SystemExit(f"Timed out waiting for sandbox {sandbox_id}")

    async def _run(self) -> None:
        eid = resolve_external_id(self.external_id)
        client = get_client()
        ws_base = resolve_ws_url()
        agent_id = resolve_agent_id(self.agent_id)

        # Step 1: ensure sandbox + get ticket
        if self.sandbox_id:
            sandbox_id = self.sandbox_id
            self._log(1, f"Using existing sandbox {sandbox_id}", color=CYAN)
            self._wait_for_sandbox_sync(client, sandbox_id)
            ticket = client.issue_ticket(sandbox_id, eid)
        else:
            sandbox, maybe_ticket = ensure_sandbox(
                client,
                agent_id=agent_id,
                external_id=eid,
                model=self.model,
                agent_version_id=self.agent_version_id,
                sandbox_param=self.sandbox_param,
                force_recreate=self.force_sandbox_recreate,
                issue_ticket=True,
                log=lambda msg: self._log(1, msg, color=CYAN),
            )
            sandbox_id = sandbox.sandbox_id
            ticket = maybe_ticket or client.issue_ticket(sandbox_id, eid)

        # Step 2: resolve or create thread
        if self.thread_id:
            thread_id = self.thread_id
        else:
            try:
                thread = client.create_thread(eid, agent_id, model=self.model)
                thread_id = thread.thread_id
            except ApiError as e:
                raise SystemExit(str(e)) from e

        self._log(1, f"Thread {thread_id}", color=CYAN)

        # Step 3: connect WS with ticket
        ws = MothershipWS(ws_base, ticket.ticket_val)
        try:
            await ws.connect()
        except Exception as e:
            raise SystemExit(f"WebSocket connect failed: {e}") from e

        try:
            try:
                await asyncio.wait_for(self._wait_for_ready(ws), timeout=60)
            except TimeoutError:
                raise SystemExit("Timed out waiting for coordinator ready (60s)") from None

            await ws.send({
                "type": "thread.resume",
                "thread_id": thread_id,
                "highest_seq": 0,
                "in_flight_client_msg_ids": [],
            })
            try:
                await asyncio.wait_for(self._wait_for_thread(ws, thread_id), timeout=60)
            except TimeoutError:
                raise SystemExit("Timed out waiting for thread bind (60s)") from None

            sys.stderr.write(f"{CYAN}Sandbox {sandbox_id} | Thread {thread_id}{RESET}\n")

            if self.print_mode:
                assert self.message is not None
                await self._one_shot(ws, thread_id, self.message)
            else:
                sys.stderr.write(f"{CYAN}Type a message and press Enter. Ctrl-C to exit.\n{RESET}\n")
                await self._interactive(ws, thread_id, initial_message=self.message or None)
        finally:
            await ws.close()

    async def _wait_for_ready(self, ws: MothershipWS) -> None:
        while True:
            msg = await ws.recv()
            self._log(3, f"< {json.dumps(msg, default=str)}")
            t = msg.get("type") or msg.get("kind")

            if t == "coordinator.ready":
                return
            elif t == "coordinator.status":
                self._log(1, msg.get("message", "Starting..."), color=CYAN)
            elif t == "coordinator.error":
                raise SystemExit(f"Coordinator error: {msg.get('message')}")
            elif t in ("delta", "final"):
                text = msg.get("text", "")
                if text:
                    self._log(1, text)

    async def _wait_for_thread(self, ws: MothershipWS, thread_id: str) -> None:
        while True:
            msg = await ws.recv()
            self._log(3, f"< {json.dumps(msg, default=str)}")
            t = msg.get("type") or msg.get("kind")

            if t == "coordinator.thread":
                action = msg.get("action", "bound")
                self._log(1, f"Thread {thread_id} {action}", color=CYAN)
                return
            elif t == "coordinator.history":
                if not self.print_mode:
                    for m in msg.get("messages", []):
                        role = m.get("role", "?")
                        content = m.get("content", "")
                        if role == "user":
                            print(f"{BOLD}> {content}{RESET}")
                        else:
                            print(content)
                    print()
            elif t == "coordinator.error":
                raise SystemExit(f"Coordinator error: {msg.get('message')}")

    async def _one_shot(self, ws: MothershipWS, thread_id: str, message: str) -> None:
        client_msg_id = str(uuid.uuid4())
        await ws.send({"type": "chat", "message": message, "client_msg_id": client_msg_id, "thread_id": thread_id})

        final_text = None
        while True:
            msg = await ws.recv()
            self._log(3, f"< {json.dumps(msg, default=str)}")
            kind = msg.get("kind") or msg.get("type")

            if kind == "final":
                final_text = msg.get("text", "")
                break
            elif kind == "delta":
                pass
            elif kind == "thinking":
                self._log(2, msg.get("text", ""))
            elif kind == "tool_call":
                self._log(2, f"  ↳ {msg.get('tool', '')}({json.dumps(msg.get('args', {}))})", color=YELLOW)
            elif kind == "tool_result":
                output = msg.get("output", "")
                color = RED if msg.get("is_error") else DIM
                self._log(2, f"  ← {output[:200]}{'...' if len(output) > 200 else ''}", color=color)
            elif kind == "error":
                raise SystemExit(f"Agent error: {msg.get('message', '')}")
            elif kind == "coordinator.error":
                raise SystemExit(f"Coordinator error: {msg.get('message', '')}")

        if is_json_output():
            print(json.dumps({"thread_id": thread_id, "response": final_text}))
        else:
            print(final_text)

    async def _interactive(self, ws: MothershipWS, thread_id: str, *, initial_message: str | None = None) -> None:
        loop = asyncio.get_event_loop()
        interrupted = asyncio.Event()

        def _on_sigint() -> None:
            interrupted.set()

        loop.add_signal_handler(signal.SIGINT, _on_sigint)

        try:
            first = True
            while True:
                if first and initial_message:
                    user_input = initial_message
                    sys.stdout.write(f"{BOLD}> {RESET}{user_input}\n")
                    sys.stdout.flush()
                    first = False
                else:
                    first = False
                    interrupted.clear()
                    input_task: asyncio.Task[str] = asyncio.ensure_future(loop.run_in_executor(None, lambda: input(f"{BOLD}> {RESET}")))
                    sigint_wait: asyncio.Task[bool] = asyncio.ensure_future(interrupted.wait())
                    done, _ = await asyncio.wait(
                        {input_task, sigint_wait},
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if interrupted.is_set():
                        input_task.cancel()
                        return

                    try:
                        user_input = input_task.result().strip()
                    except (EOFError, asyncio.CancelledError):
                        return
                    if not user_input:
                        continue

                client_msg_id = str(uuid.uuid4())
                await ws.send({"type": "chat", "message": user_input, "client_msg_id": client_msg_id, "thread_id": thread_id})

                interrupted.clear()
                stream_task = asyncio.ensure_future(self._stream_response(ws))
                sigint_task = asyncio.ensure_future(interrupted.wait())
                done, _ = await asyncio.wait([stream_task, sigint_task], return_when=asyncio.FIRST_COMPLETED)

                if interrupted.is_set() and not stream_task.done():
                    await ws.send({"type": "thread.cancel", "thread_id": thread_id})
                    self._log(1, "Interrupted.", color=CYAN)
                    try:
                        await asyncio.wait_for(stream_task, timeout=5.0)
                    except (TimeoutError, asyncio.CancelledError):
                        stream_task.cancel()
                elif stream_task.done():
                    sigint_task.cancel()
                    stream_task.result()
        finally:
            loop.remove_signal_handler(signal.SIGINT)

    async def _stream_response(self, ws: MothershipWS) -> None:
        spinner_active = True
        spinner_idx = 0

        async def _spin() -> None:
            nonlocal spinner_idx
            while spinner_active:
                frame = SPINNER_FRAMES[spinner_idx % len(SPINNER_FRAMES)]
                sys.stderr.write(f"{CLEAR_LINE}{DIM}{frame} Thinking...{RESET}")
                sys.stderr.flush()
                spinner_idx += 1
                await asyncio.sleep(0.1)

        spinner_task = asyncio.create_task(_spin())

        def _stop_spinner() -> None:
            nonlocal spinner_active
            if spinner_active:
                spinner_active = False
                sys.stderr.write(CLEAR_LINE)
                sys.stderr.flush()

        try:
            await self._stream_loop(ws, _stop_spinner)
        finally:
            _stop_spinner()
            if not spinner_task.done():
                spinner_task.cancel()

    async def _stream_loop(
        self,
        ws: MothershipWS,
        stop_spinner: _t.Callable[[], None],
    ) -> None:
        last_text_len = 0
        in_thinking = False

        while True:
            msg = await ws.recv()
            self._log(3, f"< {json.dumps(msg, default=str)}")
            kind = msg.get("kind") or msg.get("type")

            if kind == "delta":
                stop_spinner()
                text = msg.get("text", "")
                new_part = text[last_text_len:]
                if new_part:
                    if in_thinking:
                        sys.stdout.write(RESET)
                        in_thinking = False
                    sys.stdout.write(new_part)
                    sys.stdout.flush()
                last_text_len = len(text)

            elif kind == "final":
                stop_spinner()
                text = msg.get("text", "")
                new_part = text[last_text_len:]
                if new_part:
                    if in_thinking:
                        sys.stdout.write(RESET)
                    sys.stdout.write(new_part)
                sys.stdout.write("\n\n")
                sys.stdout.flush()
                return

            elif kind == "thinking":
                if self.verbose >= 2:
                    stop_spinner()
                    text = msg.get("text", "")
                    if text:
                        if not in_thinking:
                            sys.stderr.write(f"{DIM}")
                            in_thinking = True
                        sys.stderr.write(f"  {text}\n")
                        sys.stderr.flush()

            elif kind == "tool_call":
                stop_spinner()
                if self.verbose >= 2:
                    tool = msg.get("tool", "")
                    sys.stderr.write(f"{YELLOW}  ↳ {tool}({json.dumps(msg.get('args', {}), indent=None)}){RESET}\n")
                    sys.stderr.flush()

            elif kind == "tool_result":
                if self.verbose >= 2:
                    output = msg.get("output", "")
                    is_err = msg.get("is_error", False)
                    color = RED if is_err else DIM
                    preview = output[:200] + ("..." if len(output) > 200 else "")
                    sys.stderr.write(f"{color}  ← {preview}{RESET}\n")
                    sys.stderr.flush()

            elif kind == "approval_required":
                stop_spinner()
                tool = msg.get("tool", "")
                request_id = msg.get("request_id", "")
                sys.stderr.write(f"\n{YELLOW}Approval required: {tool}({json.dumps(msg.get('args', {}))}){RESET}\n")
                loop = asyncio.get_event_loop()
                try:
                    answer = await loop.run_in_executor(None, lambda: input(f"{BOLD}approve? [Y/n] {RESET}").strip().lower())
                except (EOFError, KeyboardInterrupt):
                    answer = "n"
                decision = "deny" if answer == "n" else "approve"
                await ws.send({"type": "approval", "request_id": request_id, "decision": decision})

            elif kind == "error":
                stop_spinner()
                sys.stderr.write(f"{RED}Error: {msg.get('message', '')}{RESET}\n")
                return

            elif kind == "coordinator.error":
                stop_spinner()
                sys.stderr.write(f"{RED}Coordinator error: {msg.get('message', '')}{RESET}\n")
                return
