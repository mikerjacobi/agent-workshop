"""``mothership publish`` — build an agent directory and make it the live version.

One command for what is otherwise a docker build, a push, a catalog write, a
version promotion, and a sandbox recycle.
"""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

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
from mothership_cli.workspace import Agent, AgentManifest, stage_build_context
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import CliPositionalArg


# The registry the workshop deployment pulls from. --registry or
# MOTHERSHIP_IMAGE_REGISTRY override it.
DEFAULT_REGISTRY = "us-west1-docker.pkg.dev/mothership-shared/mothership-docker-repository"

# Upload mode: when MOTHERSHIP_WORKSPACE_BUCKET is set, publish skips docker
# entirely. The workspace is uploaded to the bucket as an immutable tarball,
# and the version points at the shared runtime image, which fetches the
# tarball at boot via its WORKSPACE_URL parameter (see agents/agent-pre-start.sh).
WORKSPACE_URL_PARAM = "WORKSPACE_URL"


class PublishError(MothershipCliError):
    """Publishing failed. Handled by the CLI's top-level handler."""


def _run(command: list[str], step: str) -> None:
    if subprocess.run(command, check=False).returncode != 0:
        raise PublishError(f"{step} failed: {' '.join(command)}")


def _workspace_tarball(context: Path) -> bytes:
    """The staged workspace as a .tgz whose members are workspace-relative."""
    workspace = context / "workspace"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(workspace.rglob("*")):
            tar.add(path, arcname=str(path.relative_to(workspace)))
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


def _ensure_membership(external_id: str) -> None:
    """Enroll the caller in the target org before their first conversation.

    Sends on a thread are allowed only for members of the thread's org, and a
    new external_id is not a member of anything yet. The org API key can enroll
    them, but only while no identity is asserted beside it (asserting one drops
    the key to plain member), so this goes out on a bare client. Re-enrolling
    an existing member is a no-op, and a 403 means the caller is not using an
    org-admin credential, where membership must already exist for any of this
    to work.
    """
    org = resolve_org()
    if org == DEFAULT_ORG_ID:
        return  # everyone is JIT-enrolled in the default org
    _, profile = get_active_profile()
    bare = MothershipClient(profile.base_url, org=org, external_id=None, api_key=resolve_api_key())
    try:
        bare._request("POST", f"/api/orgs/{org}/members", json={"external_id": external_id})
    except ApiError as exc:
        if exc.status not in (403, 409):
            raise


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
        # The label already exists (e.g. --skip-build re-run); promote that one.
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
    """Build an agent directory into an image and make it the live version."""

    model_config = ConfigDict(extra="forbid")

    agent: CliPositionalArg[str] = Field(description="Directory name under agents/")
    slug: str | None = Field(default=None, description="Catalog id (default: the manifest's slug)")
    registry: str | None = Field(default=None, description="Image registry (default: $MOTHERSHIP_IMAGE_REGISTRY)")
    version: str | None = Field(default=None, description="Version label (default: a UTC timestamp)")
    agents_dir: str = Field(default="agents", description="Where agent directories live")
    skip_build: bool = Field(default=False, description="Skip docker; requires this slug+version already pushed")
    bucket: str | None = Field(default=None, description="Workspace bucket (default: $MOTHERSHIP_WORKSPACE_BUCKET); upload mode when set")
    runtime_image: str | None = Field(default=None, description="Shared runtime image for upload mode (default: $MOTHERSHIP_RUNTIME_IMAGE)")

    def cli_cmd(self) -> None:
        source = Agent.load(self.agent, self.agents_dir)
        slug = self.slug or source.manifest.slug
        registry = (self.registry or os.environ.get("MOTHERSHIP_IMAGE_REGISTRY") or DEFAULT_REGISTRY).rstrip("/")
        version = self.version or datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        bucket = self.bucket or os.environ.get("MOTHERSHIP_WORKSPACE_BUCKET")
        client = _catalog_client()
        identity = resolve_identity()
        if identity:
            _ensure_membership(identity)

        manifest = source.manifest
        if bucket:
            runtime_image = self.runtime_image or os.environ.get("MOTHERSHIP_RUNTIME_IMAGE")
            if not runtime_image:
                raise PublishError("upload mode needs a runtime image: pass --runtime-image or set MOTHERSHIP_RUNTIME_IMAGE")
            image = runtime_image
            with tempfile.TemporaryDirectory(prefix="mothership-build-") as context:
                stage_build_context(source, Path(context), self.agents_dir)
                payload = _workspace_tarball(Path(context))
            workspace_url = _upload_workspace(bucket, slug, version, payload)
            manifest = _with_workspace_param(manifest, workspace_url)
            print(f"uploaded {workspace_url} ({len(payload)} bytes)")
        else:
            image = f"{registry}/{slug}:{version}"
            if not self.skip_build:
                print(f"building {image}")
                with tempfile.TemporaryDirectory(prefix="mothership-build-") as context:
                    stage_build_context(source, Path(context), self.agents_dir)
                    _run(["docker", "build", "-t", image,
                          "-f", f"{self.agents_dir}/Dockerfile", context], "docker build")
                print(f"pushing {image}")
                _run(["docker", "push", image], "docker push")

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
