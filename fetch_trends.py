"""Multi-source KR keyword collector (Google Trends / BlackKiwi / Loword)."""

from __future__ import annotations

import ast
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import unescape
from typing import Iterable

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

GOOGLE_TRENDS_URL = "https://trends.google.co.kr/trending?geo=KR&sort=search-volume"
BLACKKIWI_ISSUE_URL = "https://blackkiwi.net/api/service/keyword/issue-keywords"
BLACKKIWI_NEW_URL = "https://blackkiwi.net/api/service/keyword/new-keywords"
LOWORD_TREND_URL = "https://loword.co.kr/api/v1/keyword/trend/getList"

SOURCE_URLS = {
    "google": "https://trends.google.co.kr/trending?geo=KR",
    "blackkiwi": "https://blackkiwi.net/service/trend",
    "loword": "https://loword.co.kr/keywordTrend",
}

CATEGORIES: dict[int, str] = {
    1: "자동차",
    2: "미용 및 패션",
    3: "비즈니스 및 금융",
    4: "엔터테인먼트",
    5: "식음료",
    6: "게임",
    7: "건강",
    8: "취미 및 레저",
    9: "취업 및 교육",
    10: "법률 및 정부",
    11: "기타",
    13: "반려동물 및 동물",
    14: "정치",
    15: "과학",
    16: "쇼핑",
    17: "스포츠",
    18: "기술",
    19: "여행 및 교통",
    20: "기후",
}

# Exclude pure entertainment / celebrity noise.
EXCLUDED_CATEGORY_IDS = {4, 6}  # entertainment, games

INFO_CATEGORY_IDS = {1, 3, 7, 9, 10, 11, 15, 16, 18, 19}

MONEY_HINTS = (
    "대출", "금리", "이자", "보험", "세금", "연말정산", "환급", "지원금", "보조금",
    "청약", "전세", "월세", "매매", "시세", "주가", "주식", "코스피", "코스닥",
    "ETF", "채권", "환율", "엔화", "달러", "가상자산", "비트코인", "이더리움",
    "회생", "파산", "근저당", "압류", "경매", "상속", "증여", "이혼", "양육",
    "연봉", "퇴직", "실업", "자격증", "시험", "수강", "취업", "이직", "노무",
    "신청", "방법", "절차", "비용", "가격", "수수료", "환불", "보상", "보험금",
    "은행", "카드", "신용", "한도", "연체", "부채", "채무", "사이드카", "주주",
    "물류", "화재", "대피", "보상금", "산재", "산업재해", "쿠팡",
    "항공", "항공권", "비자", "여권", "환승",
    "증상", "치료", "병원", "수술", "약", "질환", "질병", "검진", "이관",
    "SQLD", "ADsP", "정보처리", "공인중개사", "컴활", "법원", "국토교통",
)

ENT_BLOCK = (
    "콘서트", "드라마", "예능", "가수", "배우", "아이돌", "영화", "뮤비",
    "연애", "결혼지옥", "쇼츠", "틱톡", "릴스", "팬미팅", "월드컵응원",
)


@dataclass(frozen=True)
class TrendItem:
    rank: int
    title: str
    volume_label: str
    volume: int
    active: bool
    increase_percentage: int = 0
    related: tuple[str, ...] = ()
    category_ids: tuple[int, ...] = ()
    category_names: tuple[str, ...] = ()
    source: str = "google"
    window: str = "4h"
    source_url: str = SOURCE_URLS["google"]


