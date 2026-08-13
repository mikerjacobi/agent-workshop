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
`agents/quake-watch/skills/` — because a skill written against a specific
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
python3 .claude/skills/publish-agent/scripts/publish.py <agent>
python3 .claude/skills/run-eval/scripts/run.py <agent>
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

### Scripts are Python, and typed

Every script in this repo — agent-side and helper — follows the same three
rules. They are not style preferences; each one prevents a class of failure
that is expensive to debug through an agent.

1. **pydantic models at every interface.** No raw dicts crossing a function
   boundary, in either direction. The one exception is the line that feeds a
   model into an HTTP call or validates a response out of one.
2. **`pydantic-settings` for the CLI.** A `BaseModel` (or `BaseSettings`) with
   `CliApp.run`, so `--help` is generated from the same fields that validate
   the input, and defaults can come from the environment. Never `argparse`.
3. **No early exits.** Nothing calls `sys.exit()` mid-flow. Failures raise a
   custom exception deriving from one base, and exactly one handler in `main`
   turns that into a message and an exit code.
4. **Types are real, and checked.** No `TYPE_CHECKING` blocks, no deferred
   imports that exist only to make an error message prettier, no `x: type`
   holders the checker can't see through. `mypy` runs strict over
   `.claude/skills` and `agents`, configured in the root `pyproject.toml`:

   ```bash
   pip install mypy && mypy
   ```

   A rule that is only asserted is not a rule. That check is also why the
   vendored packages in `cli/` carry a `py.typed` marker — without it every
   model imported from them is `Any`, and a strict run passes while checking
   nothing.

`agents/quake-watch/skills/usgs-quakes/scripts/quakes.py` is the reference.
Its response models are the argument for the whole convention: the USGS feed
puts origin time in epoch *milliseconds* and hides depth as the third element
of a `[lon, lat, depth]` array. Typing those into `QuakeProperties` and
`QuakeGeometry` means each trap is gotten wrong once, in one place, instead of
every time an agent reads the JSON.

Agent-side scripts get `pydantic` and `pydantic-settings` from the image;
`agents/Dockerfile` installs them in a cached layer above the workspace copy.

Inline `curl` plus `jq` is still right for a one-off call the agent makes
directly. Reach for a script when there is a response shape worth typing.

### Path rules

**Write script paths from the workspace root, not relatively.** An agent's
working directory is the workspace, and a skill authored at
`agents/my-agent/skills/my-skill/` lands at `.claude/skills/my-skill/` inside
it. So `SKILL.md` should say
`.claude/skills/my-skill/scripts/thing.py`, not `./scripts/thing.py` — the
relative form only resolves if the agent happens to have changed directory
first. Give a `curl` fallback too, so a moved script degrades instead of
blocking. `agents/quake-watch/skills/usgs-quakes/SKILL.md` does both.

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
