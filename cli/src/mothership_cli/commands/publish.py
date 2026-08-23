"""``mothership publish`` — upload an agent directory and make it the live version.

No docker. The agent's files go to the workspace bucket as an immutable
tarball, and the catalog version points at the shared runtime image, which
fetches that tarball at boot through its WORKSPACE_URL parameter (see
agents/agent-pre-start.sh). One command for what is otherwise an upload, a
catalog write, a version promotion, and a sandbox recycle.
"""

from __future__ import annotations

import io
import os
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from mothership_cli.client import ensure_org_member
from mothership_cli.config import get_active_profile, resolve_api_key, resolve_identity, resolve_org
from mothership_cli.models.org import DEFAULT_ORG_ID
from mothership_cli.client_models.common import KeywordFilter
from mothership_cli.errors import MothershipCliError
import httpx

from mothership_cli.http import ApiError, MothershipClient
from mothership_cli.models.agent_catalog import (
    AgentCatalogEntry,
    CreateAgentInput,
    SearchAgentCatalogInput,
    UpdateAgentInput,
)
from mothership_cli.models.agent_version import CreateAgentVersionInput, SearchAgentVersionsInput
from mothership_cli.models.harness import TransportMode
from mothership_cli.models.sandbox import SandboxState, SearchSandboxesInput
from mothership_cli.workspace import Agent, AgentManifest, stage_workspace
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import CliPositionalArg


# The agent parameter the runtime image reads to find its workspace tarball.
WORKSPACE_URL_PARAM = "WORKSPACE_URL"


class PublishError(MothershipCliError):
    """Publishing failed. Handled by the CLI's top-level handler."""


def _workspace_tarball(workspace: Path) -> bytes:
    """The staged workspace as a .tgz whose members are workspace-relative."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(workspace.rglob("*")):
            # recursive=False: rglob already walks the tree, and letting tar
            # recurse too would add every file once per ancestor directory.
            tar.add(path, arcname=str(path.relative_to(workspace)), recursive=False)
    return buffer.getvalue()


def _upload_token() -> str | None:
    """An OAuth token for the bucket, from GOOGLE_APPLICATION_CREDENTIALS if
    set (a service-account key file), else None for a public-write bucket.
    google-auth instead of gcloud, so the participant flow needs no SDK."""
    key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not key_path:
        return None
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(
        key_path, scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
    credentials.refresh(Request())
    return credentials.token


def _upload_workspace(bucket: str, slug: str, version: str, payload: bytes) -> str:
    """PUT the tarball to the bucket and return its gs:// name."""
    object_name = f"{slug}/{version}.tgz"
    headers = {"Content-Type": "application/gzip"}
    token = _upload_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.put(
        f"https://storage.googleapis.com/{bucket}/{object_name}",
        content=payload,
        headers=headers,
        timeout=60.0,
    )
    if response.status_code not in (200, 201):
        raise PublishError(
            f"workspace upload failed: HTTP {response.status_code} for gs://{bucket}/{object_name}\n"
            f"{response.text[:300]}"
        )
    return f"gs://{bucket}/{object_name}"


def _with_workspace_param(manifest: AgentManifest, workspace_url: str) -> AgentManifest:
    """The manifest with WORKSPACE_URL declared and defaulted to this version's
    tarball, so every sandbox (interactive or eval) boots this exact content."""
    from mothership_cli.models.agent_catalog import AgentParameter

    parameters = [p for p in manifest.parameters if p.key != WORKSPACE_URL_PARAM]
    parameters.append(AgentParameter(
        key=WORKSPACE_URL_PARAM,
        label="Workspace tarball",
        description="gs:// tarball the runtime image unpacks into the workspace at boot.",
        default=workspace_url,
        secret=False,
    ))
    return manifest.model_copy(update={"parameters": parameters})


def _catalog_client() -> MothershipClient:
    """The client for catalog writes. Agent CRUD is org-admin-gated, and an org
    API key is org-admin only while no identity is asserted beside it — so when
    a key is present, the identity header stays off. Without a key the asserted
    identity is the only credential there is, so it stays."""
    from mothership_cli.client import get_client as _get

    _, profile = get_active_profile()
    key = resolve_api_key()
    if key:
        return MothershipClient(profile.base_url, org=resolve_org(), external_id=None, api_key=key)
    return _get()


