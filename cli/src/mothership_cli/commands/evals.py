"""``mothership evals`` — eval tasks, criterion templates, and runs.

Small surface: writes take one verbose ``--body`` JSON param validated
server-side; reads take a few common filter flags. Skills drive this CLI, so
the JSON body is the interface, not per-field flags."""

import json
import shlex
import socket
import sys
import time
from pathlib import Path

from mothership_cli.client import ApiError, ensure_org_member, get_client
from mothership_cli.client_models.api_output_model import ApiOutputModel
from mothership_cli.client_models.common import KeywordFilter
from mothership_cli.errors import MothershipCliError
from mothership_cli.evals.report import render_report as _render
from mothership_cli.models.agent_catalog import SearchAgentCatalogInput
from mothership_cli.models.eval_run import EvalResult as _EvalResult, EvalRun as _EvalRun
from mothership_cli.workspace import Agent, read_eval_task
from mothership_cli.evals import local_runner
from mothership_cli.evals.report import render_report
from mothership_cli.models.eval_run import EvalResult, EvalRun
from mothership_cli.models.eval_task import EvalTask
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import CliApp, CliPositionalArg, CliSubCommand


def _parse_body(body: str) -> dict:
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise SystemExit(f"invalid --body JSON: {e}") from e


def _print(data: dict) -> None:
    print(json.dumps(data, indent=2, default=str))


def _run(method: str, path: str, body: dict | None = None) -> None:
    client = get_client()
    try:
        data = client._request(method, client._scoped("evals", path), json=body)
    except ApiError as e:
        raise SystemExit(str(e)) from e
    _print(data)


class EvalsSearch(BaseModel):
    """Search a resource: tasks, templates, runs, or results."""

    model_config = ConfigDict(extra="forbid")

    resource: str = Field(description="One of: tasks, templates, runs, results")
    query: str = Field(default="{}", description="Search input JSON (server-validated)")

    def cli_cmd(self) -> None:
        if self.resource not in ("tasks", "templates", "runs", "results"):
            raise SystemExit(f"unknown resource: {self.resource}")
        _run("POST", f"/{self.resource}/search", _parse_body(self.query))


class EvalsCreate(BaseModel):
    """Create a task, template, or run from a JSON body."""

    model_config = ConfigDict(extra="forbid")

    resource: str = Field(description="One of: tasks, templates, runs")
    body: str = Field(description="Create input JSON (server-validated)")

    def cli_cmd(self) -> None:
        if self.resource not in ("tasks", "templates", "runs"):
            raise SystemExit(f"unknown resource: {self.resource}")
        _run("POST", f"/{self.resource}", _parse_body(self.body))


class EvalsGet(BaseModel):
    """Get one task, template, or run by id."""

    model_config = ConfigDict(extra="forbid")

    resource: str = Field(description="One of: tasks, templates, runs")
    resource_id: str = Field(description="task_id / template_id / run_id")

    def cli_cmd(self) -> None:
        if self.resource not in ("tasks", "templates", "runs"):
            raise SystemExit(f"unknown resource: {self.resource}")
        _run("GET", f"/{self.resource}/{self.resource_id}")


class EvalsUpdate(BaseModel):
    """Patch a task or template from a JSON body."""

    model_config = ConfigDict(extra="forbid")

    resource: str = Field(description="One of: tasks, templates")
    resource_id: str = Field(description="task_id / template_id")
    body: str = Field(description="Update input JSON (server-validated)")

    def cli_cmd(self) -> None:
        if self.resource not in ("tasks", "templates"):
            raise SystemExit(f"unknown resource: {self.resource}")
        _run("PATCH", f"/{self.resource}/{self.resource_id}", _parse_body(self.body))


class EvalsIngest(BaseModel):
    """Append one result to a run (external-executor door)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    body: str = Field(description="IngestResultInput JSON (server-validated)")

    def cli_cmd(self) -> None:
        _run("POST", f"/runs/{self.run_id}/results", _parse_body(self.body))


class EvalsFinalize(BaseModel):
    """Finalize a run: recompute rollups and stamp terminal status."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str = Field(default="completed", description="completed | failed")

    def cli_cmd(self) -> None:
        _run("POST", f"/runs/{self.run_id}/finalize", {"status": self.status})


class EvalsCancel(BaseModel):
    """Cancel a run and its non-terminal results."""

    model_config = ConfigDict(extra="forbid")

    run_id: str

    def cli_cmd(self) -> None:
        _run("POST", f"/runs/{self.run_id}/cancel")


