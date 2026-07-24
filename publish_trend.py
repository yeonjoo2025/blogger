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
from post_images import MissingAIThumbError, build_thumb_for_post, inject_thumb_html
from keyword_filter import (
    TopicCandidate,
    classify,
    group_trend_items,
    headline_coherence,
    is_earnings_topic,
    is_near_duplicate,
    is_qualified,
    normalize_keyword,
)
from trend_sources import KST, TrendItem, collect_all_trends, fetch_related_news

DEDUPE_LOOKBACK_HOURS = 24 * 7  # 최근 7일 동일/유사 주제 하드 스킵
NEWS_PER_CANDIDATE = 15
NEWS_SHOWN_IN_POST = 6
QUOTA_STATE_PATH = Path(".blogger_quota_state.json")
PENDING_DIR = Path("pending_posts")
MIN_USEFULNESS_SCORE = 7

# Blackkiwi "새롭게 등장한 키워드" (source=blackkiwi_new) novelty boost.
# Kept large so fresh keywords outrank stale risers inside the same tier
# after usefulness passes; does not bypass usefulness / dedupe gates.
NOVELTY_BASE_BONUS = 35.0
NOVELTY_RANK_BONUS_MAX = 12.0  # rank 1 → +12, tapering toward lower ranks

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


def source_families(sources: set[str]) -> set[str]:
    """Map raw collector names to the three editorial source families."""
    families: set[str] = set()
    for src in sources:
        s = (src or "").lower()
        if s.startswith("blackkiwi"):
            families.add("blackkiwi")
        elif s.startswith("loword"):
            families.add("loword")
        elif "google_trends" in s or s in {"gtrends", "google_trends_kr"}:
            families.add("gtrends")
    return families


def pick_tier(families: set[str]) -> int | None:
    """Return selection tier, or None when the keyword should be skipped.

    1: blackkiwi ∩ loword ∩ gtrends
    2: blackkiwi ∩ loword
    3: blackkiwi or loword (strong single-source)
    4: gtrends-only → skip by default
    """
    has_bk = "blackkiwi" in families
    has_lw = "loword" in families
    has_gt = "gtrends" in families
    if has_bk and has_lw and has_gt:
        return 1
    if has_bk and has_lw:
        return 2
    if has_bk or has_lw:
        return 3
    if has_gt:
        return None  # google-trends-only: skip
    return None


def classify_intent(keyword: str, category: str, news: list) -> str:
    """Classify reader intent. news-only is skipped unless life-safety urgent."""
    text = f"{keyword} {' '.join(getattr(n, 'title', '') for n in (news or [])[:6])}"
    how_to_markers = (
        "신청", "예약", "방법", "확인", "조회", "설정", "등록", "제출", "신고", "할인",
    )
    decision_markers = (
        "일정", "대상", "조건", "자격", "발표일", "실적발표", "어닝스", "마감", "시행",
    )
    explainer_markers = (
        "제도", "구조", "이란", "뜻", "의미", "개정", "규제", "기준",
    )
    if any(m in text for m in how_to_markers):
        return "how-to"
    if any(m in text for m in decision_markers) or is_earnings_topic(keyword, news):
        return "decision"
    if any(m in text for m in explainer_markers):
        return "explainer"
    if category == "생활안전":
        return "decision"
    return "news-only"


