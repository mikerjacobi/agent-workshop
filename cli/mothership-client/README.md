# mothership-client

The Mothership wire contract and REST client, as one pip-installable package:
the pydantic models both the server and every client validate with, plus
`MothershipClient`.

This is a **vendored copy** for the workshop. Upstream is
`VulcanSkylight/mothership`, `packages/python/client`. Nothing here is
workshop-specific, so you can read it as the real contract.

```
cli/mothership-client/
└── src/mothership_client/
    ├── client.py                MothershipClient (REST + WS)
    ├── client_models/           envelope primitives (ApiOutputModel, filters)
    ├── models/                  wire models (thread, sandbox, message, eval_*, …)
    ├── bus_protocol.py          client-stream event schema
    └── validators.py            field validators shared by wire models
```

## Why the models are here

`mothership evals create tasks --body '<json>'` sends a JSON document the
server validates against `models/eval_spec.py`. When you want to know what
fields an eval task accepts, that file is the answer — not a doc page that
can drift from it. Same for agents (`models/agent_catalog.py`) and sandboxes
(`models/sandbox.py`).

## Rules

- **Import direction**: this package imports nothing but pydantic, httpx, and
  websockets. It never imports the server.
- **The server validates with these exact classes.** A wire change is a change
  here, reviewed as such.
