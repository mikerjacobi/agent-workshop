"""Eval task spec — the JSONB document validated by a discriminated union.

A task is either platform-authored (``spec`` present) or repo-authored
(``source`` present): the spec fully describes stimulus + scorers for the
platform executor; the source points at a Harbor task directory in git and
is executed by the local Harbor runner, never by the platform.

Task kinds are union members, not migrations: adding a stimulus or scorer
kind is a new model + a match arm in the evaluator. Executors reject kinds
they don't support ("unsupported stimulus"), which is how the system stays
the record for more than it can execute.
"""

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_TASK_TIMEOUT_SEC = 1800.0


# ── Stimuli ──────────────────────────────────────────────────────────


class SnapshotMessage(BaseModel):
    """One turn of thread history, snapshotted at authoring time. Replay must
    not depend on live thread queries surviving retention (export/eject needs
    the history too)."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str
    seq: int | None = None


class AttachmentRef(BaseModel):
    """A file delivered alongside the instruction. ``uri`` is a GCS path the
    executor downloads and attaches to the outgoing message."""

    model_config = ConfigDict(extra="forbid")

    uri: str
    filename: str
    mime_type: str = "application/octet-stream"


class PromptStimulus(BaseModel):
    """Self-contained instruction, no prior context."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["prompt"] = "prompt"
    instruction: str = Field(min_length=1)
    attachments: list[AttachmentRef] = Field(default_factory=list)


class ThreadReplayStimulus(BaseModel):
    """Resume a captured conversation at a point.

    Platform tasks use the two-hop copy design: at task creation the source
    thread is copied (up to ``before_seq``, i.e. history plus the replayed
    user turn) onto an eval-owned identity — ``replay_thread_id`` — which is
    frozen by construction (no send path ever addresses it) and lives as long
    as the task, independent of the source thread's retention. At run time
    the canonical copy is copied again onto the run's sandbox identity, cut
    at ``replay_before_seq`` (the canonical's replayed user turn), and the
    copy handler's at-seq file mapping re-owns that turn's attachments for
    the run's send. Attachment logic — and whatever the copy handler learns
    later — flows into evals through those two hops for free.

    ``thread_id``/``before_seq``/``as_user`` are source provenance. ``history``
    is the inline fallback for tasks with no platform thread (hand-authored or
    Harbor-imported): the executor prefixes it into the instruction text.
    Identity injection is a fixture-script concern, never the platform's."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["thread_replay"] = "thread_replay"
    instruction: str = Field(min_length=1)
    history: list[SnapshotMessage] = Field(default_factory=list)
    attachments: list[AttachmentRef] = Field(default_factory=list)
    thread_id: str | None = None
    before_seq: int | None = None
    as_user: str | None = None
    # The eval-owned canonical copy + its replay cut (the canonical's final
    # user turn). Written by the server at task creation; never client-set
    # with meaning.
    replay_thread_id: str | None = None
    replay_before_seq: int | None = None


class SimulatedUserStimulus(BaseModel):
    """Worker-driven multi-turn chat: the evaluator sends the opening
    instruction, then generates each next user turn from ``persona`` +
    transcript via ``user_model`` until the persona signals done or
    ``max_turns`` is reached. Contract-only today: stored and exported, with
    the executor planned as follow-up work."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["simulated_user"] = "simulated_user"
    opening_instruction: str = Field(min_length=1)
    persona: str = Field(min_length=1)
    user_model: str | None = None
    max_turns: int = Field(default=20, ge=1, le=100)


Stimulus = Annotated[PromptStimulus | ThreadReplayStimulus | SimulatedUserStimulus, Field(discriminator="kind")]


# ── Scorers ──────────────────────────────────────────────────────────


class CriterionType(StrEnum):
    LIKERT = "likert"
    BINARY = "binary"


class CriterionRef(BaseModel):
    """Reference to a criterion_templates row, weighted per task."""

    model_config = ConfigDict(extra="forbid")

    template_id: str
    weight: float = Field(default=1.0, gt=0)


class InlineCriterion(BaseModel):
    """One-off criterion authored inline. Promoted to a template when reuse
    appears (an authoring operation, not a repo refactor)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    rubric: str = Field(min_length=1)
    criterion_type: CriterionType = CriterionType.LIKERT
    points: int = Field(default=5, ge=2, le=10)
    weight: float = Field(default=1.0, gt=0)


class JudgeTarget(StrEnum):
    RESPONSE = "response"
    ATTACHMENTS = "attachments"


class LLMJudgeScorer(BaseModel):
    """Rubric judge over the materialized artifacts, run in-process via
    rewardkit. ``reference`` is ground-truth context (rubric.md equivalent)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["llm_judge"] = "llm_judge"
    weight: float = Field(default=1.0, gt=0)
    criteria: list[CriterionRef | InlineCriterion] = Field(min_length=1)
    reference: str | None = None
    targets: list[JudgeTarget] = Field(default_factory=lambda: [JudgeTarget.RESPONSE, JudgeTarget.ATTACHMENTS])