def score_usefulness(
    keyword: str,
    category: str,
    news: list,
    recent_posts: list[dict],
    now: datetime,
) -> tuple[int, str, str]:
    """Return (score 0-10, intent, reason). Hard-skip cases return score 0."""
    intent = classify_intent(keyword, category, news)
    reasons: list[str] = []
    score = 0

    if was_recently_covered(keyword, recent_posts, now, DEDUPE_LOOKBACK_HOURS):
        return 0, intent, "recent_duplicate_within_7d"

    if intent == "news-only" and category != "생활안전":
        return 0, intent, "news-only_non_emergency"

    # +2 today action
    score += 2
    reasons.append("today_action+2")

    # +2 official source proxy: earnings IR / gov / company domains in news urls
    official_hints = (
        "go.kr", "fss.or.kr", "bok.or.kr", "nts.go.kr", "molit.go.kr",
        "abc.xyz", "investor", "ir.", "sec.gov", "dart.fss.or.kr",
        "korea.kr", "mss.go.kr", "moef.go.kr",
    )
    urls = " ".join(getattr(n, "url", "") or "" for n in (news or []))
    titles = " ".join(getattr(n, "title", "") or "" for n in (news or []))
    if any(h in urls.lower() for h in official_hints) or is_earnings_topic(keyword, news):
        score += 2
        reasons.append("official_source+2")
    else:
        # Still allow category-backed official path guidance from content_writer,
        # but require at least one concrete institutional keyword in headlines.
        if any(k in titles for k in ("공시", "금융위", "금감원", "국토부", "질병청", "식약처", "공정위")):
            score += 2
            reasons.append("official_mention+2")
        else:
            return 0, intent, "no_official_source"

    # +2 method/confirm/target/schedule search intent
    if intent in {"how-to", "decision", "explainer"}:
        score += 2
        reasons.append(f"intent_{intent}+2")

    # +1 verifiable facts (dates/numbers) across headlines
    fact_hits = len(re.findall(r"\d+", titles))
    if fact_hits >= 3:
        score += 1
        reasons.append("verifiable_facts+1")

    # +1 FAQ candidates possible for our category templates
    if category in {"금융", "투자", "건강", "생활안전", "법률"}:
        score += 1
        reasons.append("faq_ready+1")

    # +1 low overlap with 7d (already checked hard-skip above)
    score += 1
    reasons.append("low_7d_overlap+1")

    # +1 beginner friction point explainable
    if category in {"금융", "투자", "건강", "생활안전", "법률"} or is_earnings_topic(keyword, news):
        score += 1
        reasons.append("beginner_friction+1")

    return score, intent, ",".join(reasons)


def is_blackkiwi_new(sources: set[str]) -> bool:
    """True when the group includes Blackkiwi's newly-appeared keyword panel."""
    return any((s or "").lower() == "blackkiwi_new" for s in sources)


def novelty_bonus(items: list[TrendItem]) -> float:
    """Extra ranking points for Blackkiwi newly-appeared keywords.

    Base bonus is intentionally high (~one multi-source confirmation) so
    fresh topics surface first; top ranks in the new panel get a bit more.
    """
    new_items = [i for i in items if (i.source or "").lower() == "blackkiwi_new"]
    if not new_items:
        return 0.0
    best_new_rank = min((i.rank for i in new_items if i.rank), default=10)
    # rank 1 → full NOVELTY_RANK_BONUS_MAX, rank 10+ → ~0
    rank_bonus = max(0.0, NOVELTY_RANK_BONUS_MAX - (best_new_rank - 1) * 1.2)
    return NOVELTY_BASE_BONUS + rank_bonus