class EvalsExport(BaseModel):
    """Export platform-authored tasks as a Harbor task-dir zip."""

    model_config = ConfigDict(extra="forbid")

    out: str = Field(default="eval-tasks.zip", description="Output zip path")
    body: str = Field(default="{}", description="ExportEvalTasksInput JSON")

    def cli_cmd(self) -> None:
        client = get_client()
        try:
            raw = client._request_bytes("POST", client._scoped("evals", "/tasks/export"), json=_parse_body(self.body))
        except ApiError as e:
            raise SystemExit(str(e)) from e
        with open(self.out, "wb") as f:
            f.write(raw)
        sys.stderr.write(f"wrote {self.out} ({len(raw)} bytes)\n")


class EvalsReport(BaseModel):
    """Render a markdown report for a run (Δ columns with --previous)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    previous: str | None = Field(default=None, description="Previous run_id for Δ columns")
    out: str | None = Field(default=None, description="Write to a file instead of stdout")

    def cli_cmd(self) -> None:
        client = get_client()

        def _results(run_id: str) -> list[EvalResult]:
            data = client._request("POST", client._scoped("evals", "/results/search"), json={"run_id": {"eq": run_id}, "limit": 1000})
            return [EvalResult.model_validate(r) for r in data.get("records") or []]

        try:
            run_data = client._request("GET", client._scoped("evals", f"/runs/{self.run_id}"))
            run = EvalRun.model_validate((run_data.get("records") or [{}])[0])
            report = render_report(run, _results(self.run_id), _results(self.previous) if self.previous else None)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        if self.out:
            with open(self.out, "w") as f:
                f.write(report)
            sys.stderr.write(f"wrote {self.out}\n")
        else:
            print(report)


class EvalsRunLocal(BaseModel):
    """Run tasks locally under Harbor and ingest results into the platform.

    Requires ``harbor`` and ``git`` on PATH. Everything after ``--harbor-args``
    passes to ``harbor run`` verbatim (agent selection, env, timeouts) — the
    task's environment owns those choices, not this runner."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    task_ids: str = Field(default="", description="Comma-separated task ids (empty = all enabled for the agent)")
    tags: str = Field(default="", description="Comma-separated tag filter")
    workdir: str | None = Field(default=None, description="Materialization dir (default: a temp dir, kept for debugging)")
    harbor_args: str = Field(default="", description="Extra args passed to `harbor run` verbatim")

    def cli_cmd(self) -> None:
        client = get_client()
        query: dict = {"agent_id": {"eq": self.agent_id}, "enabled": True, "limit": 1000}
        if self.task_ids:
            query["task_id"] = {"inc": [t.strip() for t in self.task_ids.split(",") if t.strip()]}
        if self.tags:
            query["tags"] = {"inc": [t.strip() for t in self.tags.split(",") if t.strip()]}
        try:
            data = client._request("POST", client._scoped("evals", "/tasks/search"), json=query)
            tasks = [EvalTask.model_validate(r) for r in data.get("records") or []]
            if not tasks:
                raise SystemExit("no tasks matched")
            spec_tasks = [t for t in tasks if t.spec is not None]
            export_zip = None
            if spec_tasks:
                export_zip = client._request_bytes("POST", client._scoped("evals", "/tasks/export"), json={"task_ids": [t.task_id for t in spec_tasks]})

            workdir = local_runner.default_workdir() if self.workdir is None else Path(self.workdir)
            materialized = local_runner.materialize(tasks, export_zip, workdir)
            sys.stderr.write(f"materialized {len(tasks)} task(s) at {materialized.tasks_dir}\n")

            run_data = client._request("POST", client._scoped("evals", "/runs"), json={
                "agent_id": self.agent_id,
                "task_ids": [t.task_id for t in tasks],
                "executor": "external",
                "executor_meta": {"runner": "local-harbor", "host": socket.gethostname()},
            })
            run_id = (run_data.get("records") or [{}])[0].get("run_id")
            sys.stderr.write(f"run {run_id}\n")

            job_dir = local_runner.run_harbor(materialized.tasks_dir, workdir / "jobs", shlex.split(self.harbor_args))
            outcomes = local_runner.parse_job_dir(job_dir)

            by_slug = {t.slug: t for t in tasks}
            ingested = 0
            for outcome in outcomes:
                task = by_slug.get(outcome.task_slug)
                if task is None:
                    sys.stderr.write(f"skipping unknown trial task {outcome.task_slug}\n")
                    continue
                client._request("POST", client._scoped("evals", f"/runs/{run_id}/results"), json={
                    "task_id": task.task_id,
                    "status": "failed" if outcome.error else "completed",
                    "score": outcome.reward,
                    "criterion_scores": outcome.criteria,
                    "source_sha": materialized.source_shas.get(outcome.task_slug),
                    "duration_seconds": outcome.duration_seconds,
                    "error": outcome.error,
                })
                ingested += 1
            client._request("POST", client._scoped("evals", f"/runs/{run_id}/finalize"), json={"status": "completed"})
            print(json.dumps({"run_id": run_id, "job_dir": str(job_dir), "ingested": ingested}))
        except (ApiError, local_runner.LocalRunError) as e:
            raise SystemExit(str(e)) from e