def _http_get(url: str, headers: dict[str, str] | None = None) -> str:
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Accept": "application/json,text/html,*/*",
    }
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _http_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> object:
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    if headers:
        req_headers.update(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _parse_volume(label: str | int | float | None) -> int:
    if label is None:
        return 0
    if isinstance(label, (int, float)):
        return int(label)
    text = unescape(str(label)).replace(",", "").strip()
    korean = re.search(r"(\d+(?:\.\d+)?)\s*(천|만)?\+?", text)
    if korean and ("검색" in text or "회" in text or "천" in text or "만" in text or "+" in text):
        value = float(korean.group(1))
        unit = korean.group(2) or ""
        if unit == "천":
            value *= 1_000
        elif unit == "만":
            value *= 10_000
        return int(value)
    english = re.search(r"(\d+(?:\.\d+)?)([KkMm]?)\+?", text)
    if not english:
        digits = re.search(r"(\d+)", text)
        return int(digits.group(1)) if digits else 0
    value = float(english.group(1))
    unit = english.group(2).lower()
    if unit == "k":
        value *= 1_000
    elif unit == "m":
        value *= 1_000_000
    return int(value)


def _volume_label(volume: int) -> str:
    if volume >= 10_000:
        if volume % 10_000 == 0:
            return f"검색 {volume // 10000}만+회"
        return f"검색 {volume:,}+회"
    if volume >= 1000:
        if volume % 1000 == 0:
            return f"검색 {volume // 1000}천+회"
        return f"검색 {volume:,}+회"
    if volume > 0:
        return f"검색 {volume}+회"
    return "검색량 미표기"


def _parse_google_ds0(html: str) -> list[dict]:
    match = re.search(
        r"AF_initDataCallback\(\{key: 'ds:0'.*?data:(.*?), sideChannel: \{\}\}\);",
        html,
        re.S,
    )
    if not match:
        return []
    raw = match.group(1)
    for src, dst in (("null", "None"), ("true", "True"), ("false", "False")):
        raw = re.sub(rf"\b{src}\b", dst, raw)
    data = ast.literal_eval(raw)
    rows = data[1] if isinstance(data, list) and len(data) > 1 else []
    parsed = []
    for row in rows or []:
        cat_ids = tuple(int(x) for x in (row[10] or []) if x is not None)
        parsed.append(
            {
                "title": str(row[0]).strip(),
                "volume": int(row[6] or 0),
                "increase": int(row[8] or 0),
                "related": tuple(str(x) for x in (row[9] or []) if x),
                "category_ids": cat_ids or (11,),
                "active": row[1] is None,
            }
        )
    return parsed


def fetch_google_trends(hours: int) -> list[TrendItem]:
    """Google Trends supports 4/24/48/168h. Map 1h -> 4h nearest window."""
    mapped = 4 if hours <= 4 else 24 if hours <= 24 else 48 if hours <= 48 else 168
    window = f"{hours}h" if hours in {1, 4, 24} else f"{mapped}h"
    url = f"{GOOGLE_TRENDS_URL}&hours={mapped}"
    try:
        html = _http_get(url)
        rows = _parse_google_ds0(html)
    except Exception as exc:
        print(f"[google] fetch failed hours={mapped}: {exc}")
        return []

    rows.sort(key=lambda r: (-r["volume"], r["title"]))
    items: list[TrendItem] = []
    for index, row in enumerate(rows, start=1):
        cat_ids = row["category_ids"]
        items.append(
            TrendItem(
                rank=index,
                title=row["title"],
                volume_label=_volume_label(row["volume"]),
                volume=row["volume"],
                active=row["active"],
                increase_percentage=row["increase"],
                related=row["related"],
                category_ids=cat_ids,
                category_names=tuple(CATEGORIES.get(c, f"카테고리{c}") for c in cat_ids),
                source="google",
                window=window if hours != 1 else "4h~proxy",
                source_url=url,
            )
        )
    print(f"[google] hours={mapped} items={len(items)}")
    return items


def fetch_blackkiwi_issue() -> list[TrendItem]:
    try:
        data = _http_json(
            f"{BLACKKIWI_ISSUE_URL}?periodType=daily",
            headers={"Referer": SOURCE_URLS["blackkiwi"]},
        )
    except Exception as exc:
        print(f"[blackkiwi] issue failed: {exc}")
        return []
    if not isinstance(data, list):
        return []
    items = []
    for row in data:
        volume = int(row.get("traffic") or 0)
        title = str(row.get("keyword") or "").strip()
        if not title:
            continue
        items.append(
            TrendItem(
                rank=int(row.get("rank") or len(items) + 1),
                title=title,
                volume_label=_volume_label(volume),
                volume=volume,
                active=True,
                increase_percentage=1000 if row.get("isNew") else 0,
                related=(),
                category_ids=(11,),
                category_names=("기타",),
                source="blackkiwi",
                window="24h",
                source_url=SOURCE_URLS["blackkiwi"],
            )
        )
    print(f"[blackkiwi] issue items={len(items)}")
    return items


def fetch_blackkiwi_new() -> list[TrendItem]:
    try:
        data = _http_json(
            BLACKKIWI_NEW_URL,
            headers={"Referer": SOURCE_URLS["blackkiwi"]},
        )
    except Exception as exc:
        print(f"[blackkiwi] new failed: {exc}")
        return []
    if not isinstance(data, dict):
        return []
    items: list[TrendItem] = []
    for day_key, rows in data.items():
        for row in rows or []:
            title = str(row.get("keyword") or "").strip()
            volume = int(row.get("searchVolume") or 0)
            if not title:
                continue
            items.append(
                TrendItem(
                    rank=len(items) + 1,
                    title=title,
                    volume_label=_volume_label(volume),
                    volume=volume,
                    active=True,
                    related=(),
                    category_ids=(11,),
                    category_names=("기타",),
                    source="blackkiwi-new",
                    window="24h",
                    source_url=SOURCE_URLS["blackkiwi"],
                )
            )
    items.sort(key=lambda x: (-x.volume, x.title))
    # re-rank
    items = [
        TrendItem(
            rank=i,
            title=x.title,
            volume_label=x.volume_label,
            volume=x.volume,
            active=x.active,
            related=x.related,
            category_ids=x.category_ids,
            category_names=x.category_names,
            source=x.source,
            window=x.window,
            source_url=x.source_url,
        )
        for i, x in enumerate(items, start=1)
    ]
    print(f"[blackkiwi] new items={len(items)}")
    return items


def fetch_loword_hour(when: datetime | None = None) -> list[TrendItem]:
    when = when or datetime.now().astimezone()
    # API expects 'YYYY-MM-DD HH:00'
    date_key = when.strftime("%Y-%m-%d %H:00")
    try:
        data = _http_json(
            LOWORD_TREND_URL,
            method="POST",
            payload={"date": date_key},
            headers={
                "Origin": "https://loword.co.kr",
                "Referer": SOURCE_URLS["loword"],
            },
        )
    except Exception as exc:
        print(f"[loword] hour={date_key} failed: {exc}")
        return []

    if not isinstance(data, dict) or data.get("rsltCd") != "00":
        print(f"[loword] hour={date_key} empty: {data.get('rsltMsg') if isinstance(data, dict) else data}")
        return []

    trend = ((data.get("data") or {}).get("keywordTrend") or {})
    items: list[TrendItem] = []
    # Prefer google approxTraffic when present; naver has no volume -> synthetic score by rank.
    for engine, rows in trend.items():
        for row in rows or []:
            title = str(row.get("keyword") or row.get("title") or "").strip()
            if not title:
                continue
            if engine == "google":
                volume = _parse_volume(row.get("approxTraffic"))
            else:
                # rank 1 => 10000 synthetic units for sorting within source
                rank = int(row.get("rank") or 99)
                volume = max(100, 11000 - rank * 1000)
            rank = int(row.get("rank") or len(items) + 1)
            items.append(
                TrendItem(
                    rank=rank,
                    title=title,
                    volume_label=_volume_label(volume) if engine == "google" else f"로워드 {engine} {rank}위",
                    volume=volume,
                    active=True,
                    related=(),
                    category_ids=(11,),
                    category_names=("기타",),
                    source=f"loword-{engine}",
                    window="1h",
                    source_url=SOURCE_URLS["loword"],
                )
            )
    items.sort(key=lambda x: (-x.volume, x.title))
    print(f"[loword] {date_key} items={len(items)}")
    return items


def fetch_loword_windows() -> dict[str, list[TrendItem]]:
    """Build 1h / 4h / 24h views from hourly Loword snapshots.

    Sampling strategy (keeps runtime reasonable):
    - 1h: current hour
    - 4h: current + previous 3 hours
    - 24h: every 3 hours over the past day
    """
    now = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    by_window: dict[str, list[TrendItem]] = {"1h": [], "4h": [], "24h": []}
    hour_maps: dict[str, dict[str, TrendItem]] = {"1h": {}, "4h": {}, "24h": {}}

    offsets = sorted(set([0, 1, 2, 3] + list(range(0, 24, 3))))
    for offset in offsets:
        when = now - timedelta(hours=offset)
        rows = fetch_loword_hour(when)
        targets: list[str] = []
        if offset == 0:
            targets.append("1h")
        if offset < 4:
            targets.append("4h")
        if offset % 3 == 0:
            targets.append("24h")
        for item in rows:
            for window in targets:
                prev = hour_maps[window].get(item.title)
                if prev is None or item.volume > prev.volume:
                    hour_maps[window][item.title] = item

    for window, mapping in hour_maps.items():
        ranked = sorted(mapping.values(), key=lambda x: (-x.volume, x.title))
        by_window[window] = [
            TrendItem(
                rank=i,
                title=x.title,
                volume_label=x.volume_label,
                volume=x.volume,
                active=x.active,
                related=x.related,
                category_ids=x.category_ids,
                category_names=x.category_names,
                source=x.source,
                window=window,
                source_url=x.source_url,
            )
            for i, x in enumerate(ranked, start=1)
        ]
        print(f"[loword-agg] {window} unique={len(by_window[window])}")
    return by_window


def is_entertainment(item: TrendItem) -> bool:
    if any(cid in EXCLUDED_CATEGORY_IDS for cid in item.category_ids):
        return True
    title = item.title.strip()
    title_l = title.lower()
    if any(token.lower() in title_l for token in ENT_BLOCK):
        return True
    if "," in title:  # often celebrity headline style on Loword Naver
        return True
    # Bare person-name shaped tokens without practical hints.
    if re.fullmatch(r"[A-Za-z가-힣]{2,4}", title) and not any(
        h.lower() in title_l for h in MONEY_HINTS
    ):
        return True
    if any(cid == 17 for cid in item.category_ids) and not any(
        h.lower() in title_l for h in MONEY_HINTS
    ):
        return True
    return False


def informational_score(item: TrendItem) -> float:
    """Higher = better candidate for money/curiosity guide posts."""
    if is_entertainment(item):
        return -1_000_000
    title = item.title
    score = float(item.volume)
    if any(cid in INFO_CATEGORY_IDS for cid in item.category_ids):
        score *= 1.25
    hint_hits = sum(1 for h in MONEY_HINTS if h.lower() in title.lower())
    score += hint_hits * 50_000
    # Prefer concrete phrases over ultra-generic single nouns unless high volume finance.
    if len(title) >= 4:
        score += 5_000
    if re.search(r"(방법|신청|절차|뜻|증상|비용|자격|대출|보험|세금|회생|근저당)", title):
        score += 80_000
    # Soft-penalize pure politics/sports scoreboard terms without practical hints.
    if any(cid in {14, 17} for cid in item.category_ids) and hint_hits == 0:
        score *= 0.35
    return score


def collect_all_sources() -> dict[str, list[TrendItem]]:
    """Collect keywords for 1h / 4h / 24h across sources."""
    result: dict[str, list[TrendItem]] = {"1h": [], "4h": [], "24h": []}

    google_4 = fetch_google_trends(4)
    google_24 = fetch_google_trends(24)
    result["4h"].extend(google_4)
    result["24h"].extend(google_24)
    # Google has no true 1h; reuse freshest 4h list tagged separately by callers if needed.
    result["1h"].extend(google_4)

    result["24h"].extend(fetch_blackkiwi_issue())
    result["24h"].extend(fetch_blackkiwi_new())

    loword_windows = fetch_loword_windows()
    for window, rows in loword_windows.items():
        result[window].extend(rows)

    for window, rows in result.items():
        rows.sort(key=lambda x: (-informational_score(x), -x.volume, x.title))
        print(f"[collect] {window} total={len(rows)}")
    return result


def select_guide_keywords(
    collected: dict[str, list[TrendItem]] | None = None,
    limit: int = 8,
) -> list[TrendItem]:
    """Pick practical, money/curiosity keywords for guide-style posts."""
    collected = collected if collected is not None else collect_all_sources()
    best: dict[str, TrendItem] = {}
    best_score: dict[str, float] = {}

    # Prefer fresher windows when scores tie-ish: 1h > 4h > 24h
    window_bonus = {"1h": 20_000, "4h": 10_000, "24h": 0}
    for window in ("1h", "4h", "24h"):
        for item in collected.get(window, []):
            score = informational_score(item) + window_bonus[window]
            if score < 0:
                continue
            key = re.sub(r"\s+", "", item.title).lower()
            if key not in best_score or score > best_score[key]:
                best[key] = item
                best_score[key] = score

    ranked = sorted(best.values(), key=lambda x: (-informational_score(x), -x.volume, x.title))

    # Drop near-duplicate phrases (e.g. multiple Coupang fire variants).
    picked: list[TrendItem] = []
    for item in ranked:
        norm = re.sub(r"\s+", "", item.title).lower()
        duplicate = False
        for prev in picked:
            prev_norm = re.sub(r"\s+", "", prev.title).lower()
            if norm in prev_norm or prev_norm in norm:
                duplicate = True
                break
            # share a long common token
            tokens = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", item.title))
            prev_tokens = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", prev.title))
            same_topic = (
                ("화재" in item.title and "화재" in prev.title and ("쿠팡" in item.title and "쿠팡" in prev.title))
                or ("이관개방" in item.title and "이관개방" in prev.title)
                or ("회생" in item.title and "회생" in prev.title)
                or ("근저당" in item.title and "근저당" in prev.title)
            )
            if same_topic or len(tokens & prev_tokens) >= 2 and (
                "화재" in item.title and "화재" in prev.title
            ):
                duplicate = True
                break
        if not duplicate:
            picked.append(item)
        if len(picked) >= limit:
            break

    print("[select] guide keywords:")
    for i, item in enumerate(picked, start=1):
        print(
            f"  {i}. {item.title} | {item.volume_label} | "
            f"{item.source}/{item.window} | score={informational_score(item):.0f}"
        )
    return picked


def fetch_news_headlines(query: str, limit: int = 5) -> list[dict[str, str]]:
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    )
    try:
        xml = _http_get(url)
    except Exception:
        return []
    items = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.S)[:limit]:
        title_m = re.search(r"<title>(.*?)</title>", block, re.S)
        link_m = re.search(r"<link>(.*?)</link>", block, re.S)
        source_m = re.search(r"<source[^>]*>(.*?)</source>", block, re.S)
        if not title_m:
            continue
        title = unescape(re.sub(r"<[^>]+>", "", title_m.group(1))).strip()
        link = unescape(link_m.group(1)).strip() if link_m else ""
        source = unescape(source_m.group(1)).strip() if source_m else ""
        if title:
            items.append({"title": title, "link": link, "source": source})
    return items


# Backward-compatible helpers -------------------------------------------------

def fetch_trends_by_search_volume(limit: int = 15) -> list[TrendItem]:
    return fetch_google_trends(4)[:limit]


def fetch_all_trends() -> list[TrendItem]:
    return fetch_google_trends(4)


if __name__ == "__main__":
    collected = collect_all_sources()
    select_guide_keywords(collected, limit=10)
