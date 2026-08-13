# Layout

Your identity is at `SOUL.md`. Who you are helping is at `USER.md`.

Your skills are auto-discovered from `.claude/skills/`:

| Skill          | Use it for                                  |
|----------------|---------------------------------------------|
| `iss-position` | Where the ISS is right now, and its ground track |

Invoke a skill with the `Skill` tool (`Skill(skill="iss-position")`) to pull
its instructions into your context. Skills are read on demand — you are not
holding all of them at once, which is the point.

Persistent scratch space lives under your working directory.
