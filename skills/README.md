# skills/

The Mothership interactions, written as instructions rather than code. Each
one is a procedure over the `mothership` CLI: what to run, in what order, and
what the failures mean.

| Skill | Use it when |
|-------|-------------|
| [`publish-agent`](publish-agent/SKILL.md) | Building an agent directory and making it the live version |
| [`run-eval`](run-eval/SKILL.md) | Syncing eval tasks, running them, reading the scores |
| [`author-eval`](author-eval/SKILL.md) | Writing an eval task file the judge can actually apply |
| [`mothership-cli`](mothership-cli/SKILL.md) | Any direct CLI question, or a command that failed |

Read them yourself, or point Claude Code at one and ask in plain language.
They deliberately ship no scripts — the CLI is the tool, and a wrapper would
just be one more thing that can drift from it.

Requires `jq` and the `mothership` CLI (`pip install -e cli/mothership-client
-e cli/mothership-cli`).

## The other skills directory

`agents/<name>/skills/` holds skills belonging to **that agent** — the
procedures it loads at runtime, baked into its image. Same file format,
different reader.

| | `skills/` (here) | `agents/<name>/skills/` |
|---|---|---|
| Read by | You, and Claude Code on your laptop | The agent you built, in a sandbox |
| Purpose | Drive the dev loop | Do the agent's job |
| Ships in the image | No | Yes |
| Example | "how to publish an agent" | "how to query the USGS catalog" |

## Skill directory layout

Both kinds use the same structure:

```
<skill-name>/
├── SKILL.md       required — frontmatter + the procedure
├── scripts/       optional — executables the skill invokes
└── references/    optional — detail loaded only when needed
```

`SKILL.md` is read first. Put anything long and situational — a full field
reference, worked query examples, a table of error codes — in `references/`
and link to it, so it is pulled in only when the situation calls for it.
`agents/quake-watch/skills/usgs-quakes/` uses all three.

## Writing a good skill

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

## When an agent skill needs a script

Inline `curl` and `jq` is right for a one-off call. Reach for a script only
when the response has a shape worth typing — misleading units, a value buried
somewhere unexpected, an enum to map.

`agents/quake-watch/skills/usgs-quakes/scripts/quakes.py` is the reference,
and the argument for the convention: the USGS feed puts origin time in epoch
*milliseconds* and hides depth as the third element of a `[lon, lat, depth]`
array. Typing those into pydantic models means each trap is gotten wrong once,
in one place, instead of every time an agent reads the JSON.

Such scripts follow four rules:

1. **pydantic models at every interface** — no raw dicts across a function
   boundary, except the line that feeds a model into a call or validates a
   response out of one.
2. **`pydantic-settings` for the CLI**, so `--help` comes from the same fields
   that validate the input. Never `argparse`.
3. **No early exits.** Failures raise a custom exception from one base;
   exactly one handler in `main` turns it into a message and an exit code.
4. **Types are real, and checked.** No `TYPE_CHECKING` blocks, no deferred
   imports to prettify an error. `mypy` runs strict over `agents`, configured
   in the root `pyproject.toml`:

   ```bash
   pip install mypy && mypy
   ```

Write script paths from the workspace root: a skill authored at
`agents/my-agent/skills/my-skill/` lands at `.claude/skills/my-skill/` inside
the running agent, so say `.claude/skills/my-skill/scripts/thing.py`, not
`./scripts/thing.py`. Give a `curl` fallback so a moved script degrades
instead of blocking.

`agents/Dockerfile` installs `pydantic` and `pydantic-settings` into the image
in a cached layer.
