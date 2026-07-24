"""Fetch Blogger pageviews + local content mix stats for selection feedback."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from blogger_http import authed_get, build_blogger_service
from blogger_quality import classify_category, strip_html

BLOG_ID = "4736025457821775813"
STATS_PATH = Path(".blogger_stats.json")
REPO = "yeonjoo2025/blogger"


def fetch_pageviews(blog_id: str = BLOG_ID) -> dict[str, int]:
    out: dict[str, int] = {}
    for rng in ("all", "7DAYS", "30DAYS"):
        resp = authed_get(
            f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pageviews",
            params={"range": rng},
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("counts") or []:
            key = item.get("timeRange") or rng
            out[key] = int(item.get("count") or 0)
    return out


def fetch_recent_posts(blog_id: str = BLOG_ID, limit: int = 50) -> list[dict]:
    service = build_blogger_service()
    items: list[dict] = []
    req = service.posts().list(
        blogId=blog_id,
        status="LIVE",
        maxResults=min(limit, 50),
        fetchBodies=True,
        view="ADMIN",
    )
    while req is not None and len(items) < limit:
        resp = req.execute()
        items.extend(resp.get("items") or [])
        req = service.posts().list_next(req, resp)
    return items[:limit]


def summarize_posts(posts: list[dict]) -> dict:
    cats: Counter[str] = Counter()
    titles: list[str] = []
    mw = 0
    for p in posts:
        title = p.get("title") or ""
        titles.append(title)
        body = strip_html(p.get("content") or "")
        cats[classify_category(title, body)] += 1
        if "뭐길래" in title:
            mw += 1
    return {
        "total_posts": len(posts),
        "category_counts": dict(cats),
        "recent_titles": titles[:20],
        "mwogillae_in_sample": mw,
        "avg_chars": int(
            sum(len(strip_html(p.get("content") or "")) for p in posts) / max(len(posts), 1)
        ),
        "avg_labels": round(
            sum(len(p.get("labels") or []) for p in posts) / max(len(posts), 1), 1
        ),
    }


def category_boost(category: str, stats: dict) -> int:
    """Higher boost for historically stronger useful categories when PV is thin."""
    # Early blog: prefer guide/it over sports_ent/finance spam.
    base = {"guide": 3, "it": 2, "society": 1, "finance": 0, "other": 0, "sports_ent": -5}
    boost = base.get(category, 0)
    counts = (stats.get("content") or {}).get("category_counts") or {}
    # Soft diversity: if finance already dominates, nudge away.
    total = max(sum(counts.values()), 1)
    share = counts.get(category, 0) / total
    if category == "finance" and share > 0.35:
        boost -= 2
    if category == "guide" and share < 0.2:
        boost += 1
    return boost


def save_stats(path: Path = STATS_PATH) -> dict:
    pageviews = fetch_pageviews()
    posts = fetch_recent_posts()
    content = summarize_posts(posts)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "blog_id": BLOG_ID,
        "pageviews": pageviews,
        "content": content,
        "selection_hints": {
            "prefer": ["guide", "it", "society"],
            "avoid": ["sports_ent"],
            "note": "PV is blog-level only; use category mix + usefulness gates.",
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_stats(path: Path = STATS_PATH) -> dict:
    if not path.exists():
        return save_stats(path)
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Blogger stats cache")
    parser.add_argument("--print", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()
    data = save_stats()
    print(f"STATS_SAVED={STATS_PATH}")
    print(f"PAGEVIEWS_ALL={data['pageviews'].get('ALL_TIME')}")
    print(f"PAGEVIEWS_7D={data['pageviews'].get('SEVEN_DAYS')}")
    print(f"CATEGORY_COUNTS={data['content']['category_counts']}")
    if args.print:
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
