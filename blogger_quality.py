"""Hard filters, label sanitizer, usefulness/title/category gates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

MIN_BODY_CHARS = 2500
MIN_LABELS = 15
TARGET_LABELS = 20
MAX_LABEL_CHARS_TOTAL = 180
MWOGILLAE_RECENT_LIMIT = 10
MWOGILLAE_MAX_IN_RECENT = 2

REQUIRED_SECTION_PATTERNS = {
    "summary": re.compile(r"한\s*줄\s*요약|읽고\s*나면|이 글을 읽으면"),
    "audience": re.compile(r"해당되는지|대상|비대상|맞는 사람"),
    "action": re.compile(r"지금 확인|확인하는 방법|바로 할|사전판매|신청|체크"),
    "checklist": re.compile(r"체크리스트|피해야 할 실수"),
    "faq": re.compile(r"FAQ|자주 묻는|Q\.\s*|Q\."),
    "official": re.compile(
        r"공식|뉴스룸|samsung\.com|news\.samsung|\.go\.kr|IR|공시",
        re.I,
    ),
}

HARD_SKIP_RE = re.compile(
    r"("
    r"손흥민|메시|케스파|오스틴\s*보스|어벤져스|개봉일|줄거리|예고편|"
    r"무승부|연승|연패|홈런|득점|경기\s*결과|월드컵\s*결승|"
    r"아이돌|배우|연예|열애|결혼\s*축하|나혼산|예능|"
    r"방탄소년단|BTS|사키라|로다주|"
    r"KT\s*vs|두산\s*베어스|LG\s*트윈스|KBO|"
    r"lafc|mls|피파\b|축구\s*감독"
    r")",
    re.I,
)

# Allow if clearly useful IT/finance/life even when pattern loosely overlaps.
HARD_SKIP_ALLOW_RE = re.compile(
    r"(신청|예약|할인|요금|출고가|사전판매|증상|치료|근저당|실적|공시|가이드|방법)"
)

JUNK_LABEL_RE = re.compile(
    r"("
    r"움직였|여전히|예측$|핵심$|향후$|끝나면|과잉생산|"
    r"Corp$|Inc$|Ltd$|정보성글$"
    r")"
)

TITLE_GOOD_RE = re.compile(
    r"(방법|체크리스트|일정|대상|확인|신청|예약|비교|보는 법|정리|가이드|대응)"
)


@dataclass
class QualityResult:
    ok: bool
    score: int
    reasons: list[str]
    errors: list[str]

    def log_lines(self) -> list[str]:
        lines = [
            f"USEFULNESS_SCORE={self.score}",
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
    if re.search(r"예약|신청|할인|캠핑|통행료|채용|가이드|방법|요금|사전판매", text):
        return "guide"
    if re.search(r"갤럭시|제미나이|키미|AI|스마트폰|폴더블|앱|설정", text):
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


def is_hard_skip(keyword: str, title: str = "") -> tuple[bool, str]:
    text = f"{keyword} {title}".strip()
    if not text:
        return True, "empty keyword/title"
    if HARD_SKIP_RE.search(text) and not HARD_SKIP_ALLOW_RE.search(text):
        return True, f"hard_skip sports/entertainment: {text[:80]}"
    cat = classify_category(title or keyword, keyword)
    if cat == "sports_ent":
        return True, "category sports_ent blocked"
    return False, ""


def strip_html(content: str) -> str:
    content = re.sub(r"<script[\s\S]*?</script>", "", content or "", flags=re.I)
    content = re.sub(r"<style[\s\S]*?</style>", "", content or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", content)
    return re.sub(r"\s+", " ", text).strip()


def sanitize_labels(
    labels: Iterable[str],
    *,
    keyword: str = "",
    category: str = "",
    target: int = TARGET_LABELS,
) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in labels:
        lab = re.sub(r"\s+", " ", (raw or "").strip())
        if not lab:
            continue
        if len(lab) < 2 or len(lab) > 28:
            continue
        if " " in lab and len(lab.split()) >= 4:
            continue  # sentence-like
        if lab.isdigit():
            continue
        if JUNK_LABEL_RE.search(lab):
            continue
        if re.fullmatch(r"\d{4}년?", lab):
            continue
        key = normalize_text(lab)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(lab)

    # Ensure category + keyword tokens exist.
    extras: list[str] = []
    cat_map = {
        "guide": "생활정보",
        "it": "IT",
        "finance": "투자",
        "society": "생활안전",
        "other": "정보",
    }
    if category:
        extras.append(cat_map.get(category, "정보"))
    if keyword:
        for token in re.split(r"[\s,/|]+", keyword):
            token = token.strip()
            if 2 <= len(token) <= 20:
                extras.append(token)
    for lab in extras:
        key = normalize_text(lab)
        if key not in seen:
            seen.add(key)
            cleaned.insert(0, lab)

    # Fit Blogger practical limits: count + total chars.
    out: list[str] = []
    total = 0
    for lab in cleaned:
        add = len(lab) + (1 if out else 0)
        if len(out) >= target:
            break
        if total + add > MAX_LABEL_CHARS_TOTAL:
            continue
        out.append(lab)
        total += add

    # Pad with short topical tokens if under minimum.
    pads = ["일정", "확인", "방법", "체크리스트", "공식", "신청", "비교", "가이드", "주의", "FAQ"]
    for lab in pads:
        if len(out) >= target:
            break
        key = normalize_text(lab)
        if key in seen:
            continue
        if total + len(lab) + 1 > MAX_LABEL_CHARS_TOTAL:
            continue
        seen.add(key)
        out.append(lab)
        total += len(lab) + 1
    return out


def title_ok(title: str, recent_titles: list[str] | None = None) -> tuple[bool, str]:
    recent_titles = recent_titles or []
    if "뭐길래" in title:
        recent = recent_titles[:MWOGILLAE_RECENT_LIMIT]
        mw = sum(1 for t in recent if "뭐길래" in t)
        if mw >= MWOGILLAE_MAX_IN_RECENT:
            return False, (
                f"title template '뭐길래' overused "
                f"({mw}/{MWOGILLAE_RECENT_LIMIT} recent); use 방법/일정/체크리스트 form"
            )
    if not TITLE_GOOD_RE.search(title) and "뭐길래" in title:
        return False, "title is 뭐길래-only; add 방법/일정/체크리스트 signal"
    return True, ""


def token_set(text: str) -> set[str]:
    parts = re.findall(r"[가-힣A-Za-z0-9]{2,}", text.lower())
    return set(parts)


def is_near_duplicate(title: str, recent_titles: list[str], threshold: float = 0.55) -> tuple[bool, str]:
    a = token_set(title)
    if not a:
        return False, ""
    for other in recent_titles:
        b = token_set(other)
        if not b:
            continue
        overlap = len(a & b) / len(a | b)
        if overlap >= threshold:
            return True, f"near-duplicate of '{other[:60]}' (jaccard={overlap:.2f})"
    return False, ""


def score_usefulness(title: str, body_html_or_md: str) -> QualityResult:
    text = strip_html(body_html_or_md) if "<" in body_html_or_md else body_html_or_md
    text = re.sub(r"\s+", " ", text).strip()
    reasons: list[str] = []
    errors: list[str] = []
    score = 0

    skip, why = is_hard_skip("", title)
    if skip:
        errors.append(why)
        return QualityResult(False, 0, reasons, errors)

    if REQUIRED_SECTION_PATTERNS["action"].search(text):
        score += 2
        reasons.append("+2 action")
    else:
        errors.append("missing concrete action section")

    if REQUIRED_SECTION_PATTERNS["official"].search(text):
        score += 2
        reasons.append("+2 official source")
    else:
        errors.append("missing official source signal")

    if TITLE_GOOD_RE.search(title) or REQUIRED_SECTION_PATTERNS["action"].search(title):
        score += 2
        reasons.append("+2 search intent method/schedule")
    else:
        reasons.append("+0 weak title intent")

    fact_hits = len(re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|\d{4}년|\d{1,2}월|\d{1,2}일", text))
    if fact_hits >= 3:
        score += 1
        reasons.append("+1 facts")
    else:
        errors.append("need >=3 verifiable facts (dates/numbers)")

    if REQUIRED_SECTION_PATTERNS["faq"].search(text):
        score += 1
        reasons.append("+1 faq")
    else:
        errors.append("missing FAQ")

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

    # Required structure presence (hard fail independent of soft score bits).
    for key in ("summary", "audience", "action", "checklist", "faq", "official"):
        if not REQUIRED_SECTION_PATTERNS[key].search(text):
            errors.append(f"missing section:{key}")

    ok = score >= 7
    if any(e.startswith("missing section:") for e in errors):
        ok = False
    if any(e.startswith("body too short") for e in errors):
        ok = False
    if any(
        e.startswith("missing FAQ")
        or e.startswith("missing checklist")
        or e.startswith("missing official")
        or e.startswith("missing concrete")
        or e.startswith("need >=")
        for e in errors
    ):
        ok = False
    if score < 7:
        ok = False
        if f"score {score} < 7" not in errors:
            errors.append(f"score {score} < 7")
    return QualityResult(ok=ok, score=score, reasons=reasons, errors=errors)


def validate_post(
    *,
    title: str,
    body: str,
    labels: list[str],
    recent_titles: list[str] | None = None,
    keyword: str = "",
) -> tuple[QualityResult, list[str], str]:
    recent_titles = recent_titles or []
    category = classify_category(title, body)
    ok_title, title_reason = title_ok(title, recent_titles)
    dup, dup_reason = is_near_duplicate(title, recent_titles)
    result = score_usefulness(title, body)
    if not ok_title:
        result.ok = False
        result.errors.append(title_reason)
    if dup:
        result.ok = False
        result.errors.append(dup_reason)

    clean_labels = sanitize_labels(labels, keyword=keyword or title, category=category)
    if len(clean_labels) < MIN_LABELS:
        result.ok = False
        result.errors.append(f"labels {len(clean_labels)} < {MIN_LABELS}")

    # CDN / thumb checks are handled by publish_trend.
    return result, clean_labels, category
