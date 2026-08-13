"""Synchronous REST client for the mothership API — the one in-tree client,
used by the CLI (via mothership.cli.client, which adds profiles and tracing)
and by the evaluator's executor."""

from __future__ import annotations

import json
import sys
import textwrap
import time
import typing as _t
from collections.abc import Callable
from typing import TypeVar
from urllib.parse import quote

import httpx
import websockets
import websockets.asyncio.client
from mothership_client.client_models.common import KeywordFilter
from mothership_client.models.agent_catalog import AgentCatalogEntry, CreateAgentInput, SearchAgentCatalogInput, UpdateAgentInput
from mothership_client.models.agent_version import AgentVersion, CreateAgentVersionInput, SearchAgentVersionsInput, UpdateAgentVersionInput
from mothership_client.models.coordinator import RestSendMessageInput, SendMessageOutput
from mothership_client.models.feedback import AgentFeedback, SearchAgentFeedbackPaginatedInput
from mothership_client.models.message import AgentMessage, SearchAgentMessagesInput
from mothership_client.models.org import DEFAULT_ORG_ID
from mothership_client.models.sandbox import CreateSandboxInput, CreateSandboxOutput, Sandbox, SearchSandboxesInput
from mothership_client.models.thread import AgentThread, CopyThreadInput, CreateAgentThreadInput, SearchAgentThreadsInput, UpdateAgentThreadInput
from mothership_client.models.ticket import CreateTicketInput, Ticket
from pydantic import BaseModel

REQUEST_TIMEOUT = 30.0

T = TypeVar("T", bound=BaseModel)

DIM = "\033[2m"
RESET = "\033[0m"


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"HTTP {status}: {message}")


# Resource routers whose paths carry the tenancy boundary: the server mounts
# these ONLY under /api/orgs/{org_id} (see _SCOPED_ROUTE_MODULES in
# mothership.api.app). Every other group — agent-versions, users, models,
# containers, pods, config, me — is flat. Getting this set wrong is a 404, so it
# is stated once here rather than inferred per call site.
SCOPED_RESOURCES = frozenset({"agents", "sandboxes", "threads", "messages", "feedback", "files", "attachments", "evals"})


# Verbose request tracing is a CLI concern; the CLI installs its hook at
# import time (see mothership.cli.client) so this module never imports CLI
# config.
def _never_verbose() -> bool:
    return False


_VERBOSE_HOOK: Callable[[], bool] = _never_verbose


def set_verbose_hook(hook: Callable[[], bool]) -> None:
    global _VERBOSE_HOOK
    _VERBOSE_HOOK = hook


def _write_trace(line: str) -> None:
    sys.stderr.write(f"{DIM}{line}{RESET}\n")


