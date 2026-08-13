---
name: http-json
description: "How to drive a JSON REST API from the shell with curl and jq: authentication, pagination, rate limits, and what to do when a call fails. Use as a starting point when writing a skill around a new HTTP API."
---

# Driving a JSON API

This is a pattern skill. Copy it, rename it, and replace the example endpoint
with your own — the structure is what's worth keeping.

`curl`, `jq`, and `python3` are on your PATH.

## curl inline, or a script?

Inline `curl` plus `jq` is right for a one-off call: one endpoint, a couple of
fields, nothing subtle in the response.

Write a script under the skill's `scripts/` instead when the response has a
shape worth typing — units that mislead, a field buried somewhere unexpected,
an enum that has to be mapped. A pydantic model gets each of those wrong once,
where it can be fixed, rather than every time the JSON is read. See
`agents/quake-watch/skills/usgs-quakes/scripts/quakes.py` for the reference
shape and `skills/README.md` for the conventions those scripts follow.

## Read credentials from the environment

Never inline a key. Declare it as an agent parameter in `agent.json`, then:

```bash
: "${EXAMPLE_API_KEY:?EXAMPLE_API_KEY is not set}"
```

The `:?` form fails loudly with the variable name instead of silently sending
an empty header. Never echo the value back to the user, and never write it to
a file in your workspace.

Header auth:

```bash
curl -s -H "Authorization: Bearer $EXAMPLE_API_KEY" "https://api.example.org/v1/things"
```

Query-parameter auth (some public APIs, including `api.nasa.gov`):

```bash
curl -s "https://api.example.org/v1/things?api_key=$EXAMPLE_API_KEY"
```

## Always capture the status code

A bare `curl -s` swallows HTTP errors — you get an HTML error page piped into
`jq`, and a confusing parse failure instead of a clear 403. Capture both:

```bash
response=$(curl -s -w '\n%{http_code}' "https://api.example.org/v1/things")
status=$(tail -n1 <<<"$response")
body=$(sed '$d' <<<"$response")
echo "status=$status"
```

Then branch on `$status` before parsing.

## Shape the output before you read it

Pull the fields you need rather than dumping the whole document into your
context. A 400-line JSON response spends context you will want later.

```bash
curl -s "https://api.example.org/v1/things" \
  | jq '[.items[] | {id, name, updated: .updated_at}]'
```

Aggregate in `jq` when you can — it is cheaper and less error-prone than
summing numbers yourself:

```bash
jq '[.items[].mass_kg] | add'
```

## Pagination

Do not fetch every page reflexively. Fetch the first page, look at the total,
and decide:

```bash
curl -s "https://api.example.org/v1/things?limit=100&offset=0" | jq '{total: .meta.total, got: (.items | length)}'
```

If the total is large, tell the user what you're about to pull and roughly how
long it will take before you start. If you only need an aggregate, check
whether the API can compute it server-side first.

## Rate limits

Read the response headers when they carry a budget:

```bash
curl -sI "https://api.example.org/v1/things" | grep -i 'x-ratelimit'
```

On HTTP 429: stop. Report the limit and when it resets. Do not retry in a
loop — a retry loop against a shared key degrades the service for everyone
else using it, and the user would rather know the limit is exhausted.

## Status codes worth handling by name

| Status | What it means here | What to say |
|--------|--------------------|-------------|
| 401 / 403 | Key missing, invalid, or lacking scope | Name the env var and that it was rejected — never print the value |
| 404 | The resource doesn't exist | Say so; don't substitute a guess |
| 429 | Rate limited | Report the limit and reset time; stop |
| 5xx | Upstream failure | Report it as an upstream failure, not as an absence of data |

The distinction that matters most: **404 and an empty result are not the same
as "the answer is no."** An empty list is often the correct answer ("no flares
above background this week"). A 5xx is never an answer.

## When it fails

Report the URL you called (with the key redacted), the status code, and the
first line of the body. Do not answer the original question from memory as a
fallback — a wrong answer that looks confident is worse than a reported
failure, and the user can retry.
