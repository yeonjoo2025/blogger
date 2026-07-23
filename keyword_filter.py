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

# Signals that mean "entertainment / celebrity / pure gossip"
# -> must be excluded per the editorial rules, even if trending high.
# Sports is intentionally allowed (see INCLUDE_CATEGORIES["스포츠"]).
EXCLUDE_TERMS = [
    "배우", "가수", "아이돌", "걸그룹", "보이그룹", "예능", "드라마", "영화배우",
    "컴백", "열애", "결별", "이혼설", "재혼", "임신설", "근황", "화보", "콘서트",
    "팬미팅", "시상식", "데뷔", "스캔들", "저격", "디스전", "유튜버", "인플루언서",
    "틱톡커", "인스타그램", "웹툰", "예능프로", "OTT 예능",
]

# Issue categories. First matching category (by highest hit count) wins;
# keyword must have at least one hit in this table to be a candidate at all.
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
        "실적발표", "실적", "어닝스", "분기실적", "컨센서스", "EPS", "가이던스",
        "클라우드", "알파벳", "구글", "빅테크",
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
    "스포츠": [
        "야구", "축구", "농구", "배구", "골프", "테니스", "당구", "탁구", "수영",
        "육상", "격투기", "복싱", "UFC", "올림픽", "월드컵", "아시안게임",
        "국가대표", "국가대표팀", "우승", "준우승", "결승", "결승전", "8강", "4강",
        "홈런", "득점", "스코어", "중계", "리그", "경기", "시합", "시즌",
        "KBO", "K리그", "MLB", "NBA", "EPL", "프리미어리그", "라리가", "세리에",
        "챔피언스리그", "이적", "트레이드", "감독", "선수단", "선수", "구단",
        "토트넘", "손흥민", "메시", "두산", "LG트윈스", "삼성라이온즈",
        "한화이글스", "기아타이거즈", "SSG", "NC다이노스", "키움", "롯데자이언츠",
        "KT위즈", "FC", "인터 마이애미", "케스파컵", "e스포츠", "LCK",
    ],
}

MIN_NEWS_FOR_CONFIDENCE = 3
MIN_NET_SCORE = 3
# Generic nouns that only share a common word across unrelated articles
# (e.g. "이자" spanning 예금금리·카드론·시금고 기사) need a higher bar.
MIN_COHERENCE = 0.50
MIN_COHERENCE_BROAD = 0.65
MIN_COHERENCE_SHORT = 0.60

# Bare topic words that almost always pull multi-event headline bags.
BROAD_GENERIC_TERMS = {
    "이자", "금리", "대출", "주가", "주식", "환율", "세금", "물가", "보험",
    "투자", "부동산", "은행", "예금", "적금", "채권", "펀드", "코인", "증시",
    "배당", "연체", "파산", "지원금", "보조금", "환급",
}

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


_EARNINGS_MARKERS = ("실적발표", "실적 발표", "어닝스", "분기실적", "earnings")


def is_earnings_topic(keyword: str, news: list[NewsRef] | None = None) -> bool:
    text = keyword or ""
    if news:
        text += " " + " ".join(n.title for n in news[:6])
    return any(m in text for m in _EARNINGS_MARKERS)


def classify(keyword: str, news: list[NewsRef]) -> tuple[str | None, int, int]:
    """Return (best_category_or_None, include_hits, exclude_hits)."""
    corpus = keyword + " " + " ".join(n.title for n in news)

    exclude_hits = _count_hits(corpus, EXCLUDE_TERMS)

    # Earnings-release searches are investment intent (schedule/results),
    # not household loan/tax finance - force that lane early.
    if is_earnings_topic(keyword, news):
        hits = _count_hits(corpus, INCLUDE_CATEGORIES["투자"])
        return "투자", max(hits, MIN_NET_SCORE), exclude_hits

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
        return False, None, "entertainment/gossip signal dominates"

    coherence = headline_coherence(keyword, news)
    norm = normalize_keyword(keyword)
    min_coherence = MIN_COHERENCE
    if norm in BROAD_GENERIC_TERMS:
        min_coherence = MIN_COHERENCE_BROAD
    elif len(norm) <= 2:
        min_coherence = MIN_COHERENCE_SHORT
    if coherence < min_coherence:
        return (
            False,
            None,
            f"headline_coherence={coherence:.2f} < {min_coherence:.2f} "
            f"(too scattered, likely a generic term)",
        )

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


# Entity alias groups: same company/org under different surface forms.
# Matching is case-insensitive after normalize_keyword (whitespace stripped).
ENTITY_ALIAS_GROUPS: list[set[str]] = [
    {"구글", "알파벳", "google", "alphabet", "googl", "goog"},
    {"테슬라", "tesla", "tsla"},
    {"삼성전자", "삼성", "samsung", "005930"},
    {"마이크론", "micron", "mu"},
    {"애플", "apple", "aapl"},
    {"엔비디아", "nvidia", "nvda"},
    {"마이크로소프트", "microsoft", "msft"},
    {"메타", "meta", "페이스북", "facebook", "metaplatforms"},
    {"아마존", "amazon", "amzn"},
    {"넷플릭스", "netflix", "nflx"},
]

# Topic/event alias groups: same issue under different wording.
TOPIC_ALIAS_GROUPS: list[set[str]] = [
    {
        "실적발표", "실적", "어닝스", "분기실적", "가이던스", "컨센서스",
        "earnings", "어닝", "실적시즌", "분기실", "영업익", "영업이익", "eps", "매출",
    },
    {"금리", "기준금리", "이자율", "fed", "fomc"},
    {"관세", "tariff", "무역장벽"},
    {"근저당", "근저당권"},
    {"회생", "회생절차", "기업회생", "워크아웃"},
]


def _lower_norm(text: str) -> str:
    return normalize_keyword(text).lower()


def _matched_alias_groups(text: str, groups: list[set[str]]) -> set[int]:
    """Return indices of alias groups whose any member appears in text.

    Prefer longer aliases first so '실적발표' wins over bare '실적', and
    '삼성전자' wins over '삼성'.
    """
    hay = _lower_norm(text)
    if not hay:
        return set()
    matched: set[int] = set()
    for idx, group in enumerate(groups):
        for alias in sorted(group, key=len, reverse=True):
            a = alias.lower().replace(" ", "")
            if a and a in hay:
                matched.add(idx)
                break
    return matched


def is_near_duplicate(a: str, b: str) -> bool:
    """True when two titles/keywords refer to the same issue.

    Rules (stronger than substring-only):
    1) Exact / substring match on normalized text (legacy).
    2) Same entity-alias group AND same topic-alias group both hit
       in each side → treat as the same issue even if wording differs
       (e.g. "구글 실적발표" ≈ "구글(알파벳) Q2 실적 전 ...").
    Same entity with a different topic (실적 vs 제미나이 출시) is NOT
    a duplicate; same topic with a different entity (구글 실적 vs
    마이크론 실적) is also NOT a duplicate.
    """
    na, nb = normalize_keyword(a), normalize_keyword(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 2 and shorter in longer:
        return True

    ent_a = _matched_alias_groups(a, ENTITY_ALIAS_GROUPS)
    ent_b = _matched_alias_groups(b, ENTITY_ALIAS_GROUPS)
    topic_a = _matched_alias_groups(a, TOPIC_ALIAS_GROUPS)
    topic_b = _matched_alias_groups(b, TOPIC_ALIAS_GROUPS)
    if ent_a and ent_b and (ent_a & ent_b) and topic_a and topic_b and (topic_a & topic_b):
        return True
    return False
