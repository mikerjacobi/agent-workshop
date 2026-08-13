# skills/

Two kinds of skill live here, and confusing them is the most common
stumble in this repo. Both are Markdown files with the same shape. What
differs is **who reads them**.

```
skills/
├── library/     agent skills — copied into an agent, read by YOUR agent at runtime
└── workshop/    helper skills — read by Claude Code, in YOUR editor, to do the dev loop
```

| | `skills/library/` | `skills/workshop/` |
|---|---|---|
| Read by | The agent you built, running in a sandbox | Claude Code, on your laptop |
| Gets there via | You copy it into `agents/<name>/.claude/skills/` | The `.claude/skills/` symlinks at the repo root |
| Ships in the image | Yes | No |
| Example | "how to query CelesTrak" | "how to publish an agent" |

## skills/library/ — the agent skill library

Reusable skills to copy into an agent. They are files; copy them.

```bash
cp -r skills/library/http-json agents/my-agent/.claude/skills/
```

Then add the skill to the table in your agent's `CLAUDE.md`. A skill the agent
doesn't know exists will never be invoked.

| Skill | What it covers |
|-------|----------------|
| `http-json` | Driving a JSON REST API with curl and jq: auth, status codes, pagination, rate limits. Start here when wrapping a new API. |
| `time` | Current time and timezone conversion via an MCP server. The worked example of the MCP registration pattern. |

More live inside the example agents — `agents/hello-world/.claude/skills/` and
`agents/orbit-analyst/.claude/skills/` — because a skill written against a
specific agent's job is usually better than a generic one.

## skills/workshop/ — helper skills for you

These are Claude Code skills. Open this repo in Claude Code and ask for what
you want in plain language; the right one loads itself.

| Skill | Ask for it by saying |
|-------|----------------------|
| `publish-agent` | "publish my agent", "ship this change" |
| `author-eval` | "write an eval for this", "add a test" |
| `run-eval` | "run the evals", "did that make it better?" |
| `mothership-cli` | "why did that command fail?", or any direct CLI question |

They exist to keep the docker-build, catalog-registration, version-promotion,
sandbox-recycling sequence out of your head. Each wraps a script you can also
run yourself:

```bash
./skills/workshop/publish-agent/publish.sh <agent>
./skills/workshop/run-eval/run.sh <agent>
python3 skills/workshop/author-eval/validate.py agents/<agent>/evals
```

Nothing is hidden — read the script the skill calls if you want to know
exactly what happened.

## Writing a good skill

Same advice for both kinds:

- **The `description` frontmatter is always in context; the body is not.** It
  is a routing decision, so write it as "what this retrieves, and when to
  reach for it." Everything else can be long.
- **Be specific enough to be checkable.** Real commands with real parameter
  values, real response shapes, and notes on the fields that are easy to
  misread. Vague guidance produces vague behavior.
- **Say what the skill does NOT support.** The section that stops an agent
  from improvising past its data is the one that makes it trustworthy.
- **Say what failure looks like** and what to report. An empty result is often
  a valid answer; a 500 never is.

`agents/_template/.claude/skills/example-skill/SKILL.md` has the full
structure with prompts for each section.
