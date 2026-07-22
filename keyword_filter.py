"""Rule-based topic classification and selection.

Google Trends style feeds only hand us a bare keyword; we decide whether a
keyword is worth a post by looking at the keyword text *and* the real news
headlines attached to it (from ``trend_sources.fetch_related_news`` /
``TrendItem.news``). No LLM call is involved here on purpose: the pipeline
must run unattended, deterministically, every few hours.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from trend_sources import NewsRef, TrendItem

# Signals that mean "entertainment / celebrity / sports result / pure gossip"
# -> must be excluded per the editorial rules, even if trending high.
EXCLUDE_TERMS = [
    "배우", "가수", "아이돌", "걸그룹", "보이그룹", "예능", "드라마", "영화배우",
    "컴백", "열애", "결별", "이혼설", "재혼", "임신설", "근황", "화보", "콘서트",
    "팬미팅", "시상식", "데뷔", "스캔들", "저격", "디스전", "유튜버", "인플루언서",
    "틱톡커", "인스타그램", "웹툰", "예능프로", "OTT 예능",
    "야구", "축구", "농구", "배구", "골프", "올림픽", "월드컵", "국가대표팀",
    "우승", "준우승", "결승전", "8강", "4강", "감독 선임", "선수단", "홈런",
    "득점왕", "스코어", "중계", "리그", "KBO", "K리그", "MLB", "NBA", "EPL",
    "이적설", "트레이드",
]

# Real-life / money-impact categories. First matching category (by highest
# hit count) wins; keyword must have at least one hit in this table to be a
# candidate at all.
INCLUDE_CATEGORIES: dict[str, list[str]] = {
    "금융": [
        "주가", "코스피", "코스닥", "환율", "금리", "기준금리", "대출", "전세",
        "매매가", "종부세", "양도세", "국민연금", "실업급여", "최저임금", "물가",
        "인플레이션", "구조조정", "실업", "파산", "회생", "상장", "공모주", "배당",
        "증시", "나스닥", "다우존스", "다우 존스", "관세", "무역", "지원금", "보조금",
        "환급", "정산",
    ],
    "투자": [
        "투자", "재테크", "비트코인", "이더리움", "암호화폐", "가상자산", "코인",
        "ETF", "펀드", "채권", "금값", "유가", "반도체", "주식", "블랙록", "헤지펀드",
        "테슬라", "나스닥", "매수", "매도",
    ],
    "건강": [
        "감염", "확산", "유행", "독감", "코로나", "백신", "부작용", "리콜",
        "질병청", "식중독", "응급실", "의료파업", "건강보험", "전염병", "환자",
        "의약품",
    ],
    "생활안전": [
        "호우", "폭우", "물폭탄", "장마", "태풍", "지진", "폭염", "한파", "대설",
        "강풍", "우박", "해일", "산사태", "지반침하", "산불", "화재", "정전",
        "누출", "유출", "붕괴", "침수", "댐", "저수지", "방류", "대피", "경보",
        "특보", "인명피해", "해킹", "개인정보 유출", "사기", "스미싱", "보이스피싱",
        "먹튀", "안전문자", "재난문자",
    ],
    "법률": [
        "판결", "소송", "기소", "구속", "압수수색", "규제", "법안", "시행",
        "단속", "과징금", "공정위", "세무조사", "국세청", "고발", "항소",
    ],
}

MIN_NEWS_FOR_CONFIDENCE = 3
MIN_NET_SCORE = 3
MIN_COHERENCE = 0.35

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text))


def headline_coherence(keyword: str, news: list[NewsRef]) -> float:
    """How much the fetched headlines look like ONE ongoing event vs a bag
    of unrelated articles that merely happen to mention the same keyword.

    We count, across headlines, the most frequently shared non-keyword
    token and return its share of the headline count. A generic keyword
    like "구조조정" pulls headlines about many unrelated companies (low
    score); a real single event like a dam release or a market selloff
    reuses the same core words in nearly every headline (high score).
    """
    if not news:
        return 0.0
    kw_tokens = _tokenize(keyword)
    counter: Counter[str] = Counter()
    for item in news:
        tokens = _tokenize(item.title) - kw_tokens
        counter.update(tokens)
    if not counter:
        return 0.0
    _, top_freq = counter.most_common(1)[0]
    return top_freq / len(news)


@dataclass
class TopicCandidate:
    keyword: str
    category: str
    score: float
    sources: set[str]
    windows: set[str]
    traffic: int
    news: list[NewsRef]


def _count_hits(text: str, terms: list[str]) -> int:
    return sum(1 for t in terms if t in text)


def classify(keyword: str, news: list[NewsRef]) -> tuple[str | None, int, int]:
    """Return (best_category_or_None, include_hits, exclude_hits)."""
    corpus = keyword + " " + " ".join(n.title for n in news)

    exclude_hits = _count_hits(corpus, EXCLUDE_TERMS)

    best_category = None
    best_hits = 0
    for category, terms in INCLUDE_CATEGORIES.items():
        hits = _count_hits(corpus, terms)
        if hits > best_hits:
            best_hits = hits
            best_category = category

    return best_category, best_hits, exclude_hits


def is_qualified(keyword: str, news: list[NewsRef]) -> tuple[bool, str | None, str]:
    """Decide whether a keyword should even be considered.

    Returns (qualified, category, reason). When ambiguous we reject rather
    than force a write-up ("애매하면 억지로 쓰지 말고 줄인다").
    """
    if len(news) < MIN_NEWS_FOR_CONFIDENCE:
        return False, None, f"news_count={len(news)} < {MIN_NEWS_FOR_CONFIDENCE}"

    category, include_hits, exclude_hits = classify(keyword, news)
    if category is None or include_hits == 0:
        return False, None, "no real-life-impact category matched"

    net_score = include_hits - exclude_hits
    if net_score < MIN_NET_SCORE:
        return False, None, f"net_score={net_score} < {MIN_NET_SCORE} (include={include_hits}, exclude={exclude_hits})"

    if exclude_hits > include_hits:
        return False, None, "entertainment/sports signal dominates"

    coherence = headline_coherence(keyword, news)
    if coherence < MIN_COHERENCE:
        return False, None, f"headline_coherence={coherence:.2f} < {MIN_COHERENCE} (too scattered, likely a generic term)"

    return True, category, f"include={include_hits}, exclude={exclude_hits}, coherence={coherence:.2f}"


def normalize_keyword(keyword: str) -> str:
    return re.sub(r"\s+", "", keyword).strip()


def group_trend_items(items: list[TrendItem]) -> dict[str, list[TrendItem]]:
    """Group raw trend items from all sources by normalized keyword text."""
    groups: dict[str, list[TrendItem]] = {}
    for item in items:
        key = normalize_keyword(item.keyword)
        if not key:
            continue
        groups.setdefault(key, []).append(item)
    return groups


def is_near_duplicate(a: str, b: str) -> bool:
    na, nb = normalize_keyword(a), normalize_keyword(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(shorter) >= 2 and shorter in longer
