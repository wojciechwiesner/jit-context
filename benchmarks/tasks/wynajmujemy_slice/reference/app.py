"""Reference implementation. Not part of the agent workspace."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def _hash(fields: dict) -> str:
    raw = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_now(value: Optional[str]) -> datetime:
    if not value:
        return datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _blank_price(source: str) -> dict:
    return {"amount": None, "currency": "PLN", "period": None, "source": source}


def _fields(text: str, source: str, price: Optional[dict], media: list) -> dict:
    title = (text or "imported").strip()[:80] or "imported"
    stored_price = _blank_price(source)
    if price and price.get("period"):
        stored_price = {
            "amount": price.get("amount"),
            "currency": price.get("currency") or "PLN",
            "period": price.get("period"),
            "source": price.get("source") or source,
        }
    return {
        "title": {"value": title, "source": source},
        "text": {"value": text or "", "source": source},
        "price": stored_price,
        "equipment": {"sink": "unknown", "parking": "unknown"},
        "media": media or [],
    }


def _ambiguous(text: str, price: Optional[dict]) -> bool:
    if price and price.get("period"):
        return False
    lowered = (text or "").lower()
    has_amount = any(ch.isdigit() for ch in lowered)
    has_currency = "pln" in lowered or "zł" in lowered
    return has_amount and has_currency


class Store:
    def __init__(self, seed: Optional[dict], fetcher, sender):
        seed = seed or {}
        self.now = _parse_now(seed.get("now"))
        self.users = {u["token"]: u for u in seed.get("users", [])}
        self.by_id = {u["id"]: u for u in seed.get("users", [])}
        olx = {
            "discovery": False,
            "fetch": False,
            "media": False,
            "republish": False,
            "outbound": False,
        }
        olx.update((seed.get("policies") or {}).get("olx") or {})
        self.policies = {"olx": olx}
        self.fetcher = fetcher
        self.sender = sender
        self.imports = {}
        self.listings = {}
        self.inquiries = {}
        self.jobs = []
        self.receipts = {}
        self.idem = {}
        self.prefs = {}
        self.seq = 0

    def set_now(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self.now = dt.astimezone(timezone.utc)

    def next_id(self, prefix: str) -> str:
        self.seq += 1
        return f"{prefix}_{self.seq}"

    def user(self, request: Request):
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else ""
        return self.users.get(token)

    def counts(self) -> dict:
        return {
            "imports": len(self.imports),
            "listings": len(self.listings),
            "outbox": len(self.jobs),
            "authorizations": 0,
        }


def create_app(*, seed=None, fetcher=None, sender=None):
    store = Store(seed, fetcher, sender)
    app = FastAPI()
    app.state.set_now = store.set_now
    app.state.fetcher = fetcher
    app.state.store = store

    def err(code: str, status: int):
        return JSONResponse({"error": code}, status_code=status)

    def owner_listing(request: Request, listing_id: str):
        user = store.user(request)
        listing = store.listings.get(listing_id)
        if not user or not listing or listing["owner_id"] != user["id"]:
            return None, err("not_found", 404)
        return listing, None

    def public_item(listing: dict) -> dict:
        return {
            "id": listing["id"],
            "state": listing["state"],
            "title": listing["fields"]["title"]["value"],
            "equipment": listing["fields"]["equipment"],
        }

    def owner_body(listing: dict) -> dict:
        return {
            "id": listing["id"],
            "state": listing["state"],
            "version": listing["version"],
            "draft_hash": listing["draft_hash"],
            "approved_hash": listing["approved_hash"],
            "profile": listing["profile"],
            "fields": listing["fields"],
            "contact_email": listing["contact_email"],
            "confirmed_at": listing["confirmed_at"],
            "paid": False,
            "source_type": listing["source_type"],
        }

    def has_imported(listing: dict) -> bool:
        fields = listing["fields"]
        for key in ("title", "text", "price"):
            if fields[key].get("source") == "source_import":
                return True
        return False

    def ai_forbidden(fields: dict) -> bool:
        banned = {"price", "equipment", "parking", "access", "certificates", "availability"}

        def walk(node, key):
            if isinstance(node, dict) and node.get("source") == "ai_suggestion" and key in banned:
                return True
            if isinstance(node, dict):
                return any(walk(value, child) for child, value in node.items())
            return False

        return any(walk(value, key) for key, value in fields.items())

    @app.get("/r/{code}")
    def referral(code: str):
        return {"ok": True, "channel": code, "imported": False, "published": False}

    @app.get("/api/admin/counts")
    def counts(request: Request):
        user = store.user(request)
        if not user or user["role"] != "admin":
            return err("not_found", 404)
        return store.counts()

    @app.get("/api/admin/policies")
    def policies(request: Request):
        user = store.user(request)
        if not user or user["role"] != "admin":
            return err("not_found", 404)
        return store.policies

    @app.get("/api/admin/outbox")
    def outbox(request: Request):
        user = store.user(request)
        if not user or user["role"] != "admin":
            return err("not_found", 404)
        return {"jobs": store.jobs}

    @app.post("/api/admin/source-policies/{source}/enable")
    async def enable_policy(source: str, request: Request):
        user = store.user(request)
        if not user or user["role"] != "admin":
            return err("not_found", 404)
        body = await request.json()
        if not body.get("evidence_id"):
            return err("missing_evidence", 422)
        policy = store.policies.setdefault(source, {
            "discovery": False, "fetch": False, "media": False, "republish": False, "outbound": False,
        })
        if "fetch" in body:
            policy["fetch"] = bool(body["fetch"])
        if "republish" in body:
            policy["republish"] = bool(body["republish"])
        return policy

    @app.post("/api/imports")
    async def create_import(request: Request):
        user = store.user(request)
        if not user or user["role"] != "host":
            return err("unauthorized", 401)
        key = request.headers.get("idempotency-key")
        if not key:
            return err("missing_idempotency_key", 400)
        idem_key = (user["id"], key)
        if idem_key in store.idem:
            return store.idem[idem_key]
        body = await request.json()
        source_type = body.get("source_type")
        if source_type == "olx":
            policy = store.policies["olx"]
            if not policy.get("fetch"):
                payload = {
                    "id": store.next_id("imp"),
                    "status": "blocked",
                    "listing_id": None,
                    "hint": "paste_own_text",
                    "fetch_count": 0,
                }
                store.imports[payload["id"]] = {**payload, "owner_id": user["id"]}
                store.idem[idem_key] = payload
                return payload
            url = body.get("source_url")
            if store.fetcher is None:
                return err("fetcher_missing", 500)
            status, _page = store.fetcher.fetch(url)
            if status == 403:
                payload = {
                    "id": store.next_id("imp"),
                    "status": "blocked",
                    "listing_id": None,
                    "hint": None,
                    "fetch_count": 1,
                }
                store.imports[payload["id"]] = {**payload, "owner_id": user["id"]}
                store.idem[idem_key] = payload
                return payload
            fields = _fields(body.get("text") or _page, "source_import", None, body.get("media") or [])
            listing_id = store.next_id("lst")
            listing = {
                "id": listing_id,
                "owner_id": user["id"],
                "state": "awaiting_owner",
                "version": 1,
                "fields": fields,
                "draft_hash": _hash(fields),
                "approved_hash": None,
                "profile": body.get("profile") or "general",
                "contact_email": body.get("contact_email"),
                "confirmed_at": None,
                "source_type": "olx",
                "available_from": body.get("available_from"),
            }
            store.listings[listing_id] = listing
            payload = {
                "id": store.next_id("imp"),
                "status": "ready",
                "listing_id": listing_id,
                "hint": None,
                "fetch_count": 1,
            }
            store.imports[payload["id"]] = {**payload, "owner_id": user["id"]}
            store.idem[idem_key] = payload
            return payload

        text = body.get("text") or ""
        price = body.get("price")
        ambiguous = _ambiguous(text, price)
        source = "host"
        fields = _fields(text, source, None if ambiguous else price, body.get("media") or [])
        listing_id = store.next_id("lst")
        state = "draft" if ambiguous or not (price and price.get("period")) else "awaiting_owner"
        if ambiguous:
            state = "draft"
        listing = {
            "id": listing_id,
            "owner_id": user["id"],
            "state": state,
            "version": 1,
            "fields": fields,
            "draft_hash": _hash(fields),
            "approved_hash": None,
            "profile": body.get("profile") or "general",
            "contact_email": body.get("contact_email"),
            "confirmed_at": None,
            "source_type": "owner_materials",
            "available_from": body.get("available_from"),
        }
        store.listings[listing_id] = listing
        status_name = "needs_input" if ambiguous or state == "draft" else "ready"
        payload = {
            "id": store.next_id("imp"),
            "status": status_name,
            "listing_id": listing_id,
            "hint": None,
            "fetch_count": 0,
        }
        store.imports[payload["id"]] = {**payload, "owner_id": user["id"]}
        store.idem[idem_key] = payload
        return payload

    @app.get("/api/imports/{import_id}")
    def get_import(import_id: str, request: Request):
        user = store.user(request)
        row = store.imports.get(import_id)
        if not user or not row or row["owner_id"] != user["id"]:
            return err("not_found", 404)
        return {k: row[k] for k in ("id", "status", "listing_id", "hint", "fetch_count")}

    @app.patch("/api/listings/{listing_id}/draft")
    async def patch_draft(listing_id: str, request: Request):
        listing, denied = owner_listing(request, listing_id)
        if denied:
            return denied
        body = await request.json()
        if body.get("expected_version") != listing["version"]:
            return err("version_conflict", 409)
        fields_patch = body.get("fields") or {}
        if ai_forbidden(fields_patch):
            return err("undocumented_field", 422)
        for key, value in fields_patch.items():
            if key in listing["fields"] and isinstance(value, dict):
                listing["fields"][key] = value
        listing["version"] += 1
        listing["draft_hash"] = _hash(listing["fields"])
        listing["approved_hash"] = None
        return owner_body(listing)

    @app.post("/api/listings/{listing_id}/approve")
    async def approve(listing_id: str, request: Request):
        listing, denied = owner_listing(request, listing_id)
        if denied:
            return denied
        body = await request.json()
        if body.get("expected_version") != listing["version"] or body.get("draft_hash") != listing["draft_hash"]:
            return err("version_conflict", 409)
        listing["approved_hash"] = listing["draft_hash"]
        return owner_body(listing)

    @app.post("/api/listings/{listing_id}/publish")
    async def publish(listing_id: str, request: Request):
        listing, denied = owner_listing(request, listing_id)
        if denied:
            return denied
        body = await request.json()
        if body.get("expected_version") != listing["version"] or body.get("draft_hash") != listing["draft_hash"]:
            return err("version_conflict", 409)
        if listing["approved_hash"] != listing["draft_hash"]:
            return err("approval_required", 409)
        media = listing["fields"].get("media") or []
        if any(not item.get("rights_attested") for item in media):
            return err("media_rights_required", 422)
        if has_imported(listing):
            policy = store.policies.get(listing["source_type"], {})
            if not policy.get("republish"):
                return err("policy_republish_denied", 403)
        if listing["profile"] == "medical":
            listing["state"] = "pending_review"
            return owner_body(listing)
        listing["state"] = "active"
        listing["confirmed_at"] = store.now.isoformat()
        return owner_body(listing)

    @app.get("/api/listings/{listing_id}/confirm-availability")
    def peek_confirm(listing_id: str, request: Request):
        listing, denied = owner_listing(request, listing_id)
        if denied:
            return denied
        return {"confirmed_at": listing["confirmed_at"], "state": listing["state"]}

    @app.post("/api/listings/{listing_id}/confirm-availability")
    def confirm(listing_id: str, request: Request):
        listing, denied = owner_listing(request, listing_id)
        if denied:
            return denied
        listing["confirmed_at"] = store.now.isoformat()
        if listing["state"] == "paused_stale":
            listing["state"] = "active"
        return {"confirmed_at": listing["confirmed_at"], "state": listing["state"]}

    @app.get("/api/listings/{listing_id}")
    def get_listing(listing_id: str, request: Request):
        listing = store.listings.get(listing_id)
        if not listing:
            return err("not_found", 404)
        user = store.user(request)
        if user and listing["owner_id"] == user["id"]:
            return owner_body(listing)
        if listing["state"] == "active":
            return public_item(listing)
        return err("not_found", 404)

    @app.get("/api/search")
    def search(request: Request):
        sink = request.query_params.get("sink")
        items = []
        for listing in store.listings.values():
            if listing["state"] != "active":
                continue
            if sink == "true" and listing["fields"]["equipment"].get("sink") is not True:
                continue
            items.append(public_item(listing))
        return {"items": items}

    @app.post("/api/inquiries")
    async def create_inquiry(request: Request):
        user = store.user(request)
        if not user:
            return err("unauthorized", 401)
        body = await request.json()
        listing = store.listings.get(body.get("listing_id"))
        if not listing:
            return err("not_found", 404)
        inquiry_id = store.next_id("inq")
        row = {
            "id": inquiry_id,
            "listing_id": listing["id"],
            "owner_id": listing["owner_id"],
            "state": "submitted",
            "paid": False,
            "parties": [],
            "message": body.get("message") or "",
        }
        store.inquiries[inquiry_id] = row
        return {"id": inquiry_id, "state": row["state"], "paid": False}

    @app.get("/api/inquiries")
    def list_inquiries(request: Request):
        user = store.user(request)
        listing_id = request.query_params.get("listing_id")
        listing = store.listings.get(listing_id)
        if not user or not listing or listing["owner_id"] != user["id"]:
            return err("not_found", 404)
        rows = [row for row in store.inquiries.values() if row["listing_id"] == listing_id]
        return {"items": rows}

    @app.post("/api/inquiries/{inquiry_id}/mark-paid")
    def mark_paid(inquiry_id: str):
        return err("not_allowed", 405)

    @app.post("/api/inquiries/{inquiry_id}/report-rental")
    async def report_rental(inquiry_id: str, request: Request):
        user = store.user(request)
        row = store.inquiries.get(inquiry_id)
        if not user or not row:
            return err("not_found", 404)
        body = await request.json()
        party = body.get("party")
        if party in ("seeker", "host") and party not in row["parties"]:
            row["parties"].append(party)
        row["state"] = "rental_confirmed_both" if len(row["parties"]) >= 2 else "rental_reported_one_party"
        return {"id": row["id"], "state": row["state"], "paid": False}

    @app.post("/api/notifications/preferences")
    async def preferences(request: Request):
        user = store.user(request)
        if not user:
            return err("unauthorized", 401)
        body = await request.json()
        store.prefs[user["id"]] = bool(body.get("marketing"))
        return {"marketing": store.prefs[user["id"]]}

    @app.post("/api/notifications/queue")
    async def queue_job(request: Request):
        user = store.user(request)
        if not user or user["role"] != "admin":
            return err("not_found", 404)
        body = await request.json()
        job = {
            "id": store.next_id("job"),
            "user_id": body.get("user_id"),
            "purpose": body.get("purpose"),
            "channel": body.get("channel"),
            "to": body.get("to"),
            "status": "queued",
        }
        store.jobs.append(job)
        return job

    @app.post("/api/jobs/dispatch")
    def dispatch():
        for job in store.jobs:
            if job["status"] != "queued":
                continue
            if job["purpose"] == "marketing" and not store.prefs.get(job["user_id"], False):
                job["status"] = "cancelled"
                continue
            if store.sender is None:
                return err("sender_missing", 500)
            result = store.sender.send(dict(job))
            job["status"] = result
        return {"ok": True}

    @app.post("/api/jobs/freshness")
    def freshness(request: Request):
        user = store.user(request)
        if not user or user["role"] != "admin":
            return err("not_found", 404)
        for listing in store.listings.values():
            if listing["state"] != "active" or not listing["confirmed_at"]:
                continue
            confirmed = datetime.fromisoformat(listing["confirmed_at"])
            if confirmed.tzinfo is None:
                confirmed = confirmed.replace(tzinfo=timezone.utc)
            if store.now - confirmed >= timedelta(days=30):
                listing["state"] = "paused_stale"
        return {"ok": True}

    @app.post("/api/webhooks/{provider}")
    async def webhook(provider: str, request: Request):
        body = await request.json()
        key = (provider, body.get("event_id"))
        if key not in store.receipts:
            store.receipts[key] = store.next_id("rcpt")
        return {"receipt_id": store.receipts[key]}

    return app
