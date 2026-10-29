#!/usr/bin/env python3
"""Refresh the small metadata-only community Skill Marketplace index.

Usage: python scripts/refresh_skill_marketplace.py
Requires only Python stdlib and outbound access to api.github.com. Skill bodies
are not copied; the app fetches selected SKILL.md files from pinned commits.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "app" / "skills" / "marketplace_index.json"
SOURCES = [
    {"id": "aas", "repo": "sickn33/agentic-awesome-skills", "name": "Agentic Awesome Skills",
     "branch": "main", "license": "MIT", "prefixes": ["skills/"]},
    {"id": "copilot", "repo": "github/awesome-copilot", "name": "GitHub Awesome Copilot",
     "branch": "main", "license": "MIT", "prefixes": ["skills/", ".github/skills/"]},
    {"id": "anthropic", "repo": "anthropics/skills", "name": "Anthropic Skills",
     "branch": "main", "license": "Apache-2.0", "prefixes": ["skills/"]},
]


def get_json(url: str):
    req = Request(url, headers={"Accept": "application/vnd.github+json",
                               "User-Agent": "BG-LABS-Skill-Marketplace-Index-Builder"})
    with urlopen(req, timeout=45) as response:
        return json.load(response)


def main() -> int:
    skills = []
    sources = []
    for source in SOURCES:
        try:
            commit = get_json(f"https://api.github.com/repos/{source['repo']}/commits/{source['branch']}")
            ref = commit["sha"]
            tree = get_json(f"https://api.github.com/repos/{source['repo']}/git/trees/{ref}?recursive=1")
        except (HTTPError, URLError, KeyError, TimeoutError) as exc:
            print(f"ERROR: could not index {source['repo']}: {exc}", file=sys.stderr)
            return 1
        if tree.get("truncated"):
            print(f"ERROR: GitHub returned a truncated tree for {source['repo']}; refusing partial index", file=sys.stderr)
            return 1
        row = {k: source[k] for k in ("id", "repo", "name", "license")}
        row["ref"] = ref
        sources.append(row)
        count = 0
        for node in tree.get("tree", []):
            path = node.get("path", "")
            if not path.lower().endswith("/skill.md") or not any(path.startswith(p) for p in source["prefixes"]):
                continue
            parent = path.rsplit("/", 2)[-2]
            slug = re.sub(r"[^a-z0-9]+", "-", parent.lower()).strip("-")[:48].strip("-")
            if len(slug) < 2:
                continue
            skills.append({"id": source["id"] + ":" + path, "name": parent.replace("-", " ").replace("_", " ").strip().title(),
                           "slug": slug, "source_id": source["id"], "source_name": source["name"],
                           "repo": source["repo"], "ref": ref, "path": path, "license": source["license"],
                           "url": f"https://github.com/{source['repo']}/blob/{ref}/{path}"})
            count += 1
        print(f"{source['repo']}: indexed {count} SKILL.md files at {ref[:12]}")
    skills = list({row["id"]: row for row in skills}.values())
    skills.sort(key=lambda row: (row["name"].casefold(), row["source_id"], row["path"]))
    result = {"version": 1, "generated_at": datetime.now(timezone.utc).date().isoformat(),
              "source_count": len(sources), "skill_count": len(skills), "sources": sources, "skills": skills}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {len(skills)} skills ({OUTPUT.stat().st_size:,} bytes) to {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