def _find(client: MothershipClient, slug: str) -> AgentCatalogEntry | None:
    agents, _ = client.search_agents(SearchAgentCatalogInput(slug=KeywordFilter(eq=slug)))
    return agents[0] if agents else None


def _register(client: MothershipClient, slug: str, m: AgentManifest, image: str, version: str) -> AgentCatalogEntry:
    return client.create_agent(CreateAgentInput(
        slug=slug, name=m.name, description=m.description, harness=m.harness,
        transport=m.transport or TransportMode.RELAY, default_model=m.default_model,
        parameters=m.parameters, image=image, version=version,
    ))


def _promote(client: MothershipClient, agent: AgentCatalogEntry, m: AgentManifest, image: str, version: str) -> None:
    try:
        new = client.create_agent_version(CreateAgentVersionInput(
            agent_id=agent.agent_id, version=version, image=image, enabled=True))
    except ApiError as exc:
        if exc.status != 409:
            raise
        # The label already exists (e.g. a re-run at the same label); promote that one.
        versions, _ = client.search_agent_versions(agent.agent_id, SearchAgentVersionsInput(
            version=KeywordFilter(eq=version)))
        new = versions[0]
    # Model and parameters live on the catalog row rather than the version, so
    # a manifest edit needs its own call.
    client.update_agent(UpdateAgentInput(
        agent_id=agent.agent_id, name=m.name, description=m.description,
        default_model=m.default_model, parameters=m.parameters, current_version=new.version_id))


def _recycle(client: MothershipClient, agent_id: str) -> int:
    """A running sandbox keeps the image it booted with, so it would serve the
    previous version until it is stopped."""
    sandboxes, _ = client.search_sandboxes(SearchSandboxesInput(
        agent_id=KeywordFilter(eq=agent_id), state=KeywordFilter(eq=SandboxState.RUNNING)))
    for sandbox in sandboxes:
        client.stop_sandbox(sandbox.sandbox_id)
    return len(sandboxes)


class PublishCmd(BaseModel):
    """Upload an agent directory and make it the live version."""

    model_config = ConfigDict(extra="forbid")

    agent: CliPositionalArg[str] = Field(description="Directory name under agents/")
    slug: str | None = Field(default=None, description="Catalog id (default: the manifest's slug)")
    version: str | None = Field(default=None, description="Version label (default: a UTC timestamp)")
    agents_dir: str = Field(default="agents", description="Where agent directories live")
    bucket: str | None = Field(default=None, description="Workspace bucket (default: $MOTHERSHIP_WORKSPACE_BUCKET)")
    runtime_image: str | None = Field(default=None, description="Shared runtime image (default: $MOTHERSHIP_RUNTIME_IMAGE)")

    def cli_cmd(self) -> None:
        source = Agent.load(self.agent, self.agents_dir)
        slug = self.slug or source.manifest.slug
        version = self.version or datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        bucket = self.bucket or os.environ.get("MOTHERSHIP_WORKSPACE_BUCKET")
        if not bucket:
            raise PublishError("no workspace bucket: pass --bucket or set MOTHERSHIP_WORKSPACE_BUCKET")
        image = self.runtime_image or os.environ.get("MOTHERSHIP_RUNTIME_IMAGE")
        if not image:
            raise PublishError("no runtime image: pass --runtime-image or set MOTHERSHIP_RUNTIME_IMAGE")
        client = _catalog_client()
        identity = resolve_identity()
        if identity:
            ensure_org_member(identity)

        with tempfile.TemporaryDirectory(prefix="mothership-publish-") as staging:
            workspace = Path(staging) / "workspace"
            stage_workspace(source, workspace)
            payload = _workspace_tarball(workspace)
        workspace_url = _upload_workspace(bucket, slug, version, payload)
        manifest = _with_workspace_param(source.manifest, workspace_url)
        print(f"uploaded {workspace_url} ({len(payload)} bytes)")

        try:
            existing = _find(client, slug)
            if existing is None:
                agent = _register(client, slug, manifest, image, version)
                print(f"registered {slug}")
            else:
                agent = existing
                _promote(client, agent, manifest, image, version)
                print(f"promoted {slug} to {version}")
            stopped = _recycle(client, agent.agent_id)
        except ApiError as exc:
            raise PublishError(str(exc)) from exc

        if stopped:
            print(f"stopped {stopped} running sandbox(es)")
        print(f"\nagent_id  {agent.agent_id}")
        print(f"image     {image}")
        print(f"workspace {workspace_url}")
