"""Eval run + result models.

A run is the state machine (queued → running → aggregating → completed |
failed | cancelled); results are pre-created one per task in ``queued`` at run
creation so progress, retry, and crash recovery are queries. Aggregates are
computed from result rows — the stored rollups are a cache, never the source
of truth (the ``attempt_no`` hedge depends on this).

Two doors, one table: the platform evaluator claims and executes results for
internal runs; external harnesses (local Harbor runner, CI) drive the same
rows via the ingest endpoints (create run → append results → finalize).
"""

from datetime import datetime
from enum import StrEnum

from mothership_client.client_models.api_output_model import ApiOutputModel
from mothership_client.client_models.common import DatetimeFilter, KeywordFilter, NumericFilter
from mothership_client.client_models.pagination import PaginationInput
from pydantic import BaseModel, ConfigDict, Field


class EvalRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AGGREGATING = "aggregating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvalResultStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunExecutor(StrEnum):
    PLATFORM = "platform"
    EXTERNAL = "external"


class LLMCostBreakdown(BaseModel):
    """Itemized cost from LiteLLM's per-call cost_breakdown metadata."""

    model_config = ConfigDict(extra="forbid")

    input_cost: float = 0.0
    output_cost: float = 0.0
    cache_read_cost: float = 0.0
    cache_creation_cost: float = 0.0


class LLMCost(BaseModel):
    """Per-result or run-aggregated agent LLM spend, attributed exactly via
    the sandbox's per-task LiteLLM virtual key (the shippy eval shape)."""

    model_config = ConfigDict(extra="forbid")

    total_spend: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0
    cost_breakdown: LLMCostBreakdown | None = None
    mean_request_duration_ms: float | None = None
    model: str | None = None


class CriterionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    score: float = Field(ge=0.0, le=1.0)
    weight: float = 1.0
    reason: str | None = None


class EvalRunConfig(BaseModel):
    """Immutable run configuration, snapshotted at creation."""

    model_config = ConfigDict(extra="forbid")

    # None means unspecified; the executor falls back to its configured default.
    judge_model: str | None = None
    max_concurrency: int = Field(default=4, ge=1, le=64)
    max_spend_usd: float | None = Field(default=None, gt=0)
    n_attempts: int = Field(default=1, ge=1, le=1, description="Fixed at 1; schema hedge for pass@k")


class EvalRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    org_id: str | None = None
    agent_id: str
    agent_version_id: str | None = None
    agent_version_label: str | None = None
    status: EvalRunStatus = EvalRunStatus.QUEUED
    executor: RunExecutor = RunExecutor.PLATFORM
    config: EvalRunConfig = Field(default_factory=EvalRunConfig)
    # External-executor provenance (local Harbor runner): harness + versions.
    executor_meta: dict[str, str] = Field(default_factory=dict)
    task_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    mean_score: float | None = None
    median_score: float | None = None
    llm_cost: LLMCost | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str
    attempt_no: int = 1
    org_id: str | None = None
    task_slug: str = ""
    status: EvalResultStatus = EvalResultStatus.QUEUED
    score: float | None = None
    criterion_scores: list[CriterionScore] = Field(default_factory=list)
    judgment: str | None = None
    # Reproducibility stamps: content hash for platform-authored tasks,
    # resolved commit SHA for repo-authored ones.
    spec_hash: str | None = None
    source_sha: str | None = None
    thread_id: str | None = None
    sandbox_external_id: str | None = None
    artifacts_uri: str | None = None
    duration_seconds: float | None = None
    error: str | None = None
    llm_cost: LLMCost | None = None
    claimed_by: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Run lifecycle inputs ─────────────────────────────────────────────


class CreateEvalRunInput(BaseModel):
    """Create a run over the tasks matching the filter (ids, tags, or all
    enabled tasks for the agent). Pre-creates one queued result per task."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    task_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    executor: RunExecutor = RunExecutor.PLATFORM
    config: EvalRunConfig = Field(default_factory=EvalRunConfig)
    executor_meta: dict[str, str] = Field(default_factory=dict)


class IngestResultInput(BaseModel):
    """Append/overwrite one result on an external run (or patch an internal
    one — same door for both executors)."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    attempt_no: int = Field(default=1, ge=1)
    status: EvalResultStatus = EvalResultStatus.COMPLETED
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    criterion_scores: list[CriterionScore] = Field(default_factory=list)
    judgment: str | None = None
    spec_hash: str | None = None
    source_sha: str | None = None
    thread_id: str | None = None
    sandbox_external_id: str | None = None
    artifacts_uri: str | None = None
    duration_seconds: float | None = None
    error: str | None = None
    llm_cost: LLMCost | None = None


class FinalizeEvalRunInput(BaseModel):
    """Finalize an external run: recompute rollups from result rows and stamp
    terminal status. Internal runs finalize via the evaluator's aggregation
    pass through the same code path."""

    model_config = ConfigDict(extra="forbid")

    status: EvalRunStatus = EvalRunStatus.COMPLETED


# ── Search ───────────────────────────────────────────────────────────


class EvalRunSortBy(StrEnum):
    CREATED_AT = "created_at"
    STARTED_AT = "started_at"
    FINISHED_AT = "finished_at"
    MEAN_SCORE = "mean_score"


class EvalRunFilterFields(BaseModel, extra="forbid"):
    run_id: KeywordFilter[str] | None = None
    agent_id: KeywordFilter[str] | None = None
    status: KeywordFilter[EvalRunStatus] | None = None
    executor: KeywordFilter[RunExecutor] | None = None
    created_at: DatetimeFilter | None = None
    mean_score: NumericFilter[float] | None = None


class SearchEvalRunInput(EvalRunFilterFields, PaginationInput[EvalRunSortBy]):
    sort_by: EvalRunSortBy = EvalRunSortBy.CREATED_AT


class EvalResultSortBy(StrEnum):
    CREATED_AT = "created_at"
    SCORE = "score"
    TASK_SLUG = "task_slug"


class EvalResultFilterFields(BaseModel, extra="forbid"):
    run_id: KeywordFilter[str] | None = None
    task_id: KeywordFilter[str] | None = None
    task_slug: KeywordFilter[str] | None = None
    status: KeywordFilter[EvalResultStatus] | None = None
    score: NumericFilter[float] | None = None


class SearchEvalResultInput(EvalResultFilterFields, PaginationInput[EvalResultSortBy]):
    sort_by: EvalResultSortBy = EvalResultSortBy.CREATED_AT


class ArchivedSpec(BaseModel):
    """A content-addressed spec snapshot, as stamped on results."""

    model_config = ConfigDict(extra="forbid")

    spec_hash: str
    spec: dict


ArchivedSpecOutput = ApiOutputModel[ArchivedSpec]
EvalRunOutput = ApiOutputModel[EvalRun]
SearchEvalRunOutput = ApiOutputModel[EvalRun]
EvalResultOutput = ApiOutputModel[EvalResult]
SearchEvalResultOutput = ApiOutputModel[EvalResult]
