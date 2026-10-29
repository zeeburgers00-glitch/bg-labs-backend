"""Curated, license-labelled index of portable open-source agent skills.

Only SKILL.md metadata is bundled. Skill bodies are fetched on demand from
pinned upstream commits, shown for review, and imported as prompt text; no
repository code, binaries, or shell commands are executed by this feature.
"""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

_INDEX_PATH = Path(__file__).with_name("marketplace_index.json")
with _INDEX_PATH.open(encoding="utf-8") as _stream:
    _INDEX: Dict[str, Any] = json.load(_stream)
_SKILLS = _INDEX["skills"]
_BY_ID = {row["id"]: row for row in _SKILLS}
_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL = 3600


def summary() -> Dict[str, Any]:
    return {"count": len(_SKILLS), "sources": _INDEX["sources"], "generated_at": _INDEX["generated_at"],
            "notice": "Catalog entries are source references. Review every skill before importing; no source code is run."}


def search(query: str = "", source: str = "", page: int = 1, page_size: int = 25) -> Dict[str, Any]:
    q = " ".join(str(query or "").split()).casefold()[:100]
    source_key = str(source or "").strip().lower()
    page = max(1, min(int(page or 1), 200))
    page_size = max(1, min(int(page_size or 25), 50))
    rows = _SKILLS
    if source_key:
        rows = [row for row in rows if row["source_id"] == source_key]
    if q:
        rows = [row for row in rows if q in row["name"].casefold() or q in row["slug"].casefold()
                or q in row["repo"].casefold() or q in row["path"].casefold()]
    total = len(rows)
    start = (page - 1) * page_size
    return {"query": q, "source": source_key, "page": page, "page_size": page_size,
            "total": total, "pages": (total + page_size - 1) // page_size,
            "skills": rows[start:start + page_size], "catalog_total": len(_SKILLS),
            "sources": _INDEX["sources"]}


def entry(skill_id: str) -> Optional[Dict[str, Any]]:
    return _BY_ID.get(str(skill_id or ""))


def _frontmatter(text: str) -> tuple[Dict[str, str], str]:
    """Parse common scalar YAML frontmatter without adding a YAML dependency."""
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", text, flags=re.S)
    if not match:
        return {}, text
    fields: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        item = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", line)
        if item:
            fields[item.group(1).lower()] = item.group(2).strip("\"'")
    return fields, text[match.end():].strip()


async def fetch(skill_id: str) -> Dict[str, Any]:
    row = entry(skill_id)
    if not row:
        raise KeyError("Marketplace skill not found")
    cached = _CACHE.get(skill_id)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        return dict(cached[1])
    encoded_path = quote(row["path"], safe="/")
    url = f"https://api.github.com/repos/{row['repo']}/contents/{encoded_path}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), headers={
        "Accept": "application/vnd.github+json", "User-Agent": "BG-LABS-Skill-Marketplace"
    }) as client:
        response = await client.get(url, params={"ref": row["ref"]})
    if response.status_code == 404:
        raise KeyError("Pinned upstream skill file no longer exists")
    if response.status_code == 403:
        raise RuntimeError("GitHub API rate limit reached; wait before loading another skill")
    response.raise_for_status()
    data = response.json()
    if data.get("encoding") != "base64" or not data.get("content"):
        raise ValueError("Upstream did not return a text skill file")
    try:
        raw = base64.b64decode(data["content"], validate=False).decode("utf-8", errors="replace")
    except Exception as exc:
        raise ValueError("Could not decode upstream skill text") from exc
    if len(raw) > 64_000:
        raise ValueError("This skill file is over the 64 KB preview limit")
    meta, instructions = _frontmatter(raw)
    result = {**row, "description": meta.get("description", "")[:500],
              "upstream_name": meta.get("name", ""), "instructions": instructions,
              "raw_markdown": raw, "bytes": len(raw.encode("utf-8")),
              "importable": bool(instructions) and len(instructions) <= 12_000,
              "import_limit": 12_000,
              "review_notice": "Imported text can guide an LLM response. It cannot execute repo code or take external actions in BG LABS."}
    _CACHE[skill_id] = (time.monotonic(), result)
    if len(_CACHE) > 256:
        oldest = sorted(_CACHE, key=lambda key: _CACHE[key][0])[:64]
        for key in oldest:
            _CACHE.pop(key, None)
    return dict(result)


__all__ = ["summary", "search", "entry", "fetch"]
