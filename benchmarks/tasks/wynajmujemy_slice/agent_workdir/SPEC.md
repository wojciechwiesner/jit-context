# Wynajmujemy slice — implementation contract v1

Status: frozen task contract. This is a simplified service, not the full product.
It is not a tutorial. Ambiguous behavior in this file is a defect in the implementation.

Source product note (not part of the contract): Wynajmujemy.xyz specification v1, 14 September 2026.
Out of scope: payments, crawlers, photo binaries, SEO, SMS, email delivery, OLX network calls, multi-service deployment.

## 1. What this service is

A single ASGI application. Professional workspace listings for independent specialists.
Catalogue plus enquiries. The rental contract happens outside the portal.
There is no `paid` state and no code path that sets one.

`create_app(*, seed=None, fetcher=None, sender=None)` returns the ASGI app.
`app.state.set_now(dt)` sets the clock. `dt` is timezone-aware UTC.
If `seed["now"]` is set, that is the clock at startup.

Storage is process-local. Two `create_app()` calls do not share rows.

## 2. Seed

```json
{
  "now": "2026-09-14T10:00:00+00:00",
  "users": [
    {"id": "host-a", "role": "host", "org_id": "org-a", "token": "tok-a"}
  ],
  "policies": {
    "olx": {
      "discovery": false,
      "fetch": false,
      "media": false,
      "republish": false,
      "outbound": false
    }
  }
}
```

Missing `policies.olx` means the same all-false object.
`owner_materials` is always allowed as host-supplied text. It is not a fetch source.

Auth: `Authorization: Bearer <token>`. Unknown token is 401 `{"error": "unauthorized"}`.
A host must not read another host's draft, private media flags, or enquiries.
That case is 404 `{"error": "not_found"}`, not 403.

## 3. Clock, hash, errors

- Persist instants in UTC.
- Do not convert to Europe/Warsaw in this slice.
- `draft_hash` is lowercase hex SHA-256 of the canonical JSON of the listing fields.
- Canonical JSON: `sort_keys=True`, separators `(',', ':')`, UTF-8.
- The hash covers `fields` only, not `version`.
- Every error body is `{"error": "<code>"}`.
- Write calls that create or mutate an import accept `Idempotency-Key`.
  Missing key on `POST /api/imports` is 400 `missing_idempotency_key`.

## 4. Listing fields

```json
{
  "title": {"value": "Room", "source": "host"},
  "text": {"value": "...", "source": "host"},
  "price": {"amount": null, "currency": "PLN", "period": null, "source": "host"},
  "equipment": {
    "sink": "unknown",
    "parking": "unknown"
  },
  "media": []
}
```

`source` is `host`, `source_import`, or `ai_suggestion`.
Equipment values are `true`, `false`, or `unknown`. Missing input stays `unknown`.
`unknown` is not `true` and not `false`.

Forbidden AI fields: `price`, `equipment`, `parking`, `access`, `certificates`, `availability`.
A PATCH that sets any of those with `source: "ai_suggestion"` is 422 `undocumented_field`.
The stored value does not change.

## 5. States

Listing: `draft -> awaiting_owner -> pending_review -> active -> paused_stale`.

Import: `ready`, `needs_input`, `blocked`, `failed`.

Enquiry: `submitted -> rental_reported_one_party -> rental_confirmed_both`.
No transition to `paid`. `POST /api/inquiries/{id}/mark-paid` is 405 `not_allowed`.
Every enquiry payload includes `"paid": false`.

## 6. Endpoints

### GET /r/{code}

200 `{"ok": true, "channel": "<code>", "imported": false, "published": false}`.
No import row, no listing row, no authorization row, no outbox row.

### POST /api/imports

Header: `Idempotency-Key`, bearer token of a host.
Body:

```json
{
  "source_type": "owner_materials",
  "source_url": null,
  "text": "Private room. Tuesdays free.",
  "profile": "general",
  "rights_attested": true,
  "price": {"amount": 120, "currency": "PLN", "period": "hour"},
  "contact_email": "host@example.com",
  "media": []
}
```

`profile` is `general` or `medical`.
`contact_email` is private. `available_from` is optional and never confirms or publishes a listing.

Rules:

- Same user and same `Idempotency-Key` returns the original import id, the original listing id, and does not create a second listing.
- `source_type=olx` while `policies.olx.fetch` is false: status `blocked`, `hint` is `paste_own_text`, `listing_id` is null, `fetcher` is not called.
- `source_type=olx` while fetch is true: call `fetcher.fetch(url)` once. Do not call any other URL.
- Fetcher result 403: status `blocked`, one fetch only, no proxy URL, no deletion of any existing listing.
- Text that contains an amount and `PLN` or `zł`, and no `price.period`: status `needs_input`, listing may exist, `price.amount` is null, `price.period` is null. Do not store 900 as daily or monthly.
- A complete `price` object from the host is not a guess.
- Imported page text is data. It must not change policies and must not create an outbox message.
- Ready owner-materials import creates one listing in `awaiting_owner`, version 1, with the returned `draft_hash`.

Response:

```json
{
  "id": "imp_1",
  "status": "ready",
  "listing_id": "lst_1",
  "hint": null,
  "fetch_count": 0
}
```

