# Autocheck probes

One `.hurl` file = one flow. Every step must answer 2xx/3xx within `@step_max_seconds`.
The Hermes cron `autocheck-flows-sync` (every 30 min) runs all probes of every project registered
in the JIT hub and writes the result to `.planning/autocheck.json` (shown in `.planning/state.html`).

```
# @base_url: http://127.0.0.1:8000
# @step_max_seconds: 5

# @node: health
GET {{base_url}}/health
HTTP 200
```

Commands (engine: `~/Projects/active/autocheck`, `python3 -m autocheck_flow ...`):

- `scaffold <project> --url <real health URL> [--flow-id health]` - create a probe for one URL
- `probe <project> [--write]` - run the probes now (exit 1 when any flow is not ok)

Rules: probe real, running endpoints only; no placeholder URLs; no secrets in `.hurl` files.
