# Autocheck probe: observatory_health
# One file = one flow. Every step must answer 2xx/3xx within step_max_seconds.
# Runs every 30 min via the Hermes cron `autocheck-flows-sync`; result -> .planning/autocheck.json.
# @base_url: http://127.0.0.1:8765
# @step_max_seconds: 5.0

# @node: health
GET {{base_url}}/health
HTTP 200
