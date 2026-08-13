# skills/

A library of agent skills to copy into an agent. They are files; copy them.

```bash
cp -r skills/http-json agents/my-agent/skills/
```

Then add the skill to the table in your agent's `CLAUDE.md`. A skill the agent
doesn't know exists will never be invoked — that is the single most common
bug in this repo.

| Skill | What it covers |
|-------|----------------|
| `http-json` | Driving a JSON REST API with curl and jq: auth, status codes, pagination, rate limits. Start here when wrapping a new API. |
| `time` | Current time and timezone conversion via an MCP server. The worked example of the MCP registration pattern. |

More live inside the example agents — `agents/hello-world/skills/` and
`agents/orbit-analyst/skills/` — because a skill written against a specific
agent's job is usually better than a generic one.

## The other skills directory

`.claude/skills/` at the repo root holds a different thing, and confusing the
two is easy. Both are Markdown files with the same shape. What differs is
**who reads them**.

| | `skills/` (here) | `.claude/skills/` (repo root) |
|---|---|---|
| Read by | The agent you built, running in a sandbox | Claude Code, on your laptop |
| Gets there via | You copy it into `agents/<name>/skills/` | Already there |
| Ships in the image | Yes | No |
| Example | "how to query a satellite catalog" | "how to publish an agent" |

The helper skills — `publish-agent`, `author-eval`, `run-eval`,
`mothership-cli` — keep the docker-build, catalog-registration,
version-promotion, sandbox-recycling sequence out of your head. Open the repo
in Claude Code and ask in plain language; the right one loads itself. Each
wraps a script you can also run yourself:

```bash
./.claude/skills/publish-agent/scripts/publish.sh <agent>
./.claude/skills/run-eval/scripts/run.sh <agent>
python3 .claude/skills/author-eval/scripts/validate.py agents/<agent>/evals
```

Nothing is hidden — read the script the skill calls if you want to know
exactly what happened.

## Skill directory layout

Both kinds use the same structure:

```
<skill-name>/
├── SKILL.md       required — frontmatter + the procedure
├── scripts/       optional — executables the skill invokes
└── references/    optional — detail loaded only when needed
```

`SKILL.md` is what gets read first. Put anything long and situational —
a full field reference, worked query examples, a table of error codes — in
`references/` and link to it from `SKILL.md`, so the agent pulls it in only
when the situation calls for it.

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

`agents/_template/skills/example-skill/SKILL.md` has the full structure with
prompts for each section.
