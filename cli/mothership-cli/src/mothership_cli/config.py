"""Profile configuration for the mothership CLI.

Profiles live at ``~/.mothership/config.json``. Each profile stores a
``base_url`` (the API root, e.g. ``http://localhost:5100``) and optional
defaults for external_id, agent_id, and coordinator WS URL.

Resolution order: ``--profile`` flag > ``MOTHERSHIP_BASE_URL`` env var
> config file ``default_profile``.
"""

from __future__ import annotations

import os
import sys
import time
import typing as _t
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from mothership_client.models.agent_catalog import AgentParameter
from mothership_client.models.org import DEFAULT_ORG_ID
from pydantic import BaseModel, Field

if _t.TYPE_CHECKING:
    from mothership_cli.client import MothershipClient
    from mothership_client.models.sandbox import Sandbox, Ticket

CONFIG_PATH = Path.home() / ".mothership" / "config.json"

ENV_PROFILE_NAME = "env"
ENV_BASE_URL = os.environ.get("MOTHERSHIP_BASE_URL")
ENV_EXTERNAL_ID = os.environ.get("MOTHERSHIP_EXTERNAL_ID")
ENV_ORG = os.environ.get("MOTHERSHIP_ORG")
# Read from the environment only, never written to the config file — a token on
# disk in a world-readable JSON is not something the CLI should create for you.
ENV_API_KEY = os.environ.get("MOTHERSHIP_API_KEY")


class ConfigError(Exception):
    """Raised when profile resolution or config loading fails."""


class Profile(BaseModel):
    base_url: str = Field(description="Mothership API root URL")
    ws_url: str | None = Field(default=None, description="Coordinator WebSocket URL (derived from base_url if omitted)")
    org: str | None = Field(default=None, description="Org id for tenancy-scoped resources; defaults to the shared 'default' org")
    default_external_id: str | None = Field(default=None, description="Default external_id for sandbox/thread ownership")
    default_agent_id: str | None = Field(default=None, description="Default agent catalog entry")
    max_local_sandboxes: int | None = Field(default=None, description="Max running sandboxes before FIFO eviction (local dev)")
    # Indirection, not the key: one shell can hold a key per env so `--profile` alone switches credentials.
    api_key_env: str | None = Field(default=None, description="Env var holding this profile's API key (convention: MOTHERSHIP_API_KEY_<ENV>)")


class MothershipConfig(BaseModel):
    default_profile: str | None = Field(default=None, description="Name of the active profile")
    profiles: dict[str, Profile] = Field(default_factory=dict, description="Named connection profiles")


def load_config() -> MothershipConfig:
    if CONFIG_PATH.exists():
        return MothershipConfig.model_validate_json(CONFIG_PATH.read_text())
    return MothershipConfig()


def save_config(config: MothershipConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config.model_dump_json(indent=2) + "\n")


def resolve_profile(profile_override: str | None = None) -> tuple[str, Profile]:
    """Resolve the active profile.

    Priority: ``--profile`` flag > ``MOTHERSHIP_BASE_URL`` env var >
    config file ``default_profile``.
    """
    config = load_config()

    if profile_override:
        profile = config.profiles.get(profile_override)
        if not profile:
            raise ConfigError(f"Profile '{profile_override}' not found. Run: mothership profiles set {profile_override} --base-url <url>")
        return profile_override, profile

    if ENV_BASE_URL:
        return ENV_PROFILE_NAME, Profile(base_url=ENV_BASE_URL, default_external_id=ENV_EXTERNAL_ID, org=ENV_ORG)

    name = config.default_profile
    if not name:
        raise ConfigError("No profile set. Run: mothership profiles set <name> --base-url <url>")
    profile = config.profiles.get(name)
    if not profile:
        raise ConfigError(f"Profile '{name}' not found in config. Run: mothership profiles set {name} --base-url <url>")
    return name, profile


_active_profile: tuple[str, Profile] | None = None
_json_output: bool = False


def set_active_profile(name: str, profile: Profile) -> None:
    global _active_profile
    _active_profile = (name, profile)


def get_active_profile() -> tuple[str, Profile]:
    if _active_profile is None:
        raise ConfigError("No active profile. Run: mothership profiles set <name> --base-url <url>")
    return _active_profile


def set_json_output(enabled: bool) -> None:
    global _json_output
    _json_output = enabled


def is_json_output() -> bool:
    return _json_output


_verbose: bool = False


