# Mothership CLI

Command-line interface for chatting with agents, sending messages, and managing sandboxes.

## Install

From the repo root:

```bash
pip install -e . -r requirements-dev.txt
```

## Quick Start

```bash
# 1. Create a profile
mothership profile set local \
  --base-url http://localhost:5100 \
  --external-id mike \
  --agent-id shippy-openclaw \
  --max-local-sandboxes 1

# 2. Chat
mothership chat

# 3. One-shot
mothership chat --print "what vessels are near Hawaii?"

# 4. Send via REST (non-interactive)
mothership messages submit "summarize recent activity"
```

## Profiles

Profiles store connection settings and defaults. The first profile created becomes the default.

```bash
mothership profile list
mothership profile set-default prod
```

You can skip profiles entirely with `MOTHERSHIP_BASE_URL` env var.

## Identity and orgs

Every request asserts an identity via the `X-External-Id` header, taken from
`--external-id`, the profile's `default_external_id`, or `MOTHERSHIP_EXTERNAL_ID`.
Against a server with no IdP configured this is taken at face value and the user
is provisioned on first use; it is an assertion, not a credential. Set
`MOTHERSHIP_API_KEY` to send a real org API key as a bearer token instead — the
server accepts those regardless of IdP configuration.

Tenancy-scoped resources (agents, sandboxes, threads, messages, feedback, files,
attachments) live under `/api/orgs/{org_id}/…`. Everything else — users, models,
config, me, agent-versions — is flat.

The org defaults to the shared default org that every user is enrolled into, so
a single-org deployment needs no org configuration at all. The default is that
org's *id* rather than its `default` slug alias: both address the same org, but
the id also works against a server that predates the alias. Override it
per-invocation or per-profile:

```bash
mothership --org org_abc123 sandboxes search
mothership profile set prod --base-url https://… --org org_abc123
```

`MOTHERSHIP_ORG` works too.

Pass `-p <name>` to target a specific profile:

```bash
mothership -p int chat --print "hello"
```

### `max_local_sandboxes`

When set, the CLI stops the oldest sandboxes before creating a new one to keep
Docker resource usage bounded. Set to `1` for local dev. Leave unset for
remote environments.

## Chat

Interactive TUI with streaming responses:

```bash
mothership chat
mothership chat --agent-id shippy-openclaw --external-id mike
```

One-shot mode prints the response and exits:

```bash
mothership chat --print "what is Skylight?"
```

Resume a previous thread:

```bash
mothership chat --thread-id thrd_abc123
mothership chat --thread-id thrd_abc123 "follow-up question"
```

Verbosity: `-v 1` for status, `-v 2` for thinking/tool calls, `-v 3` for raw frames.

## Messages

Send a message via REST and poll for the response:

```bash
mothership messages submit "hello"
mothership messages submit "continue" --thread-id thrd_abc123
mothership messages submit "fire and forget" --fire-and-forget
```

Search messages:

```bash
mothership messages search --thread-id thrd_abc123
```

## Sandboxes

```bash
mothership sandboxes search
mothership sandboxes search --state.eq running
mothership sandboxes create shippy-openclaw
mothership sandboxes stop <sandbox-id>
```

## Threads

```bash
mothership threads search
mothership threads search --external-id mike
```

## Agents

```bash
mothership agents search
mothership agents create --agent-id my-agent --name "My Agent" --harness openclaw --image my-agent:latest
mothership agents update my-agent --default-model litellm/opus-4.6
mothership agents delete my-agent
```

## Tracing HTTP calls

Pass `--verbose` before the subcommand to write every REST call the CLI makes to
stderr — method, URL, headers, and pretty-printed request/response bodies. The
`Authorization` bearer token is redacted in the trace; the real token still goes
out on the wire.

```bash
mothership --verbose sandboxes search --state.eq running
```

```
→ POST http://localhost:5100/api/orgs/org_c21f969b5f03/sandboxes/search
  Content-Type: application/json
  X-External-Id: josh
  Authorization: Bearer ***redacted***
  {
    "limit": 100,
    "state": {"eq": "running"}
  }
← 200 OK (0.031s)
  {
    "records": [],
    "meta": {"total": 0}
  }
```

Failed responses are traced too, before the error is raised. This covers REST
only — for the coordinator WebSocket frames behind `mothership chat`, use
`chat -vvv`.

## JSON Output

Pass `--json` before the subcommand:

```bash
mothership --json threads search
mothership --json sandboxes search --state.eq running
```
