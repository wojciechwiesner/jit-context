import hashlib
from datetime import datetime, timezone
from typing import Any, Optional


class Fetcher:
    def fetch(self, url: str) -> tuple[int, str]:
        raise NotImplementedError("Fetcher not implemented")


class Sender:
    def send(self, job: dict) -> str:
        raise NotImplementedError("Sender not implemented")


def create_app(*, seed=None, fetcher=None, sender=None):
    """Create and return a Starlette app for the wynajmujemy rental service."""

    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    if seed is None:
        seed = {}

    now_utc = datetime.fromisoformat(seed.get("now", "2026-09-14T10:00:00+00:00"))

    def set_now(dt):
        nonlocal now_utc
        now_utc = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    app = Starlette()

    # --- In-memory storage (process-local) ---
    imports_db = {}  # id -> import record
    listings_db = {}  # listing_id -> listing record
    enquiries_db = {}  # inquiry_id -> enquiry record
    auths_db = {}     # user_id -> {token, role, org_id}
    policies_db = {"olx": {"discovery": False, "fetch": False, "media": False, "republish": False, "outbound": False}}

    if seed.get("users"):
        for u in seed["users"]:
            auths_db[u["id"]] = {**u}

    # --- Helpers ---

    def _get_auth(request: Request) -> Optional[dict]:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token or token not in auths_db:
            return None
        user = auths_db[token]
        if user["role"] != "host":
            return None
        return user

    def _get_listing(listing_id: str) -> Optional[dict]:
        return listings_db.get(listing_id)

    def _get_import(import_id: str) -> Optional[dict]:
        return imports_db.get(import_id)

    def _make_hash(fields: dict) -> str:
        canonical = hashlib.sha256(
            (json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)).encode("utf-8")
        ).hexdigest()
        return canonical

    # --- Routes ---

    @app.route("/r/{code}", methods=["GET"])
    async def get_listing_by_code(request: Request) -> JSONResponse:
        code = request.path_params["code"]
        listing = _get_listing(code)
        if not listing or listing["state"] != "active":
            return JSONResponse(status_code=404, content={"error": "not_found"})

        public_fields = {k: v for k, v in listing["fields"].items() if k not in ("contact_email",)}
        return JSONResponse(content={"ok": True, "channel": code, "imported": False, "published": False})

    @app.route("/api/imports", methods=["POST"])
    async def post_import(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        body = await request.json()
        source_type = body.get("source_type")
        idempotency_key = request.headers.get("Idempotency-Key")

        # Check for existing import with same key and user
        if idempotency_key:
            for imp_id, imp in imports_db.items():
                if imp["user_id"] == auth["id"] and imp["idempotency_key"] == idempotency_key:
                    return JSONResponse(content={
                        "id": imp["id"],
                        "status": imp["status"],
                        "listing_id": imp.get("listing_id"),
                        "hint": imp.get("hint"),
                        "fetch_count": imp.get("fetch_count", 0),
                    })

        # Determine policy for source_type
        if source_type == "olx":
            policy = policies_db["olx"]
            if not policy["fetch"]:
                return JSONResponse(content={
                    "id": f"imp_{len(imports_db) + 1}",
                    "status": "blocked",
                    "listing_id": None,
                    "hint": "paste_own_text",
                    "fetch_count": 0,
                })

            # Call fetcher once
            if fetcher is not None:
                status_code, body_text = fetcher.fetch(body.get("source_url"))
            else:
                return JSONResponse(status_code=500, content={"error": "internal_server_error"})

            if status_code == 403:
                return JSONResponse(content={
                    "id": f"imp_{len(imports_db) + 1}",
                    "status": "blocked",
                    "listing_id": None,
                    "hint": None,
                    "fetch_count": 1,
                })

            # Fetch succeeded; store the body as text
            listing = {
                "id": f"lst_{len(listings_db) + 1}",
                "state": "awaiting_owner",
                "version": 1,
                "fields": {"text": body_text},
                "source_type": source_type,
                "user_id": auth["id"],
            }
            listings_db[listing["id"]] = listing

            import_record = {
                "id": f"imp_{len(imports_db) + 1}",
                "status": "ready",
                "listing_id": listing["id"],
                "hint": None,
                "fetch_count": 1,
                "user_id": auth["id"],
            }
            imports_db[import_record["id"]] = import_record

        elif source_type == "owner_materials":
            # Always allowed; create one listing in awaiting_owner with draft_hash
            fields = {k: v for k, v in body.items() if k not in ("source_url",)}
            listing = {
                "id": f"lst_{len(listings_db) + 1}",
                "state": "awaiting_owner",
                "version": 1,
                "fields": fields,
                "source_type": source_type,
                "user_id": auth["id"],
            }
            listings_db[listing["id"]] = listing

            import_record = {
                "id": f"imp_{len(imports_db) + 1}",
                "status": "ready",
                "listing_id": listing["id"],
                "hint": None,
                "fetch_count": 0,
                "user_id": auth["id"],
            }
            imports_db[import_record["id"]] = import_record

        else:
            return JSONResponse(status_code=422, content={"error": "invalid_source_type"})

        return JSONResponse(content={
            "id": f"imp_{len(imports_db)}",
            "status": "ready",
            "listing_id": listing["id"],
            "hint": None,
            "fetch_count": 0,
        })

    @app.route("/api/imports/{import_id}", methods=["GET"])
    async def get_import(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        import_record = _get_import(request.path_params["import_id"])
        if not import_record or import_record["user_id"] != auth["id"]:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        listing = _get_listing(import_record.get("listing_id"))
        if not listing:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        return JSONResponse(content={
            "id": import_record["id"],
            "status": import_record["status"],
            "listing_id": import_record.get("listing_id"),
            "hint": import_record.get("hint"),
            "fetch_count": import_record.get("fetch_count", 0),
        })

    @app.route("/api/listings/{listing_id}/draft", methods=["PATCH"])
    async def patch_draft(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        listing = _get_listing(request.path_params["listing_id"])
        if not listing or listing["user_id"] != auth["id"]:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        body = await request.json()
        expected_version = body.get("expected_version")
        fields = body.get("fields", {})

        if listing["version"] != expected_version:
            return JSONResponse(status_code=409, content={"error": "version_conflict"})

        # Validate forbidden AI fields
        forbidden_ai_fields = {"price", "equipment", "parking", "access", "certificates", "availability"}
        for k, v in fields.items():
            if isinstance(v, dict) and v.get("source") == "ai_suggestion" and k in forbidden_ai_fields:
                return JSONResponse(status_code=422, content={"error": "undocumented_field"})

        # Merge fields into listing
        for k, v in fields.items():
            if isinstance(v, dict):
                listing["fields"][k] = {**listing["fields"].get(k), **v}
            else:
                listing["fields"][k] = v

        listing["version"] += 1
        listing["draft_hash"] = _make_hash(listing["fields"])
        listing["approved_hash"] = None

        return JSONResponse(content={
            "id": listing["id"],
            "state": listing["state"],
            "version": listing["version"],
            "draft_hash": listing["draft_hash"],
            "approved_hash": listing["approved_hash"],
        })

    @app.route("/api/listings/{listing_id}/approve", methods=["POST"])
    async def post_approve(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        listing = _get_listing(request.path_params["listing_id"])
        if not listing or listing["user_id"] != auth["id"]:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        body = await request.json()
        expected_version = body.get("expected_version")
        draft_hash = body.get("draft_hash")

        if listing["version"] != expected_version:
            return JSONResponse(status_code=409, content={"error": "version_conflict"})

        # Check approval hash matches exactly
        if listing["approved_hash"] is not None and listing["approved_hash"] != draft_hash:
            return JSONResponse(status_code=409, content={"error": "approval_required"})

        listing["approved_hash"] = draft_hash

        return JSONResponse(content={
            "id": listing["id"],
            "state": listing["state"],
            "version": listing["version"],
            "draft_hash": listing["draft_hash"],
            "approved_hash": listing["approved_hash"],
        })

    @app.route("/api/listings/{listing_id}/publish", methods=["POST"])
    async def post_publish(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        listing = _get_listing(request.path_params["listing_id"])
        if not listing or listing["user_id"] != auth["id"]:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        body = await request.json()
        expected_version = body.get("expected_version")
        draft_hash = body.get("draft_hash")

        if listing["version"] != expected_version:
            return JSONResponse(status_code=409, content={"error": "version_conflict"})

        # Check approval hash matches exactly
        if listing["approved_hash"] is not None and listing["approved_hash"] != draft_hash:
            return JSONResponse(status_code=409, content={"error": "approval_required"})

        # Check media rights
        for item in listing.get("fields", {}).get("media", []):
            if not item.get("rights_attested"):
                return JSONResponse(status_code=422, content={"error": "media_rights_required"})

        # Check republish policy
        source_type = listing.get("source_type")
        if source_type == "olx" and policies_db["olx"]["republish"] is False:
            for k, v in listing["fields"].items():
                if isinstance(v, dict) and v.get("source") == "source_import":
                    return JSONResponse(status_code=403, content={"error": "policy_republish_denied"})

        # Determine new state
        profile = listing["fields"].get("profile", "general")
        if profile == "medical":
            listing["state"] = "pending_review"
        else:
            listing["state"] = "active"
            listing["confirmed_at"] = now_utc.isoformat()

        return JSONResponse(content={
            "id": listing["id"],
            "state": listing["state"],
            "version": listing["version"],
            "draft_hash": listing["draft_hash"],
            "approved_hash": listing["approved_hash"],
            "confirmed_at": listing.get("confirmed_at"),
        })

    @app.route("/api/listings/{listing_id}", methods=["GET"])
    async def get_listing(request: Request) -> JSONResponse:
        auth = _get_auth(request)

        listing = _get_listing(request.path_params["listing_id"])
        if not listing:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        # Owner access for non-active states
        if listing["state"] != "active" and auth is None:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        # Public active listing omits contact_email and draft-only fields
        if listing["state"] == "active" and auth is None:
            public_fields = {k: v for k, v in listing["fields"].items() if k not in ("contact_email",)}
            return JSONResponse(content={
                "id": listing["id"],
                "state": listing["state"],
                "title": public_fields.get("title"),
                "equipment": {k: v for k, v in public_fields.get("equipment", {}).items()},
            })

        # Owner access (auth is not None)
        owner_fields = dict(listing["fields"])
        if listing["state"] == "active" and auth is not None:
            # Include contact_email for owner
            pass
        else:
            owner_fields.pop("contact_email", None)

        return JSONResponse(content={
            "id": listing["id"],
            "state": listing["state"],
            "version": listing["version"],
            "draft_hash": listing.get("draft_hash"),
            "approved_hash": listing.get("approved_hash"),
            "confirmed_at": listing.get("confirmed_at"),
            "fields": owner_fields,
        })

    @app.route("/api/listings/{listing_id}/confirm-availability", methods=["GET"])
    async def get_confirm_availability(request: Request) -> JSONResponse:
        auth = _get_auth(request)

        listing = _get_listing(request.path_params["listing_id"])
        if not listing or listing["user_id"] != auth["id"]:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        return JSONResponse(content={
            "confirmed_at": listing.get("confirmed_at"),
            "state": listing["state"],
        })

    @app.route("/api/listings/{listing_id}/confirm-availability", methods=["POST"])
    async def post_confirm_availability(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        listing = _get_listing(request.path_params["listing_id"])
        if not listing or listing["user_id"] != auth["id"]:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        now_utc = datetime.now(timezone.utc)
        listing["confirmed_at"] = now_utc.isoformat()
        if listing["state"] == "paused_stale":
            listing["state"] = "active"

        return JSONResponse(content={
            "id": listing["id"],
            "state": listing["state"],
            "confirmed_at": listing["confirmed_at"],
        })

    @app.route("/api/search", methods=["GET"])
    async def get_search(request: Request) -> JSONResponse:
        auth = _get_auth(request)

        sink_filter = request.query_params.get("sink")

        results = []
        for listing in listings_db.values():
            if listing["state"] != "active":
                continue

            fields = listing["fields"]
            equipment = fields.get("equipment", {})

            # Filter by sink
            if sink_filter:
                sink_val = equipment.get("sink")
                if sink_val != "true" and sink_val != sink_filter:
                    continue

            public_fields = {k: v for k, v in fields.items() if k not in ("contact_email",)}
            results.append({
                "id": listing["id"],
                "state": listing["state"],
                "title": public_fields.get("title"),
                "equipment": {k: v for k, v in public_fields.get("equipment", {}).items()},
            })

        return JSONResponse(content={"results": results})

    @app.route("/api/inquiries", methods=["POST"])
    async def post_inquiry(request: Request) -> JSONResponse:
        auth = _get_auth(request)

        body = await request.json()
        listing_id = body.get("listing_id")
        message = body.get("message")

        if not listing_id or not message:
            return JSONResponse(status_code=422, content={"error": "invalid_request"})

        # Check authorization for non-active listings
        listing = _get_listing(listing_id)
        if listing and listing["state"] != "active" and auth is None:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        inquiry_id = f"inq_{len(enquiries_db) + 1}"
        enquiry = {
            "id": inquiry_id,
            "listing_id": listing_id,
            "message": message,
            "state": "submitted",
            "paid": False,
        }
        enquiries_db[inquiry_id] = enquiry

        return JSONResponse(content={
            "id": inquiry_id,
            "listing_id": listing_id,
            "state": "submitted",
            "paid": False,
        })

    @app.route("/api/inquiries", methods=["GET"])
    async def get_inquiries(request: Request) -> JSONResponse:
        auth = _get_auth(request)

        listing_id = request.query_params.get("listing_id")

        if not listing_id or auth is None:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        # Verify owner access to the listing
        listing = _get_listing(listing_id)
        if not listing or listing["user_id"] != auth["id"]:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        results = []
        for enquiry in enquiries_db.values():
            if enquiry["listing_id"] == listing_id:
                results.append({
                    "id": enquiry["id"],
                    "state": enquiry["state"],
                    "paid": False,
                })

        return JSONResponse(content={"results": results})

    @app.route("/api/inquiries/{inquiry_id}/report-rental", methods=["POST"])
    async def post_report_rental(request: Request) -> JSONResponse:
        auth = _get_auth(request)

        body = await request.json()
        party = body.get("party")

        if not party or party not in ("seeker", "host"):
            return JSONResponse(status_code=422, content={"error": "invalid_party"})

        enquiry = enquiries_db.get(request.path_params["inquiry_id"])
        if not enquiry:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        listing = _get_listing(enquiry["listing_id"])
        if not listing or listing["user_id"] != auth["id"]:
            return JSONResponse(status_code=404, content={"error": "not_found"})

        # Determine state based on parties reported
        if party == "seeker" and enquiry.get("reported_parties", set()) == {"host"}:
            enquiry["state"] = "rental_confirmed_both"
        elif party == "host" and enquiry.get("reported_parties", set()) == {"seeker"}:
            enquiry["state"] = "rental_confirmed_both"
        else:
            if party == "seeker":
                enquiry["reported_parties"] = enquiry.get("reported_parties", set()) | {"seeker"}
            elif party == "host":
                enquiry["reported_parties"] = enquiry.get("reported_parties", set()) | {"host"}

        return JSONResponse(content={
            "id": enquiry["id"],
            "listing_id": enquiry["listing_id"],
            "state": enquiry["state"],
            "paid": False,
        })

    @app.route("/api/notifications/queue", methods=["POST"])
    async def post_queue_notification(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth or auth["role"] != "admin":
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        body = await request.json()
        user_id = body.get("user_id")
        purpose = body.get("purpose")
        channel = body.get("channel")
        to = body.get("to")

        if not all([user_id, purpose, channel, to]):
            return JSONResponse(status_code=422, content={"error": "invalid_request"})

        job_id = f"job_{len(outbox_db) + 1}"
        job = {
            "id": job_id,
            "purpose": purpose,
            "channel": channel,
            "to": to,
            "user_id": user_id,
            "status": "queued",
        }
        outbox_db[job_id] = job

        return JSONResponse(content={"job_id": job_id})

    @app.route("/api/notifications/preferences", methods=["POST"])
    async def post_preferences(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth or auth["role"] != "host":
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        body = await request.json()
        marketing = body.get("marketing")

        user_prefs[auth["id"]] = {"marketing": marketing}

        return JSONResponse(content={})

    @app.route("/api/jobs/dispatch", methods=["POST"])
    async def post_dispatch(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth or auth["role"] != "admin":
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        body = await request.json()
        job_ids = body.get("job_ids", [])

        results = []
        for job_id in job_ids:
            job = outbox_db.get(job_id)
            if not job:
                continue

            purpose = job["purpose"]
            user_id = job["user_id"]

            # Check marketing preference
            prefs = user_prefs.get(user_id, {})
            if purpose == "marketing" and prefs.get("marketing") is False:
                job["status"] = "cancelled"
                results.append({"job_id": job_id, "status": "cancelled"})
                continue

            # Call sender
            if sender is not None:
                try:
                    delivered = sender.send(job)
                    job["delivered"] = delivered
                    job["status"] = "sent"
                except Exception:
                    job["delivered"] = "unknown"
                    job["status"] = "failed"
            else:
                # No sender; mark as sent without calling network
                job["delivered"] = "ok"
                job["status"] = "sent"

            results.append({"job_id": job_id, "status": job["status"], "delivered": job.get("delivered")})

        return JSONResponse(content={"results": results})

    @app.route("/api/jobs/freshness", methods=["POST"])
    async def post_freshness(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth or auth["role"] != "admin":
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        now_utc = datetime.now(timezone.utc)
        threshold = now_utc.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)

        for listing in listings_db.values():
            if listing["state"] != "active":
                continue

            confirmed_at_str = listing.get("confirmed_at")
            if not confirmed_at_str:
                continue

            try:
                confirmed_at = datetime.fromisoformat(confirmed_at_str).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            if confirmed_at <= threshold:
                listing["state"] = "paused_stale"

        return JSONResponse(content={})

    @app.route("/api/webhooks/{provider}", methods=["POST"])
    async def post_webhook(request: Request) -> JSONResponse:
        body = await request.json()
        provider = request.path_params["provider"]
        event_id = body.get("event_id")
        event_type = body.get("type")

        if not event_id or not event_type:
            return JSONResponse(status_code=422, content={"error": "invalid_request"})

        receipt_key = f"{provider}:{event_id}"
        if receipt_key in webhook_receipts:
            return JSONResponse(content={"receipt_id": webhook_receipts[receipt_key]})

        # Create new listing from import.completed
        if event_type == "import.completed":
            source_url = body.get("source_url")
            text = body.get("text")
            profile = body.get("profile", "general")

            listing = {
                "id": f"lst_{len(listings_db) + 1}",
                "state": "awaiting_owner",
                "version": 1,
                "fields": {"text": text},
                "source_type": provider,
                "user_id": None,
            }
            listings_db[listing["id"]] = listing

            import_record = {
                "id": f"imp_{len(imports_db) + 1}",
                "status": "ready",
                "listing_id": listing["id"],
                "hint": None,
                "fetch_count": 0,
                "user_id": None,
            }
            imports_db[import_record["id"]] = import_record

        receipt_id = f"rec_{len(webhook_receipts) + 1}"
        webhook_receipts[receipt_key] = receipt_id

        return JSONResponse(content={"receipt_id": receipt_id})

    @app.route("/api/admin/source-policies/{source}/enable", methods=["POST"])
    async def post_enable_policy(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth or auth["role"] != "admin":
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        body = await request.json()
        evidence_id = body.get("evidence_id")

        if not evidence_id:
            return JSONResponse(status_code=422, content={"error": "missing_evidence"})

        source = request.path_params["source"]
        policy = policies_db.get(source, {})
        policy["fetch"] = True
        policy["republish"] = body.get("republish", False)
        policy["evidence_id"] = evidence_id

        return JSONResponse(content={})

    @app.route("/api/admin/counts", methods=["GET"])
    async def get_counts(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth or auth["role"] != "admin":
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        return JSONResponse(content={
            "imports": len(imports_db),
            "listings": len(listings_db),
            "outbox": len(outbox_db),
            "authorizations": len(auths_db),
        })

    @app.route("/api/admin/policies", methods=["GET"])
    async def get_policies(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth or auth["role"] != "admin":
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        return JSONResponse(content=policies_db)

    @app.route("/api/admin/outbox", methods=["GET"])
    async def get_outbox(request: Request) -> JSONResponse:
        auth = _get_auth(request)
        if not auth or auth["role"] != "admin":
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        results = []
        for job in outbox_db.values():
            results.append({
                "id": job["id"],
                "purpose": job["purpose"],
                "channel": job["channel"],
                "to": job["to"],
                "status": job["status"],
                "user_id": job["user_id"],
            })

        return JSONResponse(content={"results": results})

    # --- Imports into Starlette ---
    from starlette.responses import JSONResponse as _JSONResponse
    from starlette.routing import Route as _Route

    routes = [
        _Route("/r/{code}", get_listing_by_code, methods=["GET"]),
        _Route("/api/imports", post_import, methods=["POST"]),
        _Route("/api/imports/{import_id}", get_import, methods=["GET"]),
        _Route("/api/listings/{listing_id}/draft", patch_draft, methods=["PATCH"]),
        _Route("/api/listings/{listing_id}/approve", post_approve, methods=["POST"]),
        _Route("/api/listings/{listing_id}/publish", post_publish, methods=["POST"]),
        _Route("/api/listings/{listing_id}", get_listing, methods=["GET"]),
        _Route("/api/listings/{listing_id}/confirm-availability", get_confirm_availability, methods=["GET"]),
        _Route("/api/listings/{listing_id}/confirm-availability", post_confirm_availability, methods=["POST"]),
        _Route("/api/search", get_search, methods=["GET"]),
        _Route("/api/inquiries", post_inquiry, methods=["POST"]),
        _Route("/api/inquiries", get_inquiries, methods=["GET"]),
        _Route("/api/inquiries/{inquiry_id}/report-rental", post_report_rental, methods=["POST"]),
        _Route("/api/notifications/queue", post_queue_notification, methods=["POST"]),
        _Route("/api/notifications/preferences", post_preferences, methods=["POST"]),
        _Route("/api/jobs/dispatch", post_dispatch, methods=["POST"]),
        _Route("/api/jobs/freshness", post_freshness, methods=["POST"]),
        _Route("/api/webhooks/{provider}", post_webhook, methods=["POST"]),
        _Route("/api/admin/source-policies/{source}/enable", post_enable_policy, methods=["POST"]),
        _Route("/api/admin/counts", get_counts, methods=["GET"]),
        _Route("/api/admin/policies", get_policies, methods=["GET"]),
        _Route("/api/admin/outbox", get_outbox, methods=["GET"]),
    ]

    app.router.routes = routes

    return app
