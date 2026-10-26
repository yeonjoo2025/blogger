"""Fetch Blogger pageviews + local content mix + performance pattern hints."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from blogger_http import authed_get, build_blogger_service
from blogger_quality import (
    COMMERCIAL_INTENT_RE,
    classify_category,
    classify_intent,
    commercial_intent_score,
    strip_html,
)

BLOG_ID = "4736025457821775813"
STATS_PATH = Path(".blogger_stats.json")
PERF_PATH = Path(".blogger_performance.json")
REPO = "yeonjoo2025/blogger"

# Title/body patterns that historically fit monetizable SEO (guide/compare/apply).
WINNING_PATTERNS = [
    ("checklist", re.compile(r"체크리스트")),
    ("howto", re.compile(r"방법|가이드|보는\s*법")),
    ("schedule_apply", re.compile(r"사전판매|신청|예약|일정")),
    ("price_compare", re.compile(r"가격|출고가|비교|요금")),
    ("refund_benefit", re.compile(r"환급|지원금|혜택|할인")),
]

LOW_RPM_PATTERNS = [
    ("ticker_earnings", re.compile(r"실적|EPS|가이던스|티커|급등|급락")),
    ("sports_ent", re.compile(r"경기|무승부|연예|개봉")),
    ("mwogillae", re.compile(r"뭐길래")),
]


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


def load_performance_overrides(path: Path = PERF_PATH) -> dict:
    """Optional manual/GSC import: {urls: {url: {clicks, impressions, note}}}."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def summarize_posts(posts: list[dict], perf: dict | None = None) -> dict:
    perf = perf or {}
    url_perf = perf.get("urls") or {}
    cats: Counter[str] = Counter()
    intents: Counter[str] = Counter()
    pattern_hits: Counter[str] = Counter()
    titles: list[str] = []
    url_index: list[dict] = []
    mw = 0
    for p in posts:
        title = p.get("title") or ""
        url = p.get("url") or ""
        titles.append(title)
        body = strip_html(p.get("content") or "")
        cat = classify_category(title, body)
        intent = classify_intent(title, title, body)
        cats[cat] += 1
        intents[intent] += 1
        if "뭐길래" in title:
            mw += 1
        for name, cre in WINNING_PATTERNS:
            if cre.search(title) or cre.search(body[:400]):
                pattern_hits[name] += 1
        for name, cre in LOW_RPM_PATTERNS:
            if cre.search(title):
                pattern_hits[f"low:{name}"] += 1
        entry = {
            "title": title,
            "url": url,
            "category": cat,
            "intent": intent,
            "intent_score": commercial_intent_score(title, title, body),
            "published": p.get("published"),
            "labels_count": len(p.get("labels") or []),
            "chars": len(body),
        }
        if url in url_perf:
            entry["clicks"] = url_perf[url].get("clicks")
            entry["impressions"] = url_perf[url].get("impressions")
        url_index.append(entry)

    # Prefer posts with GSC clicks when present; else commercial intent score.
    ranked = sorted(
        url_index,
        key=lambda x: (
            x.get("clicks") is not None,
            x.get("clicks") or 0,
            x.get("intent_score") or 0,
        ),
        reverse=True,
    )
    refresh_candidates = [
        x
        for x in ranked
        if x.get("intent") in {"how-to", "compare", "price", "apply", "refresh"}
        or COMMERCIAL_INTENT_RE.search(x.get("title") or "")
    ][:8]

    return {
        "total_posts": len(posts),
        "category_counts": dict(cats),
        "intent_counts": dict(intents),
        "pattern_hits": dict(pattern_hits),
        "recent_titles": titles[:20],
        "recent_urls": [
            {"title": t["title"], "url": t["url"], "category": t["category"]}
            for t in url_index[:20]
            if t.get("url")
        ],
        "top_patterns_for_selection": [
            name
            for name, _ in sorted(
                ((n, c) for n, c in pattern_hits.items() if not n.startswith("low:")),
                key=lambda kv: kv[1],
                reverse=True,
            )[:5]
        ],
        "avoid_patterns": [
            name[4:]
            for name, _ in sorted(
                ((n, c) for n, c in pattern_hits.items() if n.startswith("low:")),
                key=lambda kv: kv[1],
                reverse=True,
            )[:5]
        ],
        "refresh_candidates": refresh_candidates,
        "mwogillae_in_sample": mw,
        "avg_chars": int(
            sum(len(strip_html(p.get("content") or "")) for p in posts) / max(len(posts), 1)
        ),
        "avg_labels": round(
            sum(len(p.get("labels") or []) for p in posts) / max(len(posts), 1), 1
        ),
    }


