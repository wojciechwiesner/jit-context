#!/usr/bin/env bash
# Builds the A/B fixture repo used by bench/ab.py.
# Usage: bash bench/setup-fixture.sh   (then: bun run build && python3 bench/ab.py 4)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
R="${AB_FIXTURE:-$HOME/.hermes/cache/scratch/ab-shopapi}"

if [ -e "$R" ]; then
  echo "Fixture already exists at $R. Remove it manually to rebuild." >&2
  exit 1
fi
mkdir -p "$R"/{api/routes,api/services,api/models,web/src,.planning,docs}
cd "$R" && git init -q

cat > api/routes/orders.py <<'EOF'
from fastapi import APIRouter
from api.services.billing import charge_order
router = APIRouter()

@router.post("/orders/{order_id}/pay")
async def pay(order_id: int):
    return await charge_order(order_id)
EOF
cat > api/routes/hooks.py <<'EOF'
from fastapi import APIRouter, Request
from api.services.payments_events import handle_event
router = APIRouter()

@router.post("/integrations/incoming")
async def incoming(request: Request):
    return await handle_event(await request.body(), request.headers)
EOF
cat > api/services/billing.py <<'EOF'
async def charge_order(order_id: int):
    """Create a payment intent for the order."""
    return {"order_id": order_id, "status": "pending"}
EOF
cat > api/services/payments_events.py <<'EOF'
import json

async def handle_event(raw: bytes, headers):
    # TODO: verify provider signature before trusting payload
    event = json.loads(raw)
    if event.get("type") == "payment_intent.succeeded":
        return {"ok": True}
    return {"ignored": event.get("type")}
EOF
cat > api/models/order.py <<'EOF'
from dataclasses import dataclass

@dataclass
class Order:
    id: int
    total_cents: int
    status: str = "new"
EOF
echo 'export const App = () => null' > web/src/App.tsx
printf '# ShopAPI\nFastAPI backend + React web.\n' > README.md
printf '# Deploy\nDocker.\n' > docs/deploy.md
cat > .planning/STATE.md <<'EOF'
# STATE
Current focus: Phase 3 - payment webhooks
Blocker: provider signature is not verified in api/services/payments_events.py (endpoint /integrations/incoming).
EOF
git add -A && git commit -qm init
echo ".jit.db*" >> .git/info/exclude

# Plugin on, Observatory pointed at a dead port (pure L0 path), global jit-context MCP disabled
# so the "without" variant cannot reach the same memory through MCP.
cat > opencode.json <<EOF
{ "\$schema": "https://opencode.ai/config.json",
  "plugin": [["file://$ROOT/dist/index.js", {"dbPath": "$R/.jit.db", "observatoryUrl": "http://127.0.0.1:1"}]],
  "mcp": { "jit-context": { "type": "local", "command": ["true"], "enabled": false } } }
EOF

# Decision recorded by an earlier session. It exists nowhere in the code.
cd "$ROOT" && bun -e "
import { L0Store } from './src/l0'
new L0Store('$R/.jit.db').record(
  'Decision 2026-09-20: webhook secret is read from env PAYWALL_WH_SECRET (never hardcode), rotation owner: Klaudia',
  '$(basename "$R")', 'prev-session', 'opencode:build')"
echo "Fixture ready at $R"