def set_verbose(enabled: bool) -> None:
    global _verbose
    _verbose = enabled


def is_verbose() -> bool:
    return _verbose


# Set by main() from the global --org flag, ahead of profile/env resolution.
_org_override: str | None = None


def set_org_override(org: str | None) -> None:
    global _org_override
    _org_override = org


def resolve_org() -> str:
    """The org whose tenancy path scoped resources are addressed under.

    ``--org`` > profile ``org`` > ``MOTHERSHIP_ORG`` > the shared default org.
    Falling back to the default rather than erroring is what makes a single-org
    deployment need no configuration at all: every user is JIT-enrolled there on
    first request, so it is always a valid target.

    The fallback is the default org's *id*, not its ``default`` slug alias. Both
    address the same org on a current server, but the id is derived from the slug
    and has been stable since the org was introduced, whereas the alias is
    recent — so defaulting to the id lets this CLI work against a deployment that
    has not picked up the alias yet. Pass ``--org default`` to use the alias.
    """
    if _org_override:
        return _org_override
    try:
        _, profile = get_active_profile()
    except ConfigError:
        return ENV_ORG or DEFAULT_ORG_ID
    return profile.org or ENV_ORG or DEFAULT_ORG_ID


def resolve_identity() -> str | None:
    """The identity asserted on every request via ``X-External-Id``.

    Distinct from ``resolve_external_id``, which resolves the external_id a
    command needs as a *value* (a sandbox's owner) and raises when there isn't
    one. This is the transport header, and it returns None rather than raising:
    a request may carry an API key instead, which is its own identity, so an
    absent external_id is not on its own an error.
    """
    if _identity_override:
        return _identity_override
    try:
        _, profile = get_active_profile()
    except ConfigError:
        return ENV_EXTERNAL_ID
    return profile.default_external_id or ENV_EXTERNAL_ID


def resolve_api_key() -> str | None:
    """The API key for the active profile.

    A profile's ``api_key_env`` wins over the generic ``MOTHERSHIP_API_KEY``, and
    an unset one is an error rather than a fallback: falling back would send the
    key sourced for one env to whichever env the next ``--profile`` names, which
    is the whole failure this indirection exists to prevent.
    """
    try:
        name, profile = get_active_profile()
    except ConfigError:
        return ENV_API_KEY
    if not profile.api_key_env:
        return ENV_API_KEY
    key = os.environ.get(profile.api_key_env)
    if not key:
        raise ConfigError(f"Profile '{name}' reads its API key from ${profile.api_key_env}, which is unset. Export it, or unset api_key_env to fall back to $MOTHERSHIP_API_KEY.")
    return key


_identity_override: str | None = None


def set_identity_override(external_id: str | None) -> None:
    global _identity_override
    _identity_override = external_id


def resolve_agent_id(override: str | None = None) -> str:
    """Return the agent_id to use: explicit override > profile default > error."""
    if override:
        return override
    _, profile = get_active_profile()
    if profile.default_agent_id:
        return profile.default_agent_id
    raise ConfigError("No --agent-id provided and no default_agent_id on the profile.")


def resolve_external_id(override: str | None = None) -> str:
    """Return the external_id to use: explicit override > profile default > error."""
    if override:
        return override
    _, profile = get_active_profile()
    if profile.default_external_id:
        return profile.default_external_id
    raise ConfigError("No external_id provided and no default_external_id on the profile.")


