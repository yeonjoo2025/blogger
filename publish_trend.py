"""Collect KR trending keywords, keep only high-impact informational topics,
and publish (or, if new posts are blocked, update an old post with) a
structured Blogger article for each one.

Pipeline:
  1. Collect keyword candidates from Google Trends KR, loword.co.kr and
     blackkiwi.net across 1h / 4h / 24h windows (trend_sources.py).
  2. Drop entertainment / celebrity / sports / pure-name topics and keep
     only finance / investment / health / life-safety / legal topics that
     real news coverage confirms (keyword_filter.py).
  3. Pick at most MAX_POSTS_PER_RUN of the strongest, non-duplicate topics
     (default 1). This is an editorial cap ("가장 이슈가 되는 것만, 애매하면
     줄인다"), independent of Blogger's API quota below - running every 4
     hours at 1/run keeps daily volume modest and sustainable on its own.
     If nothing clearly qualifies, publish nothing rather than force a
     weak post.
  4. Build a 5-section article (issue / affected / how to check / how to
     respond / related news) per topic (content_writer.py).
  5. Publish via the Blogger API, respecting a tracked daily new-post quota.
     Blogger has no officially documented per-day limit, but widely and
     consistently reported real-world behavior across many accounts puts it
     around 50 new posts/day per blog (independent of, and much lower than,
     the Cloud Console's generic per-project request quota) - and young /
     low-trust blogs are frequently throttled far below that (we observed
     just 6/day on this brand-new blog). Because the real number varies and
     isn't discoverable in advance, we only use MAX_NEW_POSTS_PER_DAY
     (default 50, override with BLOGGER_MAX_NEW_POSTS_PER_DAY) as an upper
     bound to skip an obviously-doomed insert call. The moment Blogger
     returns 403/429 (or the assumed quota is already exhausted), this run
     stops publishing entirely - no new posts and no updates of old posts -
     and waits for the next cron cycle when quota may have reset.

Run: python3 publish_trend.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from blogger_auth import load_credentials
from content_writer import build_body_html, build_title
from keyword_filter import (
    TopicCandidate,
    classify,
    group_trend_items,
    headline_coherence,
    is_near_duplicate,
    is_qualified,
    normalize_keyword,
)
from trend_sources import KST, TrendItem, collect_all_trends, fetch_related_news

DEDUPE_LOOKBACK_HOURS = 20
NEWS_PER_CANDIDATE = 15
NEWS_SHOWN_IN_POST = 6
QUOTA_STATE_PATH = Path(".blogger_quota_state.json")

# Editorial cap: how many topics we're willing to write about per run. This
# is a *content quality* decision ("가장 이슈가 되는 것만 작성, 애매하면
# 줄인다"), deliberately independent of the API quota constant below. This
# automation's cron runs every 4 hours (6x/day); at 1/run that's at most 6
# new articles/day, a modest and sustainable pace regardless of what
# Blogger's real per-day insert quota turns out to be.
MAX_POSTS_PER_RUN = int(os.environ.get("BLOGGER_MAX_POSTS_PER_RUN", "1"))

# Technical cap: an assumed upper bound on Blogger's undocumented daily
# new-post quota, used only to skip an insert call we already expect to
# fail. ~50/day per blog is the figure most consistently reported by
# developers over the years; real behavior can be much stricter for young
# blogs (see module docstring). Override with BLOGGER_MAX_NEW_POSTS_PER_DAY
# if this account's real limit is known to differ.
MAX_NEW_POSTS_PER_DAY = int(os.environ.get("BLOGGER_MAX_NEW_POSTS_PER_DAY", "50"))


def log(msg: str) -> None:
    print(f"[publish_trend] {msg}", flush=True)


_TICKER_DISPLAY_NAMES = {
    "tsla": "테슬라(TSLA)",
    "mu": "마이크론(MU)",
    "nvda": "엔비디아(NVDA)",
    "aapl": "애플(AAPL)",
    "msft": "마이크로소프트(MSFT)",
    "googl": "구글(GOOGL)",
    "amzn": "아마존(AMZN)",
    "meta": "메타(META)",
    "amd": "AMD",
    "intc": "인텔(INTC)",
    "iren": "아이렌(IREN)",
    "spy": "S&P500 ETF(SPY)",
}


def pick_display_keyword(items: list[TrendItem]) -> tuple[str, str]:
    """Return (search_keyword, display_keyword).

    search_keyword is what we feed to the news search (kept close to the
    raw trend text for recall); display_keyword is what shows up in the
    title/body (prettified for bare tickers like "tsla" -> "테슬라(TSLA)").
    """
    raw = min((i.keyword for i in items), key=len)
    pretty = _TICKER_DISPLAY_NAMES.get(raw.strip().lower())
    return raw, (pretty or raw)


def score_group(items: list[TrendItem], news_count: int, coherence: float) -> float:
    """Rank candidates mainly by how well *substantiated and focused* the
    issue is: real news volume, single-event headline coherence, and
    confirmation from more than one collection source. Trend rank/traffic/
    window breadth are only secondary tie-breakers.
    """
    sources = {i.source for i in items}
    windows = set()
    for i in items:
        windows.update(i.windows)
    best_rank = min((i.rank for i in items if i.rank), default=20)
    traffic = max((i.traffic for i in items if i.traffic), default=0)

    score = 0.0
    score += coherence * 60
    score += news_count * 3
    score += len(sources) * 15
    score += len(windows) * 4
    score += max(0, 15 - best_rank) * 0.5
    score += min(traffic, 20000) / 1000
    return score


def build_candidates(now: datetime) -> list[TopicCandidate]:
    all_items = collect_all_trends(now)
    log(f"collected {len(all_items)} raw trend items from all sources")

    groups = group_trend_items(all_items)
    log(f"grouped into {len(groups)} unique keywords")

    # Keyword text alone is often too generic to judge (e.g. "황강댐" only
    # reveals its real-life-safety angle once we see the news about a dam
    # release). So we only drop a group here when the bare keyword is
    # unambiguously entertainment/sports with no competing include signal;
    # everything else goes on to a real news lookup before judging it.
    prelim: list[tuple[str, str, list[TrendItem]]] = []
    for _norm_kw, items in groups.items():
        search_kw, display_kw = pick_display_keyword(items)
        _category_guess, include_hits, exclude_hits = classify(search_kw, [])
        if exclude_hits > 0 and include_hits == 0:
            continue
        prelim.append((search_kw, display_kw, items))

    log(f"{len(prelim)} keywords pass the quick exclude filter, checking news for each")

    candidates: list[TopicCandidate] = []
    for search_kw, display_kw, items in prelim:
        news = fetch_related_news(search_kw, limit=NEWS_PER_CANDIDATE)
        qualified, category, reason = is_qualified(search_kw, news)
        if not qualified:
            log(f"  skip '{display_kw}': {reason}")
            continue

        sources = {i.source for i in items}
        windows: set[str] = set()
        for i in items:
            windows.update(i.windows)
        traffic = max((i.traffic for i in items if i.traffic), default=0)
        coherence = headline_coherence(search_kw, news)
        score = score_group(items, len(news), coherence)

        log(
            f"  candidate '{display_kw}' [{category}] score={score:.1f} coherence={coherence:.2f} "
            f"sources={sources} windows={windows}"
        )
        candidates.append(
            TopicCandidate(
                keyword=display_kw,
                category=category,
                score=score,
                sources=sources,
                windows=windows,
                traffic=traffic,
                news=news,
            )
        )

    candidates.sort(key=lambda c: -c.score)
    return candidates


def list_all_live_posts(service, blog_id: str, max_pages: int = 15) -> list[dict]:
    posts: list[dict] = []
    request = service.posts().list(blogId=blog_id, maxResults=50, status="LIVE", fetchBodies=False)
    pages = 0
    while request is not None and pages < max_pages:
        response = request.execute()
        posts.extend(response.get("items") or [])
        request = service.posts().list_next(request, response)
        pages += 1
    return posts


def was_recently_covered(keyword: str, recent_posts: list[dict], now: datetime, hours: int) -> bool:
    norm_kw = normalize_keyword(keyword)
    cutoff = now - timedelta(hours=hours)
    for post in recent_posts:
        published = post.get("published")
        if not published:
            continue
        try:
            pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            continue
        if pub_dt < cutoff:
            continue
        title = post.get("title", "")
        norm_title = normalize_keyword(title)
        if norm_kw and (norm_kw in norm_title or is_near_duplicate(keyword, title)):
            return True
    return False


def select_final_topics(
    candidates: list[TopicCandidate], recent_posts: list[dict], now: datetime
) -> list[TopicCandidate]:
    """Greedily take the strongest candidates, but favor topical diversity:
    one same-day run should not turn into three near-identical "오늘 미국
    증시" posts just because that theme happened to dominate the trend
    feed. Each category gets picked at most once before we allow repeats.
    """
    final: list[TopicCandidate] = []
    used_categories: set[str] = set()

    for cand in candidates:
        if cand.category in used_categories:
            continue
        if any(is_near_duplicate(cand.keyword, f.keyword) for f in final):
            continue
        if was_recently_covered(cand.keyword, recent_posts, now, DEDUPE_LOOKBACK_HOURS):
            log(f"  drop '{cand.keyword}': already covered by a recent post")
            continue
        final.append(cand)
        used_categories.add(cand.category)
        if len(final) >= MAX_POSTS_PER_RUN:
            return final

    # Not enough distinct categories qualified - allow repeats to fill up
    # to MAX_POSTS_PER_RUN rather than leaving obviously good topics unused.
    for cand in candidates:
        if len(final) >= MAX_POSTS_PER_RUN:
            break
        if any(cand.keyword == f.keyword for f in final):
            continue
        if any(is_near_duplicate(cand.keyword, f.keyword) for f in final):
            continue
        if was_recently_covered(cand.keyword, recent_posts, now, DEDUPE_LOOKBACK_HOURS):
            continue
        final.append(cand)

    return final


def _today_kst_key(now: datetime) -> str:
    return now.astimezone(KST).date().isoformat()


def load_quota_exhausted_today(now: datetime) -> bool:
    """Return True if a previous run already saw today's new-post quota hit."""
    if not QUOTA_STATE_PATH.exists():
        return False
    try:
        data = json.loads(QUOTA_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(data.get("exhausted")) and data.get("date") == _today_kst_key(now)


def mark_quota_exhausted_today(now: datetime, observed_count: int) -> None:
    payload = {
        "date": _today_kst_key(now),
        "exhausted": True,
        "observed_new_posts": observed_count,
        "marked_at": now.astimezone(KST).isoformat(),
    }
    QUOTA_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def count_new_posts_today(recent_posts: list[dict], now: datetime) -> int:
    """Count posts whose original publish date falls on today's KST date.

    This only counts genuinely *new* posts created today - exactly what
    Blogger's daily new-post quota cares about.
    """
    today_kst = now.astimezone(KST).date()
    count = 0
    for post in recent_posts:
        published = post.get("published")
        if not published:
            continue
        try:
            pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            continue
        if pub_dt.astimezone(KST).date() == today_kst:
            count += 1
    return count


def publish_new_post(service, blog_id: str, title: str, content: str) -> dict:
    body = {"kind": "blogger#post", "blog": {"id": blog_id}, "title": title, "content": content}
    return service.posts().insert(blogId=blog_id, body=body, isDraft=False).execute()


def main() -> None:
    now = datetime.now(timezone.utc)

    creds = load_credentials()
    service = build("blogger", "v3", credentials=creds, cache_discovery=False)

    blogs = service.blogs().listByUser(userId="self").execute()
    blog_items = blogs.get("items") or []
    if not blog_items:
        raise SystemExit("No Blogger blogs found for this Google account.")
    blog = blog_items[0]
    blog_id = blog["id"]
    log(f"using blog: {blog.get('name', '(unnamed)')} ({blog_id})")

    recent_posts = list_all_live_posts(service, blog_id)
    log(f"fetched {len(recent_posts)} existing live posts for dedupe")

    new_posts_today = count_new_posts_today(recent_posts, now)
    remaining_quota = max(0, MAX_NEW_POSTS_PER_DAY - new_posts_today)
    log(
        f"new posts published today (KST): {new_posts_today}/{MAX_NEW_POSTS_PER_DAY} "
        f"-> {remaining_quota} new-post slot(s) left for this run"
    )
    if remaining_quota <= 0 or load_quota_exhausted_today(now):
        if remaining_quota > 0:
            log(
                "a previous run already hit today's new-post quota (403/429) - "
                "stopping without creating or updating posts"
            )
        else:
            log("daily new-post quota already used up - stopping without creating or updating posts")
        return

    candidates = build_candidates(now)
    log(f"{len(candidates)} candidates qualified after news-grounded filtering")

    final_topics = select_final_topics(candidates, recent_posts, now)
    if not final_topics:
        log("no topic clearly qualifies this run (ambiguous or already covered) - publishing nothing")
        return

    published_count = 0
    for idx, topic in enumerate(final_topics, start=1):
        if remaining_quota <= 0:
            log("daily new-post quota used up mid-run - stopping without further create/update")
            break

        title = build_title(topic.keyword, topic.category)
        content = build_body_html(topic.keyword, topic.category, topic.news)
        log(f"[{idx}/{len(final_topics)}] '{title}' (category={topic.category})")

        try:
            post = publish_new_post(service, blog_id, title, content)
            log(f"  published: {post.get('url')}")
            remaining_quota -= 1
            published_count += 1
            new_posts_today += 1
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status in (403, 429):
                mark_quota_exhausted_today(now, new_posts_today)
                log(
                    f"  new post blocked (HTTP {status}); marking today's quota exhausted "
                    f"and stopping without creating or updating further posts"
                )
                break
            log(f"  publish failed (HTTP {status}), skipping this topic")

        if idx < len(final_topics) and remaining_quota > 0:
            time.sleep(2)

    log(f"run finished - published {published_count} new post(s)")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - keep the cron run's exit status informative
        log(f"fatal error: {exc}")
        sys.exit(1)