### GET /api/imports/{id}

Owner only. Foreign host: 404.

### PATCH /api/listings/{id}/draft

Body: `{"expected_version": 1, "fields": {...}}`.
Wrong `expected_version`: 409 `version_conflict`.
Success: version increments by 1, new `draft_hash`, `approved_hash` becomes null.

### POST /api/listings/{id}/approve

Body: `{"expected_version": 1, "draft_hash": "<hash>"}`.
Mismatch: 409 `version_conflict`.
Success stores `approved_hash` for that exact hash. It does not publish.

### POST /api/listings/{id}/publish

Body: `{"expected_version": 1, "draft_hash": "<hash>"}`.

- Hash or version mismatch: 409 `version_conflict`.
- No approval for that exact hash: 409 `approval_required`.
- Any media item with `rights_attested: false`: 422 `media_rights_required`. State unchanged.
- Any field with `source: "source_import"` while that listing's source policy has `republish: false`: 403 `policy_republish_denied`.
- `profile: "medical"` and checks pass: state `pending_review`, not `active`, absent from search.
- `profile: "general"` and checks pass: state `active`, `confirmed_at` set to the current clock.
- Host-sourced fields may be published when an earlier OLX import had `republish: false`, if no remaining field has `source: "source_import"`.

### GET /api/listings/{id}

Owner receives draft, `contact_email`, `version`, `draft_hash`, `approved_hash`, `confirmed_at`, `state`, `paid: false`.
No token, or a non-owner: 404 unless state is `active`.
A public active listing omits `contact_email` and omits draft-only fields. It includes `id`, `state`, `title`, `equipment`.

### GET /api/listings/{id}/confirm-availability

200 `{"confirmed_at": "...", "state": "..."}`.
Does not change `confirmed_at` or `state`.

### POST /api/listings/{id}/confirm-availability

Owner only. Sets `confirmed_at` to now.
If state is `paused_stale`, state becomes `active`.

### GET /api/search

Query `sink=true` matches only listings whose `equipment.sink` is `true`.
`unknown` does not match. `false` does not match.
Results are `active` only. No drafts. No `pending_review`. No `paused_stale`.
No item contains `contact_email`.

### POST /api/inquiries

Body: `{"listing_id": "...", "message": "..."}`. Seeker or host token.
Creates `submitted`. Response includes `paid: false`.
Ignore any client field named `paid`.

### GET /api/inquiries?listing_id=

Listing owner only. Others: 404.

### POST /api/inquiries/{id}/report-rental

Body: `{"party": "seeker"}` or `{"party": "host"}`.
One party: `rental_reported_one_party`. Both: `rental_confirmed_both`.
`paid` remains false.

### POST /api/notifications/queue

Admin token. Body: `{"user_id", "purpose", "channel", "to"}`.
`purpose` is `marketing` or `transactional`.
Queues a job. Does not send it.

### POST /api/notifications/preferences

Bearer of that user. Body: `{"marketing": false}`.

### POST /api/jobs/dispatch

Admin. For each queued job:

- `marketing` and that user's marketing preference is false: status `cancelled`. Do not call `sender`.
- Otherwise call `sender.send(job)` once.
- `delivered` stores `delivered`.
- `unknown` stores `unknown`. Do not enqueue another channel.
- Opt-out applies to jobs queued before the opt-out.

### POST /api/jobs/freshness

Admin. Every `active` listing whose `confirmed_at` is at least 30 days before now becomes `paused_stale`.
A past `available_from` does not confirm and does not renew.

### POST /api/webhooks/{provider}

Body: `{"event_id": "...", "type": "import.completed"}`.
Same `provider` and `event_id` returns the same `receipt_id` and does not create another listing.

### POST /api/admin/source-policies/{source}/enable

Admin. Body: `{"fetch": true, "republish": false, "evidence_id": "ev_1"}`.
Missing `evidence_id`: 422 `missing_evidence`. Policy unchanged.
Non-admin: 404.

### GET /api/admin/counts

Admin. `{"imports": 0, "listings": 0, "outbox": 0, "authorizations": 0}`.

### GET /api/admin/policies

Admin. Current policy objects.

### GET /api/admin/outbox

Admin. Job objects: `id`, `purpose`, `channel`, `to`, `status`, `user_id`.

## 7. Fetcher and sender

```python
class Fetcher:
    def fetch(self, url: str) -> tuple[int, str]:
        ...

class Sender:
    def send(self, job: dict) -> str:
        ...
```

If `fetcher` is None, any fetch attempt is an error and must not be replaced with a direct HTTP call.
If `sender` is None, dispatch of a job that would send is an error. Cancellation must not require a sender.

## 8. Invariants

1. No publish without the host's approval of the exact `draft_hash`.
2. No fetch without an enabled fetch policy.
3. No marketing send without permission at dispatch time.
4. Imported text is not an instruction.
5. No invented price period.
6. Retry does not duplicate a listing or a webhook receipt.
7. Public search does not reveal drafts or contact details.
8. A click, a GET, or a one-party report is not a payment.
9. `unknown` equipment does not satisfy a positive filter.
10. A 403 from a source does not unpublish an existing listing and does not retry through another URL.
