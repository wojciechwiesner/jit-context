"""Feedby database calls over SSH (borg-ts -> docker exec feedby-sb-db psql).

Values are passed as psql variables (`-v name=value`, then `:'name'` in SQL), so psql quotes them;
each value is also shell-quoted for the SSH hop. Only slugs matching SLUG_PATTERN are accepted.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from typing import Dict, List, Optional

SSH_HOST_ENV = "JIT_FEEDBY_SSH_HOST"
DEFAULT_SSH_HOST = "borg-ts"
DB_CONTAINER = "feedby-sb-db"
DEFAULT_ORG_ID = "74b1e686-7e9e-4ba5-be93-fea0427e3e36"
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")
SSH_TIMEOUT_SECONDS = 60


class FeedbyRemoteError(RuntimeError):
    pass


def _psql(sql: str, variables: Dict[str, str]) -> List[List[str]]:
    host = os.environ.get(SSH_HOST_ENV, DEFAULT_SSH_HOST)
    var_args = " ".join(f"-v {name}={shlex.quote(value)}" for name, value in variables.items())
    remote = f"docker exec -i {DB_CONTAINER} psql -U postgres -d postgres -At -F '|' -v ON_ERROR_STOP=1 {var_args}"
    proc = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", host, remote],
        input=sql, capture_output=True, text=True, timeout=SSH_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        raise FeedbyRemoteError(proc.stderr.strip() or f"psql exit {proc.returncode}")
    return [line.split("|") for line in proc.stdout.splitlines() if line.strip()]


def check_slug(slug: str) -> str:
    if not SLUG_PATTERN.match(slug):
        raise ValueError(f"invalid Feedby slug: {slug!r}")
    return slug


def list_projects() -> List[Dict[str, str]]:
    sql = (
        "select p.slug, p.name, p.id, count(k.id) filter (where k.revoked_at is null) "
        "from projects p left join widget_keys k on k.project_id = p.id group by p.id order by p.slug;"
    )
    return [{"slug": r[0], "name": r[1], "id": r[2], "live_keys": r[3]} for r in _psql(sql, {})]


def find_project(slug: str) -> Optional[Dict[str, str]]:
    rows = _psql("select id, name from projects where slug = :'slug';", {"slug": check_slug(slug)})
    return {"id": rows[0][0], "name": rows[0][1], "slug": slug} if rows else None


def ensure_project(slug: str, name: str, org_id: str = DEFAULT_ORG_ID) -> Dict[str, str]:
    """Create the project if missing. Returns {'id', 'slug', 'created': '1'|'0'}."""
    sql = (
        "with ins as (insert into projects (org_id, name, slug) values (:'org', :'name', :'slug') "
        "on conflict (org_id, slug) do nothing returning id) "
        "select id, '1' from ins union all select id, '0' from projects "
        "where org_id = :'org' and slug = :'slug' and not exists (select 1 from ins);"
    )
    rows = _psql(sql, {"org": org_id, "name": name[:80], "slug": check_slug(slug)})
    if not rows:
        raise FeedbyRemoteError(f"project {slug} neither created nor found")
    return {"id": rows[0][0], "slug": slug, "created": rows[0][1]}


def insert_widget_key(project_id: str, key_hash: str, label: str) -> str:
    sql = (
        "insert into widget_keys (project_id, key_hash, label) values (:'pid', :'hash', :'label') "
        "returning id;"
    )
    rows = _psql(sql, {"pid": project_id, "hash": key_hash, "label": label[:60]})
    return rows[0][0]


def key_is_live(key_hash: str) -> Optional[str]:
    """Slug of the project owning an active key with this hash, or None."""
    sql = (
        "select p.slug from widget_keys k join projects p on p.id = k.project_id "
        "where k.key_hash = :'hash' and k.revoked_at is null;"
    )
    rows = _psql(sql, {"hash": key_hash})
    return rows[0][0] if rows else None
