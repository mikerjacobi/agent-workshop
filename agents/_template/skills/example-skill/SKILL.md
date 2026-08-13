---
name: example-skill
description: "One or two sentences the agent reads to decide whether to load this skill. Lead with what the skill retrieves or does, then the situations that should trigger it. This description is always in context; everything below it is not."
---

# <Skill name>

<!--
A skill is a procedure, not a topic. It gets loaded on demand, so it can be
long — but it earns its length by being specific.

Write these sections. Delete the ones that don't apply, and delete these
comments.
-->

## Setup

Anything the skill needs before its first call: an env var to read, an MCP
server to register, a tool to check for.

```bash
: "${SOME_KEY:?SOME_KEY is not set}"
```

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

## Reading the response

Show a real response shape and annotate the fields that are easy to misread —
units, time zones, one-vs-zero-indexed, "this looks like meters but is
kilometers." This section prevents most silent errors.

## What you may derive from this

The calculations the agent is allowed to do on the data, with the formulas
written out.

## What you may NOT derive from this

The adjacent conclusions the data cannot support, and what would be required
instead. This section is why a purpose-built agent beats a general one.

## When it fails

What the common failure responses look like (rate limit, bad key, empty
result) and what the agent should say about each. An empty result is usually
a valid answer, not an error — say so explicitly if that is true here.