def resolve_ws_url() -> str:
    """Return the coordinator WS base URL: profile ws_url > derived from base_url."""
    _, profile = get_active_profile()
    if profile.ws_url:
        return profile.ws_url
    parsed = urlparse(profile.base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    # Local dev: API on :5100, coordinator on :8080.
    # Deployed: same host, WS routed by path, keep port as-is.
    if parsed.hostname in ("localhost", "127.0.0.1") and parsed.port:
        netloc = f"{parsed.hostname}:8080"
    else:
        netloc = parsed.netloc
    return urlunparse((scheme, netloc, "", "", "", ""))


def resolve_sandbox_params(
    agent_params: list[AgentParameter],
    overrides: list[str],
    *,
    log: _t.Callable[[str], None] | None = None,
) -> dict[str, str]:
    """Build sandbox parameters by auto-injecting matching env vars and applying explicit overrides.

    For each parameter defined in the agent catalog, if the local environment
    has a matching env var set, it is auto-populated. Explicit ``--sandbox-param``
    overrides always win.
    """
    params: dict[str, str] = {}

    for p in agent_params:
        val = os.environ.get(p.key)
        if val:
            params[p.key] = val
            if log:
                log(f"  ↳ {p.key} (from environment)")

    for item in overrides:
        k, _, v = item.partition("=")
        params[k] = v

    return params


SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
DIM = "\033[2m"
CYAN = "\033[36m"
RESET = "\033[0m"
CLEAR_LINE = "\033[2K\r"


def ensure_sandbox(
    client: MothershipClient,
    *,
    agent_id: str,
    external_id: str,
    model: str | None = None,
    agent_version_id: str | None = None,
    sandbox_param: list[str] | None = None,
    force_recreate: bool = False,
    issue_ticket: bool = False,
    timeout: float = 120.0,
    poll_interval: float = 0.5,
    log: _t.Callable[[str], None] | None = None,
) -> tuple[Sandbox, Ticket | None]:
    """Resolve params, optionally force-recreate, create-or-reuse sandbox, wait for running.

    Returns the running sandbox and optionally a WS ticket.
    """
    from mothership_cli.client import ApiError, enforce_sandbox_limit
    from mothership_client.client_models.common import KeywordFilter
    from mothership_client.models.agent_catalog import SearchAgentCatalogInput
    from mothership_client.models.sandbox import CreateSandboxInput, SandboxState

    def _log(msg: str) -> None:
        if log:
            log(msg)
        else:
            sys.stderr.write(f"{CYAN}{msg}{RESET}\n")

    # Resolve parameters from agent catalog + env + overrides
    agents, _ = client.search_agents(SearchAgentCatalogInput(agent_id=KeywordFilter(eq=agent_id)))
    if not agents:
        raise SystemExit(f"Agent '{agent_id}' not found in catalog.")
    agent = agents[0]
    params = resolve_sandbox_params(agent.parameters, sandbox_param or [], log=_log)

    # Enforce sandbox limit
    _, profile = get_active_profile()
    enforce_sandbox_limit(
        client, profile.max_local_sandboxes,
        keep=(external_id, agent_id),
        log=_log,
    )

    # Force-recreate: stop existing sandbox first
    if force_recreate:
        try:
            existing, _ = client.create_sandbox(CreateSandboxInput(
                external_id=external_id, agent_id=agent_id,
                agent_version_id=agent_version_id, model=model,
                parameters=params, issue_ticket=False,
            ))
            if existing.state in (SandboxState.RUNNING, SandboxState.STARTING):
                _log(f"Stopping existing sandbox {existing.sandbox_id}...")
                client.stop_sandbox(existing.sandbox_id)
                time.sleep(2)
        except (ApiError, ConnectionError):
            pass

    _log(f"Ensuring sandbox for {agent_id}...")
    try:
        sandbox, ticket = client.create_sandbox(CreateSandboxInput(
            external_id=external_id, agent_id=agent_id,
            agent_version_id=agent_version_id, model=model,
            parameters=params, issue_ticket=issue_ticket,
        ))
    except (ApiError, ConnectionError) as e:
        raise SystemExit(str(e)) from e

    # Wait for sandbox to reach running state
    if sandbox.state != SandboxState.RUNNING:
        deadline = time.time() + timeout
        spinner_idx = 0
        while time.time() < deadline:
            try:
                sandbox = client.get_sandbox(sandbox.sandbox_id)
            except (ApiError, ConnectionError):
                time.sleep(poll_interval)
                continue
            if sandbox.state == SandboxState.RUNNING:
                sys.stderr.write(CLEAR_LINE)
                sys.stderr.flush()
                break
            if sandbox.state in (SandboxState.STOPPED, SandboxState.STOPPING):
                raise SystemExit(f"Sandbox {sandbox.sandbox_id} is {sandbox.state}")
            frame = SPINNER_FRAMES[spinner_idx % len(SPINNER_FRAMES)]
            sys.stderr.write(f"{CLEAR_LINE}{DIM}{frame} Waiting for sandbox ({sandbox.state})...{RESET}")
            sys.stderr.flush()
            spinner_idx += 1
            time.sleep(poll_interval)
        else:
            raise SystemExit(f"Timed out waiting for sandbox {sandbox.sandbox_id} to start")
        ticket = None

    _log(f"Sandbox {sandbox.sandbox_id} running")
    _log(f"External ID: {external_id}")

    return sandbox, ticket
