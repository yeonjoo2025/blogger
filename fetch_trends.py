"""Fetch Google Trends KR (past 4h) and group top keywords by category."""

from __future__ import annotations

import ast
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from html import unescape

TRENDS_URL = (
    "https://trends.google.com/trending?geo=KR&hours=4&sort=search-volume"
)
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Google Trends Trending Now category ids
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


@dataclass
class CategoryTrends:
    category_id: int
    category_name: str
    items: list[TrendItem] = field(default_factory=list)

    @property
    def trends_url(self) -> str:
        return (
            f"{TRENDS_URL}&category={self.category_id}"
            if self.category_id
            else TRENDS_URL
        )


def _parse_volume(label: str) -> int:
    text = unescape(label).replace(",", "").strip()
    korean = re.search(r"(\d+(?:\.\d+)?)\s*(천|만)?\+?", text)
    if korean and ("검색" in text or "회" in text or "천" in text or "만" in text):
        value = float(korean.group(1))
        unit = korean.group(2) or ""
        if unit == "천":
            value *= 1_000
        elif unit == "만":
            value *= 10_000
        return int(value)

    english = re.search(r"(\d+(?:\.\d+)?)([KkMm]?)\+?", text)
    if not english:
        return 0
    value = float(english.group(1))
    unit = english.group(2).lower()
    if unit == "k":
        value *= 1_000
    elif unit == "m":
        value *= 1_000_000
    return int(value)


def _volume_label(volume: int) -> str:
    if volume >= 10_000:
        return f"검색 {volume // 10000}만+회" if volume % 10000 == 0 else f"검색 {volume:,}+회"
    if volume >= 1000:
        return f"검색 {volume // 1000}천+회"
    if volume > 0:
        return f"검색 {volume}+회"
    return "검색량 정보 없음"


def _http_get(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_ds0(html: str) -> list[dict]:
    match = re.search(
        r"AF_initDataCallback\(\{key: 'ds:0'.*?data:(.*?), sideChannel: \{\}\}\);",
        html,
        re.S,
    )
    if not match:
        raise RuntimeError("Could not find Trends ds:0 payload")
    raw = match.group(1)
    for src, dst in (("null", "None"), ("true", "True"), ("false", "False")):
        raw = re.sub(rf"\b{src}\b", dst, raw)
    data = ast.literal_eval(raw)
    rows = data[1] if isinstance(data, list) and len(data) > 1 else []
    parsed: list[dict] = []
    for row in rows or []:
        title = str(row[0]).strip()
        volume = int(row[6] or 0)
        increase = int(row[8] or 0)
        related = tuple(str(x) for x in (row[9] or []) if x)
        category_ids = tuple(int(x) for x in (row[10] or []) if x is not None)
        active = row[1] is None
        parsed.append(
            {
                "title": title,
                "volume": volume,
                "increase": increase,
                "related": related,
                "category_ids": category_ids or (11,),
                "active": active,
            }
        )
    return parsed


def fetch_all_trends() -> list[TrendItem]:
    """Fetch past-4h KR trends (search-volume page order) with categories."""
    html = _http_get(TRENDS_URL)
    rows = _parse_ds0(html)
    # Stable overall rank by search volume desc, then title.
    rows.sort(key=lambda r: (-r["volume"], r["title"]))
    items: list[TrendItem] = []
    for index, row in enumerate(rows, start=1):
        cat_ids = row["category_ids"]
        cat_names = tuple(CATEGORIES.get(cid, f"카테고리 {cid}") for cid in cat_ids)
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
                category_names=cat_names,
            )
        )
    if not items:
        raise RuntimeError(f"No trends parsed from {TRENDS_URL}")
    return items


def group_top_by_category(
    trends: list[TrendItem] | None = None,
    top_n: int = 5,
) -> list[CategoryTrends]:
    """Group trends by category and keep top_n by search volume in each."""
    trends = trends if trends is not None else fetch_all_trends()
    buckets: dict[int, list[TrendItem]] = defaultdict(list)
    for item in trends:
        for category_id in item.category_ids:
            if category_id not in CATEGORIES:
                continue
            buckets[category_id].append(item)

    grouped: list[CategoryTrends] = []
    for category_id, name in CATEGORIES.items():
        items = buckets.get(category_id) or []
        # Deduplicate by title, keep highest volume.
        best: dict[str, TrendItem] = {}
        for item in items:
            prev = best.get(item.title)
            if prev is None or item.volume > prev.volume:
                best[item.title] = item
        ranked = sorted(best.values(), key=lambda x: (-x.volume, x.title))[:top_n]
        if not ranked:
            continue
        # Re-number ranks within category.
        category_items = [
            TrendItem(
                rank=i,
                title=item.title,
                volume_label=item.volume_label,
                volume=item.volume,
                active=item.active,
                increase_percentage=item.increase_percentage,
                related=item.related,
                category_ids=item.category_ids,
                category_names=item.category_names,
            )
            for i, item in enumerate(ranked, start=1)
        ]
        grouped.append(
            CategoryTrends(
                category_id=category_id,
                category_name=name,
                items=category_items,
            )
        )
    # Prefer categories with more / higher volume first.
    grouped.sort(
        key=lambda c: (
            -sum(i.volume for i in c.items),
            -len(c.items),
            c.category_name,
        )
    )
    return grouped


def fetch_news_headlines(query: str, limit: int = 4) -> list[dict[str, str]]:
    """Fetch recent Google News RSS headlines for a query."""
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode(
            {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
        )
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


# Backward-compatible helper used by older scripts/tests.
def fetch_trends_by_search_volume(limit: int = 15) -> list[TrendItem]:
    return fetch_all_trends()[:limit]


if __name__ == "__main__":
    groups = group_top_by_category(top_n=5)
    for group in groups:
        print(f"\n[{group.category_id}] {group.category_name}")
        for item in group.items:
            state = "active" if item.active else "lasted"
            print(
                f"  {item.rank}. {item.volume_label:>10} +{item.increase_percentage}% "
                f"{state:6} {item.title}"
            )
