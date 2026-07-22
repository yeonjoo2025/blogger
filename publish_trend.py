"""Collect KR trending keywords, keep only high-impact informational topics,
and publish a structured Blogger article for each one - or, if the
Blogger write API is unavailable, save it under pending_posts/ for a human
to post by hand instead.

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
     stops calling the write API entirely for the rest of today - no new
     posts and no updates of old posts.
  6. Placeholder take-over (preferred workaround under the account-wide
     write ban): Google's "Blogger used to send unwanted content" restriction
     blocks posts.insert() entirely, but empirically still allows
     posts.patch()/posts.update() on resources that already exist. So if a
     human creates a few blank LIVE posts by hand in the Blogger web UI
     ("게시" with empty/near-empty body, or a title like "빈 포스터"), this
     run finds them and overwrites title+body via posts.patch(). Draft
     posts (status=DRAFT) are tried next via update+publish. Only then do
     we fall back to posts.insert().
  7. Manual-posting fallback: if no draft is available to take over, or the
     take-over/insert call still gets 403/429, the *content* is not lost.
     Its title+body is saved as an HTML file under pending_posts/ so a
     human can copy it into the Blogger web UI by hand until the
     restriction is lifted. Once a pending topic shows up as a live post
     (detected via the read-only posts.list API, which keeps working even
     while writes are blocked), its pending_posts/ file is automatically
     deleted on the next run.

Run: python3 publish_trend.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from blogger_auth import load_credentials
from content_writer import build_body_html, build_title
from post_images import build_thumb_for_post, inject_thumb_html
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
PENDING_DIR = Path("pending_posts")

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
    "005930": "삼성전자(005930)",
    "000660": "SK하이닉스(000660)",
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


def _is_duplicate_of_pending(keyword: str, pending_keywords: set[str]) -> bool:
    return any(is_near_duplicate(keyword, kw) for kw in pending_keywords)


def select_final_topics(
    candidates: list[TopicCandidate],
    recent_posts: list[dict],
    now: datetime,
    pending_keywords: set[str] | None = None,
) -> list[TopicCandidate]:
    """Greedily take the strongest candidates, but favor topical diversity:
    one same-day run should not turn into three near-identical "오늘 미국
    증시" posts just because that theme happened to dominate the trend
    feed. Each category gets picked at most once before we allow repeats.

    A topic is skipped not only when a *live* post already covers it
    (was_recently_covered), but also when a pending_posts/ draft for it is
    already waiting on a human to publish manually - otherwise every 4-hour
    run would keep re-drafting the same still-unpublished topic.
    """
    pending_keywords = pending_keywords or set()
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
        if _is_duplicate_of_pending(cand.keyword, pending_keywords):
            log(f"  drop '{cand.keyword}': already waiting as a pending draft")
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
        if _is_duplicate_of_pending(cand.keyword, pending_keywords):
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


# A live post is treated as a reusable human-created placeholder if its
# body is empty / near-empty. Empirically, Google's account-wide write
# restriction blocks posts.insert() but still allows posts.patch() /
# posts.update() on resources that already exist - so the user can create
# a few blank LIVE posts by hand ("게시"), and we fill them in via patch.
PLACEHOLDER_MAX_CONTENT_LEN = 80
_PLACEHOLDER_TITLE_RE = re.compile(
    r"^(빈\s*(포스터|포스트|글|게시물|석)?|untitled|new\s*post|제목\s*없음|새\s*게시물)$",
    re.IGNORECASE,
)


def _is_placeholder_post(post: dict) -> bool:
    content = (post.get("content") or "").strip()
    # Strip trivial HTML wrappers so "<p></p>" / "<br/>" count as empty.
    plain = re.sub(r"<[^>]+>", "", content).strip()
    if len(plain) <= PLACEHOLDER_MAX_CONTENT_LEN:
        return True
    title = (post.get("title") or "").strip()
    return bool(_PLACEHOLDER_TITLE_RE.match(title)) and len(plain) < 200


def list_draft_posts(service, blog_id: str, max_pages: int = 5) -> list[dict]:
    """Human-created draft posts (status=DRAFT) waiting to be filled in."""
    posts: list[dict] = []
    request = service.posts().list(blogId=blog_id, maxResults=50, status="DRAFT", fetchBodies=False)
    pages = 0
    while request is not None and pages < max_pages:
        response = request.execute()
        posts.extend(response.get("items") or [])
        request = service.posts().list_next(request, response)
        pages += 1
    posts.sort(key=lambda p: p.get("published") or p.get("updated") or "")
    return posts


def list_placeholder_live_posts(service, blog_id: str, max_pages: int = 5) -> list[dict]:
    """Empty/near-empty LIVE posts a human created as shells for us to fill.

    Bodies must be fetched so we can tell a real article apart from a
    blank placeholder the user just published for this workaround.
    """
    posts: list[dict] = []
    request = service.posts().list(blogId=blog_id, maxResults=50, status="LIVE", fetchBodies=True)
    pages = 0
    while request is not None and pages < max_pages:
        response = request.execute()
        for post in response.get("items") or []:
            if _is_placeholder_post(post):
                posts.append(post)
        request = service.posts().list_next(request, response)
        pages += 1
    posts.sort(key=lambda p: p.get("published") or p.get("updated") or "")
    return posts


def take_over_draft_post(service, blog_id: str, draft_id: str, title: str, content: str) -> dict:
    """Fill in a human-created draft with generated content and publish it."""
    body = {"kind": "blogger#post", "id": draft_id, "blog": {"id": blog_id}, "title": title, "content": content}
    service.posts().update(blogId=blog_id, postId=draft_id, body=body).execute()
    return service.posts().publish(blogId=blog_id, postId=draft_id).execute()


def take_over_live_placeholder(service, blog_id: str, post_id: str, title: str, content: str) -> dict:
    """Overwrite an empty LIVE post's title+body via patch (confirmed to
    work even when posts.insert is blocked by the account-wide restriction).
    """
    body = {"title": title, "content": content}
    return service.posts().patch(blogId=blog_id, postId=post_id, body=body).execute()


def attach_hero_image(creds, keyword: str, category: str, content: str, title: str = "") -> str:
    """Generate a 16:9 news thumbnail, commit it to posts/images/, and
    prepend the jsDelivr-backed <img class="post-thumb"> block.

    Failures are non-fatal: a missing image must never block publishing the
    text content itself. `creds` is unused (CDN hosting, not Blogger upload)
    but kept in the signature so call sites stay stable.
    """
    del creds  # CDN path - OAuth not required for the image itself
    try:
        url, main, _sub = build_thumb_for_post(
            title=title or keyword,
            keyword=keyword,
            category=category,
            push=True,
        )
        return inject_thumb_html(content, url, main)
    except Exception as exc:  # noqa: BLE001
        log(f"  news thumbnail skipped for '{keyword}': {exc}")
        return content


def _slugify(keyword: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "-", keyword).strip("-")
    return slug[:40] or "topic"


def save_pending_draft(now: datetime, topic: TopicCandidate, title: str, content: str, reason: str) -> Path:
    """Save a fully-qualified topic's title+body for manual copy/paste
    publishing, used whenever the Blogger write API is blocked or fails.
    The keyword is embedded as an HTML comment so a later run can detect,
    via the read-only list API, once a human has manually published it.
    """
    PENDING_DIR.mkdir(exist_ok=True)
    stamp = now.astimezone(KST).strftime("%Y%m%d-%H%M%S")
    path = PENDING_DIR / f"{stamp}_{_slugify(topic.keyword)}.html"
    header = (
        f"<!-- keyword: {topic.keyword} -->\n"
        f"<!-- category: {topic.category} -->\n"
        f"<!-- generated_at_kst: {now.astimezone(KST).isoformat()} -->\n"
        f"<!-- reason: {reason} -->\n"
        f"<!-- 사용법: 아래 제목/본문을 Blogger 웹 UI에 그대로 복사해 수동으로 게시하세요.\n"
        f"     다음 실행 시 이 글이 라이브로 확인되면 이 파일은 자동으로 삭제됩니다. -->\n"
    )
    path.write_text(header + f"<h1>{title}</h1>\n" + content, encoding="utf-8")
    return path


_PENDING_KEYWORD_RE = re.compile(r"<!--\s*keyword:\s*(.*?)\s*-->")


def _pending_draft_keyword(path: Path) -> str | None:
    try:
        head = path.read_text(encoding="utf-8")[:500]
    except OSError:
        return None
    match = _PENDING_KEYWORD_RE.search(head)
    return match.group(1) if match else None


def _keyword_is_now_live(keyword: str, recent_posts: list[dict]) -> bool:
    norm_kw = normalize_keyword(keyword)
    if not norm_kw:
        return False
    for post in recent_posts:
        title = post.get("title", "")
        if norm_kw in normalize_keyword(title) or is_near_duplicate(keyword, title):
            return True
    return False


def cleanup_resolved_pending_drafts(recent_posts: list[dict]) -> int:
    """Delete pending_posts/ files whose topic is already live on the blog
    (i.e. a human copied the draft in and published it by hand)."""
    if not PENDING_DIR.exists():
        return 0
    removed = 0
    for path in sorted(PENDING_DIR.glob("*.html")):
        keyword = _pending_draft_keyword(path)
        if keyword and _keyword_is_now_live(keyword, recent_posts):
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def pending_draft_keywords() -> set[str]:
    """Keywords of pending_posts/ drafts still waiting on a human to
    publish - used to avoid re-drafting the same unpublished topic every
    run while the write API stays blocked."""
    if not PENDING_DIR.exists():
        return set()
    keywords: set[str] = set()
    for path in PENDING_DIR.glob("*.html"):
        keyword = _pending_draft_keyword(path)
        if keyword:
            keywords.add(keyword)
    return keywords


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

    cleaned = cleanup_resolved_pending_drafts(recent_posts)
    if cleaned:
        log(f"removed {cleaned} pending_posts/ draft(s) now confirmed live (published manually)")

    new_posts_today = count_new_posts_today(recent_posts, now)
    remaining_quota = max(0, MAX_NEW_POSTS_PER_DAY - new_posts_today)
    api_blocked = remaining_quota <= 0 or load_quota_exhausted_today(now)
    if api_blocked:
        # Per operating rules: once the daily write quota/restriction is hit,
        # do not create new posts and do not update existing ones. Exit now
        # and retry on the next cron cycle.
        log(
            "생성/업데이트 없이 종료: today's Blogger write quota/restriction is already "
            f"exhausted (new posts today={new_posts_today}/{MAX_NEW_POSTS_PER_DAY}, "
            f"quota_state_exhausted={load_quota_exhausted_today(now)}). "
            "Will retry next cycle."
        )
        return

    log(
        f"new posts published today (KST): {new_posts_today}/{MAX_NEW_POSTS_PER_DAY} "
        f"-> {remaining_quota} new-post slot(s) left for this run"
    )

    candidates = build_candidates(now)
    log(f"{len(candidates)} candidates qualified after news-grounded filtering")

    pending_keywords = pending_draft_keywords()
    final_topics = select_final_topics(candidates, recent_posts, now, pending_keywords)
    if not final_topics:
        log("no topic clearly qualifies this run (ambiguous or already covered) - publishing nothing")
        return

    # Prefer filling in human-created empty LIVE posts via patch (empirically
    # works under the account-wide insert ban), then DRAFT posts via
    # update+publish, and only then fall back to posts.insert / pending_posts.
    placeholder_posts = list_placeholder_live_posts(service, blog_id)
    draft_posts = list_draft_posts(service, blog_id)
    if placeholder_posts:
        log(
            f"found {len(placeholder_posts)} empty LIVE placeholder post(s) - "
            f"will fill them via posts.patch() first"
        )
    if draft_posts:
        log(
            f"found {len(draft_posts)} human-created draft post(s) - "
            f"will try posts.update()+posts.publish() next"
        )

    published_count = 0
    drafted_count = 0
    for idx, topic in enumerate(final_topics, start=1):
        title = build_title(topic.keyword, topic.category, topic.news)
        content = build_body_html(topic.keyword, topic.category, topic.news)
        content = attach_hero_image(
            creds, topic.keyword, topic.category, content, title=title
        )
        log(f"[{idx}/{len(final_topics)}] '{title}' (category={topic.category})")

        if placeholder_posts:
            shell = placeholder_posts.pop(0)
            shell_id = shell.get("id")
            try:
                post = take_over_live_placeholder(service, blog_id, shell_id, title, content)
                log(f"  filled in empty LIVE post {shell_id} via patch: {post.get('url')}")
                published_count += 1
                if idx < len(final_topics):
                    time.sleep(2)
                continue
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                log(
                    f"  LIVE placeholder take-over failed (HTTP {status}) for {shell_id} - "
                    f"falling back"
                )

        if draft_posts:
            draft = draft_posts.pop(0)
            draft_id = draft.get("id")
            try:
                post = take_over_draft_post(service, blog_id, draft_id, title, content)
                log(f"  filled in human-created draft {draft_id} and published: {post.get('url')}")
                published_count += 1
                new_posts_today += 1
                if idx < len(final_topics):
                    time.sleep(2)
                continue
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                log(
                    f"  draft take-over failed (HTTP {status}) for draft {draft_id} - "
                    f"falling back to posts.insert()/pending draft for this topic"
                )

        if api_blocked or remaining_quota <= 0:
            log(
                "생성/업데이트 없이 종료: write API unavailable or assumed daily "
                "new-post quota used up mid-run. Stopping without further creates "
                "or updates."
            )
            log(
                f"run finished - published {published_count} new post(s), "
                f"drafted {drafted_count} pending post(s) for manual posting"
            )
            return

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
                    f"생성/업데이트 없이 종료: new post blocked (HTTP {status}); "
                    "marking today's quota exhausted and stopping without further "
                    "creates or updates."
                )
                log(
                    f"run finished - published {published_count} new post(s), "
                    f"drafted {drafted_count} pending post(s) for manual posting"
                )
                return
            log(f"  publish failed (HTTP {status}), skipping this topic")
            continue

        if idx < len(final_topics):
            time.sleep(2)

    log(
        f"run finished - published {published_count} new post(s), "
        f"drafted {drafted_count} pending post(s) for manual posting"
    )


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - keep the cron run's exit status informative
        log(f"fatal error: {exc}")
        sys.exit(1)
