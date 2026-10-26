"""Hard filters, label sanitizer, usefulness/title/category/monetization gates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

MIN_BODY_CHARS = 2500
# Shared categories only — unique/singleton labels create thin /search/label pages
# that AdSense's Mediapartners-Google crawler can still see.
MIN_LABELS = 2
TARGET_LABELS = 3
MAX_LABELS = 4
ALLOWED_LABELS = (
    "생활정보",
    "세금",
    "금융",
    "예약",
    "캠핑",
    "IT",
    "혜택",
    "사이트안내",
)
MAX_LABEL_CHARS_TOTAL = 180
MIN_FAQ = 3
MIN_OFFICIAL_URLS = 1
MIN_INTERNAL_LINKS = 2
MWOGILLAE_RECENT_LIMIT = 10
MWOGILLAE_MAX_IN_RECENT = 2

# Commercial / actionable search-intent signals (money keywords).
COMMERCIAL_INTENT_RE = re.compile(
    r"("
    r"신청|예약|예매|비교|가격|출고가|요금|할인|혜택|환급|지원금|사전판매|"
    r"구매|가입|제출|발급|수수료|한도|조건|자격|납입|비과세|"
    r"총정리|신청법|받는\s*법|보는\s*법|사는\s*법|따라하기|가이드|정리|"
    r"방법|일정|대상|대응|필요\s*서류"
    r")"
)

TITLE_GOOD_RE = COMMERCIAL_INTENT_RE

# Factory titles that triggered AdSense "low value content" (ban).
TITLE_FACTORY_BAD_RE = re.compile(
    r"("
    r"확인\s*(하는\s*)?(방법|법).{0,40}체크리스트"
    r"|"
    r"체크리스트.{0,40}확인\s*(하는\s*)?(방법|법)"
    r")"
)

ASOF_RE = re.compile(r"정보\s*기준일|기준일\s*[:：]")

TITLE_FRESHNESS_RE = re.compile(r"20\d{2}|\d{1,2}\s*월|\d{1,2}/")

REQUIRED_SECTION_PATTERNS = {
    "summary": re.compile(r"한\s*줄\s*요약|읽고\s*나면|이 글을 읽으면"),
    "audience": re.compile(r"해당되는지|대상|비대상|맞는 사람"),
    "action": re.compile(
        r"지금 확인|확인하는 방법|바로 할|사전판매|신청|예약|체크|구매\s*채널"
    ),
    "checklist": re.compile(r"체크리스트|피해야 할 실수"),
    "faq": re.compile(r"FAQ|자주 묻는|Q\.\s*|Q\."),
}

# Domains that count as official / high-trust sources.
OFFICIAL_HOST_RE = re.compile(
    r"("
    r"\.go\.kr$|mois\.go\.kr|bok\.or\.kr|fss\.or\.kr|fsc\.go\.kr|"
    r"molit\.go\.kr|seoul\.go\.kr|nts\.go\.kr|"
    r"khug\.or\.kr|hug\.or\.kr|ex\.co\.kr|hipass\.co\.kr|"
    r"wooribank\.com|kbstar\.com|shinhan\.com|kb\.co\.kr|"
    r"seoulcamp\.co\.kr|samsungebiz\.com|lguplus\.com|"
    r"samsung\.com|news\.samsung|apple\.com|google\.com|blog\.google|"
    r"man7\.org|docs\.kernel\.org|kernel\.org|ubuntu\.com|"
    r"tesla\.com|ir\.tesla|sec\.gov|dart\.fss\.or\.kr|"
    r"yna\.co\.kr|yonhapnews|news\.seoul\.go\.kr|etax\.seoul\.go\.kr|"
    r"blogspot\.com|yeondodo"
    r")",
    re.I,
)

INTERNAL_HOST_RE = re.compile(r"(yeondodo\.blogspot\.com|blogspot\.com/.*/)", re.I)

HARD_SKIP_RE = re.compile(
    r"("
    r"손흥민|메시|케스파|오스틴\s*보스|어벤져스|개봉일|줄거리|예고편|"
    r"무승부|연승|연패|홈런|득점|경기\s*결과|월드컵\s*결승|"
    r"아이돌|배우|연예|열애|결혼\s*축하|나혼산|예능|"
    r"방탄소년단|BTS|사키라|로다주|"
    r"KT\s*vs|두산\s*베어스|LG\s*트윈스|KBO|"
    r"lafc|mls|피파\b|축구\s*감독|"
    # AdSense thin / one-off news wrappers (low durable action value)
    r"사이드카|서킷브레이커|OPEC|증산|감산|"
    r"폭염\s*(중대|위기)?경보|폭염\s*특보|온열질환|"
    r"무정차|시위일|백린|지진\s*국내|"
    r"판매중단|리콜\s*확인|아침메뉴|리아런치|쇼핑\s*익스프레스|"
    r"수영\s*사고|수문\s*위험|실종|"
    r"어닝|실적\s*확인|주가\s*급|컨센서스\s*대비"
    r")",
    re.I,
)

HARD_SKIP_ALLOW_RE = re.compile(
    r"(신청|예약|할인|요금|출고가|사전판매|증상|치료|가이드|가격|비교|납입|비과세|예매|환급|지원금)"
)

# Low-RPM / policy-heavy: allow only with strong commercial/action framing.
FINANCE_HEADLINE_RE = re.compile(
    r"(실적|어닝|주가|급등|급락|시총|티커|EPS|가이던스|컨센서스)",
    re.I,
)

JUNK_LABEL_RE = re.compile(
    r"("
    r"움직였|여전히|예측$|핵심$|향후$|끝나면|과잉생산|"
    r"Corp$|Inc$|Ltd$|정보성글$"
    r")"
)

# Generic pads that inflate label count without SEO value — never auto-add.
GENERIC_PAD_LABELS = {
    "일정",
    "확인",
    "방법",
    "체크리스트",
    "공식",
    "신청",
    "비교",
    "가이드",
    "주의",
    "faq",
    "정보",
    "정보성글",
}

VALID_INTENTS = frozenset(
    {"how-to", "compare", "price", "apply", "explainer", "decision", "refresh"}
)
MONEY_INTENTS = frozenset({"how-to", "compare", "price", "apply", "refresh"})


@dataclass
class QualityResult:
    ok: bool
    score: int
    reasons: list[str]
    errors: list[str]
    intent_score: int = 0

    def log_lines(self) -> list[str]:
        lines = [
            f"USEFULNESS_SCORE={self.score}",
            f"INTENT_SCORE={self.intent_score}",
            f"USEFULNESS_REASON={'; '.join(self.reasons) if self.reasons else 'n/a'}",
        ]
        for err in self.errors:
            lines.append(f"QUALITY_ERROR={err}")
        lines.append("quality ok" if self.ok else "quality fail")
        return lines


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[\s\-_/·.,!?'\"()\[\]{}]+", "", text)
    return text


def classify_category(title: str, body: str = "") -> str:
    text = f"{title} {body[:500]}"
    if re.search(
        r"예약|신청|할인|캠핑|통행료|채용|가이드|방법|요금|사전판매|가격|비교|환급|지원금",
        text,
    ):
        return "guide"
    if re.search(r"갤럭시|제미나이|키미|AI|스마트폰|폴더블|앱|설정|출고가", text):
        return "it"
    if re.search(
        r"실적|주가|주식|투자|코스피|닛케이|사이드카|마이크론|테슬라|엔비디아|관세|반도체|환율|유가",
        text,
    ):
        return "finance"
    if re.search(r"근저당|사관|황강|홈플러스|이관|법원|벌금|제도|세금", text):
        return "society"
    if HARD_SKIP_RE.search(text) and not HARD_SKIP_ALLOW_RE.search(text):
        return "sports_ent"
    return "other"


def classify_intent(keyword: str, title: str = "", body: str = "") -> str:
    text = f"{keyword} {title} {body[:800]}"
    if re.search(r"갱신|업데이트|최신\s*정리|다시\s*정리", text):
        return "refresh"
    if re.search(r"비교|vs|차이|뭐\s*살|추천\s*모델", text, re.I):
        return "compare"
    if re.search(r"가격|출고가|요금|비용|수수료|할인", text):
        return "price"
    if re.search(r"신청|예약|가입|제출|발급|사전판매|접수", text):
        return "apply"
    if re.search(r"방법|가이드|설정|확인하는|단계|체크리스트", text):
        return "how-to"
    if re.search(r"실적|어닝|주가|일정.*발표|관전", text):
        return "decision"
    if re.search(r"뭐길래|용어|제도|구조|뜻", text):
        return "explainer"
    return "explainer"


def commercial_intent_score(keyword: str, title: str, body: str = "") -> int:
    """0~10 proxy for monetizable search intent (not the usefulness score)."""
    text = f"{keyword} {title}"
    score = 0
    intent = classify_intent(keyword, title, body)
    if intent in MONEY_INTENTS:
        score += 4
    elif intent == "explainer":
        score += 2
    elif intent == "decision":
        score += 1

    if COMMERCIAL_INTENT_RE.search(text):
        score += 2
    if TITLE_FRESHNESS_RE.search(title):
        score += 1
    if FINANCE_HEADLINE_RE.search(text) and intent not in MONEY_INTENTS:
        score -= 2
    if HARD_SKIP_RE.search(text) and not HARD_SKIP_ALLOW_RE.search(text):
        score -= 5
    return max(0, min(10, score))


# One-off incident / weather / promo wrappers dressed as "확인 방법 체크리스트".
THIN_ONEOFF_RE = re.compile(
    r"("
    r"(사고|누출|단속|특보|경보|무정차|시위|지진|방류|벌금\s*\d).{0,40}"
    r"(확인\s*(하는\s*)?(방법|법)|체크리스트)"
    r"|"
    r"(확인\s*(하는\s*)?(방법|법)|체크리스트).{0,40}"
    r"(사고|누출|단속|특보|경보|무정차|시위|지진|방류)"
    r")",
    re.I,
)


def is_hard_skip(keyword: str, title: str = "") -> tuple[bool, str]:
    text = f"{keyword} {title}".strip()
    if not text:
        return True, "empty keyword/title"
    if HARD_SKIP_RE.search(text) and not HARD_SKIP_ALLOW_RE.search(text):
        return True, f"hard_skip thin/one-off or sports: {text[:80]}"
    if THIN_ONEOFF_RE.search(text) and not re.search(
        r"(신청|예약|예매|납입|지원금|환급|할인\s*신청)", text
    ):
        return True, f"hard_skip one-off news wrapper: {text[:80]}"
    cat = classify_category(title or keyword, keyword)
    if cat == "sports_ent":
        return True, "category sports_ent blocked"
    return False, ""


def strip_html(content: str) -> str:
    content = re.sub(r"<script[\s\S]*?</script>", "", content or "", flags=re.I)
    content = re.sub(r"<style[\s\S]*?</style>", "", content or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", content)
    return re.sub(r"\s+", " ", text).strip()


def extract_urls(text: str) -> list[str]:
    md = re.findall(r"\[[^\]]*\]\((https?://[^)]+)\)", text or "")
    href = re.findall(r'href=["\'](https?://[^"\']+)["\']', text or "", flags=re.I)
    bare = re.findall(r"https?://[^\s)<>\"']+", text or "")
    seen: set[str] = set()
    out: list[str] = []
    for u in md + href + bare:
        u = u.rstrip(".,);]")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def host_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def count_official_urls(text: str) -> int:
    n = 0
    for url in extract_urls(text):
        host = host_of(url)
        if not host:
            continue
        # Internal blog links do not count as official sources.
        if "blogspot.com" in host or "yeondodo" in host:
            continue
        if OFFICIAL_HOST_RE.search(host) or host.endswith(".go.kr"):
            n += 1
        elif re.search(r"(newsroom|ir\.|/ir/|investor)", url, re.I):
            n += 1
    return n


def count_internal_links(text: str, *, current_url: str = "") -> int:
    n = 0
    for url in extract_urls(text):
        host = host_of(url)
        if "yeondodo.blogspot.com" in host or (
            "blogspot.com" in host and "yeondodo" in url
        ):
            if current_url and url.rstrip("/") == current_url.rstrip("/"):
                continue
            n += 1
    return n


def count_faq_items(text: str) -> int:
    # Prefer explicit Q. / **Q. patterns
    qs = re.findall(r"(?:\*\*)?Q\.\s*", text or "")
    if len(qs) >= MIN_FAQ:
        return len(qs)
    # Fallback: FAQ section bullet questions ending with ?
    faq_block = re.search(
        r"(?:FAQ|자주 묻는)([\s\S]{0,2500})", text or "", flags=re.I
    )
    if not faq_block:
        return len(qs)
    return max(len(qs), len(re.findall(r"\?", faq_block.group(1))))


def has_table(text: str) -> bool:
    if re.search(r"<table\b", text or "", re.I):
        return True
    lines = (text or "").splitlines()
    for i, line in enumerate(lines[:-1]):
        if "|" in line and re.search(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", lines[i + 1]):
            return True
    return False


def sanitize_labels(
    labels: Iterable[str],
    *,
    keyword: str = "",
    category: str = "",
    target: int = TARGET_LABELS,
) -> list[str]:
    allowed_norm = {normalize_text(x): x for x in ALLOWED_LABELS}
    cleaned: list[str] = []
    seen: set[str] = set()

    def _add(lab: str) -> None:
        lab = re.sub(r"\s+", " ", (lab or "").strip())
        canon = allowed_norm.get(normalize_text(lab))
        if not canon or normalize_text(canon) in seen:
            return
        seen.add(normalize_text(canon))
        cleaned.append(canon)

    cat_map = {
        "guide": "생활정보",
        "it": "IT",
        "finance": "금융",
        "society": "생활정보",
        "other": "생활정보",
    }
    if category:
        _add(cat_map.get(category, "생활정보"))
    for raw in labels:
        _add(raw)
    # keyword may already be an allowed category name; never invent new labels
    if keyword:
        for token in re.split(r"[\s,/|]+", keyword):
            _add(token)
    if not cleaned:
        _add("생활정보")

    out: list[str] = []
    total = 0
    limit = min(target, MAX_LABELS)
    for lab in cleaned:
        add = len(lab) + (1 if out else 0)
        if len(out) >= limit:
            break
        if total + add > MAX_LABEL_CHARS_TOTAL:
            continue
        out.append(lab)
        total += add
    # Never auto-pad with GENERIC_PAD_LABELS — under-minimum fails at validate_post.
    return out

def title_ok(title: str, recent_titles: list[str] | None = None) -> tuple[bool, str]:
    recent_titles = recent_titles or []
    if TITLE_FACTORY_BAD_RE.search(title or ""):
        return False, (
            "title factory ban: avoid '확인 방법…체크리스트'; "
            "use 총정리/신청법/받는 법/비교/따라하기 form"
        )
    if "뭐길래" in title:
        recent = recent_titles[:MWOGILLAE_RECENT_LIMIT]
        mw = sum(1 for t in recent if "뭐길래" in t)
        if mw >= MWOGILLAE_MAX_IN_RECENT:
            return False, (
                f"title template '뭐길래' overused "
                f"({mw}/{MWOGILLAE_RECENT_LIMIT} recent); use 총정리/신청법/비교 form"
            )
    if not TITLE_GOOD_RE.search(title) and "뭐길래" in title:
        return False, "title is 뭐길래-only; add 신청/가격/비교/총정리 signal"
    if not TITLE_GOOD_RE.search(title):
        return False, "title missing commercial/action intent (신청/가격/비교/총정리…)"
    return True, ""


def token_set(text: str) -> set[str]:
    parts = re.findall(r"[가-힣A-Za-z0-9]{2,}", text.lower())
    return set(parts)


def is_near_duplicate(
    title: str,
    recent_titles: list[str],
    *,
    keyword: str = "",
    threshold: float = 0.55,
) -> tuple[bool, str]:
    a = token_set(f"{title} {keyword}")
    if not a:
        return False, ""
    for other in recent_titles:
        b = token_set(other)
        if not b:
            continue
        overlap = len(a & b) / len(a | b)
        if overlap >= threshold:
            return True, f"near-duplicate of '{other[:60]}' (jaccard={overlap:.2f})"
    if keyword:
        kn = normalize_text(keyword)
        for other in recent_titles:
            if kn and kn in normalize_text(other):
                return True, f"keyword already covered in '{other[:60]}'"
    return False, ""


def score_usefulness(
    title: str,
    body_html_or_md: str,
    *,
    require_internal_links: bool = True,
) -> QualityResult:
    raw = body_html_or_md or ""
    text = strip_html(raw) if "<" in raw else raw
    text = re.sub(r"\s+", " ", text).strip()
    reasons: list[str] = []
    errors: list[str] = []
    score = 0
    intent_score = commercial_intent_score("", title, text)

    skip, why = is_hard_skip("", title)
    if skip:
        errors.append(why)
        return QualityResult(False, 0, reasons, errors, intent_score=intent_score)

    if REQUIRED_SECTION_PATTERNS["action"].search(text):
        score += 2
        reasons.append("+2 action")
    else:
        errors.append("missing concrete action section")

    official_n = count_official_urls(raw)
    if official_n >= MIN_OFFICIAL_URLS:
        score += 2
        reasons.append(f"+2 official urls ({official_n})")
    else:
        errors.append(
            f"need >={MIN_OFFICIAL_URLS} official/trust URL "
            f"(go.kr, IR, company newsroom…); found {official_n}"
        )

    if TITLE_GOOD_RE.search(title) or REQUIRED_SECTION_PATTERNS["action"].search(title):
        score += 2
        reasons.append("+2 search intent method/schedule")
    else:
        reasons.append("+0 weak title intent")
        errors.append("title missing commercial/action intent signal")

    fact_hits = len(
        re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|\d{4}년|\d{1,2}월|\d{1,2}일", text)
    )
    if fact_hits >= 3:
        score += 1
        reasons.append("+1 facts")
    else:
        errors.append("need >=3 verifiable facts (dates/numbers)")

    faq_n = count_faq_items(raw)
    if faq_n >= MIN_FAQ:
        score += 1
        reasons.append(f"+1 faq ({faq_n})")
    else:
        errors.append(f"need >={MIN_FAQ} FAQ items; found {faq_n}")

    if REQUIRED_SECTION_PATTERNS["checklist"].search(text):
        score += 1
        reasons.append("+1 checklist")
    else:
        errors.append("missing checklist")

    if len(text) >= MIN_BODY_CHARS:
        score += 1
        reasons.append("+1 body length")
    else:
        errors.append(f"body too short ({len(text)} < {MIN_BODY_CHARS})")

    if has_table(raw):
        reasons.append("table present")

    internal_n = count_internal_links(raw)
    if require_internal_links:
        if internal_n >= MIN_INTERNAL_LINKS:
            reasons.append(f"internal links ok ({internal_n})")
        else:
            errors.append(
                f"need >={MIN_INTERNAL_LINKS} internal links to "
                f"yeondodo.blogspot.com; found {internal_n}"
            )
    else:
        reasons.append(f"internal links skipped ({internal_n})")

    for key in ("summary", "audience", "action", "checklist", "faq"):
        if not REQUIRED_SECTION_PATTERNS[key].search(text):
            errors.append(f"missing section:{key}")

    ok = score >= 7 and not errors
    if score < 7 and f"score {score} < 7" not in errors:
        errors.append(f"score {score} < 7")
        ok = False
    if errors:
        ok = False
    return QualityResult(
        ok=ok, score=score, reasons=reasons, errors=errors, intent_score=intent_score
    )


def validate_post(
    *,
    title: str,
    body: str,
    labels: list[str],
    recent_titles: list[str] | None = None,
    keyword: str = "",
    intent: str = "",
    require_internal_links: bool = True,
) -> tuple[QualityResult, list[str], str]:
    recent_titles = recent_titles or []
    category = classify_category(title, body)
    ok_title, title_reason = title_ok(title, recent_titles)
    dup, dup_reason = is_near_duplicate(title, recent_titles, keyword=keyword)
    result = score_usefulness(
        title, body, require_internal_links=require_internal_links
    )
    result.intent_score = commercial_intent_score(keyword, title, body)

    if not ok_title:
        result.ok = False
        result.errors.append(title_reason)
    if dup:
        result.ok = False
        result.errors.append(dup_reason)

    if intent:
        intent_norm = intent.strip().lower()
        if intent_norm not in VALID_INTENTS:
            result.ok = False
            result.errors.append(
                f"invalid intent '{intent}'; use one of {sorted(VALID_INTENTS)}"
            )
        elif intent_norm == "decision" and category == "finance":
            if result.intent_score < 3 and not COMMERCIAL_INTENT_RE.search(title):
                result.ok = False
                result.errors.append(
                    "finance decision posts need action title "
                    "(일정/납입/자격/신청 + number) or higher commercial intent"
                )

    if not ASOF_RE.search(body or ""):
        result.ok = False
        result.errors.append("missing 정보 기준일 (YYYY-MM-DD) in body")

    clean_labels = sanitize_labels(
        labels, keyword=keyword or title, category=category, target=TARGET_LABELS
    )
    if len(clean_labels) < MIN_LABELS:
        result.ok = False
        result.errors.append(
            f"labels {len(clean_labels)} < {MIN_LABELS} "
            "(add topical tags; generic pads like 방법/확인 are rejected)"
        )

    if result.errors:
        result.ok = False
    return result, clean_labels, category
