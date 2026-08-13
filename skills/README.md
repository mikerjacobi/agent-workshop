# skills/

The Mothership interaction skills — the dev loop, wrapped so you don't have to
hold the docker-build, catalog-registration, version-promotion,
sandbox-recycling sequence in your head.

| Skill | Ask for it by saying | What it wraps |
|-------|----------------------|---------------|
| `publish-agent` | "publish my agent", "ship this change" | `scripts/publish.py` |
| `run-eval` | "run the evals", "did that make it better?" | `scripts/run.py` |
| `author-eval` | "write an eval for this", "add a test" | `scripts/validate.py` |
| `mothership-cli` | "why did that command fail?" | reference only, no script |

Open the repo in Claude Code and ask in plain language; the right one loads
itself. Or run the scripts directly — nothing is hidden:

```bash
python3 skills/publish-agent/scripts/publish.py <agent>
python3 skills/run-eval/scripts/run.py <agent>
python3 skills/author-eval/scripts/validate.py agents/<agent>/evals
```

> `.claude/skills` is a symlink to this directory. It is the only path Claude
> Code scans for skills, and the symlink is the whole reason `.claude/`
> exists. Delete it and the scripts still work; you just have to name them
> yourself instead of asking in plain language.

## The other skills directory

`agents/<name>/skills/` holds skills belonging to **that agent** — the
procedures it loads at runtime, baked into its image. Same file format,
different reader.

| | `skills/` (here) | `agents/<name>/skills/` |
|---|---|---|
| Read by | Claude Code, on your laptop | The agent you built, in a sandbox |
| Purpose | Drive the dev loop | Do the agent's job |
| Ships in the image | No | Yes |
| Example | "how to publish an agent" | "how to query the USGS catalog" |

Start a new agent skill from `agents/_template/skills/example-skill/SKILL.md`,
which has the full structure with prompts for each section.

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
and link to it from `SKILL.md`, so it is pulled in only when the situation
calls for it. `agents/quake-watch/skills/usgs-quakes/` uses all three.

## Scripts are Python, and typed

Every script in this repo — agent-side and here — follows the same four
rules. They are not style preferences; each prevents a class of failure that
is expensive to debug through an agent.

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
   imports that exist only to prettify an error message, no `x: type` holders
   the checker can't see through. `mypy` runs strict over `skills` and
   `agents`, configured in the root `pyproject.toml`:

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
of a `[lon, lat, depth]` array. Typing those means each trap is gotten wrong
once, in one place, instead of every time an agent reads the JSON.

Agent-side scripts get `pydantic` and `pydantic-settings` from the image;
`agents/Dockerfile` installs them in a cached layer above the workspace copy.

Inline `curl` plus `jq` is still right for a one-off call an agent makes
directly. Reach for a script when there is a response shape worth typing.

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
- **Write script paths from the workspace root.** A skill authored at
  `agents/my-agent/skills/my-skill/` lands at `.claude/skills/my-skill/` inside
  the running agent's workspace, so say
  `.claude/skills/my-skill/scripts/thing.py`, not `./scripts/thing.py` — the
  relative form only resolves if the agent already changed directory. Give a
  `curl` fallback so a moved script degrades instead of blocking.
