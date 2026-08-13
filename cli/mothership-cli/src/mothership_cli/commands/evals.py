"""``mothership evals`` — eval tasks, criterion templates, and runs.

Small surface: writes take one verbose ``--body`` JSON param validated
server-side; reads take a few common filter flags. Skills drive this CLI, so
the JSON body is the interface, not per-field flags."""

import json
import shlex
import socket
import sys
from pathlib import Path

from mothership_cli.client import ApiError, get_client
from mothership_cli.evals import local_runner
from mothership_cli.evals.report import render_report
from mothership_client.models.eval_run import EvalResult, EvalRun
from mothership_client.models.eval_task import EvalTask
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import CliApp, CliSubCommand


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
    run_local: CliSubCommand[EvalsRunLocal]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)
