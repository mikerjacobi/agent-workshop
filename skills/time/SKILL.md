---
name: time
description: "Current time and timezone conversion. Use when the user asks what time it is, asks about time in a specific city or timezone, or wants to convert times between timezones."
---

# Time

This skill uses the [`mcp-server-time`](https://pypi.org/project/mcp-server-time/) MCP server. No API key, no auth.

## Register the server (once per session)

```bash
mcporter config add time --command uvx --arg mcp-server-time
```

Idempotent to re-run, but you only need it once per session. If subsequent tool calls return "Unknown tool", re-run this registration.

## Tools

Invoke via `mcporter call time.<tool_name> --args '{...}'` from `Bash`, or via the runtime's MCP tool dispatch (naming convention varies: Claude Code prefixes with `mcp__time__`, zeroclaw with `time__`).

### `get_current_time`

Get the current time in a specific timezone (or the system default).

Arguments:
- `timezone` (string, optional) — IANA timezone name like `Europe/London`. If omitted, returns system local time.

Returns something like:
```json
{
  "timezone": "America/Los_Angeles",
  "datetime": "2026-04-18T17:33:50-07:00",
  "day_of_week": "Saturday",
  "is_dst": true
}
```

### `convert_time`

Convert a time from one timezone to another. Arguments:
- `source_timezone` (string, required) — IANA timezone of the input time
- `time` (string, required) — 24-hour format, `HH:MM`
- `target_timezone` (string, required) — IANA timezone to convert to

## Common timezone names

| City | IANA |
|------|------|
| New York | `America/New_York` |
| Los Angeles / Seattle | `America/Los_Angeles` |
| London | `Europe/London` |
| Paris | `Europe/Paris` |
| Tokyo | `Asia/Tokyo` |
| Sydney | `Australia/Sydney` |
| Auckland | `Pacific/Auckland` |
| Dubai | `Asia/Dubai` |
| Singapore | `Asia/Singapore` |
| Honolulu | `Pacific/Honolulu` |
| UTC | `UTC` |

## Tips

- **You must call the tool to answer.** Do not invent times from context or memory — the current time changes every second.
- If a tool call returns "Unknown tool" with a `mcp__`-prefixed name, drop the prefix and try again — different runtimes register MCP tools under different prefixes.
- Use IANA names, not abbreviations like "EST" or "PST" (those are ambiguous).
- Map city → IANA yourself. Ask for clarification only if genuinely ambiguous.