class MothershipClient:
    """HTTP client for the mothership REST API.

    Identity is the ``X-External-Id`` header. With no IdP configured
    (``MOTHERSHIP_AUTH_ISSUER`` unset) the server's NullAdapter takes that at
    face value and JIT-provisions the user into the default org — which is how
    every deployment we run today is set up. It is an assertion, not a
    credential; ``api_key`` sends a real one when there is one to send, since
    the server's ApiKeyAdapter is active regardless of IdP config.

    ``org`` is the tenancy path segment for scoped resources, defaulting to the
    shared ``default`` org that every caller is enrolled into — so a single-org
    deployment needs no org configuration at all.
    """

    def __init__(
        self,
        base_url: str,
        *,
        org: str | None = None,
        external_id: str | None = None,
        api_key: str | None = None,
    ):
        self._base = base_url.rstrip("/")
        self._org = org
        self._external_id = external_id
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._external_id:
            headers["X-External-Id"] = self._external_id
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _scoped(self, resource: str, subpath: str = "") -> str:
        """Path for a tenancy-scoped resource, under its org."""
        if resource not in SCOPED_RESOURCES:
            raise ValueError(f"{resource} is not an org-scoped resource; use a literal /api/ path")
        org = self._org or DEFAULT_ORG_ID
        return f"/api/orgs/{quote(org, safe='')}/{resource}{subpath}"

    def _trace_request(self, method: str, url: str, body: dict | None, params: dict | None) -> None:
        """Write the outgoing request to stderr, with the bearer token redacted."""
        _write_trace(f"→ {method} {url}")
        if params:
            _write_trace(f"  params: {json.dumps(params)}")
        for name, value in self._headers().items():
            _write_trace(f"  {name}: {'Bearer ***redacted***' if name == 'Authorization' else value}")
        if body is not None:
            _write_trace(textwrap.indent(json.dumps(body, indent=2), "  "))

    def _trace_transport_error(self, exc: Exception) -> None:
        """Close a traced request that never got a response, so a connect
        failure does not read as the CLI hanging after ``→``."""
        _write_trace(f"← {type(exc).__name__}: {exc}")

    def _trace_response(self, resp: httpx.Response) -> None:
        # A response that did not come from a full client send has no .elapsed
        # and raises on access. Tracing is a debugging aid; it must not be the
        # thing that breaks a request that would otherwise have worked.
        try:
            timing = f" ({resp.elapsed.total_seconds():.3f}s)"
        except RuntimeError:
            timing = ""
        _write_trace(f"← {resp.status_code} {resp.reason_phrase}{timing}")
        if not resp.content:
            return
        try:
            body = json.dumps(resp.json(), indent=2)
        except ValueError:
            body = resp.text
        _write_trace(textwrap.indent(body, "  "))

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        retries: int = 0,
        retry_delay: float = 2.0,
        retry_on_status: set[int] | None = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> dict:

        url = f"{self._base}{path}"
        verbose = _VERBOSE_HOOK()
        last_err: Exception | None = None
        for attempt in range(1 + retries):
            if verbose:
                self._trace_request(method, url, json, params)
            try:
                resp = httpx.request(method, url, json=json, params=params, timeout=timeout, headers=self._headers())
            except httpx.ConnectError as e:
                last_err = e
                if verbose:
                    self._trace_transport_error(e)
                if attempt < retries:
                    time.sleep(retry_delay)
                    continue
                raise ConnectionError(f"cannot reach mothership API at {self._base} — is it running?") from e
            except httpx.ReadError as e:
                last_err = e
                if verbose:
                    self._trace_transport_error(e)
                if attempt < retries:
                    time.sleep(retry_delay)
                    continue
                raise ConnectionError(f"connection to {self._base} was reset — server may be restarting") from e
            if verbose:
                self._trace_response(resp)
            if not resp.is_success:
                if retry_on_status and resp.status_code in retry_on_status and attempt < retries:
                    time.sleep(retry_delay)
                    continue
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                errors = body.get("errors") or []
                msg = errors[0]["message"] if errors else resp.text[:200]
                raise ApiError(resp.status_code, msg)
            if resp.status_code == 204:
                return {}
            return resp.json()
        raise last_err  # type: ignore[misc]

    def _request_bytes(self, method: str, path: str, *, json: dict | None = None, timeout: float = REQUEST_TIMEOUT) -> bytes:
        """Like _request but for binary responses (e.g. task export zips)."""
        resp = httpx.request(method, f"{self._base}{path}", json=json, timeout=timeout, headers=self._headers())
        if not resp.is_success:
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            errors = body.get("errors") or []
            msg = errors[0]["message"] if errors else resp.text[:200]
            raise ApiError(resp.status_code, msg)
        return resp.content

    def _unwrap_raw(self, data: dict) -> tuple[list[dict], int]:
        records = data.get("records") or []
        total = (data.get("meta") or {}).get("total", len(records))
        return records, total

    def _unwrap_typed(self, data: dict, model: type[T]) -> tuple[list[T], int]:
        raw_records, total = self._unwrap_raw(data)
        return [model.model_validate(r) for r in raw_records], total

    def _search(self, path: str, query: BaseModel) -> dict:
        """POST a search and return the raw API response (records + meta)."""
        return self._request("POST", path, json=query.model_dump(mode="json", exclude_none=True, exclude_unset=True))

    # ── Agents ────────────────────────────────────────────────

    def search_agents(self, query: SearchAgentCatalogInput) -> tuple[list[AgentCatalogEntry], int]:
        data = self._request("POST", self._scoped("agents", "/search"), json=query.model_dump(mode="json", exclude_none=True))
        records, total = self._unwrap_typed(data, AgentCatalogEntry)
        return records, total

    def create_agent(self, request: CreateAgentInput) -> AgentCatalogEntry:
        # CreateAgentInput's validator expands the ``image`` shorthand into
        # ``versions`` locally, so a naive dump carries both — and the server
        # rejects "either image or versions, not both" with a 400. Post
        # validation ``versions`` is always populated (see the model), so send
        # that and drop the shorthand it came from.
        body = request.model_dump(mode="json", exclude_none=True, exclude={"image", "version"})
        data = self._request("POST", self._scoped("agents", "/"), json=body)
        records, _ = self._unwrap_typed(data, AgentCatalogEntry)
        return records[0]

    def update_agent(self, request: UpdateAgentInput) -> AgentCatalogEntry:
        data = self._request("PATCH", self._scoped("agents", f"/{request.agent_id}"), json=request.model_dump(exclude_none=True, exclude={"agent_id"}))
        records, _ = self._unwrap_typed(data, AgentCatalogEntry)
        return records[0]

    def delete_agent(self, agent_id: str) -> AgentCatalogEntry:
        data = self._request("DELETE", self._scoped("agents", f"/{agent_id}"))
        records, _ = self._unwrap_typed(data, AgentCatalogEntry)
        return records[0]

    # ── Agent Versions ─────────────────────────────────────────

    def search_agent_versions(self, query: SearchAgentVersionsInput) -> tuple[list[AgentVersion], int]:
        data = self._request("POST", "/api/agent-versions/search", json=query.model_dump(mode="json", exclude_none=True, exclude_unset=True))
        return self._unwrap_typed(data, AgentVersion)

    def create_agent_version(self, request: CreateAgentVersionInput) -> AgentVersion:
        data = self._request("POST", "/api/agent-versions/", json=request.model_dump(mode="json", exclude_none=True))
        records, _ = self._unwrap_typed(data, AgentVersion)
        return records[0]

    def update_agent_version(self, request: UpdateAgentVersionInput) -> AgentVersion:
        data = self._request("PATCH", f"/api/agent-versions/{request.version_id}", json=request.model_dump(exclude_none=True, exclude={"version_id"}))
        records, _ = self._unwrap_typed(data, AgentVersion)
        return records[0]

    def delete_agent_version(self, version_id: str) -> AgentVersion:
        data = self._request("DELETE", f"/api/agent-versions/{version_id}")
        records, _ = self._unwrap_typed(data, AgentVersion)
        return records[0]

    # ── Sandboxes ──────────────────────────────────────────────

    def create_sandbox(self, request: CreateSandboxInput) -> tuple[Sandbox, Ticket | None]:
        """Find-or-create a sandbox. Returns (sandbox, ticket) where ticket
        is non-None only when ``request.issue_ticket`` is True."""
        data = self._request("POST", self._scoped("sandboxes", "/"), json=request.model_dump(mode="json", exclude_none=True))
        output = CreateSandboxOutput.model_validate(data)
        if not output.records:
            raise ApiError(500, "no sandbox returned")
        return output.records[0], output.ticket

    def get_sandbox(self, sandbox_id: str) -> Sandbox:
        data = self._request("GET", self._scoped("sandboxes", f"/{sandbox_id}"))
        records, _ = self._unwrap_typed(data, Sandbox)
        return records[0]

    def search_sandboxes(self, query: SearchSandboxesInput) -> tuple[list[Sandbox], int]:
        data = self._request("POST", self._scoped("sandboxes", "/search"), json=query.model_dump(mode="json", exclude_none=True))
        return self._unwrap_typed(data, Sandbox)

    def stop_sandbox(self, sandbox_id: str) -> dict:
        return self._request("POST", self._scoped("sandboxes", f"/{sandbox_id}/stop"))

    def issue_ticket(self, sandbox_id: str, external_id: str) -> Ticket:
        body = CreateTicketInput(external_id=external_id)
        data = self._request("POST", self._scoped("sandboxes", f"/{sandbox_id}/tickets"), json=body.model_dump(mode="json"))
        records, _ = self._unwrap_typed(data, Ticket)
        return records[0]

    # ── Threads ───────────────────────────────────────────────

    def create_thread(
        self, external_id: str, agent_id: str, *, model: str | None = None, title: str | None = None,
    ) -> AgentThread:
        body = CreateAgentThreadInput(external_id=external_id, agent_id=agent_id, model=model, title=title)
        data = self._request("POST", self._scoped("threads", "/"), json=body.model_dump(mode="json", exclude_none=True))
        records, _ = self._unwrap_typed(data, AgentThread)
        return records[0]

    def get_thread(self, thread_id: str) -> AgentThread:
        data = self._request("GET", self._scoped("threads", f"/{thread_id}"))
        records, _ = self._unwrap_typed(data, AgentThread)
        return records[0]

    def search_threads(self, query: SearchAgentThreadsInput) -> tuple[list[AgentThread], int]:
        data = self._request("POST", self._scoped("threads", "/search"), json=query.model_dump(mode="json", exclude_none=True, exclude_unset=True))
        return self._unwrap_typed(data, AgentThread)

    def copy_thread(self, thread_id: str, target_external_id: str, title: str | None = None) -> AgentThread:
        body = CopyThreadInput(target_external_id=target_external_id, title=title)
        data = self._request("POST", self._scoped("threads", f"/{thread_id}/copy"), json=body.model_dump(mode="json", exclude_none=True))
        records, _ = self._unwrap_typed(data, AgentThread)
        return records[0]

    def update_thread(self, request: UpdateAgentThreadInput) -> AgentThread:
        data = self._request("PATCH", self._scoped("threads", f"/{request.thread_id}"), json=request.model_dump(exclude_none=True, exclude={"thread_id"}))
        records, _ = self._unwrap_typed(data, AgentThread)
        return records[0]

    # ── Messages ──────────────────────────────────────────────

    def send_message(self, thread_id: str, content: str) -> SendMessageOutput:
        body = RestSendMessageInput(thread_id=thread_id, content=content)
        data = self._request(
            "POST", self._scoped("messages", "/"), json=body.model_dump(mode="json"),
            retries=3, retry_on_status={502, 503},
        )
        records, _ = self._unwrap_typed(data, SendMessageOutput)
        return records[0]

    def search_messages(self, query: SearchAgentMessagesInput) -> tuple[list[AgentMessage], int]:
        data = self._request("POST", self._scoped("messages", "/search"), json=query.model_dump(mode="json", exclude_none=True, exclude_unset=True))
        return self._unwrap_typed(data, AgentMessage)

    def regenerate_message(self, message_id: str, timeout: float = 600.0) -> AgentMessage:
        data = self._request(
            "POST", self._scoped("messages", f"/{message_id}/regenerate"),
            retries=0, timeout=timeout,
        )
        records, _ = self._unwrap_typed(data, AgentMessage)
        return records[0]

    # ── Feedback ─────────────────────────────────────────────

    def search_feedback(self, query: SearchAgentFeedbackPaginatedInput) -> tuple[list[AgentFeedback], int]:
        data = self._request("POST", self._scoped("feedback", "/search"), json=query.model_dump(mode="json", exclude_none=True, exclude_unset=True))
        return self._unwrap_typed(data, AgentFeedback)