class GateAssert(StrEnum):
    FILE_EXISTS = "file_exists"
    VALID_JSON = "valid_json"
    VALID_YAML = "valid_yaml"
    MIN_LENGTH = "min_length"
    ATTACHMENT_MIME_PRESENT = "attachment_mime_present"


class GateCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check: GateAssert
    file: str | None = None
    value: int | str | None = None

    @model_validator(mode="after")
    def _require_target(self) -> Self:
        if self.check == GateAssert.ATTACHMENT_MIME_PRESENT:
            if not self.value:
                raise ValueError("attachment_mime_present requires value (a mime type)")
        elif not self.file:
            raise ValueError(f"{self.check} requires file")
        if self.check == GateAssert.MIN_LENGTH and not isinstance(self.value, int):
            raise ValueError("min_length requires an integer value")
        return self


class ArtifactGateScorer(BaseModel):
    """Programmatic pre-judge gate (existence / parseability / size). A failed
    gate zeroes the reward so the judge never scores garbage."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["artifact_gate"] = "artifact_gate"
    checks: list[GateCheck] = Field(min_length=1)
    zeroes_reward: bool = True


class ScriptScorer(BaseModel):
    """Partner-owned scorer script, run as a short-lived Job under Harbor's
    verifier contract (workspace in, /logs/verifier/reward.json out). ``path``
    resolves on the agent version's image unless ``image`` overrides it.
    Contract-only today: the script-step executor is planned follow-up work."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["script"] = "script"
    path: str = Field(min_length=1)
    image: str | None = None
    weight: float = Field(default=1.0, gt=0)
    timeout_sec: float = Field(default=300.0, gt=0)
    payload_context: dict[str, str | int | float | bool] = Field(default_factory=dict)


Scorer = Annotated[LLMJudgeScorer | ArtifactGateScorer | ScriptScorer, Field(discriminator="kind")]


# ── Lifecycle script steps ───────────────────────────────────────────


class ScriptStep(BaseModel):
    """Fixture (pre-sandbox, emits /output/params.json merged into sandbox
    create) or teardown (post-run, finally). Same resolution rule as
    ScriptScorer. Contract-only today, executed by planned follow-up work."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    image: str | None = None
    timeout_sec: float = Field(default=300.0, gt=0)


# ── Parameters ───────────────────────────────────────────────────────


class SecretRef(BaseModel):
    """Reference-by-name into org-scoped secret storage. Specs never contain
    secret values."""

    model_config = ConfigDict(extra="forbid")

    secret: str = Field(min_length=1)


MASKED_SECRET = "********"


class SecretValue(BaseModel):
    """Inline write-only secret parameter (the AgentParameter.secret contract
    for eval specs): stored server-side, masked to MASKED_SECRET on every API
    read, and a masked value on update means "keep the stored one". The named
    planned named SecretRef store supersedes this; both mask the same way."""

    model_config = ConfigDict(extra="forbid")

    secret_value: str = Field(min_length=1, repr=False)


# ── The spec ─────────────────────────────────────────────────────────


class EvalTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    stimulus: Stimulus
    scorers: list[Scorer] = Field(min_length=1)
    fixture: ScriptStep | None = None
    teardown: ScriptStep | None = None
    # Merged into sandbox-create parameters; SecretRef values resolve from
    # org-scoped secret storage at execution time.
    parameters: dict[str, str | SecretRef | SecretValue] = Field(default_factory=dict)
    timeout_sec: float = Field(default=DEFAULT_TASK_TIMEOUT_SEC, gt=0)

    @model_validator(mode="after")
    def _require_non_gate_scorer(self) -> Self:
        if all(isinstance(s, ArtifactGateScorer) for s in self.scorers):
            raise ValueError("at least one non-gate scorer is required (gates only zero the reward)")
        return self

    def masked(self) -> Self:
        """Copy with inline secret values replaced by the mask — the only form
        API read paths may return."""
        if not any(isinstance(v, SecretValue) for v in self.parameters.values()):
            return self
        parameters: dict[str, str | SecretRef | SecretValue] = {
            key: SecretValue(secret_value=MASKED_SECRET) if isinstance(value, SecretValue) else value
            for key, value in self.parameters.items()
        }
        return self.model_copy(update={"parameters": parameters})

    def content_hash(self) -> str:
        """Stable hash of the spec content, stamped on results at execution so
        trend lines survive rubric edits (the platform-authored twin of the
        repo-authored commit SHA)."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class TaskSource(BaseModel):
    """Repo-authored task pointer: a Harbor task directory in git. Runs stamp
    the resolved commit SHA; identity stays in the platform slug so a repo
    reorg updates the ref without orphaning run history."""

    model_config = ConfigDict(extra="forbid")

    repo: str = Field(min_length=1, description="e.g. github.com/allenai/olmoearth_agents")
    path: str = Field(min_length=1, description="Harbor task dir within the repo")
    ref: str = Field(default="main", min_length=1)