TERMINAL = {"completed", "failed", "cancelled"}


class EvalsRunError(MothershipCliError):
    """Running the agent's evals failed."""


class EvalsRun(BaseModel):
    """Sync an agent's eval files, run them, and print the report."""

    model_config = ConfigDict(extra="forbid")

    agent: CliPositionalArg[str] = Field(description="Directory name under agents/")
    slug: str | None = Field(default=None, description="Catalog id (default: the manifest's slug)")
    task: str | None = Field(default=None, description="One eval file to run (default: all of them)")
    prefix: str | None = Field(default=None, description="Task slug prefix (default: the agent slug)")
    agents_dir: str = Field(default="agents", description="Where agent directories live")
    previous: str | None = Field(default=None, description="Earlier run_id, for delta columns")
    poll_seconds: float = Field(default=15.0, gt=0)
    timeout_seconds: float = Field(default=1800.0, gt=0)

    def cli_cmd(self) -> None:
        source = Agent.load(self.agent, self.agents_dir)
        slug = self.slug or source.manifest.slug
        client = get_client()

        agents, _ = client.search_agents(SearchAgentCatalogInput(slug=KeywordFilter(eq=slug)))
        if not agents:
            raise EvalsRunError(f"'{slug}' is not in the catalog. Publish it first: mothership publish {self.agent}")
        agent_id = agents[0].agent_id

        task_ids = []
        synced_slugs: list[str] = []
        for path in source.eval_files(self.task):
            document = read_eval_task(path, agent_id, path.stem)
            task_slug = f"{self.prefix or slug}-{document['slug']}"
            document["slug"] = task_slug

            found = client._request("POST", client._scoped("evals", "/tasks/search"),
                                    json={"slug": {"eq": task_slug}, "limit": 1})
            records = (found or {}).get("records") or []
            if records:
                task_id = records[0]["task_id"]
                patch = {k: v for k, v in document.items() if k != "agent_id"}
                patch["enabled"] = True
                client._request("PATCH", client._scoped("evals", f"/tasks/{task_id}"), json=patch)
            else:
                created = client._request("POST", client._scoped("evals", "/tasks"), json=document)
                task_id = (created.get("records") or [{}])[0]["task_id"]
            sys.stderr.write(f"task {task_slug}\n")
            task_ids.append(task_id)
            synced_slugs.append(task_slug)

        data = client._request("POST", client._scoped("evals", "/runs"), json={
            "agent_id": agent_id, "task_ids": task_ids, "executor": "platform"})
        run_id = (data.get("records") or [{}])[0]["run_id"]
        sys.stderr.write(f"run {run_id}\n")

        # The platform executor mints eval-{run}-{slug} identities and sends as
        # them, but only the default org enrolls members implicitly. Enroll the
        # predicted identities (and the executor) before its first send, which
        # is minutes away behind a sandbox boot. Stopgap until server-side.
        for task_slug in synced_slugs:
            ensure_org_member(f"eval-{run_id.removeprefix('evrun_')}-{task_slug}"[:64])
        ensure_org_member("agent-evaluator")

        deadline = time.monotonic() + self.timeout_seconds
        while True:
            data = client._request("GET", client._scoped("evals", f"/runs/{run_id}"))
            run = _EvalRun.model_validate((data.get("records") or [{}])[0])
            done = run.completed_count + run.failed_count
            sys.stderr.write(f"\r  {run.status:<12} {done}/{run.task_count} ")
            sys.stderr.flush()
            if run.status in TERMINAL:
                sys.stderr.write("\n")
                break
            if time.monotonic() > deadline:
                sys.stderr.write("\n")
                raise EvalsRunError(f"still {run.status}; check: mothership evals report --run-id {run_id}")
            time.sleep(self.poll_seconds)

        def _results(rid: str) -> list:
            payload = client._request("POST", client._scoped("evals", "/results/search"),
                                      json={"run_id": {"eq": rid}, "limit": 1000})
            return [_EvalResult.model_validate(r) for r in payload.get("records") or []]

        print(_render(run, _results(run_id), _results(self.previous) if self.previous else None))
        print(f"\nrun_id: {run_id}")


class EvalsCmd(BaseModel):
    """Author and run agent evals."""

    search: CliSubCommand[EvalsSearch]
    create: CliSubCommand[EvalsCreate]
    get: CliSubCommand[EvalsGet]
    update: CliSubCommand[EvalsUpdate]
    ingest: CliSubCommand[EvalsIngest]
    finalize: CliSubCommand[EvalsFinalize]
    cancel: CliSubCommand[EvalsCancel]
    export: CliSubCommand[EvalsExport]
    report: CliSubCommand[EvalsReport]
    run: CliSubCommand[EvalsRun]
    run_local: CliSubCommand[EvalsRunLocal]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)
