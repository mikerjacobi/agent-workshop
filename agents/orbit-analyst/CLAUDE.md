# Layout

Your identity is at `SOUL.md`. Who you are helping is at `USER.md`.

Your skills are auto-discovered from your workspace (authored under `skills/` in the repo):

| Skill           | Use it for                                                        |
|-----------------|-------------------------------------------------------------------|
| `celestrak-tle` | Two-line element sets by satellite name or NORAD ID, and what you can derive from them |
| `space-weather` | Solar flares, CMEs, and geomagnetic storms from NASA DONKI        |

Invoke a skill with the `Skill` tool (`Skill(skill="celestrak-tle")`) to pull
its instructions into your context. Read the skill before you run its
commands — the endpoints have rate limits and query-parameter rules that are
easy to get wrong from memory.

## Runtime configuration

These come from the sandbox environment, declared as agent parameters in
`agent.json`:

| Env var        | What it is                                                    |
|----------------|---------------------------------------------------------------|
| `NASA_API_KEY` | Key for `api.nasa.gov`. Defaults to `DEMO_KEY`, which is heavily rate-limited. |

Read them with `$NASA_API_KEY`. Never print their values back to the user.

## Working notes

Persistent scratch space lives under your working directory. When a question
takes more than one lookup, write intermediate results to a file there rather
than holding them in your head — it makes your arithmetic auditable, which is
what this agent is for.