def enforce_sandbox_limit(
    client: MothershipClient,
    limit: int | None,
    *,
    keep: tuple[str, str] | None = None,
    log: _t.Callable[[str], _t.Any] | None = None,
) -> None:
    """Stop oldest sandboxes so at most ``limit - 1`` are running before a new
    one is created.  No-op when *limit* is ``None`` or ``<= 0``.

    *keep* ``(external_id, agent_id)`` — if given, a sandbox matching
    this pair is excluded from eviction (it would be reused by the
    upcoming ``create_sandbox`` call).
    """
    if limit is None or limit <= 0:
        return
    sandboxes, _ = client.search_sandboxes(
        SearchSandboxesInput(state=KeywordFilter(eq="running")),
    )
    kept: Sandbox | None = None
    candidates: list[Sandbox] = []
    for s in sandboxes:
        if keep and not kept and (s.external_id, s.agent_id) == keep:
            kept = s
        else:
            candidates.append(s)
    total_after = len(candidates) + (1 if kept else 0)
    # +1 headroom for the sandbox we're about to create (or reuse)
    headroom = 0 if kept else 1
    excess = total_after - limit + headroom
    if excess <= 0:
        return
    oldest = sorted(candidates, key=lambda s: s.created_at or "")[:excess]
    for s in oldest:
        if log:
            log(f"Stopping sandbox {s.sandbox_id} ({s.external_id}) to stay within limit of {limit}")
        try:
            client.stop_sandbox(s.sandbox_id)
        except ApiError:
            pass



class MothershipWS:
    """Async WebSocket client for the coordinator (ticket-authenticated)."""

    def __init__(self, ws_url: str, ticket_val: str):
        base = ws_url.rstrip("/")
        self._url = f"{base}/ws?ticket={ticket_val}"
        self._ws: websockets.asyncio.client.ClientConnection | None = None

    async def connect(self) -> None:
        self._ws = await websockets.asyncio.client.connect(
            self._url, ping_interval=30, ping_timeout=120,
        )

    async def send(self, msg: dict) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(msg))

    async def recv(self) -> dict:
        assert self._ws is not None
        try:
            raw = await self._ws.recv()
        except websockets.exceptions.ConnectionClosed as e:
            raise ConnectionError(f"WebSocket connection lost: {e}") from e
        return json.loads(raw)

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None
