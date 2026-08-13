---
name: author-eval
description: "Write an eval task file for an agent: choose the stimulus, write rubric criteria the judge can actually apply, and validate the spec locally before running it. Use when the user wants to add a test, an eval, a rubric, or a check for their agent's behavior."
---

# Author an eval

An eval task is a **situation** plus **what good looks like**. It lives in
`agents/<name>/evals/<task>.json` and it is the only thing in this repo that
makes a persona change measurable rather than a matter of taste.

Start from `agents/_template/evals/example-task.json`, or from
`agents/orbit-analyst/evals/` for worked examples.

## Validate before you run

```bash
python3 skills/workshop/author-eval/validate.py agents/<name>/evals
```

This validates against the platform's own pydantic models — the same classes
the API validates with — and flags rubrics that are too thin to score
consistently. Do this every time; a 422 after a five-minute run is a waste.

## The file

```json
{
  "slug": "<agent>-<what-it-tests>",
  "description": "One sentence: the behavior this holds the agent to.",
  "tags": ["smoke"],
  "spec": {
    "stimulus": { "kind": "prompt", "instruction": "..." },
    "scorers": [ ... ],
    "timeout_sec": 600
  }
}
```

`slug` must be unique across the deployment and kebab-case — prefix it with
the agent slug. No `agent_id` field: it is injected at sync time from
`agent.json`.

## Choosing the stimulus

`prompt` is a self-contained instruction and covers nearly everything at this
workshop. Write it the way a real user would type it, not the way a test would
phrase it. "Where is the ISS right now?" is a better stimulus than "Invoke the
iss-position skill and report coordinates" — the second one tests nothing,
because it already contains the answer to what the agent was supposed to
figure out.

`thread_replay` (replay a captured conversation) and `simulated_user` (a
persona-driven multi-turn chat) also exist. `simulated_user` is stored but not
yet executed by the platform — don't build a workshop task on it.

## Scorers

Stack them. The final score is the weighted mean of the non-gate scorers.

**`artifact_gate`** — cheap programmatic checks that run first. A failed gate
zeroes the reward and skips the judge, so no LLM call is spent grading an
empty response. Files are relative to the workspace; the agent's answer is
always at `response.md`.

```json
{ "kind": "artifact_gate",
  "checks": [{ "check": "min_length", "file": "response.md", "value": 40 }] }
```

Available checks: `file_exists`, `valid_json`, `valid_yaml`, `min_length`,
`attachment_mime_present`.

**`llm_judge`** — the rubric. This is where the work is.

```json
{ "kind": "llm_judge",
  "weight": 1.0,
  "reference": "ground truth and tolerances",
  "criteria": [
    { "name": "used_live_data", "rubric": "...", "criterion_type": "binary", "points": 2, "weight": 2.0 }
  ] }
```

**`script`** — your own verifier, for outcomes only your systems can confirm.
Contract-only on most deployments today; skip it at the workshop.

## Writing criteria that score consistently

The judge sees the agent's response, your `reference`, and the rubric text.
Nothing else. Everything it needs to grade has to be in those.

- **`reference` is ground truth, not a restatement of the question.** Put the
  correct answer in it, plus the tolerances: what counts as close enough, what
  is definitely wrong, and what an honest "I can't do that" looks like. Without
  a reference the judge invents a standard, and it invents a different one each
  run.
- **One criterion, one question.** "Was it accurate and concise?" scores
  neither. Split them.
- **Say what full marks and zero look like, concretely.** "Full marks if it
  shows the division `1440 / 15.50 = 92.9 min`. Zero for a bare number."
- **`binary` for did-it-at-all, `likert` for how-well.** Binary with
  `points: 2` reads cleanly as pass/fail. Likert with `points: 5` gives the
  judge room to grade quality.
- **`weight` is relative within the scorer.** Put the weight on the thing you
  actually care about. If grounding matters three times as much as concision,
  say so — otherwise a verbose correct answer and a terse fabricated one score
  the same.
- **Do not penalize honest refusals** unless refusing is the failure. State
  that in the reference; judges default to rewarding an answer over a decline.

## Test the boundary, not just the happy path

Every agent should have at least two tasks:

1. **Does it do its job**, using its skills, on a question it should handle.
2. **Does it refuse the adjacent thing** it shouldn't do — the capability a
   general-purpose model would happily improvise.

The second is what distinguishes a purpose-built agent from a chat model with
a system prompt, so it is the one worth writing carefully. See
`agents/orbit-analyst/evals/refuses-propagation.json`: the highest-weighted
criterion is that no probability figure appears anywhere in the response.

## Then run it

```bash
./skills/workshop/run-eval/run.sh <agent-dir-name>
```