def score_group(items: list[TrendItem], news_count: int, coherence: float) -> float:
    """Rank candidates mainly by how well *substantiated and focused* the
    issue is: real news volume, single-event headline coherence, and
    confirmation from more than one collection source. Blackkiwi newly-
    appeared keywords get a strong novelty boost; trend rank/traffic/
    window breadth remain secondary tie-breakers.
    """
    sources = {i.source for i in items}
    windows = set()
    for i in items:
        windows.update(i.windows)
    best_rank = min((i.rank for i in items if i.rank), default=20)
    traffic = max((i.traffic for i in items if i.traffic), default=0)
    families = source_families(sources)

    score = 0.0
    score += coherence * 60
    score += news_count * 3
    # Prefer blackkiwi/loword confirmation over google-trends-only boosts.
    score += len(families & {"blackkiwi", "loword"}) * 20
    score += (1 if "gtrends" in families else 0) * 5
    score += len(windows) * 4
    score += max(0, 15 - best_rank) * 0.5
    score += min(traffic, 20000) / 1000
    # Fresh Blackkiwi keywords outrank stale risers inside the same tier.
    score += novelty_bonus(items)
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
        novelty = novelty_bonus(items)

        log(
            f"  candidate '{display_kw}' [{category}] score={score:.1f} coherence={coherence:.2f} "
            f"sources={sources} windows={windows}"
            + (f" NOVELTY_BONUS={novelty:.1f}" if novelty else "")
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
    """True when a recent live post already covers the same issue.

    Uses strong near-duplicate matching (entity alias + topic alias), not
    just substring equality, so titles that rephrase the same event are
    treated as already covered.
    """
    norm_kw = normalize_keyword(keyword)
    if not norm_kw:
        return False
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
        if is_near_duplicate(keyword, title):
            log(
                f"  already covered: keyword={keyword!r} ≈ recent title={title!r} "
                f"(published={published})"
            )
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
    """Pick topics by source-tier first, then usefulness, then score.

    Tier rules (higher wins; lower tiers are ignored when a higher tier exists):
      1 = blackkiwi ∩ loword ∩ gtrends
      2 = blackkiwi ∩ loword
      3 = blackkiwi or loword alone
      gtrends-only is skipped.
    """
    pending_keywords = pending_keywords or set()

    tiered: list[tuple[int, TopicCandidate, int, str, str]] = []
    for cand in candidates:
        families = source_families(cand.sources)
        tier = pick_tier(families)
        source_hit = ",".join(sorted(families)) if families else "none"
        if tier is None:
            log(
                f"  drop '{cand.keyword}': gtrends-only or unknown sources "
                f"(SOURCE_HIT={source_hit})"
            )
            continue
        if any(is_near_duplicate(cand.keyword, f.keyword) for _, f, *_ in tiered):
            continue
        if was_recently_covered(cand.keyword, recent_posts, now, DEDUPE_LOOKBACK_HOURS):
            log(f"  drop '{cand.keyword}': already covered within 7 days")
            continue
        if _is_duplicate_of_pending(cand.keyword, pending_keywords):
            log(f"  drop '{cand.keyword}': already waiting as a pending draft")
            continue

        useful, intent, useful_reason = score_usefulness(
            cand.keyword, cand.category, cand.news, recent_posts, now
        )
        log(
            f"  gate '{cand.keyword}': SOURCE_HIT={source_hit} PICK_TIER={tier} "
            f"INTENT={intent} USEFULNESS_SCORE={useful} USEFULNESS_REASON={useful_reason}"
        )
        if useful < MIN_USEFULNESS_SCORE:
            log(f"SKIP_LOW_USEFULNESS: {cand.keyword} score={useful}")
            continue
        tiered.append((tier, cand, useful, source_hit, intent))

    if not tiered:
        return []

    best_tier = min(t for t, *_ in tiered)
    pool = [row for row in tiered if row[0] == best_tier]
    # Within the same tier: usefulness, then novelty, then trend score.
    pool.sort(
        key=lambda row: (
            -row[2],
            -int(is_blackkiwi_new(row[1].sources)),
            -row[1].score,
        )
    )

    final: list[TopicCandidate] = []
    used_categories: set[str] = set()
    for tier, cand, useful, source_hit, intent in pool:
        if cand.category in used_categories:
            continue
        if any(is_near_duplicate(cand.keyword, f.keyword) for f in final):
            continue
        novelty_tag = " NOVELTY=1" if is_blackkiwi_new(cand.sources) else ""
        log(
            f"PICK_KEYWORD={cand.keyword} PICK_TIER={tier} SOURCE_HIT={source_hit} "
            f"INTENT={intent} USEFULNESS_SCORE={useful}{novelty_tag}"
        )
        final.append(cand)
        used_categories.add(cand.category)
        if len(final) >= MAX_POSTS_PER_RUN:
            break
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


TARGET_LABEL_COUNT = 20
MAX_LABEL_COUNT = 20
_LABEL_SKIP = {
    "무슨", "일이길래", "정리", "확인", "대응", "방법", "영향", "있나",
    "이슈", "관련", "오늘", "내일", "실시간", "단독", "속보", "종합",
    "사진", "영상", "기자", "뉴스", "기사", "포인트", "체크리스트",
    "전망", "분석", "리뷰", "프리뷰", "마감", "특징주",
}
_CATEGORY_EXTRA_LABELS: dict[str, list[str]] = {
    "금융": [
        "금리", "대출", "세금", "가계", "경제", "재테크", "물가", "환율", "은행", "보험",
        "예금", "적금", "카드", "연금", "지원금", "환급", "가계부채", "금융상품",
    ],
    "투자": [
        "주식", "증시", "포트폴리오", "ETF", "실적", "공시", "나스닥", "코스피", "반도체", "시장",
        "매수", "매도", "펀드", "채권", "해외주식", "테마주", "실적시즌", "투자정보",
    ],
    "건강": [
        "의료", "질병", "예방", "건강보험", "병원", "백신", "리콜", "증상", "식약처", "건강정보",
        "감염", "진료", "의약품", "검진", "보건", "환자", "응급실", "건강관리",
    ],
    "생활안전": [
        "재난", "안전", "대피", "기상특보", "침수", "화재", "정전", "안전수칙", "재난문자", "지역안전",
        "호우", "태풍", "지진", "폭염", "통제", "대피소", "기상청", "생활안전정보",
    ],
    "법률": [
        "규제", "소송", "판결", "법령", "과징금", "계약", "권리", "절차", "고발", "시행",
        "기소", "항소", "세무조사", "공정위", "법률정보", "분쟁", "개정", "법률상담",
    ],
    "스포츠": [
        "스포츠", "경기", "시합", "리그", "중계", "스코어", "우승", "결승", "시즌",
        "야구", "축구", "농구", "배구", "골프", "올림픽", "월드컵", "국가대표",
        "KBO", "K리그", "선수", "감독", "구단", "이적", "하이라이트", "스포츠뉴스",
    ],
}
_EARNINGS_EXTRA_LABELS = [
    "실적발표", "어닝스", "분기실적", "컨센서스", "가이던스", "EPS",
    "매출", "영업이익", "빅테크", "클라우드", "AI", "알파벳", "IR", "공시",
]


def _add_label(labels: list[str], seen: set[str], candidate: str) -> None:
    clean = re.sub(r"\s+", " ", (candidate or "").strip())
    if not clean or len(clean) < 2 or len(clean) > 24:
        return
    if clean in _LABEL_SKIP:
        return
    key = clean.lower()
    if key in seen:
        return
    seen.add(key)
    labels.append(clean)


def build_labels(
    keyword: str,
    category: str,
    news: list | None = None,
    target: int = TARGET_LABEL_COUNT,
) -> list[str]:
    """Blogger labels: about `target` concise tags (default ~20).

    Order: category → full keyword → keyword tokens → news tokens →
    topic/category extras. Skips long sentence-like or gossip noise tags.
    """
    labels: list[str] = []
    seen: set[str] = set()
    target = max(1, min(int(target or TARGET_LABEL_COUNT), MAX_LABEL_COUNT))

    _add_label(labels, seen, (category or "").strip())

    kw = (keyword or "").strip()
    if kw and len(kw) <= 24:
        _add_label(labels, seen, kw)
    for tok in re.findall(r"[가-힣A-Za-z0-9]{2,}", kw):
        _add_label(labels, seen, tok)
        if len(labels) >= target:
            return labels[:target]

    if is_earnings_topic(kw, news):
        for tok in _EARNINGS_EXTRA_LABELS:
            _add_label(labels, seen, tok)
            if len(labels) >= target:
                return labels[:target]

    # Pull recurring tokens from grounded headlines for topical breadth.
    if news:
        from collections import Counter

        counter: Counter[str] = Counter()
        for item in news[:12]:
            title = getattr(item, "title", "") or ""
            for tok in re.findall(r"[가-힣A-Za-z0-9]{2,}", title):
                if tok in _LABEL_SKIP or len(tok) > 16:
                    continue
                counter[tok] += 1
        for tok, _n in counter.most_common(30):
            _add_label(labels, seen, tok)
            if len(labels) >= target:
                return labels[:target]

    for tok in _CATEGORY_EXTRA_LABELS.get(category or "", []):
        _add_label(labels, seen, tok)
        if len(labels) >= target:
            return labels[:target]

    # Soft fillers that still stay informational if we are short.
    for tok in (
        "트렌드", "정보", "이슈정리", "생활정보", "경제뉴스", "핵심정리",
        "확인방법", "대응방법", "검색이슈", "핫이슈", "오늘의이슈",
        "필수체크", "실무팁", "가이드", "요약정리",
    ):
        _add_label(labels, seen, tok)
        if len(labels) >= target:
            break

    return labels[:target]


def publish_new_post(
    service, blog_id: str, title: str, content: str, labels: list[str] | None = None
) -> dict:
    body: dict = {
        "kind": "blogger#post",
        "blog": {"id": blog_id},
        "title": title,
        "content": content,
    }
    if labels:
        body["labels"] = labels
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


def take_over_draft_post(
    service,
    blog_id: str,
    draft_id: str,
    title: str,
    content: str,
    labels: list[str] | None = None,
) -> dict:
    """Fill in a human-created draft with generated content and publish it."""
    body: dict = {
        "kind": "blogger#post",
        "id": draft_id,
        "blog": {"id": blog_id},
        "title": title,
        "content": content,
    }
    if labels:
        body["labels"] = labels
    service.posts().update(blogId=blog_id, postId=draft_id, body=body).execute()
    return service.posts().publish(blogId=blog_id, postId=draft_id).execute()


def take_over_live_placeholder(
    service,
    blog_id: str,
    post_id: str,
    title: str,
    content: str,
    labels: list[str] | None = None,
) -> dict:
    """Overwrite an empty LIVE post's title+body(+labels) via patch
    (confirmed to work even when posts.insert is blocked by the
    account-wide restriction).
    """
    body: dict = {"title": title, "content": content}
    if labels:
        body["labels"] = labels
    return service.posts().patch(blogId=blog_id, postId=post_id, body=body).execute()


def attach_hero_image(creds, keyword: str, category: str, content: str, title: str = "") -> str:
    """Generate a 16:9 news thumbnail, commit it to posts/images/, and
    prepend the jsDelivr-backed <img class="post-thumb"> block.

    AI plate is mandatory for production (see MissingAIThumbError). Other
    unexpected failures still skip the image rather than killing text
    drafting, except MissingAIThumbError which must abort publish.
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
    except MissingAIThumbError:
        raise
    except Exception as exc:  # noqa: BLE001
        log(f"  news thumbnail skipped for '{keyword}': {exc}")
        return content


def assert_publish_quality(post: dict, expected_labels: list[str], content: str) -> None:
    """Fail loud if labels/thumbnail were dropped during write."""
    got = list(post.get("labels") or [])
    if len(got) < min(15, len(expected_labels)):
        raise RuntimeError(
            f"labels missing/too few after publish: got={got!r} expected~{expected_labels!r}"
        )
    if 'class="post-thumb"' not in (content or "") and 'class="post-thumb"' not in (post.get("content") or ""):
        raise RuntimeError("post-thumb image missing from published content")
    if "cdn.jsdelivr.net/gh/yeonjoo2025/blogger@" not in (post.get("content") or content or ""):
        raise RuntimeError("thumbnail CDN URL missing from published content")
    log(f"  quality ok: labels={len(got)}, thumb=present, url={post.get('url')}")


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

    # Empty LIVE shells / human drafts can still be filled via patch/update
    # even when posts.insert is banned. Prefer that path over a hard stop.
    placeholder_posts = list_placeholder_live_posts(service, blog_id)
    draft_posts = list_draft_posts(service, blog_id)
    can_fill_shells = bool(placeholder_posts or draft_posts)

    if api_blocked and not can_fill_shells:
        log(
            "생성/업데이트 없이 종료: today's Blogger write quota/restriction is already "
            f"exhausted (new posts today={new_posts_today}/{MAX_NEW_POSTS_PER_DAY}, "
            f"quota_state_exhausted={load_quota_exhausted_today(now)}) and no empty "
            "placeholder/draft shells are available. Will retry next cycle."
        )
        return

    if api_blocked and can_fill_shells:
        log(
            "insert quota/restriction is active, but empty placeholder/draft shell(s) "
            f"exist (placeholders={len(placeholder_posts)}, drafts={len(draft_posts)}) - "
            "will fill via patch/update only (no posts.insert)"
        )
    else:
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
        labels = build_labels(topic.keyword, topic.category, news=topic.news)
        if len(labels) < 15:
            raise SystemExit(
                f"refusing to publish with too few labels ({len(labels)}): {labels}"
            )
        try:
            content = attach_hero_image(
                creds, topic.keyword, topic.category, content, title=title
            )
        except MissingAIThumbError as missing:
            log(
                "발행 중단: AI 썸네일이 없습니다. GenerateImage로 만든 뒤 "
                f"{missing.dest} 에 저장하고 python3 publish_trend.py 를 다시 실행하세요."
            )
            log(f"REQUIRED_SLUG={missing.slug}")
            log(f"REQUIRED_SAVE_PATH={missing.dest}")
            log("REQUIRED_IMAGE_PROMPT_BEGIN")
            log(missing.prompt)
            log("REQUIRED_IMAGE_PROMPT_END")
            sys.exit(2)
        if 'class="post-thumb"' not in content:
            raise SystemExit("refusing to publish without post-thumb image in content")
        log(
            f"[{idx}/{len(final_topics)}] '{title}' "
            f"(category={topic.category}, labels={len(labels)}:{labels})"
        )

        if placeholder_posts:
            shell = placeholder_posts.pop(0)
            shell_id = shell.get("id")
            try:
                post = take_over_live_placeholder(
                    service, blog_id, shell_id, title, content, labels=labels
                )
                assert_publish_quality(post, labels, content)
                log(
                    f"  filled in empty LIVE post {shell_id} via patch: {post.get('url')} "
                    f"labels={post.get('labels')}"
                )
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
                post = take_over_draft_post(
                    service, blog_id, draft_id, title, content, labels=labels
                )
                assert_publish_quality(post, labels, content)
                log(
                    f"  filled in human-created draft {draft_id} and published: "
                    f"{post.get('url')} labels={post.get('labels')}"
                )
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
            post = publish_new_post(service, blog_id, title, content, labels=labels)
            assert_publish_quality(post, labels, content)
            log(f"  published: {post.get('url')} labels={post.get('labels')}")
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
