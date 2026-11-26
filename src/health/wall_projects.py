"""Operator Wall: project tiles (active in 7 days, mirrors collapsed by git remote, charters attached)."""
from __future__ import annotations

import re
from typing import Any

from health import wall_charters, wall_external

ACTIVE_WINDOW_S = 7 * 86400
REMOTE_CACHE_S = 3600.0
GIT_TIMEOUT_S = 3
SCP_REMOTE_RE = re.compile(r"^[\w.-]+@([\w.-]+):(.+)$")


def normalise_remote(url: str) -> str:
    """git@host:org/repo.git, https://host/org/repo and ssh://git@host/org/repo.git compare equal."""
    url = url.strip().lower()
    scp = SCP_REMOTE_RE.match(url)
    if scp:
        url = f"{scp.group(1)}/{scp.group(2)}"
    url = re.sub(r"^[a-z+]+://", "", url)
    url = re.sub(r"^[^@/]+@", "", url)
    return url.rstrip("/").removesuffix(".git")


def _read_remote(path: str) -> str:
    try:
        return normalise_remote(wall_external.run(["git", "-C", path, "config", "--get", "remote.origin.url"], GIT_TIMEOUT_S))
    except Exception:
        return ""  # no remote / not a git dir: the project simply is not deduplicated


def remote_of(project: dict[str, Any]) -> str:
    path = project.get("path")
    if not path:
        return ""
    return wall_external.cached(f"remote:{path}", REMOTE_CACHE_S, lambda: _read_remote(path))[0]


def collapse_mirrors(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Projects sharing a git remote are one project: keep the shortest slug, list the rest as `mirrors`."""
    groups: dict[str, list[dict[str, Any]]] = {}
    singles: list[dict[str, Any]] = []
    for proj in projects:
        remote = remote_of(proj)
        (groups.setdefault(remote, []) if remote else singles).append(proj)
    kept = list(singles)
    for members in groups.values():
        members.sort(key=lambda p: (len(p["slug"]), p["slug"]))
        kept.append({**members[0], "mirrors": [m["slug"] for m in members[1:]]})
    return kept


def _audience(charter: dict[str, Any] | None) -> list[str]:
    return charter["audience"] if charter and charter["status"] == "approved" else []


def tiles(projects, charters, autocheck, sessions, now: float) -> list[dict[str, Any]]:
    reviews: dict[str, int] = {}
    oldest: dict[str, float] = {}  # project -> epoch of its oldest session waiting for review
    for row in sessions or []:
        if row["status"] == "review":
            reviews[row["project"]] = reviews.get(row["project"], 0) + 1
            oldest[row["project"]] = min(oldest.get(row["project"], row["since"]), row["since"])
    active = [p for p in projects or [] if now - p["last_activity"] <= ACTIVE_WINDOW_S]
    out = []
    for proj in collapse_mirrors(active):
        slug = proj["slug"]
        check = ((autocheck or {}).get("projects") or {}).get(slug)
        charter = None if charters is None else wall_charters.summary(wall_charters.find(charters, slug))
        out.append({
            "slug": slug, "title": proj["title"], "link": f"/mc?project={slug}", "charter": charter,
            "charter_known": charters is not None, "mirrors": proj.get("mirrors", []),
            "last_commit": proj.get("last_commit"), "last_activity": proj["last_activity"],
            "review_count": reviews.get(slug, 0), "oldest_review": oldest.get(slug), "blockers": proj.get("blockers", 0),
            "autocheck": check["state"] if check else None, "audience": _audience(charter),
        })
    out.sort(key=lambda t: (t["autocheck"] not in (None, "ok"), t["review_count"], t["last_activity"]), reverse=True)
    return out
