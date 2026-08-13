# Layout

Your identity is at `SOUL.md`. Who you are helping is at `USER.md`.

Your skills are auto-discovered from your workspace (authored under `skills/`
in the repo):

| Skill         | Use it for                                                      |
|---------------|-----------------------------------------------------------------|
| `geocode`     | Turning a place name into coordinates and a timezone            |
| `usgs-quakes` | Earthquakes near a point in a time window, from the USGS catalog |

Invoke a skill with the `Skill` tool (`Skill(skill="usgs-quakes")`) to pull
its instructions into your context.

Almost every question runs both, in order: `geocode` to get a point, then
`usgs-quakes` to search around it. Read `usgs-quakes` before you run it — the
response has three fields that are easy to misread, and it documents them.

## Runtime configuration

These come from the sandbox environment, declared as agent parameters in
`agent.json`. They are defaults, not limits — override them when the user asks
for something different, and say that you did.

| Env var                   | Default | What it is                                    |
|---------------------------|---------|-----------------------------------------------|
| `QUAKE_DEFAULT_RADIUS_KM` | `300`   | Search radius around the resolved point        |
| `QUAKE_MIN_MAGNITUDE`     | `2.5`   | Magnitude floor; below this is mostly noise a person would never feel |

Read them with `$QUAKE_DEFAULT_RADIUS_KM`. If unset, fall back to the defaults
above rather than failing.

## Working notes

Persistent scratch space lives under your working directory. Write the raw
GeoJSON to a file there before summarizing it — the feed is long, and the
file gives you something to re-read if the user asks a follow-up about an
event you already fetched.
