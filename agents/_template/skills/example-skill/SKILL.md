---
name: example-skill
description: "One or two sentences the agent reads to decide whether to load this skill. Lead with what the skill retrieves or does, then the situations that should trigger it. This description is always in context; everything below it is not."
---

# <Skill name>

<!--
A skill is a procedure, not a topic. It gets loaded on demand, so it can be
long — but it earns its length by being specific.

Write these sections. Delete the ones that don't apply, and delete these
comments. The guidance below is written for a JSON REST API because that is
the common case; adapt it if yours is something else.
-->

## Setup

Anything the skill needs before its first call: an env var to read, an MCP
server to register, a tool to check for.

Read credentials from the environment, never inline. Declare the key as an
agent parameter in `agent.json` first, then:

```bash
: "${SOME_KEY:?SOME_KEY is not set}"
```

The `:?` form fails loudly with the variable's name instead of silently
sending an empty header. Never echo the value back to the user.

If this skill ships a script under `scripts/`, reference it from the workspace
root — `.claude/skills/example-skill/scripts/thing.py` — not as
`./scripts/thing.py`. The relative form only resolves if the agent happens to
be in the skill directory, which it usually isn't.

## The calls

The exact commands, with real parameter values, not placeholders the agent has
to invent.

```bash
curl -s "https://example.org/api/thing?id=123" | jq
```

Capture the status code rather than piping a bare `curl` into `jq` — an HTML
error page hitting `jq` produces a confusing parse failure instead of a clear
403:

```bash
response=$(curl -s -w '\n%{http_code}' "https://example.org/api/thing?id=123")
status=$(tail -n1 <<<"$response")
body=$(sed '$d' <<<"$response")
```

## Reading the response

Show a real response shape and annotate the fields that are easy to misread —
units, time zones, one-vs-zero-indexed, "this looks like meters but is
kilometers." This section prevents most silent errors.

Pull the fields you need rather than dumping the whole document into context:

```bash
curl -s "https://example.org/api/things" | jq '[.items[] | {id, name, updated: .updated_at}]'
```

If the response has a shape worth typing — misleading units, a value buried
somewhere unexpected, an enum to map — write a script under `scripts/` with
pydantic models instead of re-deriving it in `jq` every call. See
`agents/quake-watch/skills/usgs-quakes/` for the worked example and
`skills/README.md` for the conventions those scripts follow.

## What you may derive from this

The calculations the agent is allowed to do on the data, with the formulas
written out.

## What you may NOT derive from this

The adjacent conclusions the data cannot support, and what would be required
instead. This section is why a purpose-built agent beats a general one.

## Pagination and rate limits

Don't fetch every page reflexively. Get the first page, look at the total, and
decide — and say what you're about to pull if it's large.

On HTTP 429: stop. Report the limit and when it resets. Never retry in a loop;
against a shared key that degrades the service for everyone else.

## When it fails

What the common failure responses look like and what the agent should say
about each:

| Status | Meaning | What to say |
|--------|---------|-------------|
| 401 / 403 | Key missing, invalid, or unscoped | Name the env var and that it was rejected — never print the value |
| 404 | The resource doesn't exist | Say so; don't substitute a guess |
| 429 | Rate limited | Report the limit and reset time; stop |
| 5xx | Upstream failure | Report it as an upstream failure, not as absent data |

The distinction that matters most: **an empty result is not the same as a
failure.** An empty list is often the correct answer. A 5xx never is. If that
is true for your API, say so explicitly here.

Never fall back to answering from memory. A confident wrong answer is worse
than a reported failure, because the user can retry a failure.
