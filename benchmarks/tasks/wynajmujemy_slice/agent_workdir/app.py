"""Wynajmujemy slice. Process-local catalogue and enquiries."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

PRICE_IN_TEXT = re.compile(r"\d+(?:[.,]\d+)?\s*(?:PLN|zł|zl)", re.IGNORECASE)
FORBIDDEN_AI = {"price", "equipment", "parking", "access", "certificates", "availability"}
OLX_OFF = {
    "discovery": False,
    "fetch": False,
    "media": False,
    "republish": False,
    "outbound": False,
}


def _hash(fields: dict) -> str:
    raw = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _err(code: str, status: int) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status)


def _blank_fields(text: str, price: dict, media: list, source: str) -> dict:
    return {
        "title": {"value": (text or "Listing").strip().split("\n", 1)[0][:80] or "Listing", "source": source},
        "text": {"value": text or "", "source": source},
        "price": {
            "amount": price.get("amount"),
            "currency": price.get("currency") or "PLN",
            "period": price.get("period"),
            "source": source,
        },
        "equipment": {"sink": "unknown", "parking": "unknown"},
        "media": list(media or []),
    }


def _has_source(node: Any, source: str) -> bool:
    if isinstance(node, dict):
        if node.get("source") == source:
            return True
        return any(_has_source(value, source) for value in node.values())
    if isinstance(node, list):
        return any(_has_source(item, source) for item in node)
    return False


def _ai_forbidden(fields: dict) -> bool:
    for key, value in fields.items():
        if key in FORBIDDEN_AI and isinstance(value, dict) and value.get("source") == "ai_suggestion":
            return True
        if isinstance(value, dict) and value.get("source") == "ai_suggestion" and key in FORBIDDEN_AI:
            return True
    return False


def create_app(*, seed=None, fetcher=None, sender=None):
    seed = seed or {}
    clock = {"now": _parse_time(seed.get("now")) or datetime.now(timezone.utc)}
    users = {row["token"]: row for row in seed.get("users", [])}
    policies = {"olx": dict(OLX_OFF)}
    given = (seed.get("policies") or {}).get("olx") or {}
    policies["olx"].update(given)

    imports: dict[str, dict] = {}
    listings: dict[str, dict] = {}
    inquiries: dict[str, dict] = {}
    jobs: list[dict] = []
    receipts: dict[tuple[str, str], str] = {}
    idem: dict[tuple[str, str], dict] = {}
    marketing: dict[str, bool] = {}
    seq = {"imp": 0, "lst": 0, "inq": 0, "job": 0, "rec": 0}

    def now() -> datetime:
        return clock["now"]

    def set_now(dt: datetime) -> None:
        clock["now"] = dt.astimezone(timezone.utc)

    def user_from(request: Request):
        header = request.headers.get("authorization", "")
        if not header:
            return None
        token = header[7:] if header.lower().startswith("bearer ") else ""
        if token not in users:
            return "unauthorized"
        return users[token]

    def require_user(request: Request):
        found = user_from(request)
        if found == "unauthorized":
            return None, _err("unauthorized", 401)
        if not found:
            return None, _err("unauthorized", 401)
        return found, None

    def require_admin(request: Request):
        found, error = require_user(request)
        if error and user_from(request) != "unauthorized" and not found:
            return None, _err("not_found", 404)
        if user_from(request) == "unauthorized":
            return None, _err("unauthorized", 401)
        if not found or found.get("role") != "admin":
            return None, _err("not_found", 404)
        return found, None

    def owner_view(row: dict) -> dict:
        return {
            "id": row["id"],
            "state": row["state"],
            "fields": row["fields"],
            "contact_email": row["contact_email"],
            "version": row["version"],
            "draft_hash": row["draft_hash"],
            "approved_hash": row["approved_hash"],
            "confirmed_at": _iso(row["confirmed_at"]),
            "paid": False,
            "profile": row["profile"],
        }

    def public_view(row: dict) -> dict:
        return {
            "id": row["id"],
            "state": row["state"],
            "title": row["fields"]["title"]["value"],
            "equipment": row["fields"]["equipment"],
        }

    def counts() -> dict:
        return {
            "imports": len(imports),
            "listings": len(listings),
            "outbox": len(jobs),
            "authorizations": 0,
        }

    async def referral(_request: Request) -> JSONResponse:
        code = _request.path_params["code"]
        return JSONResponse({
            "ok": True,
            "channel": code,
            "imported": False,
            "published": False,
        })

    async def create_import(request: Request) -> JSONResponse:
        actor, error = require_user(request)
        if error:
            return error
        key = request.headers.get("idempotency-key")
        if not key:
            return _err("missing_idempotency_key", 400)
        cached = idem.get((actor["id"], key))
        if cached:
            return JSONResponse(cached)
        body = await request.json()
        source_type = body.get("source_type") or "owner_materials"
        text = body.get("text") or ""
        price = body.get("price") or {}
        media = body.get("media") or []
        profile = body.get("profile") or "general"
        hint = None
        fetch_count = 0
        status = "ready"
        listing_id = None

        if source_type == "olx" and not policies["olx"]["fetch"]:
            payload = {
                "id": _next("imp"),
                "status": "blocked",
                "listing_id": None,
                "hint": "paste_own_text",
                "fetch_count": 0,
            }
            imports[payload["id"]] = {**payload, "owner_id": actor["id"]}
            idem[(actor["id"], key)] = payload
            return JSONResponse(payload)

        if source_type == "olx":
            live_fetcher = request.app.state.fetcher
            if live_fetcher is None:
                return _err("fetcher_missing", 500)
            url = body.get("source_url")
            status_code, fetched = live_fetcher.fetch(url)
            fetch_count = 1
            if status_code != 200:
                payload = {
                    "id": _next("imp"),
                    "status": "blocked",
                    "listing_id": None,
                    "hint": "paste_own_text",
                    "fetch_count": fetch_count,
                }
                imports[payload["id"]] = {**payload, "owner_id": actor["id"]}
                idem[(actor["id"], key)] = payload
                return JSONResponse(payload)
            text = fetched or text
            field_source = "source_import"
        else:
            field_source = "host"

        period = price.get("period") if isinstance(price, dict) else None
        ambiguous = PRICE_IN_TEXT.search(text or "") and not period
        stored_price = dict(price) if isinstance(price, dict) else {}
        if ambiguous:
            status = "needs_input"
            stored_price = {"amount": None, "currency": "PLN", "period": None}
        fields = _blank_fields(text, stored_price, media, field_source)
        listing_id = _next("lst")
        listings[listing_id] = {
            "id": listing_id,
            "owner_id": actor["id"],
            "state": "awaiting_owner",
            "fields": fields,
            "contact_email": body.get("contact_email"),
            "version": 1,
            "draft_hash": _hash(fields),
            "approved_hash": None,
            "confirmed_at": None,
            "profile": profile,
            "source_type": source_type,
            "available_from": body.get("available_from"),
        }
        payload = {
            "id": _next("imp"),
            "status": status,
            "listing_id": listing_id,
            "hint": hint,
            "fetch_count": fetch_count,
        }
        imports[payload["id"]] = {**payload, "owner_id": actor["id"]}
        idem[(actor["id"], key)] = payload
        return JSONResponse(payload)

    def _next(kind: str) -> str:
        seq[kind] += 1
        prefix = {"imp": "imp", "lst": "lst", "inq": "inq", "job": "job", "rec": "rec"}[kind]
        return f"{prefix}_{seq[kind]}"

    async def get_import(request: Request) -> JSONResponse:
        actor, error = require_user(request)
        if error:
            return error
        row = imports.get(request.path_params["import_id"])
        if not row or row["owner_id"] != actor["id"]:
            return _err("not_found", 404)
        return JSONResponse({
            "id": row["id"],
            "status": row["status"],
            "listing_id": row["listing_id"],
            "hint": row["hint"],
            "fetch_count": row["fetch_count"],
        })

    def _listing_or_404(listing_id: str, actor):
        row = listings.get(listing_id)
        if not row or not actor or row["owner_id"] != actor["id"]:
            return None
        return row

    async def get_listing(request: Request) -> JSONResponse:
        row = listings.get(request.path_params["listing_id"])
        if not row:
            return _err("not_found", 404)
        actor = user_from(request)
        if actor == "unauthorized":
            return _err("unauthorized", 401)
        if actor and actor["id"] == row["owner_id"]:
            return JSONResponse(owner_view(row))
        if row["state"] == "active":
            return JSONResponse(public_view(row))
        return _err("not_found", 404)

    async def patch_draft(request: Request) -> JSONResponse:
        actor, error = require_user(request)
        if error:
            return error
        row = _listing_or_404(request.path_params["listing_id"], actor)
        if not row:
            return _err("not_found", 404)
        body = await request.json()
        if body.get("expected_version") != row["version"]:
            return _err("version_conflict", 409)
        incoming = body.get("fields") or {}
        if _ai_forbidden(incoming):
            return _err("undocumented_field", 422)
        fields = dict(row["fields"])
        for key, value in incoming.items():
            if key == "equipment" and isinstance(value, dict) and "source" not in value:
                merged = dict(fields.get("equipment") or {})
                merged.update(value)
                fields["equipment"] = merged
            else:
                fields[key] = value
        row["fields"] = fields
        row["version"] += 1
        row["draft_hash"] = _hash(fields)
        row["approved_hash"] = None
        return JSONResponse(owner_view(row))

    async def approve(request: Request) -> JSONResponse:
        actor, error = require_user(request)
        if error:
            return error
        row = _listing_or_404(request.path_params["listing_id"], actor)
        if not row:
            return _err("not_found", 404)
        body = await request.json()
        if body.get("expected_version") != row["version"] or body.get("draft_hash") != row["draft_hash"]:
            return _err("version_conflict", 409)
        row["approved_hash"] = row["draft_hash"]
        return JSONResponse(owner_view(row))

    async def publish(request: Request) -> JSONResponse:
        actor, error = require_user(request)
        if error:
            return error
        row = _listing_or_404(request.path_params["listing_id"], actor)
        if not row:
            return _err("not_found", 404)
        body = await request.json()
        if body.get("expected_version") != row["version"] or body.get("draft_hash") != row["draft_hash"]:
            return _err("version_conflict", 409)
        if row["approved_hash"] != row["draft_hash"]:
            return _err("approval_required", 409)
        if any(item.get("rights_attested") is False for item in row["fields"].get("media") or []):
            return _err("media_rights_required", 422)
        source_name = row.get("source_type") or "owner_materials"
        policy = policies.get(source_name) or OLX_OFF
        if _has_source(row["fields"], "source_import") and not policy.get("republish"):
            return _err("policy_republish_denied", 403)
        if row["profile"] == "medical":
            row["state"] = "pending_review"
        else:
            row["state"] = "active"
            row["confirmed_at"] = now()
        return JSONResponse(owner_view(row))

    async def peek_confirm(request: Request) -> JSONResponse:
        row = listings.get(request.path_params["listing_id"])
        if not row:
            return _err("not_found", 404)
        return JSONResponse({"confirmed_at": _iso(row["confirmed_at"]), "state": row["state"]})

    async def post_confirm(request: Request) -> JSONResponse:
        actor, error = require_user(request)
        if error:
            return error
        row = _listing_or_404(request.path_params["listing_id"], actor)
        if not row:
            return _err("not_found", 404)
        row["confirmed_at"] = now()
        if row["state"] == "paused_stale":
            row["state"] = "active"
        return JSONResponse({"confirmed_at": _iso(row["confirmed_at"]), "state": row["state"]})

    async def search(request: Request) -> JSONResponse:
        sink = request.query_params.get("sink")
        items = []
        for row in listings.values():
            if row["state"] != "active":
                continue
            equipment = row["fields"]["equipment"]
            if sink == "true" and equipment.get("sink") != "true":
                continue
            items.append(public_view(row))
        return JSONResponse({"items": items})

    async def create_inquiry(request: Request) -> JSONResponse:
        actor, error = require_user(request)
        if error:
            return error
        body = await request.json()
        row = listings.get(body.get("listing_id"))
        if not row or row["state"] != "active":
            return _err("not_found", 404)
        inquiry_id = _next("inq")
        inquiries[inquiry_id] = {
            "id": inquiry_id,
            "listing_id": row["id"],
            "message": body.get("message") or "",
            "state": "submitted",
            "paid": False,
            "parties": set(),
        }
        return JSONResponse({
            "id": inquiry_id,
            "listing_id": row["id"],
            "state": "submitted",
            "paid": False,
        })

    async def list_inquiries(request: Request) -> JSONResponse:
        actor, error = require_user(request)
        if error:
            return error
        listing_id = request.query_params.get("listing_id")
        row = listings.get(listing_id)
        if not row or row["owner_id"] != actor["id"]:
            return _err("not_found", 404)
        items = [
            {"id": item["id"], "state": item["state"], "paid": False, "listing_id": item["listing_id"]}
            for item in inquiries.values()
            if item["listing_id"] == listing_id
        ]
        return JSONResponse({"items": items})

    async def report_rental(request: Request) -> JSONResponse:
        actor, error = require_user(request)
        if error:
            return error
        item = inquiries.get(request.path_params["inquiry_id"])
        if not item:
            return _err("not_found", 404)
        body = await request.json()
        party = body.get("party")
        if party in {"seeker", "host"}:
            item["parties"].add(party)
        if item["parties"] >= {"seeker", "host"}:
            item["state"] = "rental_confirmed_both"
        elif item["parties"]:
            item["state"] = "rental_reported_one_party"
        return JSONResponse({"id": item["id"], "state": item["state"], "paid": False})

    async def mark_paid(_request: Request) -> JSONResponse:
        return _err("not_allowed", 405)

    async def queue_note(request: Request) -> JSONResponse:
        _admin, error = require_admin(request)
        if error:
            return error
        body = await request.json()
        job_id = _next("job")
        jobs.append({
            "id": job_id,
            "user_id": body.get("user_id"),
            "purpose": body.get("purpose"),
            "channel": body.get("channel"),
            "to": body.get("to"),
            "status": "queued",
        })
        return JSONResponse({"id": job_id, "status": "queued"})

    async def preferences(request: Request) -> JSONResponse:
        actor, error = require_user(request)
        if error:
            return error
        body = await request.json()
        marketing[actor["id"]] = bool(body.get("marketing"))
        return JSONResponse({"marketing": marketing[actor["id"]]})

    async def dispatch(request: Request) -> JSONResponse:
        _admin, error = require_admin(request)
        if error:
            return error
        for job in jobs:
            if job["status"] != "queued":
                continue
            opted_out = job["purpose"] == "marketing" and not marketing.get(job["user_id"], False)
            if opted_out:
                job["status"] = "cancelled"
                continue
            live_sender = request.app.state.sender
            if live_sender is None:
                return _err("sender_missing", 500)
            result = live_sender.send(dict(job))
            job["status"] = result if result in {"delivered", "unknown"} else "unknown"
        return JSONResponse({"ok": True})

    async def freshness(request: Request) -> JSONResponse:
        _admin, error = require_admin(request)
        if error:
            return error
        cutoff = now() - timedelta(days=30)
        for row in listings.values():
            if row["state"] == "active" and row["confirmed_at"] and row["confirmed_at"] <= cutoff:
                row["state"] = "paused_stale"
        return JSONResponse({"ok": True})

    async def webhook(request: Request) -> JSONResponse:
        _admin, error = require_admin(request)
        if error:
            return error
        body = await request.json()
        provider = request.path_params["provider"]
        slot = (provider, str(body.get("event_id")))
        if slot not in receipts:
            receipts[slot] = _next("rec")
        return JSONResponse({"receipt_id": receipts[slot]})

    async def enable_policy(request: Request) -> JSONResponse:
        found = user_from(request)
        if found == "unauthorized":
            return _err("unauthorized", 401)
        if not found or found.get("role") != "admin":
            return _err("not_found", 404)
        body = await request.json()
        if not body.get("evidence_id"):
            return _err("missing_evidence", 422)
        source = request.path_params["source"]
        current = policies.setdefault(source, dict(OLX_OFF))
        if "fetch" in body:
            current["fetch"] = bool(body["fetch"])
        if "republish" in body:
            current["republish"] = bool(body["republish"])
        return JSONResponse(current)

    async def admin_counts(request: Request) -> JSONResponse:
        _admin, error = require_admin(request)
        if error:
            return error
        return JSONResponse(counts())

    async def admin_policies(request: Request) -> JSONResponse:
        _admin, error = require_admin(request)
        if error:
            return error
        return JSONResponse(policies)

    async def admin_outbox(request: Request) -> JSONResponse:
        _admin, error = require_admin(request)
        if error:
            return error
        return JSONResponse({"jobs": list(jobs)})

    app = Starlette(routes=[
        Route("/r/{code}", referral, methods=["GET"]),
        Route("/api/imports", create_import, methods=["POST"]),
        Route("/api/imports/{import_id}", get_import, methods=["GET"]),
        Route("/api/listings/{listing_id}", get_listing, methods=["GET"]),
        Route("/api/listings/{listing_id}/draft", patch_draft, methods=["PATCH"]),
        Route("/api/listings/{listing_id}/approve", approve, methods=["POST"]),
        Route("/api/listings/{listing_id}/publish", publish, methods=["POST"]),
        Route("/api/listings/{listing_id}/confirm-availability", peek_confirm, methods=["GET"]),
        Route("/api/listings/{listing_id}/confirm-availability", post_confirm, methods=["POST"]),
        Route("/api/search", search, methods=["GET"]),
        Route("/api/inquiries", create_inquiry, methods=["POST"]),
        Route("/api/inquiries", list_inquiries, methods=["GET"]),
        Route("/api/inquiries/{inquiry_id}/report-rental", report_rental, methods=["POST"]),
        Route("/api/inquiries/{inquiry_id}/mark-paid", mark_paid, methods=["POST"]),
        Route("/api/notifications/queue", queue_note, methods=["POST"]),
        Route("/api/notifications/preferences", preferences, methods=["POST"]),
        Route("/api/jobs/dispatch", dispatch, methods=["POST"]),
        Route("/api/jobs/freshness", freshness, methods=["POST"]),
        Route("/api/webhooks/{provider}", webhook, methods=["POST"]),
        Route("/api/admin/source-policies/{source}/enable", enable_policy, methods=["POST"]),
        Route("/api/admin/counts", admin_counts, methods=["GET"]),
        Route("/api/admin/policies", admin_policies, methods=["GET"]),
        Route("/api/admin/outbox", admin_outbox, methods=["GET"]),
    ])
    app.state.set_now = set_now
    app.state.fetcher = fetcher
    app.state.sender = sender
    return app