def category_boost(category: str, stats: dict) -> int:
    """Higher boost for monetizable categories; demote finance spam when over-indexed."""
    base = {"guide": 4, "it": 3, "society": 1, "finance": -1, "other": 0, "sports_ent": -5}
    boost = base.get(category, 0)
    counts = (stats.get("content") or {}).get("category_counts") or {}
    total = max(sum(counts.values()), 1)
    share = counts.get(category, 0) / total
    if category == "finance" and share > 0.25:
        boost -= 3
    if category == "guide" and share < 0.25:
        boost += 2
    if category == "it" and share < 0.15:
        boost += 1

    # Performance-pattern nudge from catalogued winning patterns.
    top = (stats.get("content") or {}).get("top_patterns_for_selection") or []
    if category in {"guide", "it"} and top:
        boost += 1
    return boost


def intent_boost(intent: str, stats: dict) -> int:
    money = {"how-to": 3, "compare": 3, "price": 3, "apply": 4, "refresh": 4}
    soft = {"explainer": 1, "decision": 0}
    boost = money.get(intent, soft.get(intent, 0))
    intents = (stats.get("content") or {}).get("intent_counts") or {}
    total = max(sum(intents.values()), 1)
    if intent == "decision" and intents.get("decision", 0) / total > 0.3:
        boost -= 2
    return boost


def selection_score(
    *,
    category: str,
    intent: str,
    keyword: str,
    title: str,
    stats: dict,
) -> int:
    """Composite score for picking the next topic (higher = better)."""
    score = 0
    score += category_boost(category, stats)
    score += intent_boost(intent, stats)
    score += commercial_intent_score(keyword, title)
    title_body = f"{keyword} {title}"
    for name, cre in WINNING_PATTERNS:
        if cre.search(title_body):
            score += 2
            break
    for name, cre in LOW_RPM_PATTERNS:
        if cre.search(title_body):
            score -= 3
    # Prefer patterns already working on the blog.
    for pat in (stats.get("content") or {}).get("top_patterns_for_selection") or []:
        for name, cre in WINNING_PATTERNS:
            if name == pat and cre.search(title_body):
                score += 2
    return score


def save_stats(path: Path = STATS_PATH) -> dict:
    pageviews = fetch_pageviews()
    posts = fetch_recent_posts()
    perf = load_performance_overrides()
    content = summarize_posts(posts, perf)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "blog_id": BLOG_ID,
        "pageviews": pageviews,
        "content": content,
        "selection_hints": {
            "prefer_categories": ["guide", "it", "society"],
            "prefer_intents": ["apply", "how-to", "compare", "price", "refresh"],
            "avoid_categories": ["sports_ent"],
            "avoid_intents": ["decision"] if content.get("intent_counts", {}).get("decision", 0) > 8 else [],
            "prefer_patterns": content.get("top_patterns_for_selection") or [
                "checklist",
                "schedule_apply",
                "price_compare",
            ],
            "refresh_first": [
                {"title": r["title"], "url": r["url"]}
                for r in (content.get("refresh_candidates") or [])[:5]
            ],
            "note": (
                "Use selection_score/intent; PV is blog-level only. "
                "Optional per-URL clicks: write .blogger_performance.json from GSC."
            ),
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
    print(f"INTENT_COUNTS={data['content'].get('intent_counts')}")
    print(f"TOP_PATTERNS={data['content'].get('top_patterns_for_selection')}")
    print(f"REFRESH_CANDIDATES={len(data['content'].get('refresh_candidates') or [])}")
    hints = data.get("selection_hints") or {}
    print(f"PREFER_INTENTS={hints.get('prefer_intents')}")
    print(f"PREFER_PATTERNS={hints.get('prefer_patterns')}")
    if args.print:
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
