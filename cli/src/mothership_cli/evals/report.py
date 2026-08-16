"""Markdown report for an eval run (port of generate_eval_report.py's shape:
executive summary, task table with Δ vs a previous run, per-task criterion
detail). Pure rendering over run/result models so the CLI, API, or a future
notification hook can all use it."""

from mothership_cli.models.eval_run import EvalResult, EvalResultStatus, EvalRun

PASS_THRESHOLD = 0.8
NEEDS_WORK_THRESHOLD = 0.5


def _verdict(score: float | None) -> str:
    if score is None:
        return "Error"
    if score >= PASS_THRESHOLD:
        return "Pass"
    if score >= NEEDS_WORK_THRESHOLD:
        return "Needs work"
    return "Fail"


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def _fmt_score(score: float | None) -> str:
    return f"{score:.2f}" if score is not None else "—"


def _fmt_delta(current: float | None, previous: float | None) -> str:
    if current is None or previous is None:
        return "—"
    delta = current - previous
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.2f}"


def render_report(run: EvalRun, results: list[EvalResult], previous: list[EvalResult] | None = None) -> str:
    prev_by_task = {r.task_slug: r for r in (previous or [])}
    completed = [r for r in results if r.status == EvalResultStatus.COMPLETED]
    failed = [r for r in results if r.status == EvalResultStatus.FAILED]
    verdicts = [_verdict(r.score) for r in completed]

    lines = [
        f"# Eval Report — {run.run_id}",
        "",
        "## Executive summary",
        "",
        f"- **Agent:** {run.agent_id}" + (f" @ {run.agent_version_label}" if run.agent_version_label else ""),
        f"- **Status:** {run.status.value} ({run.executor.value} executor)",
        f"- **Overall score:** {_fmt_score(run.mean_score)} mean / {_fmt_score(run.median_score)} median ({run.task_count} task(s))",
        f"- **Verdicts:** {verdicts.count('Pass')} pass, {verdicts.count('Needs work')} needs work, {verdicts.count('Fail')} fail, {len(failed)} error",
    ]
    if run.llm_cost and run.llm_cost.total_spend:
        lines.append(f"- **LLM spend:** ${run.llm_cost.total_spend:.2f}")
    if run.started_at and run.finished_at:
        lines.append(f"- **Wall clock:** {_fmt_duration((run.finished_at - run.started_at).total_seconds())}")
    lines += [
        "",
        "| Task | Duration | Previous | Score | Δ | Verdict |",
        "| ---- | -------- | -------- | ----- | --- | ------- |",
    ]
    for result in sorted(results, key=lambda r: r.task_slug):
        prev = prev_by_task.get(result.task_slug)
        verdict = _verdict(result.score) if result.status == EvalResultStatus.COMPLETED else result.status.value
        lines.append(
            f"| {result.task_slug} | {_fmt_duration(result.duration_seconds)} | {_fmt_score(prev.score) if prev else '—'} "
            f"| {_fmt_score(result.score)} | {_fmt_delta(result.score, prev.score if prev else None)} | {verdict} |"
        )
    lines.append("")

    for result in sorted(results, key=lambda r: r.task_slug):
        lines += ["---", "", f"## {result.task_slug} — {_fmt_score(result.score)} ({_fmt_duration(result.duration_seconds)})", ""]
        meta = []
        if result.thread_id:
            meta.append(f"thread `{result.thread_id}`")
        if result.spec_hash:
            meta.append(f"spec `{result.spec_hash[:12]}`")
        if result.source_sha:
            meta.append(f"sha `{result.source_sha[:12]}`")
        if meta:
            lines += [" · ".join(meta), ""]
        if result.error:
            lines += ["```", result.error, "```", ""]
        for criterion in result.criterion_scores:
            lines.append(f"- **{criterion.name}** — {criterion.score:.2f} (w={criterion.weight})")
            if criterion.reason:
                reason = criterion.reason.strip().replace("\n", "\n  > ")
                lines.append(f"  > {reason}")
        if result.judgment:
            lines += ["", "<details><summary>Judge output</summary>", "", result.judgment, "", "</details>"]
        lines.append("")
    return "\n".join(lines)
