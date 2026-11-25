# Autocheck probe: mission_control_hub
# Mission Control on :8767 serves the hub page and its project catalog API.
# /api/hub/projects scans 70+ repos on demand (measured 4.4-6.6 s), hence the 15 s step SLA.
# @base_url: http://127.0.0.1:8767
# @step_max_seconds: 15

# @node: hub_page
GET {{base_url}}/hub
HTTP 200

# @node: hub_projects_api
GET {{base_url}}/api/hub/projects
HTTP 200
