---
name: author-eval
description: "Write an eval task file for an agent: the question to ask, and the criteria a judge grades the answer against. Use when the user wants to add a test, an eval, a rubric, or a check for their agent's behavior."
---

# Write an eval

One file per task, in `agents/<dir>/evals/`. Copy an existing one and change
it: `agents/quake-watch/evals/recent-activity.json` is the worked example.

```json
{
  "slug": "what-it-tests",
  "description": "One sentence.",
  "tags": ["smoke"],
  "spec": {
    "stimulus": { "kind": "prompt", "instruction": "The message to send." },
    "scorers": [
      { "kind": "artifact_gate",
        "checks": [{ "check": "min_length", "file": "response.md", "value": 80 }] },
      { "kind": "llm_judge",
        "reference": "The correct answer, and how close counts as close enough.",
        "criteria": [
          { "name": "did_the_thing", "rubric": "What full marks and zero look like.",
            "criterion_type": "binary", "points": 2, "weight": 2.0 }
        ] }
    ],
    "timeout_sec": 900
  }
}
```

No `agent_id`: `mothership evals run` fills that in.

The judge sees the agent's answer, your `reference`, and the rubric text, and
nothing else. So `reference` has to carry the actual correct answer along with
the tolerances, otherwise the judge invents a standard and picks a different
one each run. Write the instruction the way a user would type it, not the way a
test would phrase it.

Use `binary` for whether the agent did something at all and `likert` for how
well. `weight` is relative within the scorer, so put the weight on what you
care about.

Then run it:

```bash
mothership evals run <dir> --slug <slug> --task <filename>
```

A 422 means the file does not validate, and the error names the field. Every
field a task accepts is defined in
`cli/src/mothership_cli/models/eval_spec.py`.
